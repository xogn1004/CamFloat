"""One user-requested connection check in a disposable, muted process."""
import multiprocessing
import queue
import time

from PySide6.QtCore import QObject, QTimer, Signal


def probe_worker(url, directory, result):
    from pathlib import Path
    from camera_model import make_vlc_instance
    import vlc
    instance = player = media = None
    try:
        instance = make_vlc_instance(Path(directory), '--vout=dummy', '--aout=dummy', '--avcodec-hw=none')
        player = instance.media_player_new()
        media = instance.media_new(url)
        media.add_option(':rtsp-tcp')
        media.add_option(':no-audio')
        player.set_media(media)
        if player.play() == -1:
            result.put((False, '연결할 수 없습니다. 주소와 비밀번호를 확인하세요.'))
            return
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            stats = vlc.MediaStats()
            if media.get_stats(stats) and stats.decoded_video > 0:
                result.put((True, '연결됨'))
                return
            if player.get_state().value in (6, 7):
                result.put((False, '연결할 수 없습니다. 주소와 비밀번호를 확인하세요.'))
                return
            time.sleep(.1)
        result.put((False, '응답이 없습니다. 카메라 전원과 네트워크를 확인하세요.'))
    except Exception:
        result.put((False, '연결을 확인하지 못했습니다. 다시 시도하세요.'))
    finally:
        # The parent terminates a native stop/release that fails to return.
        if player:
            player.release()
        if media:
            media.release()
        if instance:
            instance.release()


class ConnectionProbe(QObject):
    finished = Signal(bool, str)

    def __init__(self, parent):
        super().__init__(parent)
        self.process = None
        self.queue = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)

    def start(self, url, directory):
        self.cancel(notify=False)
        context = multiprocessing.get_context('spawn')
        self.queue = context.Queue()
        self.process = context.Process(target=probe_worker, args=(url, str(directory), self.queue), daemon=True)
        try:
            self.process.start()
        except Exception:
            self.cancel(notify=False)
            self.finished.emit(False, '연결 확인을 시작하지 못했습니다.')
            return
        self.deadline = time.monotonic() + 16
        self.timer.start()

    def poll(self):
        try:
            success, message = self.queue.get_nowait()
        except (queue.Empty, EOFError, OSError, ValueError):
            if self.process.is_alive() and time.monotonic() < self.deadline:
                return
            success, message = False, '연결을 확인하지 못했습니다. 다시 시도하세요.'
        self.cancel(notify=False)
        self.finished.emit(success, message)

    def cancel(self, notify=True):
        self.timer.stop()
        if self.process is not None:
            if self.process.pid is not None and self.process.is_alive():
                self.process.terminate()
            if self.process.pid is not None:
                self.process.join(timeout=0)
            self.process = None
        if self.queue is not None:
            self.queue.close()
            self.queue.cancel_join_thread()
            self.queue = None
        if notify:
            self.finished.emit(False, '')
