"""Portable, passwordless camera files. Every CamFloat client can open them.

The embedded format key prevents casual plain-text exposure only; it is not an
access-control boundary against someone who has the app or its source code.
Treat imported records as untrusted even after their GCM tag is checked.
"""
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from camera_model import new_camera, supports_quality, validate_rtsp_url
from camera_draft import duplicate_target

MAGIC = b'CamFloat\x00\x01'
MAX_BYTES = 4 * 1024 * 1024
MAX_CAMERAS = 256
# Shared across installations and future compatible releases. Not a user secret.
_FORMAT_KEY = bytes.fromhex('a03ba32b45d3aee1087f0767bc9948a7235df337c1443b839fe711390245f263')


def _record(raw):
    if not isinstance(raw, dict) or raw.get('connection_locked'):
        raise ValueError('읽을 수 없는 카메라 정보가 있습니다.')
    result = new_camera()
    for key, limit in [('name', 80), ('url', 8192), ('sd_url', 8192)]:
        value = raw.get(key, '')
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError('카메라 정보가 올바르지 않습니다.')
        result[key] = value
    validate_rtsp_url(result['url'])
    if result['sd_url']:
        validate_rtsp_url(result['sd_url'])
    enabled = raw.get('enabled', True)
    if type(enabled) is not bool:
        raise ValueError('카메라 정보가 올바르지 않습니다.')
    result['enabled'] = enabled
    if raw.get('quality', 'HD') not in ('HD', 'SD'):
        raise ValueError('카메라 정보가 올바르지 않습니다.')
    result['quality'] = raw.get('quality', 'HD')
    if result['quality'] == 'SD' and not supports_quality(result):
        raise ValueError('SD 주소가 없습니다.')
    # Audio is a local preference, never a transferred camera property.
    # Ignore these fields even in older archives that used to include them.
    return result


def encode(cameras):
    if not cameras or len(cameras) > MAX_CAMERAS:
        raise ValueError('내보낼 카메라 목록을 확인하세요.')
    keys = ('name', 'url', 'sd_url', 'quality', 'enabled')
    records = [{key: checked[key] for key in keys} for checked in map(_record, cameras)]
    payload = json.dumps(dict(version=1, cameras=records), ensure_ascii=False, allow_nan=False).encode('utf-8')
    nonce = os.urandom(12)
    blob = MAGIC + nonce + AESGCM(_FORMAT_KEY).encrypt(nonce, payload, MAGIC)
    if len(blob) > MAX_BYTES:
        raise ValueError('카메라 목록이 너무 큽니다.')
    return blob


def decode(blob):
    if len(blob) > MAX_BYTES or not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 28:
        raise ValueError('CamFloat 카메라 파일을 선택하세요.')
    try:
        start = len(MAGIC)
        payload = AESGCM(_FORMAT_KEY).decrypt(blob[start:start + 12], blob[start + 12:], MAGIC)
        raw = json.loads(payload)
        if not isinstance(raw, dict) or type(raw.get('version')) is not int or raw['version'] != 1:
            raise ValueError()
        records = raw.get('cameras')
        if not isinstance(records, list) or not 1 <= len(records) <= MAX_CAMERAS:
            raise ValueError()
        return [_record(record) for record in records]
    except (InvalidTag, UnicodeError, ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError('파일을 읽을 수 없습니다. 다른 파일을 선택하세요.') from None


def read_file(path):
    with Path(path).open('rb') as stream:
        return decode(stream.read(MAX_BYTES + 1))


def import_candidates(records, existing):
    result = []
    duplicates = 0
    number = max([c.get('number') or 0 for c in existing] + [0])
    for raw in records:
        camera = _record(raw)
        if duplicate_target(camera['url'], existing + result, camera['id']):
            duplicates += 1
            continue
        number += 1
        camera['number'] = number
        result.append(camera)
    return result, duplicates
