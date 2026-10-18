"""Lossless RTSP field editing; the original URL wins until fields change."""
import ipaddress
from urllib.parse import unquote, urlsplit, urlunsplit

from camera_model import build_url, validate_rtsp_url


def split_address_port(value, default_port):
    """Accept host:port pastes without guessing the port of bare IPv6."""
    host = value.strip()
    if any(ch in host for ch in '/@?#\\') or any(ch.isspace() for ch in host):
        # Show the address/input-mode message before trying to parse a port.
        build_url(host, default_port, '', '')
    port_text = None
    if host.startswith('['):
        address, closed, suffix = host[1:].partition(']')
        try:
            if not closed or (suffix and not suffix.startswith(':')):
                raise ValueError()
            ipaddress.IPv6Address(address)
        except ValueError:
            raise ValueError('IP 또는 도메인을 확인하세요.') from None
        host = address
        if suffix:
            port_text = suffix[1:]
    elif host.count(':') == 1:
        host, port_text = host.rsplit(':', 1)
    if port_text is not None:
        if not port_text.isascii() or not port_text.isdecimal() or not 1 <= int(port_text) <= 65535:
            raise ValueError('포트는 1–65535 사이로 입력하세요.')
        default_port = int(port_text)
    # Reuse the builder's validation for protocols, whitespace and malformed hosts.
    build_url(host, default_port, '', '')
    return host, default_port


class ConnectionDraft:
    def __init__(self, url=''):
        self.original = url
        self.fields = None
        if url:
            try:
                self.fields = self.parse(url)
            except ValueError:
                pass

    @staticmethod
    def parse(url):
        p = validate_rtsp_url(url)
        return (p.hostname or '', p.port or 554, unquote(p.username or ''),
                unquote(p.password or ''), (p.path or '/') + ('?' + p.query if p.query else ''))

    def from_fields(self, fields):
        if self.fields == fields and self.original:
            validate_rtsp_url(self.original)
            return self.original
        changed = build_url(*fields)
        if self.fields and fields[2:4] == self.fields[2:4] and '@' in urlsplit(self.original).netloc:
            # Editing only a host/path must not re-encode unchanged credentials.
            parts = urlsplit(changed)
            auth = urlsplit(self.original).netloc.rsplit('@', 1)[0]
            authority = parts.netloc.rsplit('@', 1)[-1]
            changed = urlunsplit((parts.scheme, auth + '@' + authority, parts.path, parts.query, parts.fragment))
        return changed

    def adopt(self, url):
        fields = self.parse(url)
        self.original, self.fields = url, fields
        return fields


def duplicate_target(url, others, identifier):
    def target(value):
        p = validate_rtsp_url(value)
        return (p.hostname.casefold(), p.port or 554, p.path, p.query, p.username)
    key = target(url)
    for camera in others:
        if camera['id'] == identifier or camera.get('connection_locked'):
            continue
        try:
            if target(camera['url']) == key:
                return True
        except ValueError:
            pass
    return False
