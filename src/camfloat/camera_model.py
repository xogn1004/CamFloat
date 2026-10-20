from __future__ import annotations

import base64
import copy
import ctypes
import json
import os
import sys
import re
import tempfile
import ipaddress
import uuid
from ctypes import wintypes
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

APP_NAME = 'CamFloat'
APP_TITLE = 'CamFloat - RTSP Stream Viewer'
APP_USER_MODEL_ID = 'CamFloat.Desktop.Player'
DLL_HANDLES = []
LOAD_WARNINGS = []


def bounded_int(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (ValueError, TypeError, OverflowError):
        return default


def redact(text, cameras=()):
    # Query strings can contain access tokens, so redact the entire RTSP URL.
    result = re.sub(r'(?i)rtsp[s]?://[^\s\'\"<>]+', 'rtsp://[주소 숨김]', str(text))
    for camera in cameras:
        for key in ('url', 'sd_url'):
            try:
                parts = urlsplit(camera.get(key, ''))
                for value in (parts.hostname, parts.username, parts.password):
                    if value and len(value) >= 3:
                        for spelling in {value, unquote(value)}:
                            result = result.replace(spelling, '[정보 숨김]')
            except ValueError:
                pass
    return result


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
    return dict(id=uuid.uuid4().hex, number=None, enabled=True, name=name, url=url, sd_url='', quality='HD', volume=100, muted=False, control_port=5000, ptz=None)


def default_config():
    return dict(version=4, cameras=[], slots=[None] * 4, layout_slots=None, layout=1, split_orientation='horizontal', always_on_top=False,
                hardware_acceleration=True, master_muted=False, opacity=80, geometry=None,
                verify_connection_info=True, shortcuts_prompted=False)


def reset_settings(cameras):
    """Keep registry identities and connections; reset playback and app settings."""
    config = default_config()
    config['cameras'] = copy.deepcopy(cameras)
    for camera in config['cameras']:
        camera.update(quality='HD', volume=100, muted=False)
    fill_empty_slots(config, [c['id'] for c in config['cameras'] if c.get('enabled', True)])
    return config


def camera_display_name(camera):
    """A host must not escape the privacy policy through an old default alias."""
    name = str(camera.get('name') or '').strip()
    fallback = f"카메라 {camera.get('number') or ''}".strip()
    try:
        host = urlsplit(camera.get('url', '')).hostname
    except ValueError:
        host = None
    if 'rtsp://' in name.casefold() or 'rtsps://' in name.casefold():
        return fallback
    if host and host.casefold() in name.casefold():
        return re.sub(re.escape(host), '[주소 숨김]', name, flags=re.IGNORECASE) if name.casefold() != host.casefold() else fallback
    return name or fallback


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


def ensure_layout_slots(config, previous_cameras=None):
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
    # Single view always keeps a usable camera. Use the former registry order
    # to find the successor when the selected camera was removed/disabled.
    single_allowed = {c['id'] for c in config['cameras']
                      if c.get('enabled', True) and not c.get('connection_locked')}
    if clean['1'][0] not in single_allowed:
        old_single = maps.get('1', legacy) if isinstance(maps, dict) else legacy
        old_id = old_single[0] if isinstance(old_single, list) and old_single else None
        order = [c['id'] for c in (previous_cameras if previous_cameras is not None else config['cameras'])]
        if old_id in order:
            position = order.index(old_id) + 1
            order = order[position:] + order[:position]
        else:
            order = []
        order += [c['id'] for c in config['cameras']]
        clean['1'][0] = next((cid for cid in order if cid in single_allowed), None)
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
    # Existing settings predate onboarding; only a missing file or an explicit
    # reset should ask. A saved False survives until the next startup offer.
    result['shortcuts_prompted'] = bool(raw.get('shortcuts_prompted', True))
    for key in ('always_on_top', 'hardware_acceleration'):
        result[key] = bool(raw.get(key, result[key]))
    result['master_muted'] = bool(raw.get('master_muted', False))
    policy = raw.get('verify_connection_info', False)
    try:
        result['verify_connection_info'] = crypt(policy, decrypt=True) == 'yes' if isinstance(policy, str) else bool(policy)
    except (OSError, ValueError, UnicodeError):
        result['verify_connection_info'] = True  # damaged protection policy fails closed
        LOAD_WARNINGS.append('정보 보호 설정을 확인할 수 없어 본인 확인을 유지합니다.')
    layout = raw.get('layout', 1)
    result['layout'] = layout if type(layout) is int and layout in (1, 2, 4) else 1
    orientation = raw.get('split_orientation', 'horizontal')
    result['split_orientation'] = 'vertical' if orientation == 'vertical' else 'horizontal'
    result['opacity'] = bounded_int(raw.get('opacity'), result['opacity'], 20, 100)
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
        camera['sd_url'] = camera['sd_url'] if isinstance(camera['sd_url'], str) else ''
        try:
            if encrypted:
                for key in ('url', 'sd_url', 'name'):
                    camera[key] = crypt(str(camera.get(key) or ''), decrypt=True)
        except (OSError, ValueError, UnicodeError):
            camera['protected_connection'] = {key: item.get(key, '') for key in ('url', 'sd_url', 'name')}
            camera.update(url='', sd_url='', name='연결 정보 확인 필요', connection_locked=True)
            LOAD_WARNINGS.append('일부 카메라의 연결 정보를 복호화하지 못했습니다. 원본 정보를 보존하며 해당 카메라는 연결하지 않습니다.')
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
        port = camera.get('control_port', 5000)
        camera['control_port'] = port if type(port) is int and 1 <= port <= 65535 else 5000
        from camfloat.ptz_metadata import validated, binding
        try:
            hints = camera.get('ptz')
            if encrypted and isinstance(hints, str):
                if len(hints) > 8192:
                    raise ValueError('Invalid control cache')
                hints = json.loads(crypt(hints, decrypt=True))
            checked_hints = validated(hints, camera)
            if 'control_port' not in item and checked_hints and checked_hints['port'] != 5000:
                # Preserve a nonstandard port discovered by an older version.
                camera['control_port'] = checked_hints['port']
                checked_hints = dict(checked_hints, binding=binding(camera))
            camera['ptz'] = checked_hints
        except (OSError, ValueError, TypeError, UnicodeError):
            camera['ptz'] = None  # Corrupt control cache must not block playback.
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


def preserve_damaged(path):
    # Even an unparsable legacy file may contain plaintext credentials.
    payload = crypt(base64.b64encode(path.read_bytes()).decode('ascii'))
    damaged = path.with_name(f'settings-damaged-{uuid.uuid4().hex[:8]}.json')
    damaged.write_text(json.dumps(dict(format='camfloat-recovery-dpapi', data=payload)), encoding='utf-8')


def encrypt_document(document, plaintext=False):
    protected = copy.deepcopy(document)
    for collection in ('cameras', 'streams'):
        entries = protected.get(collection, [])
        for camera in entries if isinstance(entries, list) else []:
            if not isinstance(camera, dict):
                continue
            locked = camera.pop('protected_connection', None)
            camera.pop('connection_locked', None)
            if locked:
                camera.update(locked)
            for key in ('url', 'sd_url', 'name'):
                value = camera.get(key)
                if isinstance(value, str) and value and ((plaintext and not locked) or not value.startswith('dpapi:')):
                    camera[key] = crypt(value)
            hints = camera.get('ptz')
            if isinstance(hints, dict):
                camera['ptz'] = crypt(json.dumps(hints, ensure_ascii=False))
    policy = protected.get('verify_connection_info')
    if isinstance(policy, bool):
        protected['verify_connection_info'] = crypt('yes' if policy else 'no')
    return protected


def protect_old_backups(path):
    candidates = [path.with_suffix('.backup.json'), path.with_name('settings-v1.backup.json')]
    candidates.extend(path.parent.glob('settings-damaged-*.json'))
    for backup in candidates:
        if not backup.is_file():
            continue
        temporary = None
        try:
            raw = backup.read_bytes()
            try:
                document = json.loads(raw.decode('utf-8-sig'))
            except (ValueError, UnicodeError):
                document = None
            if isinstance(document, dict) and document.get('format') == 'camfloat-recovery-dpapi':
                continue
            if isinstance(document, dict) and any(isinstance(document.get(k), list) for k in ('cameras', 'streams')):
                protected = encrypt_document(document)
                if protected == document:
                    continue
            else:
                protected = dict(format='camfloat-recovery-dpapi', data=crypt(base64.b64encode(raw).decode('ascii')))
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=backup.parent,
                    prefix='protected-backup-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(protected, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, backup)
        except (OSError, ValueError, TypeError, UnicodeError):
            LOAD_WARNINGS.append('이전 백업 일부를 암호화하지 못했습니다. 원본은 보존했습니다.')
        finally:
            if temporary and temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass


def load_config():
    LOAD_WARNINGS.clear()
    path = data_path()
    protect_old_backups(path)
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
            preserve_damaged(path)
            LOAD_WARNINGS.append('설정 파일을 읽지 못해 새 설정으로 시작했습니다. 기존 파일은 settings-damaged 백업에 보관했습니다.')
            return default_config()
        preserve_damaged(path)
        LOAD_WARNINGS.append('설정 파일을 읽지 못해 직전 저장 백업을 복구했습니다.')
        return restored


def save_config(config):
    ensure_layout_slots(config)
    path = data_path()
    protect_old_backups(path)
    if path.exists() and not path.with_name('settings-v1.backup.json').exists():
        try:
            previous = json.loads(path.read_text(encoding='utf-8-sig'))
            if isinstance(previous, dict) and 'streams' in previous:
                legacy = encrypt_document(previous)
                path.with_name('settings-v1.backup.json').write_text(json.dumps(legacy, ensure_ascii=False), encoding='utf-8')
        except (ValueError, TypeError):
            pass
    stored = encrypt_document(config, plaintext=True)
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
                previous = encrypt_document(json.loads(path.read_text(encoding='utf-8-sig')))
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
        raise ValueError('RTSP 주소를 확인하세요. 특수문자가 있는 비밀번호는 ‘간편 입력’을 이용하세요.') from None
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
        raise ValueError('IP 또는 도메인을 입력하세요. 전체 주소는 ‘RTSP 주소’에서 입력하세요.')
    if ':' in host:
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            raise ValueError('포트는 옆의 포트 칸에 입력하세요.') from None
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
    # Pin ctypes to our engine, even when another VLC is installed/registered.
    os.environ['PYTHON_VLC_LIB_PATH'] = str(folder / 'libvlc.dll')
    os.environ['PYTHON_VLC_MODULE_PATH'] = str(folder / 'plugins')
    import vlc
    # mmdevice controls a Windows audio session shared by players in this
    # process: muting/turning down one SCREEN also changes its peers. Use the
    # per-player DirectSound output. Explicit overrides (e.g. the silent
    # connection probe) still take precedence.
    if not any(option == '--aout' or option.startswith('--aout=') for option in options):
        options = ('--aout=directsound', *options)
    # Follow VLC's default buffer. Forcing 450 ms can repeatedly display the
    # connection-time HEVC image on some cameras while counters still advance.
    return vlc.Instance('--no-video-title-show', '--no-snapshot-preview', '--quiet', '--rtsp-tcp', *options)
