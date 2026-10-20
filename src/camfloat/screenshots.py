"""Video-only PNG capture. Native player access stays on its playback worker."""
from datetime import datetime
from pathlib import Path
import tempfile
import uuid

from PySide6.QtCore import QObject, QStandardPaths, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices


def screenshot_directory():
    pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
    return (Path(pictures) if pictures else Path.home() / 'Pictures') / 'CamFloat'


class Screenshots(QObject):
    completed = Signal(int, object, bool)
    saved = Signal(int, object)
    failed = Signal(int)
    changed = Signal(int)

    def __init__(self, parent=None, *, directory=None):
        super().__init__(parent)
        self.directory_override = Path(directory) if directory is not None else None
        self.pending = set()
        self.closed = False
        self.completed.connect(self.finish)

    def directory(self):
        return self.directory_override if self.directory_override is not None else screenshot_directory()

    def capture(self, index, worker):
        if self.closed or index in self.pending:
            return False
        folder = self.directory()
        # No camera names, network addresses or credentials in filenames.
        name = f'CamFloat_{datetime.now():%Y%m%d_%H%M%S_%f}_SCREEN{index + 1}_{uuid.uuid4().hex[:6]}.png'
        destination = folder / name

        def capture(player):
            temporary = None
            ok = False
            try:
                if player is not None and player.is_playing() and player.has_vout() > 0:
                    folder.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(prefix='.camfloat-', suffix='.png', dir=folder, delete=False) as stream:
                        temporary = Path(stream.name)
                    # Zero dimensions ask VLC for the decoded frame's own size.
                    if player.video_take_snapshot(0, str(temporary), 0, 0) == 0:
                        with temporary.open('rb') as stream:
                            valid = stream.read(8) == b'\x89PNG\r\n\x1a\n'
                        if valid:
                            temporary.rename(destination)  # Windows refuses to overwrite an existing file.
                            temporary = None
                            ok = True
            except Exception:
                pass  # File/native exception text may contain private information.
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass
                try:
                    self.completed.emit(index, destination if ok else None, ok)
                except RuntimeError:
                    pass

        self.pending.add(index)
        if not worker.request_snapshot(capture):
            self.pending.discard(index)
            return False
        self.changed.emit(index)
        return True

    @Slot(int, object, bool)
    def finish(self, index, path, ok):
        self.pending.discard(index)
        if self.closed:
            return
        self.changed.emit(index)
        if ok:
            self.saved.emit(index, path)
        else:
            self.failed.emit(index)

    def open_folder(self):
        try:
            folder = self.directory()
            folder.mkdir(parents=True, exist_ok=True)
            return QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))
        except OSError:
            return False

    def close(self):
        self.closed = True
