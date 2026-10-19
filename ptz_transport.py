"""A deadline and cancellation gate for ONE motion request, with no retry queue."""
import socket
import threading
import time


class MotionCancelled(OSError):
    pass


class MotionAttempt:
    def __init__(self, cancelled, before_send, on_event, timeout=1, write_lock=None):
        self.cancelled = cancelled
        self.before_send = before_send
        self.on_event = on_event
        self.deadline = time.monotonic() + timeout
        self.expired = threading.Event()
        self.connection = None
        self.socket = None
        self.timer = None
        self.sent = False
        self.aborted = False
        self.write_lock = write_lock or threading.Lock()
        self.write_acquired = False

    def start(self, connection):
        self.connection = connection
        if self.cancelled.is_set():
            self.aborted = True
            raise MotionCancelled()
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            self.expired.set()
            raise TimeoutError()
        self.timer = threading.Timer(remaining, self.expire)
        self.timer.daemon = True
        self.timer.start()

    def acquire_write(self, connection):
        self.socket = getattr(connection, 'sock', None)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0 or not self.write_lock.acquire(timeout=remaining):
            raise TimeoutError()
        self.write_acquired = True

    def remaining(self):
        return max(0, self.deadline - time.monotonic())

    def release_write(self):
        if self.write_acquired:
            self.write_acquired = False
            self.write_lock.release()

    def before_request(self, connection):
        self.socket = getattr(connection, 'sock', None)
        if self.expired.is_set() or time.monotonic() >= self.deadline:
            raise TimeoutError()
        if self.cancelled.is_set() or not self.before_send():
            self.aborted = True
            raise MotionCancelled()
        self.on_event('write_started')

    def request_sent(self):
        self.sent = True
        self.on_event('sent')

    def expire(self):
        self.expired.set()
        # shutdown also interrupts response.read() holding a socket file object.
        stream = self.socket or getattr(self.connection, 'sock', None)
        if stream is not None:
            try:
                stream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def finish(self):
        self.release_write()
        if self.timer is not None:
            self.timer.cancel()
