from __future__ import annotations

import json
import copy
import multiprocessing
import sys
import traceback
import time
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QActionGroup, QColor, QCursor, QIcon, QPainter, QPen, QShortcut, QKeySequence
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QMenu,
    QMessageBox, QSlider, QToolButton, QToolTip, QVBoxLayout, QWidget, QWidgetAction)

from camera_model import (APP_NAME, APP_TITLE, LOAD_WARNINGS, camera_url, crypt, data_path, default_config, find_vlc_directory,
    ensure_layout_slots, fill_empty_slots, load_config, make_vlc_instance,
    new_camera, redact, save_config, supports_quality, camera_display_name)
from dialogs import CameraManager, UsageDialog
from native_window import (app_is_foreground, configure_app_identity, is_topmost, set_topmost,
                          taskbar_icon_state, ensure_taskbar_minimize, taskbar_can_minimize, system_minimize)
from playback import PlaybackWorker
from playback_profiles import PROFILES, instance_options, select_profile
from playback_diagnostics import PlaybackDiagnostics
from single_instance import InstanceGuard
from icons import icon
from chrome import AppChrome
from menu_labels import (CAMERAS, TOPMOST, LAYOUT, OPACITY, fullscreen_name, menu_text, tooltip,
                         topmost_name, master_mute_name, hardware_name)
from volume_popup import VolumePopup

VERSION = '1.0.0-rc.3'
MENU_STYLE = '''QMenu{background:#151c27;color:#dae5f5;border:1px solid #354155;
padding:7px;border-radius:10px;font-family:Segoe UI;font-size:12px;}
QMenu::item{padding:7px 24px 7px 10px;border-radius:5px;}
QMenu::item:selected{background:#2b3b52;} QMenu::item:disabled{color:#7e8ca2;}
QMenu::separator{height:1px;background:#303b4e;margin:6px 4px;}
QSlider::groove:horizontal{height:3px;background:#36455b;border-radius:1px;}
QSlider::sub-page:horizontal{background:#8dbbfa;border-radius:1px;}
QSlider::handle:horizontal{background:#d4e6ff;width:10px;margin:-4px 0;border-radius:5px;}'''


def app_icon():
    return QIcon(str(Path(__file__).resolve().with_name('camfloat.ico')))


class PlayerTile(QWidget):
    def __init__(self, host, index, instance):
        super().__init__(host)
        self.host, self.index, self.instance = host, index, instance
        self.setStyleSheet('background:#080b10;')
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        player = instance.media_player_new()
        player.set_hwnd(int(self.winId()))
        player.video_set_mouse_input(False)
        player.video_set_key_input(False)
        self.current_key = None
        self.worker = PlaybackWorker(instance, player, hwnd=int(self.winId()), profile=host.playback_profile)
        self.attempt_started = 0
        self.retry_at = None
        self.retry_count = 0
        self.status_text = ''
        self.last_clock = None
        self.last_progress = 0
        self.clock_progress_seen = False
        self.ever_played = False
        self.initial_failed = False
        self.last_frame_count = None
        self.last_frame_progress = 0
        self.overlay = InputOverlay(host, index)

    @property
    def player(self):
        return self.worker.player

    def play_camera(self, camera):
        if not camera or camera.get('connection_locked'):
            self.stop()
            if camera and camera.get('connection_locked'):
                self.status_text = '연결 정보 확인 필요\n저장한 Windows 계정 또는 설정 백업을 확인하세요'
            return
        url = camera_url(camera)
        key = (camera['id'], url, self.host.config['hardware_acceleration'])
        if key != self.current_key:
            self.current_key = key
            self.retry_count = 0
            self.ever_played = False
            self.initial_failed = False
            self.start_attempt(camera)
        self.apply_audio(camera)

    def start_attempt(self, camera, reset=False):
        self.attempt_started = time.monotonic()
        self.last_clock = None
        self.clock_progress_seen = False
        self.last_progress = self.attempt_started
        self.last_frame_count = None
        self.last_frame_progress = self.attempt_started
        self.retry_at = None
        self.initial_failed = False
        self.status_text = '영상 연결 중…'
        self.worker.request((camera_url(camera), self.host.config['hardware_acceleration'],
                             camera['volume'], self.host.audio_muted(camera)), reset=reset)

    def apply_audio(self, camera):
        self.worker.set_audio(camera['volume'], self.host.audio_muted(camera))

    def clock_stalled(self, now):
        clock = self.player.get_time()
        if clock < 0:
            return False
        if self.last_clock is None:
            self.last_clock, self.last_progress = clock, now
        elif clock != self.last_clock:
            self.last_clock, self.last_progress = clock, now
            self.clock_progress_seen = True
        # Some cameras never expose a media clock. Only watch clocks which
        # actually advanced, and allow 20 seconds for jitter/buffering.
        return self.clock_progress_seen and now - self.last_progress > 20

    def stop(self):
        if self.current_key is not None:
            self.worker.request(None)
            self.current_key = None
        self.retry_at = None
        self.retry_count = 0
        self.status_text = ''
        self.ever_played = False
        self.initial_failed = False

    def media_statistics(self):
        import vlc
        media = self.player.get_media()
        if media is None:
            return None
        try:
            stats = vlc.MediaStats()
            if not media.get_stats(stats):
                return None
            return {name: getattr(stats, name) for name in (
                'read_bytes', 'demux_read_bytes', 'demux_corrupted', 'demux_discontinuity',
                'decoded_video', 'decoded_audio', 'displayed_pictures', 'lost_pictures', 'played_abuffers')}
        finally:
            media.release()

    def displayed_frames(self):
        stats = self.media_statistics()
        return stats['displayed_pictures'] if stats else None

    def frames_stalled(self, now):
        count = self.displayed_frames()
        if count is None or count <= 0:
            return False
        if count != self.last_frame_count:
            self.last_frame_count, self.last_frame_progress = count, now
        return now - self.last_frame_progress > 20

    def release(self):
        self.worker.shutdown()
        self.overlay.close()


class InputOverlay(QWidget):
    """Owned layered window: VLC's native video child cannot steal its input."""
    def __init__(self, host, index):
        super().__init__(host, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.host, self.index = host, index
        self.setWindowTitle(f'CamFloat · 화면 {index + 1}')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.origin = None
        self.start_geometry = None
        self.edges = ()
        self.hovered = False
        self.activation_press = False
        self.click_candidate = False
        self.dragged = False
        self.multi_click = False
        self.label = QWidget(self)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        label_box = QVBoxLayout(self.label)
        label_box.setContentsMargins(0, 0, 0, 0)
        label_box.setSpacing(3)
        badges = QHBoxLayout()
        badges.setSpacing(5)
        self.screen_badge = QLabel(f'SCREEN {index + 1}')
        self.quality_badge = QLabel('HD')
        for badge in (self.screen_badge, self.quality_badge):
            badge.setStyleSheet('background:rgba(12,18,28,218);color:#e8f1ff;'
                                'font-size:10px;font-weight:600;padding:3px 6px;border-radius:4px;')
            badges.addWidget(badge)
        self.quality_badge.setStyleSheet('background:rgba(43,105,174,155);color:#e9f4ff;'
                                        'font-size:10px;font-weight:600;padding:3px 6px;border-radius:4px;')
        badges.addStretch()
        label_box.addLayout(badges)
        self.camera_name = QLabel()
        self.camera_name.setTextFormat(Qt.TextFormat.PlainText)
        self.camera_name.setStyleSheet('background:rgba(12,18,28,205);color:#ecf3ff;'
                                      'font-size:11px;padding:2px 6px;border-radius:4px;')
        label_box.addWidget(self.camera_name, 0, Qt.AlignmentFlag.AlignLeft)
        self.empty = QLabel(self)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setStyleSheet('color:#9bacc4;background:transparent;font-size:13px;')
        self.empty.setWordWrap(True)
        self.empty.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.bar = QWidget(self)
        self.bar.setObjectName('screenBar')
        self.bar.setStyleSheet('QWidget#screenBar{background:rgba(19,24,33,235);border-radius:10px;'
            'border:1px solid rgba(174,194,223,35);color:#dce8f8;}'
            'QSlider::groove:horizontal{height:3px;background:#3b485c;border-radius:1px;}'
            'QSlider::sub-page:horizontal{background:#8dbbfa;}'
            'QSlider::handle:horizontal{background:#d4e6ff;width:9px;margin:-3px 0;border-radius:4px;}')
        row = QHBoxLayout(self.bar)
        row.setContentsMargins(5, 3, 5, 3)
        row.setSpacing(3)
        def button(symbol, tooltip, callback):
            item = QToolButton(self.bar)
            item.setFixedSize(26, 26)
            item.setIconSize(QSize(17, 17))
            item.setIcon(icon(symbol))
            item.setToolTip(tooltip)
            item.setAccessibleName(tooltip)
            item.setStyleSheet('QToolButton{border:0;background:transparent;border-radius:4px;}'
                              'QToolButton:hover{background:rgba(102,158,235,70);}'
                              'QToolButton:pressed{background:rgba(102,158,235,110);}')
            item.clicked.connect(lambda: (self.host.select_slot(self.index), callback()))
            item.installEventFilter(self)
            return item
        self.reload = button('refresh', tooltip('이 영상 다시 연결', 'Ctrl+R'), lambda: self.host.reconnect(self.index))
        self.choose = button('camera', '이 화면의 카메라 지정', self.choose_camera)
        self.mute = button('muted', tooltip('이 영상 음소거 해제', 'M'), lambda: self.host.toggle_mute(self.index))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(64)
        self.volume.setToolTip('이 영상 음량')
        self.volume.setAccessibleName('이 영상 음량')
        self.volume.installEventFilter(self)
        self.volume.valueChanged.connect(lambda value: self.host.set_volume(self.index, value))
        self.value = QLabel('100')
        self.value.setFixedWidth(23)
        self.value.setStyleSheet('background:transparent;')
        row.addWidget(self.reload)
        row.addWidget(self.mute)
        row.addWidget(self.volume)
        row.addWidget(self.value)
        row.addWidget(self.choose)
        self.fullscreen = button('fullscreen', tooltip('전체화면', 'F11'), lambda: self.host.toggle_fullscreen(self.index))
        row.addWidget(self.fullscreen)
        self.previous = button('left', '이전 카메라 (←)', lambda: self.host.cycle_camera(-1))
        self.following = button('right', '다음 카메라 (→)', lambda: self.host.cycle_camera(1))
        for item in (self.previous, self.following):
            item.setParent(self)
            item.setFixedSize(32, 40)
            item.setStyleSheet('QToolButton{background:rgba(12,18,28,190);border:0;border-radius:7px;}'
                              'QToolButton:hover{background:rgba(48,101,170,220);}')
        self.bar.hide()
        self.label.hide()
        self.previous.hide()
        self.following.hide()
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.setInterval(2500)
        self.idle_timer.timeout.connect(self.hide_idle_controls)
        self.volume_popup = VolumePopup(self)

    def reveal_controls(self):
        self.hovered = True
        self.refresh()
        self.idle_timer.start()

    def hide_idle_controls(self):
        if (self.bar.underMouse() or self.previous.underMouse() or self.following.underMouse()
                or self.volume.isSliderDown() or self.volume_popup.isVisible()):
            self.idle_timer.start()
            return
        self.hovered = False
        self.label.hide()
        self.bar.hide()
        self.previous.hide()
        self.following.hide()
        self.volume_popup.hide()

    def choose_camera(self):
        self.host.select_slot(self.index)
        menu = self.host.new_menu(parent=self)
        self.host.populate_camera_menu(menu, self.index)
        menu.exec(self.choose.mapToGlobal(QPoint(0, 0)) - QPoint(0, menu.sizeHint().height()))
        menu.deleteLater()
        self.reveal_controls()

    def paintEvent(self, event):
        painter = QPainter(self)
        # Alpha must stay nonzero so the layered HWND receives input over video.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 4))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if self.host.selection_border_visible(self.index):
            painter.setPen(QPen(QColor('#77b5ff'), 2))
            painter.drawRect(self.rect().adjusted(1, 1, -2, -2))

    def closeEvent(self, event):
        if not self.host.closing:
            event.ignore()
            self.host.close()
            return
        super().closeEvent(event)

    def resizeEvent(self, event):
        self.label.move(8, 8)
        compact = self.width() < 230 or self.height() < 140
        self.empty.setGeometry(self.rect().adjusted(8, 32, -8, -8 if compact else -42))
        self.arrange_controls()
        super().resizeEvent(event)
        self.refresh()

    def nativeEvent(self, event_type, message):
        # WM_MOUSEACTIVATE precedes activation. Checking isActiveWindow inside
        # mousePressEvent is too late: the first returning click would deselect.
        import ctypes
        from ctypes import wintypes
        native = wintypes.MSG.from_address(int(message))
        if native.message == 0x0021:
            self.activation_press = not self.host.app_is_foreground()
        return super().nativeEvent(event_type, message)

    def eventFilter(self, watched, event):
        if watched == self.mute:
            if event.type() == QEvent.Type.Enter:
                self.volume_popup.show_for_speaker()
            elif event.type() == QEvent.Type.Leave:
                self.volume_popup.schedule_hide()
            elif event.type() == QEvent.Type.Wheel:
                self.adjust_volume_wheel(event)
                return True
        if event.type() == QEvent.Type.MouseButtonPress:
            # A control consumes its returning click. Do not retain that native
            # activation snapshot for the next click on the video background.
            self.activation_press = False
            self.host.last_double = None
            self.host.select_slot(self.index)
        return super().eventFilter(watched, event)

    def expanded_controls(self):
        return self.width() >= 310 and self.height() >= 150

    def adjust_volume_wheel(self, event):
        camera = self.host.camera_for_slot(self.index)
        if camera and event.angleDelta().y():
            steps = max(1, abs(event.angleDelta().y()) // 120)
            self.host.set_volume(self.index, camera['volume'] + (5 * steps if event.angleDelta().y() > 0 else -5 * steps))
        event.accept()

    def arrange_controls(self):
        expanded = self.expanded_controls()
        if expanded and hasattr(self, 'volume_popup'):
            self.volume_popup.hide()
        self.volume.setVisible(expanded)
        self.value.setVisible(expanded)
        width = 232 if expanded else 128
        self.bar.setGeometry(max(5, self.width() - width - 8), max(4, self.height() - 40), width, 32)
        self.previous.move(10, max(48, (self.height() - 40) // 2))
        self.following.move(max(10, self.width() - 42), max(48, (self.height() - 40) // 2))

    def show_status(self, text):
        if self.width() < 230 or self.height() < 140:
            text = text.split('\n')[0]
        self.empty.setText(text)
        self.empty.setVisible(bool(text))

    def refresh(self):
        camera = self.host.camera_for_slot(self.index)
        name = camera_display_name(camera) if camera else '비어 있음'
        self.screen_badge.setText(self.host.slot_name(self.index))
        self.quality_badge.setText(camera['quality'] if camera else '—')
        self.camera_name.setText(self.camera_name.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight,
                                                                         max(20, self.width() - 32)))
        self.camera_name.setAccessibleName(name)
        self.label.setMaximumWidth(max(110, self.width() - 16))
        self.label.adjustSize()
        self.label.setVisible(self.hovered)
        self.arrange_controls()
        self.bar.setVisible(self.hovered)
        enlarged = self.host.focused_screen is not None
        navigation = self.hovered and (enlarged or (self.host.config['layout'] == 1 and
            sum(c.get('enabled', True) for c in self.host.config['cameras']) > 1))
        self.previous.setVisible(navigation)
        self.following.setVisible(navigation)
        self.previous.setToolTip(tooltip('이전 SCREEN' if enlarged else '이전 카메라', '←'))
        self.following.setToolTip(tooltip('다음 SCREEN' if enlarged else '다음 카메라', '→'))
        self.previous.setAccessibleName(self.previous.toolTip())
        self.following.setAccessibleName(self.following.toolTip())
        self.reload.setEnabled(bool(camera) and not camera.get('connection_locked'))
        self.mute.setEnabled(bool(camera))
        self.volume.setEnabled(bool(camera))
        self.fullscreen.setIcon(icon('restore' if self.host.isFullScreen() else 'fullscreen'))
        self.fullscreen.setToolTip(tooltip(fullscreen_name(self.host.isFullScreen()), 'F11'))
        self.fullscreen.setAccessibleName(self.fullscreen.toolTip())
        if camera:
            self.volume.blockSignals(True)
            self.volume.setValue(camera['volume'])
            self.volume.blockSignals(False)
            self.value.setText(str(camera['volume']))
            self.mute.setIcon(icon('muted' if self.host.audio_muted(camera) else 'volume'))
            name = '이 영상 음소거 해제' if camera['muted'] else '이 영상 음소거'
            if self.host.config.get('master_muted', False):
                name = '전체 음소거 중 · 개별 ' + ('음소거 해제' if camera['muted'] else '음소거')
            self.mute.setToolTip(tooltip(name, 'M'))
            self.mute.setAccessibleName(self.mute.toolTip())
            self.volume_popup.slider.blockSignals(True)
            self.volume_popup.slider.setValue(camera['volume'])
            self.volume_popup.slider.blockSignals(False)
            self.show_status(self.host.tiles[self.index].status_text)
        else:
            self.volume_popup.hide()
            self.show_status('화면 비움 상태\n카메라가 지정되지 않았습니다')
        if hasattr(self.host, 'chrome'):
            self.host.position_screen_labels()
        self.update()

    def enterEvent(self, event):
        self.reveal_controls()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered = False
        self.label.hide()
        self.bar.hide()
        self.previous.hide()
        self.following.hide()
        self.volume_popup.hide()
        super().leaveEvent(event)

    def hideEvent(self, event):
        if hasattr(self, 'volume_popup'):
            self.volume_popup.hide_timer.stop()
            self.volume_popup.hide()
        super().hideEvent(event)

    def mousePressEvent(self, event):
        self.click_candidate = False
        self.dragged = False
        self.multi_click = False
        if event.button() == Qt.MouseButton.RightButton:
            self.host.select_slot(self.index)
            self.host.show_context_menu(self.index, event.globalPosition().toPoint(), self)
        elif event.button() == Qt.MouseButton.LeftButton:
            returning = self.activation_press or not self.host.app_is_foreground()
            self.activation_press = False
            self.multi_click = self.host.consume_third_click(event.globalPosition().toPoint())
            if not self.multi_click:
                self.click_candidate = self.host.selected == self.index and not returning
                self.host.select_slot(self.index)
            self.origin = event.globalPosition().toPoint()
            self.start_geometry = QRect(self.host.geometry())
            self.edges = self.host.edges_at(self.origin)
            if self.edges:
                self.click_candidate = False
        event.accept()

    def mouseMoveEvent(self, event):
        self.reveal_controls()
        point = event.globalPosition().toPoint()
        if self.origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if (point - self.origin).manhattanLength() >= 3:
                self.dragged = True
                self.click_candidate = False
                self.host.drag_geometry(self.start_geometry, point - self.origin, self.edges)
        else:
            self.setCursor(self.host.resize_cursor(self.host.edges_at(point)))
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.click_candidate and not self.dragged and not self.multi_click:
            self.host.deselect_slot(self.index)
        self.click_candidate = False
        if self.origin is not None:
            self.host.queue_save()
        self.origin = None
        self.start_geometry = None
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.host.edges_at(event.globalPosition().toPoint()):
            self.origin = None
            self.click_candidate = False
            self.multi_click = True
            self.host.select_slot(self.index)
            self.host.record_double_click(self.index, event.globalPosition().toPoint())
            self.host.toggle_focus(self.index)
        event.accept()


class VideoLayout:
    """Geometry-only layout: enlarging a native video never reparents its HWND."""
    def __init__(self, host):
        self.host = host

    def activate(self):
        self.host.arrange_tiles()
        return True


class PlayerWindow(QWidget):
    def __init__(self, config, instance, persist=True):
        super().__init__()
        self.config, self.instance, self.persist_enabled = config, instance, persist
        self.config.setdefault('master_muted', False)
        self.config.setdefault('split_orientation', 'horizontal')
        self.playback_profile = QApplication.instance().property('playback_profile') or 'auto'
        QApplication.setEffectEnabled(Qt.UIEffect.UI_FadeMenu, False)
        QApplication.setEffectEnabled(Qt.UIEffect.UI_AnimateMenu, False)
        ensure_layout_slots(self.config)
        self.selected = None
        self.last_double = None
        self.modal_depth = 0
        self.closing = False
        self.focused_screen = None
        self.fullscreen_geometry = None
        self.fullscreen_previous_focus = None
        self.fullscreen_entry_layout = None
        self.save_error_reported = False
        self.tiles = []
        self.setWindowTitle(APP_TITLE + (
            f' · {PROFILES[self.playback_profile]}' if self.playback_profile != 'auto' else ''))
        self.setWindowIcon(app_icon())
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(300, 180)
        self.setStyleSheet('PlayerWindow{background:#080b10;}')
        self.grid = VideoLayout(self)
        for index in range(4):
            self.tiles.append(PlayerTile(self, index, instance))
        self.chrome = AppChrome(self)
        self.chrome_restack_pending = False
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(350)
        self.save_timer.timeout.connect(self.persist)
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(1200)
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start()
        geometry = config.get('geometry')
        if geometry:
            self.setGeometry(*geometry)
        else:
            self.resize(960, 540)
            self.move(QApplication.primaryScreen().availableGeometry().topLeft() + QPoint(80, 80))
        self.fit_to_screen()
        self.shortcuts = []
        for key, callback in [('Ctrl+M', self.manage_cameras), ('F1', self.show_help),
                ('Ctrl+T', lambda: self.set_always_on_top(not self.config['always_on_top'])),
                ('Ctrl+0', lambda: self.set_opacity(100)), ('Escape', self.handle_escape),
                ('F11', lambda: self.toggle_fullscreen(self.selected)),
                ('Left', lambda: self.cycle_camera(-1)), ('Right', lambda: self.cycle_camera(1)),
                ('M', lambda: self.toggle_mute(self.selected)),
                ('Ctrl+Shift+M', self.mute_all),
                ('Ctrl+R', lambda: self.reconnect(self.selected))]:
            self.add_shortcut(key, callback)
        for count in (1, 2, 4):
            self.add_shortcut(str(count), lambda n=count: self.set_layout(n))
        self.add_shortcut('Alt+A', self.chrome.reveal)
        QApplication.instance().installEventFilter(self)
        self.refresh_layout()

    def add_shortcut(self, key, callback):
        shortcut = QShortcut(QKeySequence(key), self)
        shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut.activated.connect(lambda: callback() if not self.modal_depth and not self.closing else None)
        self.shortcuts.append(shortcut)

    def fit_to_screen(self):
        screens = QApplication.screens()
        screen = max(screens, key=lambda s: (s.availableGeometry().intersected(self.geometry()).width()
                                            * s.availableGeometry().intersected(self.geometry()).height()))
        area = screen.availableGeometry()
        width, height = min(self.width(), area.width()), min(self.height(), area.height())
        self.setGeometry(max(area.left(), min(self.x(), area.right() - width + 1)),
                         max(area.top(), min(self.y(), area.bottom() - height + 1)), width, height)

    def camera_for_slot(self, index):
        if index is None or not 0 <= index < self.config['layout']:
            return None
        identifier = self.config['slots'][index]
        return next((c for c in self.config['cameras'] if c['id'] == identifier and c.get('enabled', True)), None)

    def slot_name(self, index):
        return f'SCREEN {index + 1}'

    def select_slot(self, index):
        self.selected = index
        for tile in self.tiles:
            tile.overlay.update()
        self.queue_chrome_front()

    def queue_chrome_front(self):
        if not hasattr(self, 'chrome') or self.closing or self.chrome_restack_pending:
            return
        self.chrome_restack_pending = True
        QTimer.singleShot(0, self.restore_chrome_front)

    def restore_chrome_front(self):
        self.chrome_restack_pending = False
        if not self.closing:
            self.chrome.maintain_front()

    def position_screen_labels(self):
        for tile in self.tiles:
            overlay = tile.overlay
            label_rect = QRect(overlay.mapToGlobal(QPoint(8, 8)), overlay.label.size())
            overlap = self.chrome.isVisible() and self.chrome.geometry().intersects(label_rect)
            overlay.label.move(8, 62 if overlap and overlay.height() >= 180 else 8)
            overlay.label.setVisible(overlay.hovered and not (overlap and overlay.height() < 180))

    app_is_foreground = staticmethod(app_is_foreground)

    def deselect_slot(self, index):
        if self.selected == index:
            self.select_slot(None)

    def selection_border_visible(self, index):
        return (self.selected == index and self.config['layout'] > 1
                and not (self.isFullScreen() and self.focused_screen is not None))

    def repair_overlays(self):
        if self.closing:
            return
        QToolTip.hideText()
        self.sync_overlays()
        for tile in self.tiles:
            tile.overlay.update()
            tile.overlay.bar.update()
        self.chrome.update()
        self.chrome.panel.update()

    def record_double_click(self, index, position):
        self.last_double = (index, QPoint(position), time.monotonic())

    def consume_third_click(self, position):
        previous, self.last_double = self.last_double, None
        if previous is None:
            return False
        index, point, timestamp = previous
        if (time.monotonic() - timestamp > QApplication.doubleClickInterval() / 1000
                or (point - position).manhattanLength() > QApplication.startDragDistance()):
            return False
        self.select_slot(index)
        if self.config['layout'] > 1:
            if self.fullscreen_geometry is None:
                self.toggle_fullscreen(index)
            else:
                self.single_view(index)
        return True

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.WindowActivate and isinstance(watched, QWidget)
                and (watched is self or any(watched is t.overlay for t in self.tiles))):
            # Windows can promote an owned SCREEN after mouse activation has
            # returned. Repair once in the next event turn without taking focus.
            self.queue_chrome_front()
        if (event.type() == QEvent.Type.KeyRelease and event.key() == Qt.Key.Key_Alt
                and not self.modal_depth and not self.closing and self.app_is_foreground()):
            self.chrome.reveal()
        return super().eventFilter(watched, event)

    def persist(self):
        if not self.persist_enabled:
            return
        geometry = self.fullscreen_geometry or (self.normalGeometry() if self.isMinimized() or self.isMaximized() else self.geometry())
        self.config['geometry'] = [geometry.x(), geometry.y(), geometry.width(), geometry.height()]
        try:
            save_config(self.config)
            self.save_error_reported = False
        except Exception:
            self.save_timer.stop()
            if not self.save_error_reported:
                self.save_error_reported = True
                with self.modal():
                    QMessageBox.warning(self, APP_NAME, '설정을 저장하지 못했습니다. 저장 폴더의 접근 권한을 확인하세요.')

    def queue_save(self):
        if self.persist_enabled and not self.closing:
            self.save_timer.start()

    def refresh_layout(self):
        count = self.config['layout']
        if self.selected is not None and self.selected >= count:
            self.select_slot(None)
        for index, tile in enumerate(self.tiles):
            if index < count:
                tile.show()
                tile.play_camera(self.camera_for_slot(index))
            else:
                tile.hide()
                tile.stop()
            tile.overlay.refresh()
        self.grid.activate()
        self.set_opacity(self.config['opacity'], save=False)
        self.chrome.refresh()
        QTimer.singleShot(0, self.sync_overlays)

    def arrange_tiles(self):
        count = self.config['layout']
        columns, rows = ((1, 1) if count == 1 else
                         (1, 2) if count == 2 and self.config['split_orientation'] == 'vertical' else
                         (2, count // 2))
        for index, tile in enumerate(self.tiles[:count]):
            row, col = divmod(index, columns)
            left, right = self.width() * col // columns, self.width() * (col + 1) // columns
            top, bottom = self.height() * row // rows, self.height() * (row + 1) // rows
            tile.setGeometry(left, top, right - left, bottom - top)
        if self.focused_screen is not None:
            tile = self.tiles[self.focused_screen]
            tile.setGeometry(self.rect())
            tile.raise_()

    def sync_overlays(self):
        show = self.isVisible() and not self.isMinimized() and not self.modal_depth and not self.closing
        for index, tile in enumerate(self.tiles):
            overlay = tile.overlay
            visible = index < self.config['layout'] and (self.focused_screen is None or index == self.focused_screen)
            if show and visible:
                overlay.setGeometry(QRect(tile.mapToGlobal(QPoint(0, 0)), tile.size()))
                if not overlay.isVisible():
                    overlay.show()
                    set_topmost(overlay, self.config['always_on_top'])
                    overlay.raise_()
            else:
                overlay.hide()
        if hasattr(self, 'chrome'):
            if show:
                self.chrome.position()
                if self.chrome.isVisible():
                    self.chrome.maintain_front()
                self.position_screen_labels()
            else:
                self.chrome.hide()

    def showEvent(self, event):
        super().showEvent(event)
        ensure_taskbar_minimize(self)
        set_topmost(self, self.config['always_on_top'])
        QTimer.singleShot(0, self.sync_overlays)

    def hideEvent(self, event):
        for tile in self.tiles:
            tile.overlay.hide()
        if hasattr(self, 'chrome'):
            self.chrome.hide()
        super().hideEvent(event)

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.tiles:
            self.sync_overlays()
        if hasattr(self, 'save_timer'):
            self.queue_save()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'grid'):
            self.grid.activate()
        QTimer.singleShot(0, self.sync_overlays)
        if hasattr(self, 'save_timer'):
            self.queue_save()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            if hasattr(self, 'chrome'):
                self.apply_opacity()
            QTimer.singleShot(0, self.sync_overlays)

    def closeEvent(self, event):
        if not self.closing:
            self.persist()
            self.closing = True
            self.status_timer.stop()
            self.save_timer.stop()
            self.chrome.timer.stop()
            QApplication.instance().removeEventFilter(self)
            self.chrome.close()
            for tile in self.tiles:
                tile.release()
        if not all(tile.worker.done.is_set() for tile in self.tiles):
            event.ignore()
            self.hide()
            QTimer.singleShot(50, self.close)
            return
        super().closeEvent(event)
        # We hid the window while stop() ran. Qt does not emit lastWindowClosed
        # for an already-hidden window, so explicitly finish the application.
        QApplication.instance().quit()

    def edges_at(self, point):
        if self.isFullScreen():
            return ()
        rect = self.frameGeometry()
        return tuple(name for name, yes in [('left', abs(point.x() - rect.left()) < 10),
            ('right', abs(point.x() - rect.right()) < 10), ('top', abs(point.y() - rect.top()) < 10),
            ('bottom', abs(point.y() - rect.bottom()) < 10)] if yes)

    @staticmethod
    def resize_cursor(edges):
        if ('left' in edges and 'top' in edges) or ('right' in edges and 'bottom' in edges):
            return Qt.CursorShape.SizeFDiagCursor
        if ('right' in edges and 'top' in edges) or ('left' in edges and 'bottom' in edges):
            return Qt.CursorShape.SizeBDiagCursor
        if 'left' in edges or 'right' in edges:
            return Qt.CursorShape.SizeHorCursor
        if edges:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def drag_geometry(self, rect, delta, edges):
        if self.isFullScreen():
            return
        target = QRect(rect)
        if not edges:
            target.translate(delta)
        else:
            if 'left' in edges:
                target.setLeft(min(rect.left() + delta.x(), rect.right() - self.minimumWidth() + 1))
            if 'right' in edges:
                target.setRight(max(rect.right() + delta.x(), rect.left() + self.minimumWidth() - 1))
            if 'top' in edges:
                target.setTop(min(rect.top() + delta.y(), rect.bottom() - self.minimumHeight() + 1))
            if 'bottom' in edges:
                target.setBottom(max(rect.bottom() + delta.y(), rect.top() + self.minimumHeight() - 1))
        self.setGeometry(target)
        self.grid.activate()
        self.sync_overlays()

    def set_layout(self, count, orientation=None):
        if count not in (1, 2, 4):
            raise ValueError('화면 구성은 1, 2, 4만 지원합니다.')
        QToolTip.hideText()
        if orientation is not None and orientation not in ('horizontal', 'vertical'):
            raise ValueError('2분할 방향은 좌우 또는 상하만 지원합니다.')
        same_layout = self.config['layout'] == count
        if count == 2:
            if orientation is not None:
                self.config['split_orientation'] = orientation
            elif same_layout:
                self.config['split_orientation'] = ('horizontal' if
                    self.config['split_orientation'] == 'vertical' else 'vertical')
        self.last_double = None
        if self.focused_screen is not None:
            self.restore_focus()
        self.config['layout'] = count
        self.config['slots'] = self.config['layout_slots'][str(count)]
        if same_layout:
            # A direction change only moves the existing native video surfaces.
            self.grid.activate()
            for tile in self.tiles:
                tile.overlay.refresh()
            self.sync_overlays()
            self.chrome.refresh()
        else:
            self.refresh_layout()
        self.queue_save()

    def set_always_on_top(self, enabled):
        # Preserve all VLC video HWNDs. Qt setWindowFlags would recreate them.
        set_topmost(self, enabled)
        for index, tile in enumerate(self.tiles):
            if index < self.config['layout'] and tile.overlay.isVisible():
                set_topmost(tile.overlay, enabled)
        self.config['always_on_top'] = bool(enabled)
        for widget in (self.chrome,):
            if widget.isVisible():
                set_topmost(widget, enabled)
        self.chrome.refresh()
        self.queue_chrome_front()
        self.queue_save()

    def set_opacity(self, value, save=True):
        self.config['opacity'] = max(20, min(100, int(value)))
        self.apply_opacity()
        if save:
            self.queue_save()

    def apply_opacity(self):
        alpha = 1.0 if self.isFullScreen() else self.config['opacity'] / 100
        self.setWindowOpacity(alpha)
        for tile in self.tiles:
            tile.overlay.setWindowOpacity(alpha)
        self.chrome.setWindowOpacity(alpha)

    def audio_muted(self, camera):
        return bool(self.config.get('master_muted', False) or camera['muted'])

    def set_volume(self, index, value):
        camera = self.camera_for_slot(index)
        if camera:
            camera['volume'] = max(0, min(100, int(value)))
            self.tiles[index].apply_audio(camera)
            self.tiles[index].overlay.refresh()
            self.select_slot(index)
            self.queue_save()

    def toggle_mute(self, index):
        camera = self.camera_for_slot(index)
        if camera:
            camera['muted'] = not camera['muted']
            self.tiles[index].apply_audio(camera)
            self.tiles[index].overlay.refresh()
            self.select_slot(index)
            self.queue_save()

    def set_quality(self, index, quality):
        if quality not in ('HD', 'SD'):
            return
        camera = self.camera_for_slot(index)
        if camera and supports_quality(camera):
            camera['quality'] = quality
            self.tiles[index].play_camera(camera)
            self.tiles[index].overlay.refresh()
            self.queue_save()

    @staticmethod
    def assign_to_slots(slots, index, identifier):
        if identifier is not None and identifier in slots:
            other = slots.index(identifier)
            slots[other], slots[index] = slots[index], slots[other]
        else:
            slots[index] = identifier

    def assign_camera(self, index, identifier, keep_focus=False):
        if index >= self.config['layout']:
            return
        if identifier is not None and not any(c['id'] == identifier and c.get('enabled', True)
                and not c.get('connection_locked') for c in self.config['cameras']):
            return
        self.assign_to_slots(self.config['slots'], index, identifier)
        self.refresh_layout()
        self.queue_save()

    def cycle_camera(self, direction):
        if self.focused_screen is not None:
            self.single_view((self.focused_screen + direction) % self.config['layout'])
            self.tiles[self.focused_screen].overlay.reveal_controls()
            return
        cameras = [c for c in self.config['cameras'] if c.get('enabled', True)]
        if self.config['layout'] != 1 or len(cameras) < 2:
            return
        identifiers = [camera['id'] for camera in cameras]
        current = self.config['slots'][0]
        position = identifiers.index(current) if current in identifiers else (-1 if direction > 0 else 0)
        self.assign_camera(0, identifiers[(position + direction) % len(identifiers)], keep_focus=True)
        self.tiles[0].overlay.reveal_controls()

    @contextmanager
    def modal(self):
        self.modal_depth += 1
        for shortcut in self.shortcuts:
            shortcut.setEnabled(False)
        self.sync_overlays()
        try:
            yield
        finally:
            self.modal_depth -= 1
            if not self.modal_depth:
                for shortcut in self.shortcuts:
                    shortcut.setEnabled(True)
            self.sync_overlays()

    def manage_cameras(self):
        with self.modal():
            statuses = {}
            for index, tile in enumerate(self.tiles[:self.config['layout']]):
                camera = self.camera_for_slot(index)
                if camera:
                    statuses[camera['id']] = ('연결 확인 중' if tile.worker.busy else
                        '연결 끊김' if tile.initial_failed or tile.retry_at is not None or tile.worker.error else
                        '재생 중' if tile.ever_played else '미확인')
            dialog = CameraManager(self.config['cameras'], self, layout_slots=self.config['layout_slots'],
                layout=self.config['layout'], commit_callback=self.commit_camera_draft, statuses=statuses)
            dialog.exec()
            dialog.deleteLater()

    def commit_camera_draft(self, cameras, layout_slots, verify_connection_info):
        candidate = copy.deepcopy(self.config)
        candidate.update(cameras=copy.deepcopy(cameras), layout_slots=copy.deepcopy(layout_slots),
                         verify_connection_info=bool(verify_connection_info))
        ensure_layout_slots(candidate)
        try:
            if self.persist_enabled:
                save_config(candidate)
        except (OSError, ValueError, TypeError):
            return False
        self.config = candidate
        self.refresh_layout()
        return True

    def apply_camera_registry(self, cameras, assigned_slots=None, layout_slots=None):
        previous = {c['id']: c.get('enabled', True) for c in self.config['cameras']}
        self.config['cameras'] = cameras
        if layout_slots is not None:
            self.config['layout_slots'] = layout_slots
        ensure_layout_slots(self.config)
        if layout_slots is None:
            additions = [c['id'] for c in cameras if c.get('enabled', True) and not previous.get(c['id'], False)]
            fill_empty_slots(self.config, additions)
        if assigned_slots is not None:
            self.config['layout_slots'][str(self.config['layout'])] = list(assigned_slots)
            ensure_layout_slots(self.config)
        self.refresh_layout()
        self.persist()

    def update_status(self):
        for index, tile in enumerate(self.tiles[:self.config['layout']]):
            camera = self.camera_for_slot(index)
            if not camera or tile.current_key is None:
                continue
            if tile.initial_failed:
                tile.status_text = '최초 연결 실패\n다시 연결 버튼으로 재시도'
                tile.overlay.show_status(tile.status_text)
                continue
            # A reset may replace and release the old native player. Do not
            # inspect that player until the serialized worker has published it.
            if tile.worker.busy:
                tile.status_text = '영상 연결 준비 중…'
                tile.overlay.show_status(tile.status_text)
                continue
            state = tile.player.get_state().value
            now = time.monotonic()
            visible_output = not self.isMinimized() and (self.focused_screen is None or self.focused_screen == index)
            if not visible_output:
                tile.last_frame_count, tile.last_frame_progress = None, now
            stalled = state == 3 and (tile.clock_stalled(now) or (visible_output and tile.frames_stalled(now)))
            if state == 3 and tile.player.has_vout() > 0 and not tile.worker.error and not stalled:
                tile.ever_played = True
                tile.initial_failed = False
                tile.status_text = ''
                tile.retry_at = None
                if now - tile.attempt_started > 20:
                    tile.retry_count = 0
                # Some audio devices become available only after the stream opens.
                tile.apply_audio(camera)
            elif tile.retry_at is not None:
                if now >= tile.retry_at:
                    tile.start_attempt(camera, reset=True)
                else:
                    seconds = max(1, int(tile.retry_at - now + .99))
                    tile.status_text = f'연결 끊김 · {seconds}초 후 자동 재연결\nIP주소·비밀번호·카메라 전원을 확인하세요'
            elif state in (4, 5, 6, 7) or tile.worker.error or stalled or now - tile.attempt_started > 15:
                if not tile.ever_played:
                    tile.initial_failed = True
                    tile.retry_at = None
                    tile.worker.request(None)
                    tile.status_text = '최초 연결 실패\n다시 연결 버튼으로 재시도'
                else:
                    delay = min(30, 2 ** min(tile.retry_count + 1, 5))
                    tile.retry_count += 1
                    tile.retry_at = now + delay
                    tile.status_text = f'연결 끊김 · {delay}초 후 자동 재연결\nIP주소·비밀번호·카메라 전원을 확인하세요'
            else:
                tile.status_text = '영상 연결 중…'
            tile.overlay.show_status(tile.status_text)

    def reconnect(self, index):
        camera = self.camera_for_slot(index)
        if camera and not camera.get('connection_locked'):
            self.tiles[index].retry_count = 0
            self.tiles[index].start_attempt(camera, reset=True)

    def single_view(self, index):
        if self.config['layout'] == 1 or not 0 <= index < self.config['layout']:
            return
        QToolTip.hideText()
        self.focused_screen = index
        self.select_slot(index)
        self.grid.activate()
        for tile in self.tiles:
            tile.overlay.refresh()
        self.sync_overlays()

    def restore_focus(self):
        if self.focused_screen is not None:
            QToolTip.hideText()
            if self.isFullScreen():
                self.fullscreen_previous_focus = None
            self.focused_screen = None
            self.grid.activate()
            for tile in self.tiles:
                tile.overlay.refresh()
            self.sync_overlays()

    def restore_slot(self, index):
        return index

    def activate(self):
        if self.fullscreen_geometry is not None:
            self.showFullScreen()
        else:
            self.showNormal()
        self.raise_()
        self.activateWindow()
        self.sync_overlays()

    def toggle_focus(self, index):
        if self.focused_screen is not None:
            self.restore_focus()
        elif self.config['layout'] > 1:
            self.single_view(index)
        else:
            self.toggle_fullscreen(index)

    def toggle_layout_fullscreen(self):
        self.toggle_fullscreen(None)

    def toggle_fullscreen(self, index=None):
        QToolTip.hideText()
        if self.fullscreen_geometry is not None:
            self.exit_fullscreen(restore_previous=True)
            return
        self.fullscreen_geometry = QRect(self.geometry())
        self.fullscreen_previous_focus = self.focused_screen
        self.fullscreen_entry_layout = self.config['layout']
        if index is not None and self.config['layout'] > 1:
            self.single_view(index)
        else:
            self.restore_focus()
        self.showFullScreen()
        self.apply_opacity()
        QTimer.singleShot(0, self.sync_overlays)
        for tile in self.tiles:
            tile.overlay.refresh()
        self.chrome.refresh()

    def exit_fullscreen(self, restore_layout=False, restore_previous=False):
        if self.fullscreen_geometry is None:
            return
        geometry = QRect(self.fullscreen_geometry)
        previous = self.fullscreen_previous_focus
        if restore_layout or restore_previous:
            self.restore_focus()
        if (restore_previous and previous is not None and self.config['layout'] == self.fullscreen_entry_layout
                and previous < self.config['layout']):
            self.single_view(previous)
        self.showNormal()
        self.apply_opacity()
        self.fullscreen_geometry = None
        self.fullscreen_previous_focus = None
        self.fullscreen_entry_layout = None
        self.setGeometry(geometry)
        self.grid.activate()
        self.sync_overlays()
        for tile in self.tiles:
            tile.overlay.refresh()
        self.chrome.refresh()
        self.queue_save()

    def handle_escape(self):
        if self.focused_screen is not None:
            self.restore_focus()
        elif self.fullscreen_geometry is not None:
            self.exit_fullscreen()

    def mute_all(self):
        self.config['master_muted'] = not self.config.get('master_muted', False)
        for index, tile in enumerate(self.tiles):
            camera = self.camera_for_slot(index)
            if camera:
                tile.apply_audio(camera)
            tile.overlay.refresh()
        self.chrome.refresh()
        self.queue_save()

    def show_help(self):
        with self.modal():
            dialog = UsageDialog(VERSION, PROFILES[self.playback_profile], self)
            dialog.setWindowIcon(self.windowIcon())
            dialog.exec()

    def new_menu(self, title='', parent=None):
        QToolTip.hideText()
        menu = QMenu(title, parent or self)
        menu.setStyleSheet(MENU_STYLE)
        menu.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        if parent is not self.chrome:
            # Screen menus must never compete with the independent tool HWND.
            # The toolbar's own app menu keeps its anchor visible.
            menu.aboutToShow.connect(self.chrome.hide)
        menu.aboutToHide.connect(lambda: QTimer.singleShot(0, self.repair_overlays))
        return menu

    def populate_camera_menu(self, menu, index):
        camera = self.camera_for_slot(index)
        group = QActionGroup(menu)
        group.setExclusive(True)
        enabled = [c for c in self.config['cameras'] if c.get('enabled', True)]
        for item in enabled:
            action = menu.addAction(icon('camera'), f"{item['number']}. {camera_display_name(item)}")
            action.setEnabled(not item.get('connection_locked'))
            action.setCheckable(True)
            action.setChecked(bool(camera and camera['id'] == item['id']))
            group.addAction(action)
            action.triggered.connect(lambda checked=False, cid=item['id']: self.assign_camera(index, cid, keep_focus=True))
        if not enabled:
            menu.addAction('사용 중인 카메라 없음').setEnabled(False)
        menu.addSeparator()
        if camera:
            menu.addAction(icon('close'), '이 화면 비우기', lambda: self.assign_camera(index, None, keep_focus=True))
        menu.addAction(icon('cameras'), menu_text(CAMERAS, 'Ctrl+M'), self.manage_cameras)

    def build_context_menu(self, index, parent=None):
        menu = self.new_menu(parent=parent)
        camera = self.camera_for_slot(index)
        title = menu.addAction(f"{self.slot_name(index)}  |  {camera_display_name(camera) if camera else '비어 있음'}")
        title.setEnabled(False)
        assign = menu.addMenu(icon('camera'), '이 화면의 카메라 지정')
        self.populate_camera_menu(assign, index)
        if camera:
            quality = menu.addMenu(icon('quality'), '이 영상 화질')
            quality.setEnabled(supports_quality(camera))
            quality.setToolTip('사용자 지정 경로는 카메라 수정에서 SD 전체 주소를 추가하세요.')
            quality_group = QActionGroup(quality)
            for label in ('HD', 'SD'):
                action = quality.addAction(label)
                action.setCheckable(True)
                action.setChecked(camera['quality'] == label)
                quality_group.addAction(action)
                action.triggered.connect(lambda checked=False, q=label: self.set_quality(index, q))
            volume_menu = menu.addMenu(icon('volume'), '이 영상 음량')
            volume_widget = QWidget()
            volume_box = QVBoxLayout(volume_widget)
            volume_label = QLabel(f"음량 {camera['volume']}%")
            volume_label.setStyleSheet('color:white;')
            volume_slider = QSlider(Qt.Orientation.Horizontal)
            volume_slider.setRange(0, 100)
            volume_slider.setValue(camera['volume'])
            volume_slider.setMinimumWidth(200)
            volume_slider.valueChanged.connect(lambda n: (volume_label.setText(f'음량 {n}%'), self.set_volume(index, n)))
            volume_box.addWidget(volume_label)
            volume_box.addWidget(volume_slider)
            volume_action = QWidgetAction(volume_menu)
            volume_action.setDefaultWidget(volume_widget)
            volume_menu.addAction(volume_action)
            mute = menu.addAction(icon('muted'), menu_text('이 영상 음소거 해제' if camera['muted'] else '이 영상 음소거', 'M'))
            mute.setCheckable(True)
            mute.setChecked(camera['muted'])
            mute.triggered.connect(lambda: self.toggle_mute(index))
            menu.addAction(icon('refresh'), menu_text('이 영상 다시 연결', 'Ctrl+R'), lambda: self.reconnect(index))
            if self.config['layout'] > 1:
                menu.addAction(icon('enlarge'), menu_text('이 화면만 크게 보기', '더블클릭'), lambda: self.single_view(index))
        if self.focused_screen is not None:
            menu.addAction(icon('restore'), menu_text('이전 분할로 복원', 'Esc'), self.restore_focus)
        menu.addAction(icon('restore' if self.isFullScreen() else 'fullscreen'), menu_text(fullscreen_name(self.isFullScreen()), 'F11'),
                       lambda: self.toggle_fullscreen(index))
        menu.addSeparator()
        menu.addMenu(self.build_app_menu(menu)).setIcon(icon('more'))
        return menu

    def build_app_menu(self, parent=None):
        menu = self.new_menu('앱 메뉴', parent)
        layouts = menu.addMenu(icon('layout'), LAYOUT)
        layout_group = QActionGroup(layouts)
        for count, orientation, label, symbol in (
                (1, None, '1분할', 'layout1'),
                (2, 'horizontal', '2분할 · 좌우', 'layout2'),
                (2, 'vertical', '2분할 · 상하', 'layout2_vertical'),
                (4, None, '4분할', 'layout4')):
            action = layouts.addAction(icon(symbol), menu_text(label, str(count)))
            action.setCheckable(True)
            action.setChecked(self.config['layout'] == count and
                              (orientation is None or orientation == self.config['split_orientation']))
            layout_group.addAction(action)
            action.triggered.connect(lambda checked=False, n=count, o=orientation: self.set_layout(n, o))
        menu.addAction(icon('muted' if self.config['master_muted'] else 'volume'),
            menu_text(master_mute_name(self.config['master_muted']), 'Ctrl+Shift+M'), self.mute_all)
        menu.addAction(icon('cameras'), menu_text(CAMERAS, 'Ctrl+M'), self.manage_cameras)
        menu.addAction(icon('restore' if self.isFullScreen() else 'fullscreen'),
            menu_text(fullscreen_name(self.isFullScreen()), 'F11'), self.toggle_layout_fullscreen)
        menu.addSeparator()
        menu.addAction(icon('pin'), menu_text(topmost_name(self.config['always_on_top']), 'Ctrl+T'),
            lambda: self.set_always_on_top(not self.config['always_on_top']))
        hardware_enabled = self.config['hardware_acceleration'] and self.playback_profile != 'cpu'
        hardware = menu.addAction(icon('chip'), hardware_name(hardware_enabled),
            lambda: self.set_hardware(not self.config['hardware_acceleration']))
        if self.playback_profile == 'cpu':
            hardware.setEnabled(False)
            hardware.setToolTip('CPU 출력 모드에서는 하드웨어 가속을 사용하지 않습니다.')
        opacity_menu = menu.addMenu(icon('opacity'), OPACITY)
        widget = QWidget()
        box = QVBoxLayout(widget)
        opacity_label = QLabel(f"투명도 {100 - self.config['opacity']}% · 전체화면은 적용 안함")
        opacity_label.setStyleSheet('color:white;')
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 80)
        slider.setValue(100 - self.config['opacity'])
        slider.setMinimumWidth(200)
        slider.valueChanged.connect(lambda n: (
            opacity_label.setText(f'투명도 {n}% · 전체화면은 적용 안함'), self.set_opacity(100 - n)))
        box.addWidget(opacity_label)
        box.addWidget(slider)
        action = QWidgetAction(opacity_menu)
        action.setDefaultWidget(widget)
        opacity_menu.addAction(action)
        opacity_menu.addAction(menu_text('불투명하게 복원', 'Ctrl+0'), lambda: self.set_opacity(100))
        menu.addSeparator()
        menu.addAction(icon('help'), menu_text('사용법 / 정보', 'F1'), self.show_help)
        menu.addAction(icon('minimize'), '최소화', self.showMinimized)
        menu.addAction(icon('close'), menu_text('종료', 'Alt+F4'), self.close)
        menu.addSeparator()
        suffix = f' · {PROFILES[self.playback_profile]}' if self.playback_profile != 'auto' else ''
        menu.addAction(f'CamFloat {VERSION}{suffix}').setEnabled(False)
        return menu

    def set_hardware(self, enabled):
        self.config['hardware_acceleration'] = bool(enabled)
        self.refresh_layout()
        self.queue_save()

    def show_context_menu(self, index, point, parent):
        menu = self.build_context_menu(index, parent)
        menu.exec(point)
        menu.deleteLater()


def exception_handler(kind, value, trace):
    try:
        path = data_path().with_name('error.log')
        if path.exists() and path.stat().st_size > 1_000_000:
            path.replace(path.with_suffix('.previous.log'))
        with path.open('a', encoding='utf-8') as log:
            window = getattr(QApplication.instance(), '_camfloat_window', None)
            cameras = window.config['cameras'] if window is not None else ()
            log.write(redact(''.join(traceback.format_exception(kind, value, trace)), cameras) + '\n')
    except OSError:
        pass
    QMessageBox.critical(None, APP_NAME, '처리 중 오류가 발생했습니다.\n오류 기록: %LOCALAPPDATA%\\CamFloat\\error.log')


def demo_video_url(argument):
    path = Path(argument).expanduser().resolve()
    if not path.is_file():
        raise ValueError('테스트할 로컬 동영상 파일을 찾지 못했습니다.')
    return QUrl.fromLocalFile(str(path)).toString()


def main():
    configure_app_identity()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setWindowIcon(app_icon())
    try:
        profile = select_profile(sys.argv[1:], sys.executable)
    except ValueError as error:
        QMessageBox.critical(None, APP_NAME, str(error))
        return 1
    app.setProperty('playback_profile', profile)
    app.setQuitOnLastWindowClosed(True)
    sys.excepthook = exception_handler
    checking = '--self-check' in sys.argv
    demo = '--demo-video' in sys.argv
    guard = None
    if not checking and not demo:
        guard = InstanceGuard()
        if not guard.acquire():
            if profile != 'auto':
                QMessageBox.information(None, APP_NAME,
                    'CamFloat가 이미 실행 중입니다.\n기존 CamFloat를 종료한 뒤 이 호환 모드를 다시 실행하세요.')
            return 0
    folder = find_vlc_directory()
    if folder is None:
        QMessageBox.critical(None, APP_NAME, 'VLC media player를 설치한 뒤 다시 실행하세요.')
        return 1
    try:
        instance = make_vlc_instance(folder, *instance_options(profile))
        if instance is None:
            raise RuntimeError('VLC 초기화 실패')
    except (OSError, RuntimeError, NameError):
        QMessageBox.critical(None, APP_NAME, 'VLC를 불러오지 못했습니다. 64비트 VLC를 설치하거나 복구 설치한 뒤 다시 실행하세요.')
        return 1
    try:
        config = default_config() if checking or demo else load_config()
    except Exception:
        QMessageBox.critical(None, APP_NAME, '저장된 카메라 설정을 읽지 못했습니다. 기존 설정 파일을 확인하세요.')
        instance.release()
        return 1
    if demo:
        position = sys.argv.index('--demo-video') + 1
        if position >= len(sys.argv):
            QMessageBox.critical(None, APP_NAME, '--demo-video 다음에 로컬 동영상 경로가 필요합니다.')
            instance.release()
            return 1
        try:
            video = demo_video_url(sys.argv[position])
        except ValueError as exc:
            QMessageBox.critical(None, APP_NAME, str(exc))
            instance.release()
            return 1
        config['cameras'] = [new_camera(f'테스트 카메라 {index + 1}', video) for index in range(6)]
        config['slots'] = [c['id'] for c in config['cameras'][:4]]
        config['layout'] = 4
        config['geometry'] = [100, 100, 900, 540]
        for camera in config['cameras']:
            camera['muted'] = True
    window = PlayerWindow(config, instance, persist=not (checking or demo))
    app._camfloat_window = window
    diagnostics = None
    if not checking and not demo:
        try:
            import vlc
            diagnostics = PlaybackDiagnostics(profile, VERSION, vlc.libvlc_get_version().decode('utf-8', 'replace'))
            diagnostic_timer = QTimer(window)
            diagnostic_timer.setInterval(2000)
            diagnostic_timer.timeout.connect(lambda: diagnostics.sample(window))
            diagnostic_timer.start()
        except OSError:
            # A read-only profile must not prevent camera playback.
            pass
    if guard:
        guard.activated.connect(window.activate)
    window.show()
    if checking:
        verify_deadline = time.monotonic() + 12
        def verify():
            if demo and time.monotonic() < verify_deadline and not all(t.player.is_playing() for t in window.tiles):
                QTimer.singleShot(200, verify)
                return
            report = {'ok': False, 'version': VERSION}
            code = 1
            try:
                video_streams = 0
                if demo:
                    video_streams = sum(bool(tile.player.is_playing()) for tile in window.tiles)
                    assert video_streams == 4, f'Only {video_streams} sample videos started'
                for count in (1, 2, 4, 1):
                    window.set_layout(count)
                    app.processEvents()
                    assert sum(t.isVisible() for t in window.tiles) == count
                handles = [int(t.winId()) for t in window.tiles]
                for value in (False, True, False, True):
                    window.set_always_on_top(value)
                    assert is_topmost(window) == value
                    assert handles == [int(t.winId()) for t in window.tiles]
                    if demo:
                        assert window.tiles[0].player.is_playing()
                window.set_opacity(65)
                assert abs(window.windowOpacity() - .65) < .01
                window.toggle_layout_fullscreen()
                app.processEvents()
                assert window.windowOpacity() == 1.0 and window.config['opacity'] == 65
                window.handle_escape()
                assert abs(window.windowOpacity() - .65) < .01
                window.set_opacity(100)
                individual_mutes = [c['muted'] for c in window.config['cameras']]
                window.mute_all()
                assert window.config['master_muted']
                window.mute_all()
                assert [c['muted'] for c in window.config['cameras']] == individual_mutes
                assert crypt(crypt('roundtrip'), decrypt=True) == 'roundtrip'
                taskbar = taskbar_icon_state(window)
                assert taskbar['small'] and taskbar['large'] and not taskbar['tool_window'], taskbar
                assert taskbar_can_minimize(window)
                system_minimize(window)
                app.processEvents()
                assert window.isMinimized() and all(not t.overlay.isVisible() for t in window.tiles)
                window.activate()
                app.processEvents()
                assert not window.isMinimized()
                report.update(ok=True, layouts=[1, 2, 4], topmost=True, stable_video_handles=True,
                              opacity=True, dpapi=True, vlc=True, sample_video_streams=video_streams,
                              taskbar_icon=taskbar, taskbar_system_minimize=True,
                              fullscreen_opacity_lock=True, master_mute_preserves_individual=True)
                code = 0
            except Exception:
                report['error'] = traceback.format_exc()
            finally:
                data_path().with_name('startup-check.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                window.close()
                app.exit(code)
        QTimer.singleShot(1500 if demo else 300, verify)
    elif LOAD_WARNINGS:
        def show_recovery():
            with window.modal():
                QMessageBox.warning(window, '설정 복구', '\n'.join(LOAD_WARNINGS))
        QTimer.singleShot(300, show_recovery)
    elif not config['cameras']:
        QTimer.singleShot(300, window.manage_cameras)
    code = app.exec()
    if diagnostics:
        diagnostics.close()
    for tile in window.tiles:
        tile.worker.done.wait(5)
    if all(tile.worker.done.is_set() for tile in window.tiles):
        instance.release()
    if guard:
        guard.release()
    return code


if __name__ == '__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
