"""Manual ONVIF PTZ investigation. No cloud account, media or microphone access.

Uses ONVIF Core UsernameToken PasswordDigest and PTZ ContinuousMove/Stop.
Device disconnects are recorded as unconfirmed, never interpreted as success.
"""
import argparse
import base64
import datetime as dt
import hashlib
import http.client
import json
from pathlib import Path
import secrets
import sys
import threading
import time
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.camera_ptz_trial import load_cameras

SOAP = 'http://www.w3.org/2003/05/soap-envelope'
WSSE = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd'
WSU = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd'
PROFILE = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0'
ENCODING = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0'
DEVICE = 'http://www.onvif.org/ver10/device/wsdl'
MEDIA = 'http://www.onvif.org/ver10/media/wsdl'
PTZ = 'http://www.onvif.org/ver20/ptz/wsdl'
SCHEMA = 'http://www.onvif.org/ver10/schema'
READ_OPERATIONS = {'GetCapabilities', 'GetProfiles', 'GetNodes', 'GetStatus', 'GetPresets',
                   'GetAudioOutputs', 'GetAudioDecoderConfigurations', 'GetAudioOutputConfigurations'}
ALLOWED = READ_OPERATIONS | {'ContinuousMove', 'Stop'}
ERRORS = (OSError, ValueError, http.client.HTTPException, ET.ParseError)
for prefix, namespace in [('s', SOAP), ('wsse', WSSE), ('wsu', WSU), ('tds', DEVICE),
                          ('trt', MEDIA), ('tptz', PTZ), ('tt', SCHEMA)]:
    ET.register_namespace(prefix, namespace)


def element(parent, namespace, name, text=None, **attributes):
    child = ET.SubElement(parent, ET.QName(namespace, name), attributes)
    child.text = text
    return child


def direction_valid(pan, tilt):
    return (type(pan) is int and type(tilt) is int
            and (pan, tilt) in ((-1, 0), (1, 0), (0, -1), (0, 1)))


def envelope(parts, namespace, operation, profile_token=None, pan=None, tilt=0):
    if operation not in ALLOWED or (pan is not None and not direction_valid(pan, tilt)) or (pan is None and tilt != 0):
        raise ValueError('Unsupported request')
    root = ET.Element(ET.QName(SOAP, 'Envelope'))
    header = element(root, SOAP, 'Header')
    token = element(element(header, WSSE, 'Security'), WSSE, 'UsernameToken')
    nonce = secrets.token_bytes(16)
    created = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + unquote(parts.password or '').encode()).digest()).decode()
    element(token, WSSE, 'Username', unquote(parts.username or ''))
    element(token, WSSE, 'Password', digest, Type=PROFILE + '#PasswordDigest')
    element(token, WSSE, 'Nonce', base64.b64encode(nonce).decode(), EncodingType=ENCODING + '#Base64Binary')
    element(token, WSU, 'Created', created)
    op = element(element(root, SOAP, 'Body'), namespace, operation)
    if operation == 'GetCapabilities':
        element(op, DEVICE, 'Category', 'All')
    if operation in ('Stop', 'ContinuousMove', 'GetStatus', 'GetPresets'):
        if not profile_token:
            raise ValueError('Profile required')
        element(op, PTZ, 'ProfileToken', profile_token)
    if operation == 'Stop':
        element(op, PTZ, 'PanTilt', 'true')
        element(op, PTZ, 'Zoom', 'false')
    if operation == 'ContinuousMove':
        if not direction_valid(pan, tilt):
            raise ValueError('Direction required')
        velocity = element(op, PTZ, 'Velocity')
        element(velocity, SCHEMA, 'PanTilt', x=str(pan), y=str(tilt))
        element(velocity, SCHEMA, 'Zoom', x='0')
        # Device-side bound plus an independent explicit Stop request below.
        element(op, PTZ, 'Timeout', 'PT0.25S')
    return ET.tostring(root, xml_declaration=True, encoding='utf-8')


def service_path(url, host):
    parts = urlsplit(url or '')
    if (parts.scheme != 'http' or parts.hostname != host or (parts.port or 80) != 5000
            or parts.username or parts.password or parts.query or parts.fragment
            or not parts.path.startswith('/onvif/') or any(c in parts.path for c in '\r\n')):
        raise ValueError('Untrusted service address')
    return parts.path


class Client:
    def __init__(self, camera, connection_factory=http.client.HTTPConnection):
        self.parts = urlsplit(camera['url'])
        self.connection_factory = connection_factory
        self.profile_token = None
        self.ptz_path = None

    def call(self, path, namespace, operation, pan=None, on_sent=None, tilt=0):
        body = envelope(self.parts, namespace, operation, self.profile_token, pan, tilt)
        connection = self.connection_factory(self.parts.hostname, 5000, timeout=1)
        result = {'operation': operation, 'response_verified': False, 'request_sent': False}
        root = None
        action = namespace + '/' + operation
        try:
            connection.request('POST', path, body, {'Content-Type': 'application/soap+xml; charset=utf-8; action="' + action + '"',
                                                   'SOAPAction': '"' + action + '"', 'Connection': 'close'})
            result['request_sent'] = True
            if on_sent:
                on_sent()
            response = connection.getresponse()
            result['http_status'] = response.status
            raw = response.read(262145)
            if len(raw) > 262144 or b'<!DOCTYPE' in raw.upper():
                raise ValueError('Invalid SOAP reply')
            root = ET.fromstring(raw)
            soap_body = root.find('{' + SOAP + '}Body')
            if soap_body is not None:
                fault = soap_body.find('{' + SOAP + '}Fault')
                expected = soap_body.find('{' + namespace + '}' + operation + 'Response')
                result['soap_fault'] = fault is not None
                result['response_verified'] = response.status == 200 and fault is None and expected is not None
        except ERRORS as error:
            result['error'] = type(error).__name__
        finally:
            connection.close()
        return result, root

    def discover(self):
        report = {'capabilities_verified': False, 'profile_verified': False}
        caps = None
        for _ in range(2):
            result, caps = self.call('/onvif/device_service', DEVICE, 'GetCapabilities')
            if result['response_verified']:
                break
        report['capabilities_verified'] = result['response_verified']
        if not result['response_verified']:
            return report
        local = lambda node: node.tag.rsplit('}', 1)[-1]
        services = {}
        for node in caps.iter():
            if local(node) in ('Media', 'PTZ'):
                addr = next((n.text for n in node if local(n) == 'XAddr'), None)
                if addr:
                    services[local(node)] = service_path(addr, self.parts.hostname)
        if 'PTZ' not in services or 'Media' not in services:
            return report
        self.ptz_path = services['PTZ']
        for path in dict.fromkeys([services['Media'], '/onvif/media_service']):
            result, profiles = self.call(path, MEDIA, 'GetProfiles')
            if not result['response_verified']:
                continue
            for profile in profiles.iter('{' + MEDIA + '}Profiles'):
                ptz = profile.find('{' + SCHEMA + '}PTZConfiguration')
                if ptz is not None and profile.get('token'):
                    self.profile_token = profile.get('token')
                    report['profile_verified'] = True
                    report['ptz_configuration_present'] = True
                    return report
        return report

    def control(self, operation, pan=None, on_sent=None, tilt=0):
        if not self.ptz_path or not self.profile_token:
            raise ValueError('Discovery required')
        return self.call(self.ptz_path, PTZ, operation, pan, on_sent, tilt=tilt)[0]


def pulse(client, pan, tilt=0):
    if not direction_valid(pan, tilt):
        raise ValueError('Unsupported direction')
    result = {'pan_sign': pan, 'tilt_sign': tilt, 'requested_ms': 200, 'device_timeout_ms': 250, 'physical_result': 'unconfirmed'}
    def stop():
        result['timed_stop'] = client.control('Stop')
    timer = threading.Timer(.2, stop)
    started = False
    def sent():
        nonlocal started
        timer.start()
        started = True
    try:
        result['move'] = client.control('ContinuousMove', pan, on_sent=sent, tilt=tilt)
    finally:
        try:
            if started:
                timer.join(2)
        finally:
            result['final_stop'] = client.control('Stop')
    return result


def save(results, probe=False):
    folder = ROOT / 'verification/current/camera-control'
    folder.mkdir(parents=True, exist_ok=True)
    filename = 'onvif-probe-latest.json' if probe else 'onvif-manual-latest.json'
    (folder / filename).write_text(json.dumps(results[-50:], indent=2) + '\n', encoding='utf-8')


def previous_results():
    path = ROOT / 'verification/current/camera-control/onvif-manual-latest.json'
    try:
        if path.stat().st_size > 1024 * 1024:
            return []
        result = json.loads(path.read_text(encoding='utf-8'))
        return result[-50:] if isinstance(result, list) and all(isinstance(row, dict) for row in result) else []
    except (OSError, ValueError):
        return []


def main(argv=None):
    parser = argparse.ArgumentParser(description='카메라 ONVIF 회전 시험')
    parser.add_argument('--probe', action='store_true', help='기능 조회만 수행. 이동·정지 요청 없음')
    parser.add_argument('--delay', type=int, default=3, help='이동 전 대기 시간, 0~300초 (기본 3초)')
    args = parser.parse_args(argv)
    if not 0 <= args.delay <= 300:
        parser.error('대기 시간은 0~300초로 입력하세요.')
    cameras = load_cameras()
    if args.probe:
        reports = [{'camera_number': c['number'], **Client(c).discover()} for c in cameras]
        save(reports, probe=True)
        print(json.dumps(reports, indent=2))
        return 0
    print('\nCamFloat · ONVIF 회전 시험\n')
    for camera in cameras:
        name = ''.join(c for c in camera.get('name', '') if c.isprintable())[:60]
        print(f"  {camera['number']}. {name}")
    number = input('\n시험할 카메라 번호 (Q: 종료): ').strip()
    camera = next((c for c in cameras if str(c['number']) == number), None)
    if camera is None:
        return 0
    client = Client(camera)
    discovered = client.discover()
    results = previous_results()
    results.append({'camera_number': camera['number'], 'discovery': discovered})
    save(results)
    if not discovered.get('profile_verified'):
        print('회전 제어 정보를 확인하지 못했습니다. 이동 요청은 보내지 않았습니다.')
        return 1
    paths = list(dict.fromkeys([client.ptz_path, '/onvif/ptz_service']))
    path_index = 0
    print('\n회전 제어 정보 확인 완료. 실제 렌즈를 보면서 시험하세요.')
    print('0.2초 뒤 정지를 요청합니다. 멈추지 않으면 제조사 앱에서 정지하세요.')
    print('기기가 응답 없이 연결을 끊을 수 있으므로 실제 움직임을 확인해야 합니다.')
    print('렌즈 반전 설정에 따라 이동 방향이 다를 수 있습니다.')
    print(f'이동 전 {args.delay}초 대기합니다. 상하 방향은 아직 실제 동작 미확인입니다.')
    while True:
        print(f'\n연결 경로 {path_index + 1}/{len(paths)}')
        choice = input('Enter/R: 좌우 양방향 / U/D: 상하 양방향 / S: 정지 / N: 다른 경로 / Q: 종료 > ').strip().casefold()
        if choice == 'q':
            return 0
        if choice == 'n':
            path_index = (path_index + 1) % len(paths)
            client.ptz_path = paths[path_index]
            continue
        if choice == 's':
            status = client.control('Stop')
            results.append({'camera_number': camera['number'], 'path_index': path_index + 1, 'stop': status})
            save(results)
            print('정지 응답 확인' if status['response_verified'] else '정지 요청 완료. 응답은 확인되지 않아 실제 상태를 확인하세요.')
            continue
        directions = {'': (-1, 0), 'r': (1, 0), 'u': (0, 1), 'd': (0, -1)}
        if choice not in directions:
            continue
        for seconds in range(args.delay, 0, -1):
            if seconds <= 5 or seconds % 10 == 0:
                print(f'{seconds}...', flush=True)
            time.sleep(1)
        pan, tilt = directions[choice]
        result = pulse(client, pan, tilt)
        result.update(camera_number=camera['number'], path_index=path_index + 1)
        results.append(result)
        save(results)
        print('이동 요청 완료. 응답만으로 실제 움직임을 판단하지 않습니다.')
        observed = input('움직이고 멈췄나요? Y: 움직이고 멈춤 / N: 움직임 없음 / Enter: 미확인 > ').strip().casefold()
        result['physical_result'] = {'y': 'moved_and_stopped', 'n': 'not_moved'}.get(observed, 'unconfirmed')
        save(results)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print('\n시험을 종료했습니다.')
    except ERRORS + (KeyError,):
        print('시험을 진행하지 못했습니다. 등록 정보와 네트워크를 확인하세요.')
        raise SystemExit(1)
