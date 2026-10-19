"""Validated local control hints, bound to a single camera connection."""
import hashlib

DEFAULT_PATH = '/onvif/deviceio_service'
DEFAULT_PORT = 5000
DEFAULT_PROFILE = 'IPCProfilesToken0'


def binding(camera):
    return hashlib.sha256(str(camera.get('url', '')).encode('utf-8')).hexdigest()


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
    return dict(binding=binding(camera), path=path, port=port, profile=profile,
                checked=value.get('checked') is True,
                source=value.get('source') if value.get('source') in ('device', 'default', 'confirmed') else 'default')


def defaults(camera):
    return dict(binding=binding(camera), path=DEFAULT_PATH, port=DEFAULT_PORT,
                profile=DEFAULT_PROFILE, checked=False, source='default')


def from_client(client, camera):
    return validated(dict(binding=binding(camera), path=client.ptz_path,
                          port=client.ptz_port, profile=client.profile_token,
                          source='device', checked=True), camera)
