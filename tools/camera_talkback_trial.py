"""Manual camera speaker experiment using a quiet generated tone, never a mic.

Vendor framing candidate: https://github.com/realldz/yoosee-intercom
RTSP OPEN acknowledgement is not proof of audible camera output.
"""
import argparse
import json
import math
from pathlib import Path
import struct
import sys
import time
from urllib.parse import urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.camera_ptz_trial import Client, load_cameras

RATE = 8000
DURATION = 2.0
AMPLITUDE = 1000  # About 3% of signed 16-bit full scale, no volume setting changes.


def tone_frames(seconds=DURATION):
    """Repeat two soft notes with gaps for a bounded interval at 8 kHz."""
    if not 1 <= seconds <= 30 or not float(seconds).is_integer():
        raise ValueError('Duration must be 1 to 30 whole seconds')
    for frame in range(int(seconds * 50)):
        samples = []
        for offset in range(160):
            absolute_t = (frame * 160 + offset) / RATE
            t = absolute_t % 2
            frequency = 0
            start = 0
            if .4 <= t < .65:
                frequency, start = 440, .4
            elif .9 <= t < 1.15:
                frequency, start = 660, .9
            if frequency:
                elapsed = t - start
                fade = min(1, elapsed / .015, (.25 - elapsed) / .015, (seconds - absolute_t) / .015)
                value = round(AMPLITUDE * max(0, fade) * math.sin(2 * math.pi * frequency * elapsed))
            else:
                value = 0
            samples.append(value)
        pcm = struct.pack('<160h', *samples)
        payload = bytes(12) + pcm
        # This documented vendor candidate uses little-endian length, not RTP.
        yield struct.pack('<BBH', 0x24, 0x02, len(payload)) + payload


def trial(camera, path='/onvif0', literal_length=True, send_tone=True,
          client_factory=Client, sleeper=time.sleep, monotonic=time.monotonic,
          duration_seconds=DURATION):
    if path not in ('/onvif0', '/onvif1'):
        raise ValueError('Unsupported audio path')
    if not 1 <= duration_seconds <= 30 or not float(duration_seconds).is_integer():
        raise ValueError('Duration must be 1 to 30 whole seconds')
    result = dict(camera_number=camera['number'], path_variant=path,
                  literal_length=literal_length, microphone_used=False, frames_sent=0,
                  sample_rate=RATE, generated_audio_seconds=duration_seconds if send_tone else 0,
                  physical_result='unconfirmed')
    client = None
    open_attempted = False
    def headers(command):
        return ['Content-type: AudioCtlCmd:' + command,
                'Content-length: ' + ('strlen(Content-type)' if literal_length else '0')]
    try:
        client = client_factory(camera['url'])
        result['description_status'] = client.request('DESCRIBE', ['Accept: application/sdp'])
        if result['description_status'] != 200:
            return result
        parts = client.parts
        client.uri = urlunsplit(('rtsp', f'{parts.hostname}:{parts.port or 554}', path, '', ''))
        open_attempted = True
        result['open_status'] = client.request('USER_CMD_SET', headers('OPEN'))
        if result['open_status'] != 200 or not send_tone:
            return result
        deadline = monotonic() + duration_seconds + 1
        started = monotonic()
        for index, frame in enumerate(tone_frames(duration_seconds)):
            if monotonic() > deadline:
                result['error'] = 'transmission_deadline'
                break
            wait = started + index * .02 - monotonic()
            if wait > 0:
                sleeper(wait)
            client.sock.sendall(frame)
            result['frames_sent'] += 1
        if result['frames_sent'] == int(duration_seconds * 50):
            remaining = started + duration_seconds - monotonic()
            if remaining > 0:
                sleeper(remaining)
    except (OSError, ValueError, IndexError) as error:
        result['error'] = type(error).__name__
    finally:
        if client:
            if open_attempted:
                try:
                    result['close_status'] = client.request('USER_CMD_SET', headers('CLOSE'))
                except (OSError, ValueError, IndexError) as error:
                    result['close_error'] = type(error).__name__
            client.close()
    return result


def save(results, probe=False):
    folder = ROOT / 'verification/current/camera-control'
    folder.mkdir(parents=True, exist_ok=True)
    filename = 'talkback-probe-latest.json' if probe else 'talkback-manual-latest.json'
    (folder / filename).write_text(json.dumps(results[-30:], indent=2) + '\n', encoding='utf-8')


def seconds_argument(value, lower, upper):
    try:
        seconds = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError('초 단위 정수를 입력하세요.') from None
    if not lower <= seconds <= upper:
        raise argparse.ArgumentTypeError(f'{lower}~{upper}초 범위로 입력하세요.')
    return seconds


def prompt_seconds(title, default, lower, upper):
    while True:
        value = input(f'{title} ({lower}~{upper}초, Enter: {default}초): ').strip()
        if not value:
            return default
        try:
            return seconds_argument(value, lower, upper)
        except argparse.ArgumentTypeError as error:
            print(str(error))


def countdown(seconds, sleeper=time.sleep):
    for remaining in range(seconds, 0, -1):
        if remaining <= 10 or remaining % 10 == 0:
            print(f'시작까지 {remaining}초...', flush=True)
        sleeper(1)


def main(argv=None):
    parser = argparse.ArgumentParser(description='카메라 스피커 테스트 · 마이크 사용 안 함')
    parser.add_argument('--probe', action='store_true', help='첫 내부망 기기에 열기·닫기만 요청. 소리 전송 없음')
    parser.add_argument('--delay', type=lambda value: seconds_argument(value, 0, 300),
                        help='시작 대기 시간 (0~300초). 생략하면 실행 중 입력')
    parser.add_argument('--duration', type=lambda value: seconds_argument(value, 1, 30),
                        help='테스트음 전송 시간 (1~30초). 생략하면 실행 중 입력')
    args = parser.parse_args(argv)
    cameras = load_cameras()
    if not cameras:
        print('시험할 내부망 카메라가 없습니다.')
        return 1
    if args.probe:
        result = trial(cameras[0], send_tone=False)
        save([result], probe=True)
        print(json.dumps(result, indent=2))
        return 0
    print('\nCamFloat · 카메라 스피커 시험\n')
    for camera in cameras:
        name = ''.join(c for c in camera.get('name', '') if c.isprintable())[:60]
        print(f"  {camera['number']}. {name}")
    number = input('\n시험할 카메라 번호 (Q: 종료): ').strip()
    camera = next((c for c in cameras if str(c['number']) == number), None)
    if camera is None:
        return 0
    print('\n작은 테스트음을 간격을 두고 반복합니다. 마이크와 카메라 음량 설정은 사용하지 않습니다.')
    print('소리가 나면 카메라 바로 옆에서 들리는지 확인하세요.')
    delay = args.delay if args.delay is not None else prompt_seconds('몇 초 후 시작할까요?', 10, 0, 300)
    duration = args.duration if args.duration is not None else prompt_seconds('몇 초 동안 보낼까요?', 3, 1, 30)
    variants = [('/onvif0', True), ('/onvif1', False), ('/onvif1', True)]
    variant = 0
    results = []
    while True:
        print(f'\n{delay}초 후 시작 · {duration}초 동안 전송')
        choice = input(f'시험 방식 {variant + 1}/3 · Enter: 시작 / T: 시간 설정 / N: 다음 방식 / Q: 종료 > ').strip().casefold()
        if choice == 'q':
            return 0
        if choice == 'n':
            variant = (variant + 1) % len(variants)
            continue
        if choice == 't':
            delay = prompt_seconds('몇 초 후 시작할까요?', delay, 0, 300)
            duration = prompt_seconds('몇 초 동안 보낼까요?', duration, 1, 30)
            continue
        if choice:
            continue
        countdown(delay)
        print(f'연결 후 {duration}초 동안 테스트음을 전송합니다.', flush=True)
        path, literal = variants[variant]
        result = trial(camera, path, literal, duration_seconds=duration)
        result['start_delay_seconds'] = delay
        results.append(result)
        save(results)
        if not result['frames_sent']:
            print('음성 데이터를 전송하지 못했습니다. 다음 방식으로 시험할 수 있습니다.')
            continue
        print('테스트음 데이터 전송:', result['frames_sent'], f'/ {duration * 50}개. 실제 청취 확인이 필요합니다.')
        heard = input('카메라에서 들렸나요? Y: 들림 / N: 안 들림 / Enter: 미확인 > ').strip().casefold()
        result['physical_result'] = {'y': 'heard', 'n': 'not_heard'}.get(heard, 'unconfirmed')
        save(results)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print('\n시험을 종료했습니다.')
    except (OSError, ValueError, KeyError, IndexError):
        print('시험을 진행하지 못했습니다. 등록 정보와 네트워크를 확인하세요.')
        raise SystemExit(1)
