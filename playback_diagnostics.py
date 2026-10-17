"""Bounded playback counters. Never record camera addresses, names or credentials."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import time
from datetime import datetime, timezone

from camera_model import data_path


class PlaybackDiagnostics:
    def __init__(self, profile, version, engine_version):
        folder = data_path().parent / 'diagnostics'
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / f'playback-{profile}.jsonl'
        self.logger = logging.Logger(f'CamFloat playback {os.getpid()}')
        self.handler = RotatingFileHandler(self.path, maxBytes=2_000_000, backupCount=2, encoding='utf-8')
        self.handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger.addHandler(self.handler)
        self.started = time.monotonic()
        self.closed = False
        self.write('session', profile=profile, version=version, vlc=engine_version, pid=os.getpid())

    def write(self, event, **fields):
        if not self.closed:
            self.logger.info(json.dumps(dict(event=event, utc=datetime.now(timezone.utc).isoformat(),
                elapsed=round(time.monotonic() - self.started, 2), **fields), ensure_ascii=False))

    def sample(self, window):
        if window.closing or self.closed:
            return
        for index, tile in enumerate(window.tiles[:window.config['layout']]):
            camera = window.camera_for_slot(index)
            if not camera or tile.current_key is None:
                continue
            row = dict(screen=index + 1, camera_number=camera.get('number'), quality=camera['quality'],
                attempt=tile.worker.revision, busy=tile.worker.busy, phase=tile.worker.phase,
                error=tile.worker.error, error_type=tile.worker.last_error,
                first_failure=tile.initial_failed, ever_played=tile.ever_played,
                visible=not window.isMinimized() and (window.focused_screen is None or window.focused_screen == index))
            if not tile.worker.busy and not tile.worker.done.is_set():
                try:
                    row.update(state=tile.player.get_state().value, time_ms=tile.player.get_time(),
                               video_outputs=tile.player.has_vout(), statistics=tile.media_statistics())
                except Exception as error:
                    # Exception messages from native libraries may contain URLs.
                    row['sample_error'] = type(error).__name__
            self.write('sample', **row)

    def close(self):
        if not self.closed:
            self.write('session_end')
            self.closed = True
            self.handler.close()
            self.logger.removeHandler(self.handler)
