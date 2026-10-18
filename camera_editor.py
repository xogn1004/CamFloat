"""Camera connection draft form with independent sensitive field disclosure."""
import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QStackedWidget, QVBoxLayout, QWidget)

from camera_model import (camera_display_name, camera_url, find_vlc_directory, new_camera,
                          supports_quality, validate_rtsp_url)
from camera_draft import ConnectionDraft, duplicate_target
from connection_probe import ConnectionProbe
from privacy import PrivacyController, SensitiveField
from ui_theme import STYLE


class CameraEditor(QDialog):
    def __init__(self, camera=None, parent=None, *, privacy=None, others=(), number=None):
        super().__init__(parent)
        self.camera = copy.deepcopy(camera or new_camera())
        self.editing = camera is not None
        self.others = others
        self.camera['number'] = self.camera.get('number') or number
        self.continue_adding = False
        self.setWindowTitle('카메라 수정' if camera else '카메라 추가')
        self.setStyleSheet(STYLE)
        self.resize(640, 660)
        self.setMinimumSize(490, 420)
        self.privacy = privacy or PrivacyController(self)
        self.draft = ConnectionDraft(self.camera['url'])
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        title = QLabel(self.windowTitle())
        title.setStyleSheet('font-size:20px;font-weight:600;')
        root.addWidget(title)
        root.addWidget(QLabel('연결 정보는 저장 후에도 항목별로 다시 확인할 수 있습니다.'))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 12, 0, 8)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.name = QLineEdit(camera_display_name(self.camera) if camera else '')
        self.name.setMaxLength(80)
        self.name.setPlaceholderText('예: 거실, 현관 · 비우면 카메라 번호로 지정')
        form.addRow('별명', self.name)
        self.mode = QComboBox()
        self.mode.addItems(['간편 입력', 'RTSP 주소'])
        form.addRow('입력 방식', self.mode)
        body.addLayout(form)
        self.pages = QStackedWidget()
        simple, full = QWidget(), QWidget()
        simple_form, full_form = QFormLayout(simple), QFormLayout(full)
        simple_form.setContentsMargins(0, 8, 0, 4)
        full_form.setContentsMargins(0, 8, 0, 4)
        self.fields = {}
        for key, label in [('host', 'IP / 도메인'), ('username', '아이디'), ('password', '비밀번호'),
                           ('path', '영상 경로'), ('full_url', '전체 RTSP 주소'), ('sd_url', 'SD 전체 주소')]:
            field = SensitiveField(self.privacy, label, editable=True)
            self.fields[key] = field
            setattr(self, key, field.edit)
        self.host.setPlaceholderText('IP 또는 도메인')
        self.username.setText('admin' if not camera else '')
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(554)
        self.path.setText('/onvif1')
        simple_form.addRow('IP / 도메인', self.fields['host'])
        simple_form.addRow('포트', self.port)
        simple_form.addRow('아이디', self.fields['username'])
        simple_form.addRow('비밀번호', self.fields['password'])
        full_form.addRow('전체 RTSP 주소', self.fields['full_url'])
        self.full_url.setPlaceholderText('RTSP 주소를 붙여넣으세요')
        self.pages.addWidget(simple)
        self.pages.addWidget(full)
        body.addWidget(self.pages)
        self.quality = QComboBox()
        self.quality.addItems(['HD', 'SD'])
        self.quality.setCurrentText(self.camera['quality'])
        quality_form = QFormLayout()
        quality_form.addRow('기본 화질', self.quality)
        body.addLayout(quality_form)
        self.advanced = QPushButton('고급 설정 펼치기')
        self.advanced.setCheckable(True)
        body.addWidget(self.advanced, 0, Qt.AlignmentFlag.AlignLeft)
        advanced = QWidget()
        advanced_form = QFormLayout(advanced)
        advanced_form.setContentsMargins(0, 4, 0, 4)
        advanced_form.addRow('영상 경로', self.fields['path'])
        advanced_form.addRow('SD 전체 주소', self.fields['sd_url'])
        hint = QLabel('ipTIME: HD /onvif1 · SD /onvif2\n다른 기종은 제공된 SD 주소를 입력하세요.')
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#96a9c3;')
        advanced_form.addRow(hint)
        body.addWidget(advanced)
        advanced.hide()
        self.advanced.toggled.connect(lambda on: (advanced.setVisible(on),
            self.advanced.setText('고급 설정 접기' if on else '고급 설정 펼치기')))
        body.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet('color:#f5ba98;')
        self.error.hide()
        root.addWidget(self.error)
        self.privacy.notice.connect(self.show_notice)
        connection_row = QHBoxLayout()
        self.check = QPushButton('연결 확인')
        self.check.clicked.connect(self.check_connection)
        self.cancel_check = QPushButton('확인 취소')
        self.cancel_check.hide()
        self.cancel_check.clicked.connect(lambda: self.probe.cancel())
        connection_row.addWidget(self.check)
        connection_row.addWidget(self.cancel_check)
        connection_row.addStretch()
        root.addLayout(connection_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setText('변경 반영' if camera else '목록에 추가')
        save.setObjectName('primary')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        if not camera:
            again = buttons.addButton('추가하고 계속', QDialogButtonBox.ButtonRole.ActionRole)
            again.clicked.connect(lambda: self.validate(continue_adding=True))
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.probe = ConnectionProbe(self)
        self.probe.finished.connect(self.probe_finished)
        self.finished.connect(lambda *_: self.probe.cancel(notify=False))
        self.finished.connect(lambda *_: self.privacy.hide_all())
        self.full_url.setText(self.camera['url'])
        self.sd_url.setText(self.camera.get('sd_url', ''))
        if self.draft.fields:
            self.load_fields(self.draft.fields)
        # Known ipTIME fields are approachable; custom URLs keep their raw form.
        known_path = bool(self.draft.fields and self.draft.fields[4].split('?', 1)[0].rstrip('/').lower()
                          in ('', '/onvif1', '/onvif2', '/'))
        self.mode.setCurrentIndex(1 if camera and not known_path else 0)
        self.pages.setCurrentIndex(self.mode.currentIndex())
        self.mode.currentIndexChanged.connect(self.switch_mode)
        if not camera:
            self.fields['host'].reveal()
            self.fields['username'].reveal()

    def show_notice(self, text):
        if self.isVisible():
            self.show_error(text)

    def show_error(self, message):
        self.error.setText(message)
        self.error.show()

    def load_fields(self, fields):
        host, port, username, password, path = fields
        self.host.setText(host)
        self.port.setValue(port)
        self.username.setText(username)
        self.password.setText(password)
        self.path.setText(path)

    def simple_url(self):
        return self.draft.from_fields((self.host.text().strip(), self.port.value(), self.username.text(),
                                       self.password.text(), self.path.text()))

    def switch_mode(self, index):
        self.privacy.hide_all()
        self.error.hide()
        try:
            if index == 1:
                self.full_url.setText(self.simple_url())
            else:
                self.load_fields(self.draft.adopt(self.full_url.text().strip()))
        except ValueError as exc:
            if index == 0:
                self.mode.blockSignals(True)
                self.mode.setCurrentIndex(1)
                self.mode.blockSignals(False)
                self.show_error(str(exc))
                return
        self.pages.setCurrentIndex(index)

    def collect(self):
        url = self.simple_url() if self.mode.currentIndex() == 0 else self.full_url.text().strip()
        validate_rtsp_url(url)
        result = copy.deepcopy(self.camera)
        result.update(url=url, sd_url=self.sd_url.text().strip(), quality=self.quality.currentText())
        if result['sd_url']:
            validate_rtsp_url(result['sd_url'])
        if result['quality'] == 'SD' and not supports_quality(result):
            raise ValueError('SD 화질을 사용하려면 고급 설정에 SD 전체 주소를 입력하세요.')
        result['name'] = self.name.text().strip() or f"카메라 {result.get('number') or ''}".strip()
        return result

    def validate(self, *_args, continue_adding=False):
        try:
            result = self.collect()
        except ValueError as exc:
            self.show_error(str(exc))
            return
        if duplicate_target(result['url'], self.others, result['id']):
            if QMessageBox.question(self, '중복 연결 정보', '같은 영상 주소의 카메라가 있습니다. 추가 또는 변경할까요?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
        self.camera = result
        self.continue_adding = continue_adding
        self.accept()

    def check_connection(self):
        try:
            result = self.collect()
        except ValueError as exc:
            self.show_error(str(exc))
            return
        folder = find_vlc_directory()
        if folder is None:
            self.show_error('64비트 VLC를 설치한 뒤 연결을 확인하세요.')
            return
        self.check.setEnabled(False)
        self.cancel_check.show()
        self.show_error('연결 확인 중…')
        self.probe.start(camera_url(result), folder)

    def probe_finished(self, success, message):
        self.check.setEnabled(True)
        self.cancel_check.hide()
        self.show_error(message)

    def done(self, result):
        self.probe.cancel(notify=False)
        self.privacy.hide_all()
        super().done(result)
