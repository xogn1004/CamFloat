"""Validated local control hints, bound to a single camera connection."""
import hashlib
import ipaddress
from urllib.parse import urlsplit

DEFAULT_PATH = '/onvif/deviceio_service'
DEFAULT_PORT = 5000
DEFAULT_PROFILE = 'IPCProfilesToken0'


def control_port(camera):
    value = camera.get('control_port', DEFAULT_PORT)
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError('방향 조작 포트를 확인하세요.')
    return value


def supported_target(camera):
    """Transport scope, independent of whether this camera is enabled."""
    try:
        parts = urlsplit(camera.get('url', ''))
        control_port(camera)
        if parts.scheme != 'rtsp' or not parts.hostname or parts.port == 0:
            return False
        try:
            address = ipaddress.ip_address(parts.hostname)
        except ValueError:
            # DDNS names are contacted exactly as registered, without following
            # any host returned in an ONVIF response.
            name = parts.hostname.rstrip('.').encode('idna').decode('ascii')
            labels = name.split('.')
            return (name.lower() != 'localhost' and len(name) <= 253 and len(labels) >= 2
                    and all(0 < len(label) <= 63 and label[0].isalnum() and label[-1].isalnum()
                            and all(c.isalnum() or c == '-' for c in label) for label in labels))
        return (address.version == 4 and not any((address.is_loopback, address.is_link_local,
                address.is_multicast, address.is_unspecified, address.is_reserved)))
    except (AttributeError, TypeError, ValueError):
        return False


def support_state(camera):
    if camera.get('connection_locked'):
        return 'unknown'
    if not supported_target(camera):
        return 'unsupported'
    info = validated(camera.get('ptz'), camera)
    if not info:
        return 'unchecked'
    if info.get('lookup_result'):
        return info['lookup_result']
    if info['source'] in ('device', 'confirmed'):
        return 'supported'
    return 'unknown' if info['checked'] else 'unchecked'


def binding(camera):
    value = str(camera.get('url', ''))
    port = control_port(camera)
    # Preserve compatible existing caches for the original default port.
    if port != DEFAULT_PORT:
        value += '\ncontrol_port=' + str(port)
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def validated(value, camera):
    if not isinstance(value, dict) or value.get('binding') != binding(camera):
        return None
    path, port, profile = (value.get(k) for k in ('path', 'port', 'profile'))
    if (not isinstance(path, str) or not path.startswith('/') or path.startswith('//')
            or len(path) > 1024 or any(ord(c) <= 32 or c in '\\?#' for c in path)
            or type(port) is not int or not 1 <= port <= 65535
            or not isinstance(profile, str) or not 1 <= len(profile) <= 256
            or any(ord(c) < 32 for c in profile)):
        return None
    result = dict(binding=binding(camera), path=path, port=port, profile=profile,
                checked=value.get('checked') is True,
                source=value.get('source') if value.get('source') in ('device', 'default', 'confirmed') else 'default')
    if value.get('lookup_result') in ('supported', 'unknown'):
        result['lookup_result'] = value['lookup_result']
    return result


def defaults(camera):
    return dict(binding=binding(camera), path=DEFAULT_PATH, port=control_port(camera),
                profile=DEFAULT_PROFILE, checked=False, source='default')


def from_client(client, camera):
    return validated(dict(binding=binding(camera), path=client.ptz_path,
                          port=client.ptz_port, profile=client.profile_token,
                          source='device', checked=True), camera)
