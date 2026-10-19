"""Manual experimental RTSP PTZ trial; separate from CamFloat and release builds.

Protocol candidates: https://github.com/realldz/onvif_proxy_server
An RTSP 200 response does not establish physical movement or stop support.
"""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import parse_http_list, parse_keqv_list

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
FORMATS = ('content_type', 'ptz_header', 'user_body', 'user_header', 'parameter_body')
NETWORK_ERRORS = (OSError, ValueError, IndexError)


def eligible_cameras(config):
    cameras = []
    for camera in config.get('cameras', []):
        if not camera.get('enabled', True) or camera.get('connection_locked'):
            continue
        try:
            parts = urlsplit(camera['url'])
            address = ipaddress.ip_address(parts.hostname)
            port = parts.port or 554
        except (KeyError, ValueError, TypeError):
            continue
        if (parts.scheme == 'rtsp' and address.version == 4 and address.is_private
                and not any((address.is_loopback, address.is_link_local,
                             address.is_multicast, address.is_unspecified, address.is_reserved))
                and 1 <= port <= 65535):
            cameras.append(camera)
    return cameras


def digest_header(challenge, uri, username, password, method, nonce_count=1):
    if not challenge.lower().startswith('digest '):
        raise ValueError('Unsupported authentication')
    values = parse_keqv_list(parse_http_list(challenge[7:]))
    if values.get('algorithm', 'MD5').upper() != 'MD5' or not values.get('nonce'):
        raise ValueError('Unsupported digest')
    realm, nonce = values.get('realm', ''), values['nonce']
    if any(c in value for value in (uri, username, realm, nonce, values.get('opaque', '')) for c in '\r\n'):
        raise ValueError('Invalid authentication field')
    md5 = lambda text: hashlib.md5(text.encode('utf-8')).hexdigest()
    quote = lambda text: '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'
    ha1 = md5(f'{username}:{realm}:{password}')
    ha2 = md5(f'{method}:{uri}')
    fields = [f'username={quote(username)}', f'realm={quote(realm)}',
              f'nonce={quote(nonce)}', f'uri={quote(uri)}']
    qops = [q.strip() for q in values.get('qop', '').split(',') if q.strip()]
    if qops:
        if 'auth' not in qops:
            raise ValueError('Unsupported digest qop')
        cnonce = secrets.token_hex(16)
        nc = f'{nonce_count:08x}'
        response = md5(f'{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}')
        fields += ['qop=auth', 'nc=' + nc, 'cnonce=' + quote(cnonce)]
    else:
        response = md5(f'{ha1}:{nonce}:{ha2}')
    fields += ['response=' + quote(response), 'algorithm=MD5']
    if 'opaque' in values:
        fields.append('opaque=' + quote(values['opaque']))
    return 'Authorization: Digest ' + ', '.join(fields)


def command(variant, direction):
    if variant not in FORMATS or direction not in ('STOP', 'LEFT', 'RIGHT'):
        raise ValueError('Unsupported command')
    if variant == 'content_type':
        return 'SET_PARAMETER', ['Content-type: ptzCmd: ' + direction], b''
    if variant == 'ptz_header':
        return 'SET_PARAMETER', ['ptzCmd: ' + direction], b''
    if variant == 'user_header':
        return 'USER_CMD_SET', ['ptzCmd: ' + direction], b''
    method = 'USER_CMD_SET' if variant == 'user_body' else 'SET_PARAMETER'
    return method, ['Content-Type: text/parameters'], ('ptzCmd: ' + direction).encode('ascii')


class Client:
    def __init__(self, url):
        self.parts = urlsplit(url)
        self.uri = urlunsplit(('rtsp', f'{self.parts.hostname}:{self.parts.port or 554}',
                              self.parts.path or '/', self.parts.query, ''))
        if any(c in self.uri for c in '\r\n'):
            raise ValueError('Invalid URI')
        self.sock = socket.create_connection((self.parts.hostname, self.parts.port or 554), timeout=.8)
        self.sequence = 0
        self.challenge = ''
        self.nonce_count = 0

    def close(self):
        self.sock.close()

    def request(self, method, headers=(), body=b''):
        self.sequence += 1
        lines = [f'{method} {self.uri} RTSP/1.0', f'CSeq: {self.sequence}',
                 'User-Agent: CamFloat-PTZ-trial', *headers]
        if self.challenge:
            self.nonce_count += 1
            lines.append(digest_header(self.challenge, self.uri,
                                      unquote(self.parts.username or ''),
                                      unquote(self.parts.password or ''), method, self.nonce_count))
        if body:
            lines.append(f'Content-Length: {len(body)}')
        deadline = time.monotonic() + .8
        self.sock.settimeout(.8)
        self.sock.sendall(('\r\n'.join(lines) + '\r\n\r\n').encode('utf-8') + body)
        data = b''
        def read():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Reply timeout')
            self.sock.settimeout(remaining)
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError('Connection closed')
            return chunk
        while b'\r\n\r\n' not in data:
            if len(data) >= 32768:
                raise ValueError('Header too large')
            data += read()
        head, _, payload = data.partition(b'\r\n\r\n')
        response_lines = head.decode('iso-8859-1').split('\r\n')
        if not response_lines[0].startswith('RTSP/1.0 '):
            raise ValueError('Invalid RTSP reply')
        status = int(response_lines[0].split(' ')[1])
        fields = {}
        for line in response_lines[1:]:
            if ':' in line:
                key, value = line.split(':', 1)
                fields[key.lower()] = value.strip()
        if fields.get('cseq') != str(self.sequence):
            raise ValueError('Unexpected reply sequence')
        length = int(fields.get('content-length', '0'))
        if not 0 <= length <= 65536:
            raise ValueError('Response too large')
        while len(payload) < length:
            payload += read()
        if status == 401 and not self.challenge:
            self.challenge = fields.get('www-authenticate', '')
            if not self.challenge:
                raise ValueError('Missing authentication challenge')
            return self.request(method, headers, body)
        return status

    def ptz(self, variant, direction):
        return self.request(*command(variant, direction))


def pulse(camera, variant, direction, duration_ms=180, client_factory=Client):
    if direction not in ('LEFT', 'RIGHT', 'STOP') or variant not in FORMATS or not 100 <= duration_ms <= 250:
        raise ValueError('Unsupported trial')
    result = dict(camera_number=camera['number'], format=variant, direction=direction,
                  requested_ms=duration_ms, physical_result='unconfirmed')
    move = stop = timer = None
    def safe_stop(client, key):
        try:
            result[key] = client.ptz(variant, 'STOP')
        except NETWORK_ERRORS as error:
            result[key + '_error'] = type(error).__name__
    try:
        move = client_factory(camera['url'])
        result['initial_stop_status'] = move.ptz(variant, 'STOP')
        if direction == 'STOP' or result['initial_stop_status'] != 200:
            return result
        stop = client_factory(camera['url'])
        result['backup_stop_status'] = stop.ptz(variant, 'STOP')
        if result['backup_stop_status'] != 200:
            return result
        timer = threading.Timer(duration_ms / 1000, safe_stop, (stop, 'timed_stop_status'))
        # A separate authenticated connection stops even if the movement reply blocks.
        timer.start()
        result['move_status'] = move.ptz(variant, direction)
        timer.join(1.5)
    except NETWORK_ERRORS as error:
        result['error'] = type(error).__name__
    finally:
        if timer:
            # Never cancel the scheduled stop on a failed move or Ctrl+C.
            timer.join(1.5)
        if move:
            safe_stop(move, 'final_stop_status')
            move.close()
        if stop:
            stop.close()
        if timer and result.get('timed_stop_status') != 200 and result.get('final_stop_status') != 200:
            fallback = None
            try:
                fallback = client_factory(camera['url'])
                safe_stop(fallback, 'fallback_stop_status')
            except NETWORK_ERRORS as error:
                result['fallback_stop_error'] = type(error).__name__
            finally:
                if fallback:
                    fallback.close()
    return result


def load_cameras():
    # Read only: load_config() also repairs/migrates profiles and is unsuitable here.
    from camfloat.camera_model import normalize
    folder = Path(os.environ.get('CAMFLOAT_DATA_DIR') or Path(os.environ['LOCALAPPDATA']) / 'CamFloat')
    stored = json.loads((folder / 'settings.json').read_text(encoding='utf-8-sig'))
    return eligible_cameras(normalize(stored, encrypted=True))


def save_results(results):
    folder = ROOT / 'verification/current/camera-control'
    folder.mkdir(parents=True, exist_ok=True)
    # Only numeric IDs, fixed command names, response codes and observation enums.
    # No addresses, credentials, camera names, raw replies, audio or pictures.
    (folder / 'manual-latest.json').write_text(json.dumps(results[-50:], indent=2) + '\n', encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description='카메라 회전 시험 도구 (실험용)')
    parser.add_argument('--list', action='store_true', help='시험 가능한 카메라 목록만 표시')
    args = parser.parse_args(argv)
    cameras = load_cameras()
    print('\nCamFloat · 카메라 회전 시험\n')
    if not cameras:
        print('시험할 내부망 카메라가 없습니다. CamFloat에 먼저 등록하세요.')
        return 1
    for camera in cameras:
        name = ''.join(c for c in camera.get('name', '') if c.isprintable())[:60]
        print(f"  {camera['number']}. {name}")
    if args.list:
        return 0
    print('\n화면이나 렌즈를 보면서 시험하세요. 움직임은 0.18초 뒤 정지 요청합니다.')
    print('멈추지 않으면 제조사 앱에서 정지하세요. 등록 정보와 저장 위치 설정은 바꾸지 않습니다.\n')
    number = input('시험할 카메라 번호 (Q: 종료): ').strip()
    camera = next((c for c in cameras if str(c['number']) == number), None)
    if camera is None:
        return 0
    variant_index = 0
    results = []
    while True:
        print(f'\n시험 방식 {variant_index + 1}/5')
        print('Enter: 왼쪽 짧게 / R: 오른쪽 짧게 / S: 정지 / N: 다음 방식 / Q: 종료')
        choice = input('> ').strip().casefold()
        if choice == 'q':
            return 0
        if choice == 'n':
            variant_index = (variant_index + 1) % len(FORMATS)
            continue
        if choice not in ('', 'r', 's'):
            continue
        direction = {'': 'LEFT', 'r': 'RIGHT', 's': 'STOP'}[choice]
        if direction != 'STOP':
            for seconds in (3, 2, 1):
                print(f'{seconds}...', flush=True)
                time.sleep(1)
        result = pulse(camera, FORMATS[variant_index], direction)
        results.append(result)
        save_results(results)
        if direction == 'STOP':
            print('정지 요청:', result.get('initial_stop_status', '응답 없음'))
            continue
        if 'move_status' not in result:
            print('연결 검사에 실패해 이동 요청을 보내지 않았습니다.')
            print('다른 영상 연결을 줄이거나 다음 방식으로 시험하세요.')
            continue
        print('이동 응답:', result['move_status'], '/ 자동 정지 응답:', result.get('timed_stop_status', '응답 없음'))
        if result.get('timed_stop_status') != 200 and result.get('final_stop_status') != 200:
            print('정지 응답을 받지 못했습니다. 제조사 앱에서 정지 상태를 확인하세요.')
        print('응답 코드만으로는 실제 동작 여부를 알 수 없습니다.')
        observed = input('실제로 움직였나요? Y: 움직임 / N: 안 움직임 / Enter: 미확인 > ').strip().casefold()
        result['physical_result'] = {'y': 'moved', 'n': 'not_moved'}.get(observed, 'unconfirmed')
        save_results(results)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print('\n시험을 종료했습니다.')
    except (OSError, ValueError, KeyError, IndexError):
        print('시험을 시작하지 못했습니다. 등록 정보와 네트워크를 확인하세요.')
        raise SystemExit(1)
