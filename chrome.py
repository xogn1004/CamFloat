"""Application controls above native video, independent of SCREEN selection."""
import time

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QToolButton, QWidget

from icons import icon
from native_window import set_topmost


PANEL_STYLE = '''QFrame#panel{background:rgba(17,21,28,220);border:1px solid rgba(174,194,223,25);
border-radius:9px;} QToolButton{color:#aeb9c9;background:transparent;border:0;
border-radius:5px;font-family:Segoe UI;font-size:11px;font-weight:500;}
QToolButton:hover{background:rgba(153,182,223,30);color:#f2f6ff;}
QToolButton:pressed{background:rgba(153,182,223,50);}
QToolButton:checked{color:#cce2ff;background:rgba(106,163,239,43);}
QToolTip{background:#1b2432;color:#e4ecf8;border:1px solid #364358;padding:6px;}'''


class AppChrome(QWidget):
    def __init__(self, host):
        super().__init__(host, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.host = host
        self.setWindowTitle('CamFloat · 앱 도구')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(242, 36)
        self.panel = QFrame(self)
        self.panel.setObjectName('panel')
        self.panel.setGeometry(self.rect())
        self.panel.setStyleSheet(PANEL_STYLE)
        row = QHBoxLayout(self.panel)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(2)
        self.layout_buttons = {}
        for count in (1, 2, 4):
            button = self.button(row, None, f'{count}분할 ({count})', lambda n=count: host.set_layout(n))
            button.setText(str(count))
            button.setFixedWidth(24)
            button.setCheckable(True)
            self.layout_buttons[count] = button
        separator = QFrame()
        separator.setFixedSize(1, 18)
        separator.setStyleSheet('background:rgba(174,194,223,35);border:0;')
        row.addWidget(separator)
        row.addSpacing(3)
        self.pin = self.button(row, 'pin', '항상 위 (Ctrl+T)',
                               lambda: host.set_always_on_top(not host.config['always_on_top']))
        self.pin.setCheckable(True)
        self.fullscreen = self.button(row, 'fullscreen', '분할 전체화면', host.toggle_layout_fullscreen)
        self.manager = self.button(row, 'camera', '카메라 관리 (Ctrl+M)', host.manage_cameras)
        self.more = self.button(row, 'more', '앱 메뉴 (Alt)', self.show_menu)
        self.deadline = 0
        self.edge_since = None
        self.menu_open = False
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def button(self, row, symbol, tooltip, callback):
        item = QToolButton(self.panel)
        item.setFixedSize(28, 28)
        item.setIconSize(QSize(16, 16))
        if symbol:
            item.setIcon(icon(symbol))
        item.setToolTip(tooltip)
        item.setAccessibleName(tooltip)
        item.clicked.connect(lambda checked=False: callback())
        row.addWidget(item)
        return item

    def refresh(self):
        for count, button in self.layout_buttons.items():
            button.setChecked(count == self.host.config['layout'])
        self.pin.setChecked(self.host.config['always_on_top'])
        self.fullscreen.setIcon(icon('restore' if self.host.isFullScreen() else 'fullscreen'))
        self.fullscreen.setToolTip('전체화면 해제' if self.host.isFullScreen() else '분할 전체화면')
        self.fullscreen.setAccessibleName(self.fullscreen.toolTip())

    def position(self):
        self.move(self.host.mapToGlobal(QPoint((self.host.width() - self.width()) // 2, 8)))

    def reveal(self, linger=1.2):
        if self.host.modal_depth or self.host.closing or self.host.isMinimized() or not self.host.isVisible():
            return
        self.position()
        self.refresh()
        self.deadline = time.monotonic() + linger
        if not self.isVisible():
            self.show()
            set_topmost(self, self.host.config['always_on_top'])
            self.raise_()
        self.host.position_screen_labels()

    def poll(self):
        if self.host.closing or self.host.modal_depth or self.host.isMinimized() or not self.host.isVisible():
            self.hide()
            self.host.position_screen_labels()
            return
        # Crossing the video must never summon a toolbar. Require a short dwell
        # on the top edge; dragging/resizing must not reveal it either.
        point = self.host.mapFromGlobal(QCursor.pos())
        edge = QRect((self.host.width() - self.width()) // 2, 0, self.width(), 8)
        active = self.host.config['always_on_top'] or self.host.app_is_foreground()
        dragging = QApplication.mouseButtons() != Qt.MouseButton.NoButton
        now = time.monotonic()
        if active and not dragging and edge.contains(point):
            if self.edge_since is None:
                self.edge_since = now
            if now - self.edge_since >= .28:
                self.reveal(linger=.45)
        else:
            self.edge_since = None
        if self.isVisible() and self.geometry().adjusted(-6, -8, 6, 6).contains(QCursor.pos()):
            self.deadline = now + .45
        if self.isVisible() and not self.menu_open and now > self.deadline:
            self.hide()
            self.host.position_screen_labels()

    def show_menu(self):
        self.menu_open = True
        menu = self.host.build_app_menu(self)
        try:
            menu.exec(self.more.mapToGlobal(QPoint(self.more.width(), self.more.height() + 10))
                      - QPoint(menu.sizeHint().width(), 0))
        finally:
            self.menu_open = False
            menu.deleteLater()
            self.reveal()

    def closeEvent(self, event):
        if not self.host.closing:
            event.ignore()
            self.host.close()
        else:
            super().closeEvent(event)


class LayoutToast(QWidget):
    def __init__(self, host):
        super().__init__(host, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint | Qt.WindowType.WindowTransparentForInput)
        self.host = host
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.label = QLabel(self)
        self.label.setStyleSheet('background:rgba(19,24,33,238);color:#e2edfc;'
            'border:1px solid rgba(174,194,223,42);border-radius:12px;'
            'font-family:Segoe UI;font-size:12px;font-weight:500;padding:11px 19px;')
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(1800)
        self.timer.timeout.connect(self.hide)

    def position(self):
        self.move(self.host.mapToGlobal(QPoint((self.host.width() - self.width()) // 2,
                                               max(12, self.host.height() - self.height() - 18))))

    def notify(self, count):
        self.label.setText(f'{count}분할로 변경되었습니다')
        self.label.adjustSize()
        self.resize(self.label.size())
        self.position()
        self.show()
        set_topmost(self, self.host.config['always_on_top'])
        self.raise_()
        self.timer.start()
