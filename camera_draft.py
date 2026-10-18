"""Lossless RTSP field editing; the original URL wins until fields change."""
from urllib.parse import unquote, urlsplit, urlunsplit

from camera_model import build_url, validate_rtsp_url


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
