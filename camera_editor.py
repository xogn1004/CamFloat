"""Camera connection draft form with independent sensitive field disclosure."""
import copy
from urllib.parse import urlsplit, urlunsplit

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from camera_model import (camera_display_name, camera_url, find_vlc_directory, new_camera,
                          supports_quality, validate_rtsp_url)
from camera_draft import ConnectionDraft, duplicate_target
from connection_probe import ConnectionProbe
from privacy import PrivacyController, SensitiveField
from icons import icon
from ui_theme import CAMERA_STYLE


class InputPages(QStackedWidget):
    """An address-only page must not reserve the height of the larger simple form."""
    def sizeHint(self):
        return self.currentWidget().sizeHint() if self.currentWidget() else super().sizeHint()

    def minimumSizeHint(self):
        return self.sizeHint()


def field_group(label, control):
    group = QWidget()
    layout = QVBoxLayout(group)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    caption = QLabel(label)
    caption.setObjectName('fieldCaption')
    layout.addWidget(caption)
    layout.addWidget(control)
    return group


class CameraEditor(QDialog):
    def __init__(self, camera=None, parent=None, *, privacy=None, others=(), number=None):
        super().__init__(parent)
        self.camera = copy.deepcopy(camera or new_camera())
        self.editing = camera is not None
        self.others = others
        self.camera['number'] = self.camera.get('number') or number
        self.setWindowTitle('카메라 수정' if camera else '카메라 추가')
        self.setStyleSheet(CAMERA_STYLE)
        self.resize(520, 420)
        self.setMinimumSize(460, 360)
        self.privacy = privacy or PrivacyController(self)
        self.draft = ConnectionDraft(self.camera['url'])
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(8)
        title = QLabel(self.windowTitle())
        title.setStyleSheet('font-size:18px;font-weight:600;')
        root.addWidget(title)
        explanation = QLabel('비밀번호·RTSP 주소 보기는 본인인증이 필요합니다.')
        explanation.setWordWrap(True)
        explanation.setStyleSheet('color:#98adc8;font-size:11px;')
        root.addWidget(explanation)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 6, 0, 0)
        body.setSpacing(10)
        self.name = QLineEdit(camera_display_name(self.camera) if camera else '')
        self.name.setMaxLength(80)
        self.name.setPlaceholderText('예: 거실, 현관 · 비우면 카메라 번호로 지정')
        body.addWidget(field_group('별명', self.name))
        self.mode = QComboBox()
        self.mode.addItems(['간편 입력', 'RTSP 주소'])
        body.addWidget(field_group('입력 방식', self.mode))
        self.pages = InputPages()
        self.pages.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        simple, full = QWidget(), QWidget()
        simple_form, full_form = QVBoxLayout(simple), QVBoxLayout(full)
        for form in (simple_form, full_form):
            form.setContentsMargins(0, 0, 0, 0)
            form.setSpacing(10)
        self.fields = {}
        for key, label in [('host', 'IP / 도메인'), ('username', '아이디'), ('password', '비밀번호'),
                           ('path', '영상 경로 (HD)'), ('full_url', 'RTSP 주소'), ('sd_url', '영상 경로 (SD)')]:
            field = SensitiveField(self.privacy, label, editable=True,
                                   required=key in ('password', 'full_url', 'sd_url'),
                                   public=key == 'path' or (not self.editing and key in ('host', 'username')))
            self.fields[key] = field
            setattr(self, key, field.edit)
        self.host.setPlaceholderText('IP 또는 도메인')
        self.username.setText('admin' if not camera else '')
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(554)
        self.path.setText('/onvif1')
        address_row = QHBoxLayout()
        address_row.setSpacing(10)
        address_row.addWidget(field_group('IP / 도메인', self.fields['host']), 1)
        port_group = field_group('포트', self.port)
        port_group.setFixedWidth(94)
        address_row.addWidget(port_group)
        simple_form.addLayout(address_row)
        account_row = QHBoxLayout()
        account_row.setSpacing(10)
        account_row.addWidget(field_group('아이디', self.fields['username']), 1)
        account_row.addWidget(field_group('비밀번호', self.fields['password']), 1)
        simple_form.addLayout(account_row)
        full_form.addWidget(field_group('RTSP 주소', self.fields['full_url']))
        self.full_url.setPlaceholderText('RTSP 주소를 붙여넣으세요')
        self.pages.addWidget(simple)
        self.pages.addWidget(full)
        body.addWidget(self.pages)
        self.quality = QComboBox()
        self.quality.addItems(['HD', 'SD'])
        self.quality.setCurrentText(self.camera['quality'])
        options_row = QHBoxLayout()
        quality_group = field_group('기본 화질', self.quality)
        quality_group.setFixedWidth(108)
        options_row.addWidget(quality_group)
        options_row.addStretch()
        self.advanced = QPushButton('고급 설정')
        self.advanced.setObjectName('disclosure')
        self.advanced.setIcon(icon('down'))
        self.advanced.setIconSize(QSize(14, 14))
        self.advanced.setCheckable(True)
        options_row.addWidget(self.advanced, 0, Qt.AlignmentFlag.AlignBottom)
        body.addLayout(options_row)
        self.advanced_panel = QWidget()
        advanced_form = QVBoxLayout(self.advanced_panel)
        advanced_form.setContentsMargins(0, 0, 0, 0)
        advanced_form.setSpacing(10)
        advanced_form.addWidget(field_group('영상 경로 (HD)', self.fields['path']))
        advanced_form.addWidget(field_group('영상 경로 (SD)', self.fields['sd_url']))
        self.sd_url.setPlaceholderText('/onvif2 또는 RTSP 주소')
        hint = QLabel('ipTIME: HD /onvif1 · SD /onvif2\nSD는 영상 경로나 별도의 RTSP 주소를 입력할 수 있습니다.')
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#96a9c3;font-size:10px;')
        advanced_form.addWidget(hint)
        body.addWidget(self.advanced_panel)
        self.advanced_panel.hide()
        self.advanced.toggled.connect(self.toggle_advanced)
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
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setText('변경 반영' if camera else '목록에 추가')
        save.setObjectName('primary')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        connection_row.addWidget(buttons)
        root.addLayout(connection_row)
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
        self._simple_snapshot = self.simple_fields()
        self._preserve_full_draft = False
        self.fit_form()

    def fit_form(self):
        self.pages.updateGeometry()
        height = (420 if self.mode.currentIndex() == 0 else 370) + (150 if self.advanced.isChecked() else 0)
        screen = self.screen().availableGeometry()
        self.resize(min(self.width(), screen.width()), min(height, screen.height() - 60))

    def toggle_advanced(self, on):
        self.advanced_panel.setVisible(on)
        self.advanced.setIcon(icon('up' if on else 'down'))
        self.fit_form()

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

    def simple_fields(self):
        return (self.host.text().strip(), self.port.value(), self.username.text(),
                self.password.text(), self.path.text())

    def simple_url(self):
        return self.draft.from_fields(self.simple_fields())

    def switch_mode(self, index):
        self.privacy.hide_all()
        self.error.hide()
        if index == 1:
            # Preserve a partial pasted URL until the simple fields actually change.
            if not self._preserve_full_draft or self.simple_fields() != self._simple_snapshot:
                try:
                    self.full_url.setText(self.simple_url())
                except ValueError:
                    pass
        else:
            try:
                self.load_fields(self.draft.adopt(self.full_url.text().strip()))
            except ValueError:
                if self.full_url.text().strip():
                    self.show_error('입력 중인 RTSP 주소는 유지했습니다. 간편 입력에서 연결 정보를 입력하세요.')
            self._simple_snapshot = self.simple_fields()
            self._preserve_full_draft = True
        self.pages.setCurrentIndex(index)
        self.fit_form()

    def collect(self):
        url = self.simple_url() if self.mode.currentIndex() == 0 else self.full_url.text().strip()
        validate_rtsp_url(url)
        result = copy.deepcopy(self.camera)
        sd_url = self.sd_url.text().strip()
        if sd_url.startswith('/'):
            base = urlsplit(url)
            path, separator, query = sd_url.partition('?')
            sd_url = urlunsplit((base.scheme, base.netloc, path, query if separator else '', ''))
        result.update(url=url, sd_url=sd_url, quality=self.quality.currentText())
        if result['sd_url']:
            validate_rtsp_url(result['sd_url'])
        if result['quality'] == 'SD' and not supports_quality(result):
            raise ValueError('SD 화질을 사용하려면 고급 설정에 영상 경로 (SD)를 입력하세요.')
        result['name'] = self.name.text().strip() or f"카메라 {result.get('number') or ''}".strip()
        return result

    def validate(self, *_args):
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
