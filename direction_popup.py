"""A child panel inside the input overlay; no additional native tool window."""
from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel, QToolButton

from icons import icon
from ptz_control import camera_key


class DirectionPopup(QFrame):
    def __init__(self, overlay):
        super().__init__(overlay)
        self.overlay = overlay
        self.target = None
        self.compact = True
        self.held_direction = None
        self.hold_timer = QTimer(self)
        self.hold_timer.setInterval(160)
        self.hold_timer.timeout.connect(self.repeat_move)
        self.setObjectName('directionPopup')
        self.setStyleSheet('QFrame#directionPopup{background:rgba(19,24,33,248);'
            'border:1px solid #405069;border-radius:9px;}'
            'QToolButton{border:0;background:transparent;border-radius:5px;}'
            'QToolButton:hover{background:rgba(102,158,235,70);}'
            'QToolButton:pressed{background:rgba(102,158,235,110);}'
            'QToolButton:disabled{background:transparent;}'
            'QLabel{color:#b9cbe3;background:transparent;font-size:10px;}')
        self.buttons = {}
        for name, text, pan, tilt in (('left', '왼쪽으로', -1, 0), ('up', '위로', 0, 1),
                                      ('down', '아래로', 0, -1), ('right', '오른쪽으로', 1, 0)):
            button = QToolButton(self)
            button.setFixedSize(28, 28)
            button.setIconSize(QSize(17, 17))
            button.setIcon(icon(name))
            button.setToolTip(text)
            button.setAccessibleName(text)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setAutoRepeat(False)
            button.pressed.connect(lambda x=pan, y=tilt: self.start_move(x, y))
            button.released.connect(self.end_move)
            button.installEventFilter(self)
            overlay.tips.add(button)
            self.buttons[name] = button
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def control(self):
        return self.overlay.host.direction_control

    def show_panel(self):
        host = self.overlay.host
        camera = host.camera_for_slot(self.overlay.index)
        if not camera or camera.get('connection_locked'):
            return
        host.close_direction_panels()
        self.overlay.volume_popup.hide()
        self.overlay.tips.clear()
        self.target = camera_key(camera)
        self.show()
        self.overlay.move_camera.setChecked(True)
        host.chrome.hide()
        self.control().prepare(camera)
        self.update_state()
        self.raise_()

    def close_panel(self):
        self.end_move()
        if self.target is None:
            return
        owned = self.control().target == self.target
        self.target = None
        self.hide()
        self.overlay.move_camera.setChecked(False)
        self.overlay.tips.clear()
        if owned:
            self.control().cancel()
        self.overlay.update()

    def update_state(self):
        if self.target is None or self.isHidden():
            return
        camera = self.overlay.host.camera_for_slot(self.overlay.index)
        if (camera_key(camera) != self.target or not camera or not camera.get('enabled', True)
                or camera.get('connection_locked')):
            self.close_panel()
            return
        control = self.control()
        if control.state == 'idle' and not control.busy:
            control.prepare(camera)
            return
        state = control.state
        if control.target != self.target:
            state = 'stopping'
        message = {'connecting': '조작 연결 중…', 'stopping': '잠시 기다려 주세요',
                   'error': '조작 연결 실패\n닫고 다시 열어주세요',
                   'move_error': '이동 응답을\n확인하지 못했습니다',
                   'local_only': '내부망 카메라에서\n사용할 수 있습니다'}.get(state, '')
        self.status.setText(message)
        if message:
            self.end_move()
        self.status.setVisible(bool(message))
        for button in self.buttons.values():
            button.setVisible(not message)
            button.setEnabled(state in ('ready', 'moving'))
        self.arrange()

    def arrange(self):
        overlay = self.overlay
        # Check available pane height as well as width, including a 150x90 pane.
        self.compact = overlay.width() < 310 or overlay.height() < 190
        message = bool(self.status.text())
        width = 130 if self.compact or message else 100
        height = 40 if self.compact and not message else 46 if message else 100
        self.setFixedSize(width, height)
        positions = ({name: (6 + i * 30, 6) for i, name in enumerate(self.buttons)} if self.compact else
                     {'up': (36, 6), 'left': (6, 36), 'right': (66, 36), 'down': (36, 66)})
        for name, button in self.buttons.items():
            button.move(*positions[name])
        self.status.setGeometry(5, 4, width - 10, height - 8)
        anchor = overlay.move_camera.mapTo(overlay, QPoint(overlay.move_camera.width() // 2, 0))
        x = max(4, min(anchor.x() - width // 2, overlay.width() - width - 4))
        y = max(4, min(anchor.y() - height - 5, overlay.height() - height - 4))
        self.move(x, y)
        self.raise_()

    def move_camera(self, pan, tilt):
        camera = self.overlay.host.camera_for_slot(self.overlay.index)
        if self.target == camera_key(camera):
            self.control().move(camera, pan, tilt)
            self.overlay.idle_timer.start()

    def start_move(self, pan, tilt):
        self.end_move()
        self.held_direction = (pan, tilt)
        self.move_camera(pan, tilt)
        if self.held_direction is not None and self.isVisible():
            self.hold_timer.start()

    def repeat_move(self):
        if self.held_direction is None or not self.isVisible():
            self.end_move()
            return
        self.move_camera(*self.held_direction)

    def end_move(self):
        self.hold_timer.stop()
        self.held_direction = None

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Leave, QEvent.Type.Hide, QEvent.Type.UngrabMouse):
            self.end_move()
        if event.type() == QEvent.Type.MouseButtonPress:
            self.overlay.activation_press = False
            self.overlay.host.last_double = None
            self.overlay.host.select_slot(self.overlay.index)
        return super().eventFilter(watched, event)

    def hideEvent(self, event):
        self.end_move()
        super().hideEvent(event)

    def mousePressEvent(self, event):
        event.accept()

    def mouseDoubleClickEvent(self, event):
        event.accept()
