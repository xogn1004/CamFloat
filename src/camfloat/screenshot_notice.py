"""A brief clickable notice, sized for the smallest SCREEN."""
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QToolButton


class ScreenshotNotice(QToolButton):
    def __init__(self, overlay):
        super().__init__(overlay)
        self.overlay = overlay
        self.can_open = False
        self.setStyleSheet('QToolButton{background:#26394f;color:#edf4ff;border:1px solid #526b8b;'
                          'border-radius:6px;padding:5px 8px;font-size:11px;}'
                          'QToolButton:hover{background:#324e70;}')
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.clicked.connect(self.open_folder)
        overlay.installEventFilter(self)
        overlay.tips.add(self)
        self.hide()

    def display(self, *, saved):
        self.can_open = saved
        self.setText('저장했습니다' if saved else '저장하지 못했습니다')
        self.setToolTip('스크린샷 폴더 열기' if saved else '잠시 후 다시 시도하세요')
        self.setAccessibleName(self.text() + (' · 스크린샷 폴더 열기' if saved else ''))
        self.setCursor(Qt.CursorShape.PointingHandCursor if saved else Qt.CursorShape.ArrowCursor)
        self.place()
        self.show()
        self.raise_()
        self.timer.start(3500)

    def place(self):
        self.setFixedSize(min(max(90, self.sizeHint().width()), max(50, self.overlay.width() - 16)), 28)
        self.move(max(4, (self.overlay.width() - self.width()) // 2), max(4, self.overlay.height() - 75))

    def open_folder(self):
        if self.can_open:
            self.overlay.host.open_screenshot_folder()
            self.hide()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize and self.isVisible():
            self.place()
        elif event.type() == QEvent.Type.Hide:
            self.timer.stop()
            self.hide()
        return False
