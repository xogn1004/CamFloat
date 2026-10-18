"""Application controls above native video, independent of SCREEN selection."""
import time

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QCursor, QPainter
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QToolButton, QWidget

from icons import icon
from native_window import keep_above_owned_windows, set_topmost
from menu_labels import CAMERAS, fullscreen_name, topmost_name, master_mute_name, tooltip
from hover_tips import HoverTips


PANEL_STYLE = '''QFrame#panel{background:rgba(19,24,33,242);border:1px solid rgba(174,194,223,42);
border-radius:12px;} QToolButton{color:#aebcd0;background:transparent;border:0;
border-radius:7px;font-family:Segoe UI;font-size:11px;font-weight:600;}
QToolButton:hover{background:rgba(153,182,223,30);color:#f2f6ff;}
QToolButton:pressed{background:rgba(153,182,223,50);}
QToolButton:checked{color:#cce2ff;background:rgba(106,163,239,43);}
QToolTip{background:#1b2432;color:#e4ecf8;border:1px solid #364358;padding:6px;}'''


class AppChrome(QWidget):
    def __init__(self, host):
        super().__init__(host, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.host = host
        self.tips = HoverTips(self)
        self.setWindowTitle('CamFloat · 앱 도구')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(270, 36)
        self.last_state = None
        self.panel = QFrame(self)
        self.panel.setObjectName('panel')
        self.panel.setGeometry(self.rect())
        self.panel.setStyleSheet(PANEL_STYLE)
        row = QHBoxLayout(self.panel)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(2)
        self.layout_buttons = {}
        for count in (1, 2, 4):
            button = self.button(row, f'layout{count}', tooltip(f'{count}분할', str(count)), lambda n=count: host.set_layout(n))
            button.setFixedWidth(24)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            self.layout_buttons[count] = button
        separator = QFrame()
        separator.setFixedSize(1, 18)
        separator.setStyleSheet('background:rgba(174,194,223,35);border:0;')
        row.addWidget(separator)
        row.addSpacing(3)
        self.master_mute = self.button(row, 'volume', tooltip('전체 음소거', 'Ctrl+Shift+M'), host.mute_all)
        self.master_mute.setCheckable(True)
        self.manager = self.button(row, 'cameras', tooltip(CAMERAS, 'Ctrl+M'), host.manage_cameras)
        self.fullscreen = self.button(row, 'fullscreen', tooltip('전체화면', 'F11'), host.toggle_layout_fullscreen)
        separator = QFrame()
        separator.setFixedSize(1, 18)
        separator.setStyleSheet('background:rgba(174,194,223,35);border:0;')
        row.addWidget(separator)
        row.addSpacing(3)
        self.pin = self.button(row, 'pin', tooltip('항상 위에', 'Ctrl+T'),
                               lambda: host.set_always_on_top(not host.config['always_on_top']))
        self.pin.setCheckable(True)
        self.more = self.button(row, 'more', tooltip('앱 메뉴', 'Alt / Alt+A'), self.show_menu)
        self.deadline = 0
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
        self.tips.add(item)
        item.clicked.connect(lambda checked=False: callback())
        row.addWidget(item)
        return item

    def refresh(self):
        state = (self.host.config['layout'], self.host.config['always_on_top'],
                 self.host.isFullScreen(), self.host.config.get('master_muted', False),
                 self.host.config['split_orientation'])
        if state == self.last_state:
            return
        self.last_state = state
        for count, button in self.layout_buttons.items():
            button.setChecked(count == self.host.config['layout'])
        vertical = state[4] == 'vertical'
        self.layout_buttons[2].setIcon(icon('layout2_vertical' if vertical else 'layout2'))
        direction = ('좌우' if vertical else '상하') if state[0] == 2 else ('상하' if vertical else '좌우')
        self.layout_buttons[2].setToolTip(tooltip(f'2분할 · {direction}로 전환', '2'))
        self.layout_buttons[2].setAccessibleName(self.layout_buttons[2].toolTip())
        self.pin.setChecked(self.host.config['always_on_top'])
        self.pin.setToolTip(tooltip(topmost_name(state[1]), 'Ctrl+T'))
        self.pin.setAccessibleName(self.pin.toolTip())
        self.master_mute.setChecked(state[3])
        self.master_mute.setIcon(icon('muted' if state[3] else 'volume'))
        self.master_mute.setToolTip(tooltip(master_mute_name(state[3]), 'Ctrl+Shift+M'))
        self.master_mute.setAccessibleName(self.master_mute.toolTip())
        self.fullscreen.setIcon(icon('restore' if self.host.isFullScreen() else 'fullscreen'))
        self.fullscreen.setToolTip(tooltip(fullscreen_name(self.host.isFullScreen()), 'F11'))
        self.fullscreen.setAccessibleName(self.fullscreen.toolTip())

    def position(self):
        position = self.host.mapToGlobal(QPoint((self.host.width() - self.width()) // 2, 10))
        if self.pos() != position:
            self.move(position)

    def maintain_front(self):
        if (not self.isVisible() or self.menu_open or QApplication.activePopupWidget() is not None
                or self.host.modal_depth or self.host.closing
                or (not self.host.config['always_on_top'] and not self.host.app_is_foreground())):
            return
        if keep_above_owned_windows(self, [self.host] + [t.overlay for t in self.host.tiles]):
            self.update()
            self.panel.update()

    def hideEvent(self, event):
        self.tips.clear()
        # Recompose the layered input surfaces exposed by this owned window.
        exposed = QRect(self.geometry())
        super().hideEvent(event)
        for tile in self.host.tiles:
            overlay = tile.overlay
            intersection = exposed.intersected(overlay.geometry())
            if overlay.isVisible() and not intersection.isEmpty():
                intersection.translate(-overlay.pos())
                overlay.update(intersection)
        self.host.position_screen_labels()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)

    def reveal(self):
        if (self.host.modal_depth or self.host.closing or self.host.isMinimized()
                or not self.host.isVisible() or QApplication.activePopupWidget() is not None):
            return
        self.position()
        self.refresh()
        self.deadline = time.monotonic() + 1.6
        if not self.isVisible():
            self.show()
            set_topmost(self, self.host.config['always_on_top'])
        self.maintain_front()
        self.host.position_screen_labels()

    def poll(self):
        if self.host.closing or self.host.modal_depth or self.host.isMinimized() or not self.host.isVisible():
            self.hide()
            self.host.position_screen_labels()
            return
        # A popup owns input and stacking until its entire submenu chain closes.
        # In particular, do not show()/set_topmost() a hidden toolbar here.
        if QApplication.activePopupWidget() is not None:
            return
        # No invisible window covers the video. Only the narrow top-centre zone
        # reveals controls; keep them while crossing from video to the toolbar.
        point = self.host.mapFromGlobal(QCursor.pos())
        zone = QRect((self.host.width() - self.width()) // 2 - 8, 10, self.width() + 16, 48)
        if zone.contains(point) and (self.host.config['always_on_top'] or self.host.app_is_foreground()):
            self.reveal()
            return
        elif self.isVisible() and not self.menu_open and time.monotonic() > self.deadline:
            self.hide()
            self.host.position_screen_labels()
        if self.isVisible():
            self.maintain_front()

    def show_menu(self):
        self.menu_open = True
        menu = self.host.build_app_menu(self)
        try:
            menu.exec(self.more.mapToGlobal(QPoint(self.more.width(), self.more.height() + 10))
                      - QPoint(menu.sizeHint().width(), 0))
        finally:
            self.menu_open = False
            menu.deleteLater()
            self.more.setDown(False)
            self.host.repair_overlays()
            self.reveal()

    def closeEvent(self, event):
        if not self.host.closing:
            event.ignore()
            self.host.close()
        else:
            super().closeEvent(event)
