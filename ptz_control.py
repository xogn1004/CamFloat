"""Nonblocking, one-shot direction commands for registered LAN cameras."""
import ipaddress
import threading
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Signal, Slot
from onvif_control import Client, direction_valid, pulse


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
        self.completed.connect(self.finish)

    def prepare(self, camera):
        if self.closed or self.busy:
            return False
        target = camera_key(camera)
        if target == self.target and self.client is not None and self.state == 'ready':
            self.changed.emit()
            return True
        self.revision += 1
        self.target = target
        self.client = None
        if not eligible(camera):
            self.state = 'local_only'
            self.changed.emit()
            return False
        self.cancelled = threading.Event()
        self.state = 'connecting'
        # Copy only the required connection, never persist or include it in errors.
        connection = {'url': camera['url']}
        def discover():
            client = Client(connection)
            report = client.discover()
            return (client, 'ready') if report.get('profile_verified') else (None, 'error')
        self.launch(discover)
        return True

    def move(self, camera, pan, tilt):
        if (self.closed or self.busy or self.state != 'ready' or self.client is None
                or camera_key(camera) != self.target or not eligible(camera)
                or not direction_valid(pan, tilt)):
            return False
        client, cancelled = self.client, self.cancelled
        self.state = 'moving'
        def perform():
            result = pulse(client, pan, tilt, cancelled=cancelled)
            # A valid movement reply is still not proof of physical movement.
            state = 'ready' if result.get('move', {}).get('response_verified') else 'move_error'
            return (client if state == 'ready' else None, state)
        self.launch(perform)
        return True

    def launch(self, operation):
        self.busy = True
        # Completion delivery may start a newer request before this thread exits.
        # Each request owns its completion event so an old thread cannot mark
        # the newer operation finished during application shutdown.
        done = self.done = threading.Event()
        revision = self.revision
        def run():
            result = (None, 'error')
            try:
                result = operation()
            except Exception:
                pass  # Never forward exception messages containing connection data.
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
        if revision == self.revision:
            self.client, self.state = result
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
        self.changed.emit()

    def shutdown(self):
        self.closed = True
        self.cancel()
