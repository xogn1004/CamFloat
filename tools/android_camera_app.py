"""Inspect only the installed ipTIME CCTV APK through an authorized USB device.

Does not install apps, collect app data/accounts/logcat, or change phone settings.
APK code is read as ZIP data and is never executed or imported.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'com.cctv.iptime'
SDK_MARKERS = {
    'ThroughTek_TUTK_candidate': (b'iotc_initialize', b'avsendioctrl', b'avclientstart', b'libiotcapis', b'libavapis'),
    'PPCS_candidate': (b'ppcs_initialize', b'ppcs_connect', b'libppcs'),
    'HiChip_candidate': (b'hichip', b'hichip_p2p'),
    'ONVIF_candidate': (b'getcapabilities', b'continuousmove', b'getpresets'),
}
CONTROL_MARKERS = ('preset', 'privacy', 'ptz', 'talk', 'sleep')


class InvestigationError(Exception):
    pass


def adb_run(adb, args, timeout=20):
    try:
        return subprocess.run([str(adb), '-d', *args], capture_output=True, timeout=timeout,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired):
        raise InvestigationError('휴대폰 연결 명령을 실행하지 못했습니다.') from None


def apk_paths(output):
    paths = []
    for line in output.decode('utf-8', 'strict').splitlines():
        if not line.startswith('package:'):
            continue
        path = line[len('package:'):]
        parts = PurePosixPath(path)
        if (not path.startswith('/data/app/') or '..' in parts.parts
                or any(ord(c) < 32 for c in path)
                or not re.fullmatch(r'[A-Za-z0-9_.+-]+\.apk', parts.name)):
            raise InvestigationError('앱 파일 경로가 예상 형식과 달라 복사를 중단했습니다.')
        paths.append(path)
    if not paths or len(paths) > 30 or len(set(PurePosixPath(p).name for p in paths)) != len(paths):
        raise InvestigationError('ipTIME CCTV 앱 파일을 확인하지 못했습니다. 휴대폰의 앱 설치 상태를 확인하세요.')
    return paths


def inspect_apk(path):
    with path.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    report = dict(file=path.name, bytes=path.stat().st_size, sha256=checksum,
                  native_libraries=[], sdk_markers={name: False for name in SDK_MARKERS},
                  control_word_occurrences={name: 0 for name in CONTROL_MARKERS})
    if report['bytes'] > 256 * 1024 * 1024:
        raise InvestigationError('앱 파일이 분석 크기 제한을 초과했습니다.')
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 30000 or sum(e.file_size for e in entries) > 768 * 1024 * 1024:
            raise InvestigationError('앱 압축 구조가 분석 제한을 초과했습니다.')
        for entry in entries:
            native = bool(re.fullmatch(r'lib/[A-Za-z0-9_-]+/[A-Za-z0-9_.+-]+\.so', entry.filename))
            dex = bool(re.fullmatch(r'classes[0-9]*\.dex', entry.filename))
            if native:
                report['native_libraries'].append(entry.filename)
            if not (native or dex) or entry.file_size > 64 * 1024 * 1024:
                continue
            data = archive.read(entry).lower()
            for name, markers in SDK_MARKERS.items():
                if any(marker in data for marker in markers):
                    report['sdk_markers'][name] = True
            for name in CONTROL_MARKERS:
                report['control_word_occurrences'][name] += data.count(name.encode('ascii'))
    # Report only fixed categories and library filenames; never raw strings/URLs/keys.
    return report


def collect(adb, output):
    state = adb_run(adb, ['get-state'])
    if state.returncode or state.stdout.strip() != b'device':
        raise InvestigationError('USB로 휴대폰을 연결하고 USB 디버깅·이 PC 연결 허용을 완료하세요. 여러 USB 디버깅 기기가 연결돼 있다면 하나만 남겨주세요.')
    located = adb_run(adb, ['shell', 'pm', 'path', PACKAGE])
    if located.returncode:
        raise InvestigationError('ipTIME CCTV 앱의 파일 위치를 조회하지 못했습니다.')
    paths = apk_paths(located.stdout)
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    for remote in paths:
        filename = PurePosixPath(remote).name
        destination = output / filename
        pending = output / (filename + '.part')
        pulled = adb_run(adb, ['pull', remote, str(pending)], timeout=90)
        if pulled.returncode or not pending.is_file():
            raise InvestigationError('앱 파일 복사에 실패했습니다. 계정 데이터에는 접근하지 않았습니다.')
        inspection = inspect_apk(pending)
        inspection['file'] = filename
        pending.replace(destination)
        reports.append(inspection)
        print(f'앱 파일 확인: {filename}', flush=True)
    report = dict(package=PACKAGE, usb_only=True, account_data_collected=False,
                  logcat_collected=False, phone_modified=False, files=reports,
                  interpretation='SDK names and keyword hits are investigation hints, not verified camera features.')
    (output / 'inspection.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    adb = Path(os.environ['LOCALAPPDATA']) / 'CamFloatQA/android/platform-tools/adb.exe'
    if not adb.is_file():
        raise InvestigationError('준비된 Android 연결 도구를 찾지 못했습니다.')
    print('CamFloat · ipTIME CCTV 앱 조사\n')
    print('USB로 승인된 휴대폰에서 ipTIME CCTV APK만 복사합니다.')
    output = ROOT / 'verification/current/android-app'
    report = collect(adb, output)
    print(f"\n완료: 앱 파일 {len(report['files'])}개")
    print('계정 정보·사진·앱 데이터·다른 앱·통신 기록은 수집하지 않았습니다.')
    print('파일 위치: ' + str(output))
    print('조사 후 USB 디버깅을 끄고 연결을 해제해도 됩니다.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except InvestigationError as error:
        print(str(error))
        raise SystemExit(1)
    except (OSError, ValueError, zipfile.BadZipFile):
        print('앱 파일을 확인하지 못했습니다. 원본 앱이나 휴대폰 설정은 변경하지 않았습니다.')
        raise SystemExit(1)
