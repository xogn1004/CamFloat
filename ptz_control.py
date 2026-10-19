"""Nonblocking, one-shot direction commands for registered LAN cameras."""
import ipaddress
import threading
import time
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from onvif_control import Client, direction_valid
from ptz_metadata import defaults, from_client, validated
from ptz_timing import DirectionTiming
from ptz_transport import MotionAttempt


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


def delivery_failed(result):
    """A missing acknowledgement is distinct from a rejected/unsent command."""
    status = result.get('http_status')
    return (result.get('soap_fault') is True
            or (type(status) is int and status >= 400)
            or (not result.get('request_sent') and not result.get('response_verified')))


class DirectionControl(QObject):
    changed = Signal()
    completed = Signal(int, object)
    metadata_ready = Signal(object, object)
    discovered = Signal(object, object)

    def __init__(self, parent=None, *, version='', diagnostics_enabled=True, clock=time.monotonic):
        super().__init__(parent)
        self.target = None
        self.client = None
        self.state = 'idle'
        self.clock = clock
        self.jobs_lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.jobs = {}
        self.sequence = 0
        self.latest_applied = 0
        self.latest_write = 0
        self.last_click = {}
        self.input_cancelled = threading.Event()
        self.input_open = False
        self.input_number = 0
        self.timing = DirectionTiming(version, diagnostics_enabled, clock)
        self.flush_timer = QTimer(self)
        self.flush_timer.setSingleShot(True)
        self.flush_timer.setInterval(100)
        self.flush_timer.timeout.connect(self.timing.flush)
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
        self.last_reply = None
        self.completed.connect(self.finish)
        self.discovered.connect(self.lookup_finished)

    @property
    def busy(self):
        with self.jobs_lock:
            return bool(self.jobs)

    def begin_input(self):
        self.end_input()
        self.flush_timer.stop()
        self.input_cancelled = threading.Event()
        self.input_open = True
        self.input_number += 1
        self.timing.record('input_start', input=self.input_number)

    def end_input(self):
        self.input_cancelled.set()
        if self.input_open:
            self.input_open = False
            self.timing.record('input_end', input=self.input_number)
            self.flush_timer.start()

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
        if self.closed:
            return False
        self.end_input()
        self.cancelled.set()
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

    def move(self, camera, pan, tilt, *, repeat=False):
        if (self.closed or self.state not in ('ready', 'moving', 'move_error', 'send_limit')
                or camera_key(camera) != self.target or not eligible(camera)
                or not direction_valid(pan, tilt)):
            return False
        now = self.clock()
        key = camera_key(camera)
        if not repeat and now - self.last_click.get(key, float('-inf')) < .5:
            self.timing.record('click_ignored', pan=pan, tilt=tilt)
            return False
        if repeat and (not self.input_open or self.input_cancelled.is_set()):
            return False
        if not self.input_open:
            self.begin_input()
        with self.jobs_lock:
            at_limit = len(self.jobs) >= 4
        if at_limit:
            self.timing.record('request_limit', active=4)
            self.end_input()
            self.state = 'send_limit'
            self.changed.emit()
            return False
        if not repeat:
            self.last_click[key] = now
        client = self.make_client(camera)
        self.client = client
        cancelled = self.cancelled
        input_cancelled = self.input_cancelled
        self.state = 'moving'
        connection = dict(camera)
        revision = self.revision
        self.sequence += 1
        sequence = self.sequence
        started = self.clock()
        number = camera.get('number')
        number = number if type(number) is int else None
        self.timing.record('dispatch', seq=sequence, input=self.input_number,
                           camera=number, pan=pan, tilt=tilt, repeat=repeat)
        def before_send():
            with self.jobs_lock:
                if (cancelled.is_set() or input_cancelled.is_set()
                        or sequence < self.latest_write):
                    self.timing.record('unsent_cancelled', seq=sequence)
                    return False
                self.latest_write = sequence
                return True
        attempt = MotionAttempt(input_cancelled, before_send,
                                lambda event: self.timing.record(event, seq=sequence),
                                write_lock=self.write_lock)
        with self.jobs_lock:
            self.jobs[sequence] = attempt
            self.done.clear()
        def run():
            response = None
            try:
                if cancelled.is_set() or input_cancelled.is_set():
                    response = {'cancelled': True, 'request_sent': False}
                else:
                    response = client.step(pan, tilt, attempt=attempt)
            except Exception:
                response = {'response_verified': False, 'request_sent': attempt.sent}
            finally:
                response = response or {'response_verified': False, 'request_sent': attempt.sent}
                self.timing.record('reply', seq=sequence,
                    duration_ms=round((self.clock() - started) * 1000, 3),
                    sent=bool(response.get('request_sent')), verified=bool(response.get('response_verified')),
                    cancelled=bool(response.get('cancelled')), deadline=bool(response.get('deadline_exceeded')),
                    status=response.get('http_status') if type(response.get('http_status')) is int else None)
                with self.jobs_lock:
                    self.jobs.pop(sequence, None)
                    if not self.jobs:
                        self.done.set()
                try:
                    self.completed.emit(revision, (sequence, input_cancelled, client, response, connection))
                except RuntimeError:
                    pass  # QObject may already be gone at process shutdown.
        threading.Thread(target=run, name='CamFloat direction', daemon=True).start()
        self.changed.emit()
        return True

    @Slot(int, object)
    def finish(self, revision, result):
        if not self.input_open:
            self.flush_timer.start()
        if self.closed:
            return
        sequence, input_cancelled, client, response, camera = result
        if not self.busy and self.state in ('moving', 'send_limit'):
            self.state = 'ready' if self.target is not None else 'idle'
            self.changed.emit()
        # Replies may finish out of order or belong to a closed panel/camera.
        if revision != self.revision:
            return
        if sequence < self.latest_applied:
            if not self.busy and self.state == 'moving':
                self.state = 'ready'
                self.changed.emit()
            return
        self.latest_applied = sequence
        self.last_reply = response
        current_input = input_cancelled is self.input_cancelled
        failed = delivery_failed(response) and not response.get('cancelled')
        if camera and response and current_input:
            key = camera_key(camera)
            if response.get('response_verified'):
                info = from_client(client, camera)
                if info:
                    info['source'] = 'confirmed'
                    self.cache[key] = info
                    self.metadata_ready.emit(key, info)
            elif failed and not input_cancelled.is_set():
                self.discover(camera, force=True)
        # An old reply must not interrupt a new press or restart a limited hold.
        if self.state == 'send_limit':
            if not self.busy:
                self.state = 'ready'
        elif current_input:
            self.client = client
            self.state = 'move_error' if failed else 'moving' if self.busy else 'ready'
        elif not self.busy and self.state == 'moving':
            self.state = 'ready'
        self.changed.emit()

    def cancel(self):
        self.end_input()
        self.revision += 1
        self.cancelled.set()
        self.target = None
        self.client = None
        self.state = 'idle'
        # Cached metadata survives closing a panel. No Stop request is sent.
        self.changed.emit()

    def shutdown(self):
        self.closed = True
        self.lookups.clear()
        self.cancel()
        self.timing.flush()
