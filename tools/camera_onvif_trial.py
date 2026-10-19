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

# Re-export the shared protocol API for existing manual tools and callers.
from onvif_control import (SOAP, WSSE, WSU, PROFILE, ENCODING, DEVICE, MEDIA, PTZ,
    SCHEMA, READ_OPERATIONS, ALLOWED, ERRORS, element, direction_valid,
    envelope, service_path, Client, pulse)


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
    print(f'이동 전 {args.delay}초 대기합니다. 상하좌우의 짧은 이동은 사용자 시험으로 확인했습니다.')
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
