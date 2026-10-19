"""Bounded timing evidence only: no names, addresses, credentials or raw replies."""
from collections import deque
import json
import os
import threading
import time

from camera_model import data_path


class DirectionTiming:
    def __init__(self, version='', enabled=True, clock=time.monotonic):
        self.clock = clock
        self.origin = clock()
        self.version = version
        self.enabled = enabled
        self.events = deque(maxlen=1500)
        self.lock = threading.Lock()
        self.path = None

    def record(self, event, **numbers):
        row = dict(event=event, ms=round((self.clock() - self.origin) * 1000, 3))
        # Callers supply fixed event names; only scalar numeric fields are accepted.
        row.update({key: value for key, value in numbers.items()
                    if value is None or type(value) in (int, float, bool)})
        with self.lock:
            self.events.append(row)

    def snapshot(self):
        with self.lock:
            return dict(version=self.version, click_ms=500, repeat_ms=160,
                        request_limit_ms=500, max_requests=4, events=list(self.events))

    def flush(self):
        if not self.enabled:
            return
        try:
            folder = data_path().parent / 'diagnostics'
            folder.mkdir(parents=True, exist_ok=True)
            self.path = folder / 'direction-timing.json'
            temporary = self.path.with_suffix(f'.{os.getpid()}.tmp')
            temporary.write_text(json.dumps(self.snapshot(), ensure_ascii=False) + '\n', encoding='utf-8')
            temporary.replace(self.path)
        except OSError:
            pass  # Diagnostics must not affect movement or display an error dialog.
