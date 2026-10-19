"""Nonblocking, one-shot direction commands for registered LAN cameras."""
import ipaddress
import threading
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Signal, Slot
from onvif_control import Client, direction_valid
from ptz_metadata import defaults, from_client, validated


def camera_key(camera):
    if not camera:
        return None
    return (camera.get('id'), camera.get('url', ''))


def eligible(camera):
    if not camera or not camera.get('enabled', True) or camera.get('connection_locked'):
        return False
    try:
        parts = urlsplit(camera.get('url', ''))
        address = ipaddress.ip_address(parts.hostname)
        return (parts.scheme == 'rtsp' and address.version == 4 and address.is_private
                and not any((address.is_loopback, address.is_link_local, address.is_multicast,
                             address.is_unspecified, address.is_reserved)))
    except (TypeError, ValueError):
        return False


class DirectionControl(QObject):
    changed = Signal()
    completed = Signal(int, object)
    metadata_ready = Signal(object, object)
    discovered = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.target = None
        self.client = None
        self.state = 'idle'
        self.busy = False
        self.closed = False
        self.revision = 0
        self.cancelled = threading.Event()
        self.done = threading.Event()
        self.done.set()
        self.lookup_done = threading.Event()
        self.lookup_done.set()
        self.cache = {}
        self.lookups = {}
        self.active_lookup = None
        self.completed.connect(self.finish)
        self.discovered.connect(self.lookup_finished)

    def hints(self, camera):
        key = camera_key(camera)
        return validated(self.cache.get(key), camera) or validated(camera.get('ptz'), camera) or defaults(camera)

    def make_client(self, camera):
        info = self.hints(camera)
        client = Client({'url': camera['url']})
        client.ptz_path, client.ptz_port, client.profile_token = info['path'], info['port'], info['profile']
        return client

    def discover(self, camera, force=False):
        """Registration/first-use lookup. Never move and never block a button."""
        if self.closed or not eligible(camera):
            return
        key = camera_key(camera)
        if key == self.active_lookup or key in self.lookups:
            return
        if not force and self.hints(camera)['checked']:
            return
        self.lookups[key] = dict(camera)
        self.next_lookup()

    def next_lookup(self):
        if self.closed or self.active_lookup is not None or not self.lookups:
            return
        key, camera = next(iter(self.lookups.items()))
        del self.lookups[key]
        self.active_lookup = key
        previous = self.hints(camera)
        done = self.lookup_done = threading.Event()
        def run():
            info = None
            try:
                client = Client({'url': camera['url']})
                if client.discover().get('profile_verified'):
                    info = from_client(client, camera)
            except Exception:
                pass
            if info is None:
                info = dict(previous, checked=True)
            try:
                self.discovered.emit(key, info)
            finally:
                done.set()
        threading.Thread(target=run, name='CamFloat control lookup', daemon=True).start()

    @Slot(object, object)
    def lookup_finished(self, key, info):
        self.active_lookup = None
        if self.closed:
            return
        # A successful movement response received since lookup started wins
        # over a failed lookup's default result.
        current = self.cache.get(key)
        if current and current['source'] == 'confirmed' and info['source'] == 'default':
            info = dict(current, checked=True)
        self.cache[key] = info
        self.metadata_ready.emit(key, info)
        # Apply on the NEXT user command only, never retry a movement here.
        self.next_lookup()

    def prepare(self, camera):
        if self.closed or self.busy:
            return False
        self.revision += 1
        self.target = camera_key(camera)
        self.cancelled = threading.Event()
        if not eligible(camera):
            self.client = None
            self.state = 'local_only'
            self.changed.emit()
            return False
        self.client = self.make_client(camera)
        self.state = 'ready'
        self.discover(camera)
        self.changed.emit()
        return True

    def move(self, camera, pan, tilt):
        if (self.closed or self.busy or self.state not in ('ready', 'move_error')
                or camera_key(camera) != self.target or not eligible(camera)
                or not direction_valid(pan, tilt)):
            return False
        client = self.make_client(camera)
        self.client = client
        cancelled = self.cancelled
        self.state = 'moving'
        connection = dict(camera)
        def perform():
            if cancelled.is_set():
                return (client, 'ready', None, connection)
            result = client.step(pan, tilt)
            state = 'ready' if result.get('response_verified') else 'move_error'
            return (client, state, result, connection)
        self.launch(perform)
        return True

    def launch(self, operation):
        self.busy = True
        done = self.done = threading.Event()
        revision = self.revision
        def run():
            result = (None, 'move_error', None, None)
            try:
                result = operation()
            except Exception:
                pass  # Never expose a credential-bearing exception string.
            finally:
                try:
                    self.completed.emit(revision, result)
                finally:
                    done.set()
        threading.Thread(target=run, name='CamFloat direction', daemon=True).start()
        self.changed.emit()

    @Slot(int, object)
    def finish(self, revision, result):
        self.busy = False
        if self.closed:
            return
        client, state, response, camera = result
        if camera and response:
            key = camera_key(camera)
            if response.get('response_verified'):
                info = from_client(client, camera)
                if info:
                    info['source'] = 'confirmed'
                    self.cache[key] = info
                    self.metadata_ready.emit(key, info)
            elif revision == self.revision:
                self.discover(camera, force=True)
        if revision == self.revision:
            self.client, self.state = client, state
        else:
            self.client = None
            self.state = 'idle'
        self.changed.emit()

    def cancel(self):
        self.revision += 1
        self.cancelled.set()
        self.target = None
        self.client = None
        self.state = 'stopping' if self.busy else 'idle'
        # Cached metadata survives closing a panel. No Stop request is sent.
        self.changed.emit()

    def shutdown(self):
        self.closed = True
        self.lookups.clear()
        self.cancel()
