"""Show a responsive window while libVLC loads its native libraries/plugins."""
import threading

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QEventLoop, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from camfloat.camera_model import APP_TITLE
from camfloat.icons import icon
from camfloat.native_window import ensure_taskbar_minimize, set_topmost


class LoadingWindow(QWidget):
    painted = Signal()

    def __init__(self, config):
        super().__init__()
        self.cancelled = False
        self.finished = False
        self.first_paint = True
        self.drag_origin = None
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(QApplication.windowIcon())
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(300, 180)
        self.setStyleSheet('LoadingWindow{background:#080b10;} QLabel{color:#96a9c3;background:transparent;}'
                           'QToolButton{border:0;background:transparent;border-radius:5px;}'
                           'QToolButton:hover{background:#2b3b52;}')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 10, 16)
        header = QHBoxLayout()
        header.addWidget(QLabel('CamFloat'))
        header.addStretch()
        close = QToolButton()
        close.setIcon(icon('close'))
        close.setToolTip('종료')
        close.setAccessibleName('종료')
        close.setFixedSize(28, 28)
        close.clicked.connect(self.close)
        header.addWidget(close)
        layout.addLayout(header)
        label = QLabel('시작하는 중…')
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label, 1)
        layout.addSpacing(28)
        screen = QApplication.primaryScreen().availableGeometry()
        geometry = config.get('geometry')
        self.setGeometry(QRect(*geometry) if geometry else
                         QRect(screen.topLeft() + QPoint(80, 80), screen.size().boundedTo(QSize(960, 540))))
        if not any(s.availableGeometry().intersects(self.geometry()) for s in QApplication.screens()):
            self.move(screen.topLeft() + QPoint(40, 40))
        self.setWindowOpacity(config.get('opacity', 80) / 100)
        self.topmost = config.get('always_on_top', False)

    def showEvent(self, event):
        super().showEvent(event)
        ensure_taskbar_minimize(self)
        set_topmost(self, self.topmost)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.first_paint:
            self.first_paint = False
            self.painted.emit()

    def activate(self):
        if not self.cancelled and not self.finished:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_origin = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self.drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_origin)

    def mouseReleaseEvent(self, event):
        self.drag_origin = None

    def closeEvent(self, event):
        if not self.finished:
            self.cancelled = True
        super().closeEvent(event)


def initialize_engine(config, initialize, timing, activation=None):
    """Return (engine, loading window), or (None, None) on cancellation.

    A cancelled initialization is allowed to finish privately, then released.
    The native initializer cannot safely be interrupted in the middle of a DLL
    load. No player or camera connection is created after cancellation.
    """
    app = QApplication.instance()
    window = LoadingWindow(config)
    window.painted.connect(lambda: timing.mark('startup_window_painted'))
    if activation is not None:
        activation.connect(window.activate)
    loop = QEventLoop()

    class Result(QObject):
        ready = Signal()

    result = Result()
    result.ready.connect(loop.quit)
    outcome = {}

    def run():
        try:
            outcome['engine'] = initialize()
        except BaseException as error:
            outcome['error'] = error
        finally:
            result.ready.emit()

    worker = threading.Thread(target=run, name='CamFloat engine initialization')
    previous = app.quitOnLastWindowClosed()
    succeeded = False
    app.setQuitOnLastWindowClosed(False)
    try:
        window.show()
        timing.mark('startup_window_shown')
        worker.start()
        loop.exec()
        worker.join()  # ready is emitted only after the native initializer returned.
        engine = outcome.get('engine')
        if window.cancelled:
            if engine is not None:
                engine.release()
            return None, None
        if 'error' in outcome:
            raise outcome['error']
        if engine is None:
            raise RuntimeError('VLC initialization returned no instance')
        # Preserve a move made while the engine was loading.
        config['geometry'] = [window.x(), window.y(), window.width(), window.height()]
        succeeded = True
        return engine, window
    finally:
        window.finished = True
        if not succeeded:
            window.close()
            window.deleteLater()
        result.deleteLater()
        app.setQuitOnLastWindowClosed(previous)
