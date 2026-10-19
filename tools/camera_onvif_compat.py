"""Opt-in manual wire-format comparisons; never used by the app player.

ONVIF PTZ WSDL: https://www.onvif.org/ver20/ptz/wsdl/ptz.wsdl
No repeating movement, token collection, presets, settings writes or audio.
"""
import json
from pathlib import Path
import threading
import time
import xml.etree.ElementTree as ET

from camfloat.onvif_control import Client, PTZ, SCHEMA, SOAP, direction_valid


VARIANTS = {
    '1': ('minimal', 'minimal', '최소 이동 요청 + 최소 정지 요청'),
    '2': ('minimal', 'zero', '최소 이동 요청 + 속도 0 정지'),
    '3': ('space', 'zero', '좌표계 명시 이동 + 속도 0 정지'),
}


class CompatibilityClient(Client):
    """Keep experiments out of the app's validated direction input rules."""
    def __init__(self, camera, *args, **kwargs):
        super().__init__(camera, *args, **kwargs)
        self.move_format = 'minimal'
        self.stop_format = 'minimal'

    def build_envelope(self, namespace, operation, pan, tilt, device_timeout_ms):
        if namespace != PTZ or operation not in ('ContinuousMove', 'Stop'):
            return super().build_envelope(namespace, operation, pan, tilt, device_timeout_ms)
        if self.move_format not in ('minimal', 'space') or self.stop_format not in ('minimal', 'zero'):
            raise ValueError('Unsupported comparison')
        zero_stop = (operation == 'ContinuousMove' and type(pan) is int and pan == 0
                     and type(tilt) is int and tilt == 0)
        if zero_stop and self.stop_format != 'zero':
            raise ValueError('Zero velocity is only permitted for the explicit stop comparison')
        body = super().build_envelope(namespace, operation, 1 if zero_stop else pan,
                                      tilt, device_timeout_ms)
        root = ET.fromstring(body)
        op = root.find('{' + SOAP + '}Body').find('{' + PTZ + '}' + operation)
        if operation == 'Stop':
            # Both optional axis flags omitted, keeping the ProfileToken.
            for field in ('PanTilt', 'Zoom'):
                op.remove(op.find('{' + PTZ + '}' + field))
        else:
            op.remove(op.find('{' + PTZ + '}Timeout'))
            velocity = op.find('{' + PTZ + '}Velocity')
            velocity.remove(velocity.find('{' + SCHEMA + '}Zoom'))
            axes = velocity.find('{' + SCHEMA + '}PanTilt')
            axes.set('x', '0.0' if zero_stop else f'{pan:.1f}')
            axes.set('y', f'{tilt:.1f}')
            if self.move_format == 'space':
                axes.set('space', 'http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace')
        return ET.tostring(root, xml_declaration=True, encoding='utf-8')

    def request_stop(self):
        if self.stop_format == 'zero':
            return self.call(self.ptz_path, PTZ, 'ContinuousMove', pan=0, tilt=0, timeout=.3)[0]
        return self.call(self.ptz_path, PTZ, 'Stop', timeout=.3)[0]


def compare(client, variant, pan, tilt):
    if variant not in VARIANTS or not direction_valid(pan, tilt):
        raise ValueError('Unsupported comparison')
    client.move_format, client.stop_format, _ = VARIANTS[variant]
    report = dict(variant=variant, pan_sign=pan, tilt_sign=tilt, stop_after_ms=1000,
                  move_requests=0, physical_result='unconfirmed')
    interrupted = threading.Event()
    started = threading.Event()
    def stop():
        interrupted.wait(1)
        try:
            report['timed_stop'] = client.request_stop()
        except Exception as error:
            report['timed_stop'] = {'error': type(error).__name__, 'response_verified': False}
    timer = threading.Thread(target=stop, name='CamFloat compatibility stop', daemon=True)
    def sent():
        report['move_requests'] = 1
        timer.start()
        started.set()
    try:
        report['move'] = client.call(client.ptz_path, PTZ, 'ContinuousMove', pan=pan,
                                     tilt=tilt, timeout=.3, on_sent=sent)[0]
    except BaseException:
        interrupted.set()
        raise
    finally:
        if started.is_set():
            timer.join()
            try:
                report['final_stop'] = client.request_stop()
            finally:
                # Retain one conventional Stop as an independent fallback.
                report['fallback_stop'] = client.call(client.ptz_path, PTZ, 'Stop', timeout=.3)[0]
    return report


def load_history(path):
    try:
        if path.stat().st_size > 1024 * 1024:
            return []
        data = json.loads(path.read_text(encoding='utf-8'))
        return data[-50:] if isinstance(data, list) and all(isinstance(r, dict) for r in data) else []
    except (OSError, ValueError):
        return []


def menu(client, camera, delay, root):
    print('\nONVIF 호환성 비교 · 실제 렌즈를 보며 한 번씩 시험하세요.')
    print('이동 명령 한 번 → 1초 뒤 정지 요청. 반복 전송은 없습니다.')
    print('이번 방식은 기기 시간 제한을 생략합니다. 정지 동작은 아직 미확인입니다.')
    print('멈추지 않으면 제조사 앱에서 멈추세요. Q는 다음 시험을 종료합니다.')
    variant = '1'
    path = Path(root) / 'verification/current/camera-control/compat-manual-latest.json'
    results = load_history(path)
    while True:
        print(f'\n현재 방식 {variant}: {VARIANTS[variant][2]}')
        print('1/2/3: 방식 선택 · L/R/U/D: 좌/우/상/하 · Q: 종료')
        choice = input('> ').strip().casefold()
        if choice == 'q':
            return 0
        if choice in VARIANTS:
            variant = choice
            continue
        directions = {'l': (-1, 0), 'r': (1, 0), 'u': (0, 1), 'd': (0, -1)}
        if choice not in directions:
            continue
        if delay:
            print(f'{delay}초 뒤 한 번 전송합니다.', flush=True)
            time.sleep(delay)
        result = compare(client, variant, *directions[choice])
        result['camera_number'] = camera['number']
        results.append(result)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(results[-50:], indent=2) + '\n', encoding='utf-8')
        answer = input('C: 연속 이동 후 멈춤 / S: 한 칸 / N: 이동 없음 / X: 계속 움직임 / Enter: 미확인 > ').strip().casefold()
        result['physical_result'] = {'c': 'continuous_and_stopped', 's': 'single_step',
                                     'n': 'not_moved', 'x': 'did_not_stop'}.get(answer, 'unconfirmed')
        path.write_text(json.dumps(results[-50:], indent=2) + '\n', encoding='utf-8')
        if answer == 'x':
            print('제조사 앱에서 멈춘 뒤 상태를 확인하세요. 추가 시험은 중단합니다.')
            return 1
