"""Local startup durations only; never collect settings or camera information."""
import sys
import time


class StartupTiming:
    def __init__(self, clock=time.perf_counter):
        self.clock = clock
        self.origin = getattr(sys, '_camfloat_started_at', clock())
        self.stages = []
        self.finished = False

    def mark(self, stage):
        if not self.finished:
            self.stages.append(dict(stage=stage, ms=round((self.clock() - self.origin) * 1000, 3)))

    def watch(self, window, *, enabled=True):
        if not enabled:
            return
        from PySide6.QtCore import QEvent, QObject, QTimer
        timing = self

        class FirstPaint(QObject):
            def eventFilter(self, watched, event):
                if event.type() == QEvent.Type.Paint:
                    timing.mark('first_paint')
                    watched.removeEventFilter(self)
                    # Keep file I/O outside the first paint handler.
                    QTimer.singleShot(0, self, timing.finish)
                return False

        window._startup_observer = FirstPaint(window)
        window.installEventFilter(window._startup_observer)

    def finish(self):
        if self.finished:
            return
        self.mark('event_loop_ready')
        self.finished = True
        try:
            import json
            from camera_model import data_path
            folder = data_path().parent / 'diagnostics'
            folder.mkdir(parents=True, exist_ok=True)
            # Fixed field names and numeric durations, no paths/URLs or user text.
            (folder / 'startup.json').write_text(json.dumps(dict(stages=self.stages)), encoding='utf-8')
        except OSError:
            pass  # A diagnostic write must never stop playback.
