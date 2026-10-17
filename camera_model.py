from __future__ import annotations

import base64
import copy
import ctypes
import json
import os
import shutil
import sys
import re
import tempfile
import ipaddress
import uuid
from ctypes import wintypes
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

APP_NAME = 'CamFloat'
DLL_HANDLES = []
LOAD_WARNINGS = []


def bounded_int(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (ValueError, TypeError, OverflowError):
        return default


def redact(text):
    # Query strings can contain access tokens, so redact the entire RTSP URL.
    return re.sub(r'(?i)rtsp[s]?://[^\s\'\"<>]+', 'rtsp://[주소 숨김]', str(text))


def data_path():
    folder = Path(os.environ.get('CAMFLOAT_DATA_DIR') or Path(os.environ['LOCALAPPDATA']) / APP_NAME)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / 'settings.json'


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]


def crypt(value, decrypt=False):
    if not value:
        return ''
    if decrypt and not value.startswith('dpapi:'):
        return value
    raw = base64.b64decode(value[6:]) if decrypt else value.encode('utf-8')
    buf = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    result = Blob()
    function = getattr(ctypes.windll.crypt32, 'CryptUnprotectData' if decrypt else 'CryptProtectData')
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p if decrypt else wintypes.LPCWSTR,
                         ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                         ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None if decrypt else APP_NAME, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError()
    try:
        result_bytes = ctypes.string_at(result.data, result.size)
        return result_bytes.decode('utf-8') if decrypt else 'dpapi:' + base64.b64encode(result_bytes).decode('ascii')
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(ctypes.cast(result.data, ctypes.c_void_p))


def new_camera(name='', url=''):
    return dict(id=uuid.uuid4().hex, number=None, enabled=True, name=name, url=url, sd_url='', quality='HD', volume=100, muted=False)


def default_config():
    return dict(version=4, cameras=[], slots=[None] * 4, layout_slots=None, layout=1, always_on_top=True,
                hardware_acceleration=True, opacity=100, geometry=None)


def ensure_camera_numbers(cameras):
    used = set()
    next_number = max([c.get('number', 0) for c in cameras if type(c.get('number')) is int] + [0]) + 1
    for camera in cameras:
        number = camera.get('number')
        if type(number) is not int or number < 1 or number in used:
            while next_number in used:
                next_number += 1
            camera['number'] = next_number
            next_number += 1
        used.add(camera['number'])
        camera['enabled'] = bool(camera.get('enabled', True))


def ensure_layout_slots(config):
    ensure_camera_numbers(config['cameras'])
    allowed = {camera['id'] for camera in config['cameras'] if camera.get('enabled', True)}
    maps = config.get('layout_slots')
    legacy = config.get('slots', [])
    legacy = legacy if isinstance(legacy, list) else []
    clean = {}
    for count in (1, 2, 4):
        source = maps.get(str(count), legacy) if isinstance(maps, dict) else legacy
        source = source if isinstance(source, list) else []
        slots, used = [None] * 4, set()
        for index, cid in enumerate(source[:count]):
            if isinstance(cid, str) and cid in allowed and cid not in used:
                slots[index] = cid
                used.add(cid)
        clean[str(count)] = slots
    config['layout_slots'] = clean
    config['slots'] = clean[str(config['layout'])]
    return clean


def fill_empty_slots(config, identifiers):
    maps = ensure_layout_slots(config)
    allowed = {c['id'] for c in config['cameras'] if c.get('enabled', True)}
    for count in (1, 2, 4):
        slots = maps[str(count)]
        for cid in identifiers:
            if cid in allowed and cid not in slots:
                empty = next((i for i in range(count) if slots[i] is None), None)
                if empty is not None:
                    slots[empty] = cid


def normalize(raw, encrypted=False):
    if not isinstance(raw, dict):
        raise ValueError('설정 형식이 올바르지 않습니다.')
    result = default_config()
    for key in ('always_on_top', 'hardware_acceleration'):
        result[key] = bool(raw.get(key, True))
    layout = raw.get('layout', 1)
    result['layout'] = layout if type(layout) is int and layout in (1, 2, 4) else 1
    result['opacity'] = bounded_int(raw.get('opacity'), 100, 20, 100)
    geometry = raw.get('geometry')
    if isinstance(geometry, list) and len(geometry) == 4:
        try:
            result['geometry'] = [int(n) for n in geometry]
            result['geometry'][:2] = [max(-100000, min(100000, n)) for n in result['geometry'][:2]]
            result['geometry'][2:] = [max(1, min(16384, n)) for n in result['geometry'][2:]]
        except (ValueError, TypeError, OverflowError):
            pass
    if 'cameras' not in raw:
        streams = raw.get('streams', [])
        streams = streams if isinstance(streams, list) else []
        requested = raw.get('order', list(range(len(streams))))
        requested = requested if isinstance(requested, list) else []
        order = list(dict.fromkeys(i for i in requested if isinstance(i, int)))
        order += [i for i in range(len(streams)) if i not in order]
        source = [streams[i] for i in order if isinstance(i, int) and 0 <= i < len(streams)]
    else:
        source = raw['cameras'] if isinstance(raw['cameras'], list) else []
    seen = set()
    for item in source:
        if not isinstance(item, dict) or not isinstance(item.get('url'), str) or not item['url']:
            continue
        camera = new_camera()
        camera.update({key: item[key] for key in camera if key in item})
        if not isinstance(camera['id'], str) or not camera['id'] or camera['id'] in seen:
            camera['id'] = uuid.uuid4().hex
        seen.add(camera['id'])
        camera['url'] = crypt(camera['url'], decrypt=True) if encrypted else camera['url']
        camera['sd_url'] = camera['sd_url'] if isinstance(camera['sd_url'], str) else ''
        if encrypted:
            camera['sd_url'] = crypt(camera['sd_url'], decrypt=True)
        try:
            urlsplit(camera['url'])
            urlsplit(camera['sd_url'])
        except ValueError:
            LOAD_WARNINGS.append('잘못된 카메라 주소가 있어 해당 항목을 제외했습니다. 이전 설정은 백업에 보관됩니다.')
            continue
        camera['name'] = str(camera['name'] or f"카메라 {len(seen)}")[:80]
        camera['quality'] = 'SD' if camera['quality'] == 'SD' else 'HD'
        if camera['quality'] == 'SD' and not supports_quality(camera):
            camera['quality'] = 'HD'
        camera['volume'] = bounded_int(camera['volume'], 100, 0, 100)
        camera['muted'] = bool(camera['muted'])
        result['cameras'].append(camera)
    ids = [c['id'] for c in result['cameras']]
    slots = raw.get('slots', ids[:4])
    slots = slots if isinstance(slots, list) else ids[:4]
    used = set()
    result['slots'] = []
    for cid in slots[:4]:
        valid = isinstance(cid, str) and cid in ids and cid not in used
        result['slots'].append(cid if valid else None)
        if valid:
            used.add(cid)
    result['slots'] += [None] * (4 - len(result['slots']))
    result['layout_slots'] = raw.get('layout_slots')
    ensure_layout_slots(result)
    return result


def load_config():
    LOAD_WARNINGS.clear()
    path = data_path()
    if not path.exists():
        return default_config()
    try:
        return normalize(json.loads(path.read_text(encoding='utf-8-sig')), encrypted=True)
    except (ValueError, TypeError, OSError):
        backup = path.with_suffix('.backup.json')
        try:
            restored = normalize(json.loads(backup.read_text(encoding='utf-8-sig')), encrypted=True)
        except (ValueError, TypeError, OSError):
            # Preserve the original for recovery before allowing a fresh config.
            damaged = path.with_name(f'settings-damaged-{uuid.uuid4().hex[:8]}.json')
            shutil.copy2(path, damaged)
            LOAD_WARNINGS.append('설정 파일을 읽지 못해 새 설정으로 시작했습니다. 기존 파일은 settings-damaged 백업에 보관했습니다.')
            return default_config()
        shutil.copy2(path, path.with_name(f'settings-damaged-{uuid.uuid4().hex[:8]}.json'))
        LOAD_WARNINGS.append('설정 파일을 읽지 못해 직전 저장 백업을 복구했습니다.')
        return restored


def save_config(config):
    ensure_layout_slots(config)
    path = data_path()
    if path.exists() and not path.with_name('settings-v1.backup.json').exists():
        try:
            previous = json.loads(path.read_text(encoding='utf-8-sig'))
            if isinstance(previous, dict) and 'streams' in previous:
                legacy = copy.deepcopy(previous)
                for camera in legacy.get('streams', []):
                    if isinstance(camera, dict) and camera.get('url') and not camera['url'].startswith('dpapi:'):
                        camera['url'] = crypt(camera['url'])
                path.with_name('settings-v1.backup.json').write_text(json.dumps(legacy, ensure_ascii=False), encoding='utf-8')
        except (ValueError, TypeError):
            pass
    stored = copy.deepcopy(config)
    for camera in stored['cameras']:
        camera['url'] = crypt(camera['url'])
        camera['sd_url'] = crypt(camera.get('sd_url', ''))
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='settings-', suffix='.tmp', delete=False) as stream:
            temp = Path(stream.name)
            json.dump(stored, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            try:
                normalize(json.loads(path.read_text(encoding='utf-8-sig')), encrypted=True)
                previous = json.loads(path.read_text(encoding='utf-8-sig'))
                for collection in ('cameras', 'streams'):
                    for camera in previous.get(collection, []):
                        if not isinstance(camera, dict):
                            continue
                        for key in ('url', 'sd_url'):
                            value = camera.get(key)
                            if isinstance(value, str) and value and not value.startswith('dpapi:'):
                                camera[key] = crypt(value)
                path.with_suffix('.backup.json').write_text(json.dumps(previous, ensure_ascii=False), encoding='utf-8')
            except (ValueError, TypeError, OSError):
                pass
        os.replace(temp, path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def camera_url(camera):
    if camera['quality'] == 'SD' and camera.get('sd_url'):
        return camera['sd_url']
    return stream_url_for_quality(camera['url'], camera['quality'])


def supports_quality(camera):
    path = urlsplit(camera['url']).path.rstrip('/').lower()
    return bool(camera.get('sd_url')) or not path or path.endswith(('/onvif1', '/onvif2'))


def validate_rtsp_url(url):
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() != 'rtsp' or not parts.hostname or any(c.isspace() for c in url):
            raise ValueError()
        if parts.port == 0 or parts.netloc.endswith(':') or parts.fragment:
            raise ValueError()
        if ':' in parts.hostname:
            ipaddress.IPv6Address(parts.hostname)
    except ValueError:
        raise ValueError('유효한 rtsp:// 주소와 포트(1–65535)를 입력하세요. 비밀번호의 #, @ 등은 % 인코딩하거나 IP 입력 방식을 사용하세요.') from None
    return parts


def stream_url_for_quality(url, quality):
    parts = urlsplit(url.strip())
    # Preserve arbitrary RTSP paths; change only the known ipTIME channel suffix.
    if parts.scheme.lower() != 'rtsp':
        return url
    path = parts.path.rstrip('/')
    if path.lower().endswith(('/onvif1', '/onvif2')):
        path = path[:-7]
    elif path:
        return url
    return urlunsplit((parts.scheme, parts.netloc, path + ('/onvif2' if quality == 'SD' else '/onvif1'),
                       parts.query, parts.fragment))


def build_url(host, port, username, password, path='/onvif1'):
    host = host.strip().strip('[]')
    if not host or any(ch in host for ch in '/@?#\\') or any(ch.isspace() for ch in host):
        raise ValueError('IP 또는 도메인만 입력하세요. 전체 주소는 RTSP 주소 입력 방식을 선택하세요.')
    if ':' in host:
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            raise ValueError('포트는 포트 칸에 따로 입력하세요. IP / 도메인 칸에는 주소만 입력하세요.') from None
        host = '[' + host + ']'
    if not 1 <= int(port) <= 65535:
        raise ValueError('포트는 1–65535 사이로 입력하세요.')
    if password and not username:
        raise ValueError('비밀번호를 사용하려면 아이디도 입력하세요.')
    auth = quote(username, safe='') + ':' + quote(password, safe='') + '@' if username else ''
    url = f"rtsp://{auth}{host}:{int(port)}/" + path.lstrip('/')
    validate_rtsp_url(url)
    return url


def address_label(url):
    try:
        parts = urlsplit(url)
        if parts.scheme == 'file':
            return '로컬 테스트 영상'
        host = parts.hostname or ''
        return f"{'[' + host + ']' if ':' in host else host}:{parts.port or 554}"
    except ValueError:
        return '주소 확인 필요'


def find_vlc_directory():
    candidates = [Path(getattr(sys, '_MEIPASS', '.')) / 'vlc']
    if os.environ.get('VLC_HOME'):
        candidates.append(Path(os.environ['VLC_HOME']))
    candidates += [Path(os.environ[key]) / 'VideoLAN/VLC' for key in ('ProgramFiles', 'ProgramFiles(x86)') if key in os.environ]
    return next((p for p in candidates if (p / 'libvlc.dll').is_file()), None)


def make_vlc_instance(folder, *options):
    DLL_HANDLES.append(os.add_dll_directory(str(folder)))
    os.environ['PATH'] = str(folder) + os.pathsep + os.environ.get('PATH', '')
    os.environ['VLC_PLUGIN_PATH'] = str(folder / 'plugins')
    import vlc
    # Follow VLC's default buffer. Forcing 450 ms can repeatedly display the
    # connection-time HEVC image on some cameras while counters still advance.
    return vlc.Instance('--no-video-title-show', '--quiet', '--rtsp-tcp', *options)
