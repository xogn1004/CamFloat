"""Serialize slow libVLC lifecycle calls away from the Qt event loop."""
from __future__ import annotations

import threading


class PlaybackWorker:
    def __init__(self, instance, player, hwnd=None):
        self.instance, self.player = instance, player
        self.condition = threading.Condition()
        self.pending = None
        self.pending_reset = False
        self.hwnd = hwnd
        self.revision = 0
        self.handled = 0
        self.closing = False
        self.busy = False
        self.error = False
        self.audio = (100, False)
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.run, name='CamFloat playback', daemon=True)
        self.thread.start()

    def request(self, request, reset=False):
        with self.condition:
            if self.closing:
                return
            self.pending = request
            self.pending_reset = bool(reset)
            if request:
                self.audio = request[2:]
            self.revision += 1
            self.busy = True
            self.condition.notify()

    def set_audio(self, volume, muted):
        with self.condition:
            self.audio = (volume, muted)
            self.player.audio_set_volume(volume)
            self.player.audio_set_mute(muted)

    def shutdown(self):
        with self.condition:
            self.closing = True
            self.condition.notify()

    def run(self):
        active = False
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self.closing or self.revision != self.handled)
                    revision, request, closing = self.revision, self.pending, self.closing
                    reset = self.pending_reset
                try:
                    if active:
                        self.player.stop()
                        active = False
                    with self.condition:
                        # Discard obsolete changes queued while stop() was blocking.
                        if not closing and revision != self.revision:
                            continue
                    if closing:
                        break
                    self.error = False
                    if request:
                        if reset and self.hwnd is not None:
                            # A fresh decoder/output also repairs a wedged vout.
                            replacement = self.instance.media_player_new()
                            try:
                                replacement.set_hwnd(self.hwnd)
                                replacement.video_set_mouse_input(False)
                                replacement.video_set_key_input(False)
                            except Exception:
                                replacement.release()
                                raise
                            with self.condition:
                                previous, self.player = self.player, replacement
                            previous.release()
                        url, hardware, volume, muted = request
                        media = self.instance.media_new(url)
                        try:
                            media.add_option(':rtsp-tcp')
                            media.add_option(':network-caching=450')
                            if url.startswith('file:'):
                                media.add_option(':input-repeat=65535')
                            media.add_option(':avcodec-hw=any' if hardware else ':avcodec-hw=none')
                            self.player.set_media(media)
                        finally:
                            media.release()
                        active = True
                        if self.player.play() == -1:
                            self.error = True
                        # No pause feature is exposed by CamFloat. Never carry
                        # an accidental VLC pause state through reconnection.
                        if hasattr(self.player, 'set_pause'):
                            self.player.set_pause(0)
                        if self.hwnd is not None:
                            self.player.video_set_mouse_input(False)
                            self.player.video_set_key_input(False)
                        with self.condition:
                            volume, muted = self.audio
                            self.player.audio_set_volume(volume)
                            self.player.audio_set_mute(muted)
                except Exception:
                    self.error = True
                finally:
                    with self.condition:
                        self.handled = revision
                        self.busy = self.revision != revision
        finally:
            # HWNDs are kept alive by PlayerWindow until every worker finishes.
            try:
                self.player.release()
            finally:
                self.done.set()
