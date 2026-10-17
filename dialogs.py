from __future__ import annotations

import copy
from urllib.parse import unquote, urlsplit

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from camera_model import (address_label, build_url, default_config, ensure_camera_numbers,
    ensure_layout_slots, fill_empty_slots, new_camera, supports_quality, validate_rtsp_url)
from icons import icon

STYLE = '''
QDialog {background:#171c25; color:#e7edf6; font-family:"Malgun Gothic"; font-size:12px;}
QLabel,QCheckBox {color:#d8e2f0;}
QLineEdit,QComboBox,QSpinBox {background:#242d3b;color:#f4f7fc;border:1px solid #435066;
    border-radius:5px; padding:7px; min-height:19px;}
QLineEdit:focus,QComboBox:focus {border-color:#75afff;}
QPushButton {background:#303f55;color:#f4f7fc;border:0;border-radius:5px;padding:9px 15px;}
QPushButton:hover {background:#405575;} QPushButton:disabled {color:#647083;background:#232a35;}
QTableWidget {background:#202734;color:#e9eff8;gridline-color:#303b4b;border:1px solid #39475c;
    selection-background-color:#324e74;selection-color:#ffffff;}
QHeaderView::section {background:#293547;color:#c5d5e9;padding:9px;border:0;}
'''


class CameraEditor(QDialog):
    def __init__(self, camera=None, parent=None):
        super().__init__(parent)
        self.camera = copy.deepcopy(camera or new_camera())
        self.setWindowTitle('카메라 수정' if camera else '카메라 등록')
        self.setStyleSheet(STYLE)
        self.resize(620, 520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(self.camera['name'])
        self.name.setMaxLength(80)
        self.name.setPlaceholderText('예: 거실, 현관, 사무실')
        self.name.setObjectName('camera_name')
        form.addRow('별명', self.name)
        self.mode = QComboBox()
        self.mode.addItems(['IP / 도메인과 로그인 정보 입력', 'RTSP 전체 주소 붙여넣기'])
        form.addRow('입력 방식', self.mode)
        layout.addLayout(form)
        self.pages = QStackedWidget()
        simple = QWidget()
        simple_form = QFormLayout(simple)
        simple_form.setContentsMargins(0, 10, 0, 10)
        self.host = QLineEdit()
        self.host.setPlaceholderText('192.168.0.10 또는 camera.example.com')
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(554)
        self.username = QLineEdit('admin')
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.path = QLineEdit('/onvif1')
        for title, widget in [('IP / 도메인', self.host), ('포트', self.port), ('아이디', self.username),
                              ('RTSP 비밀번호', self.password), ('영상 경로', self.path)]:
            simple_form.addRow(title, widget)
        self.pages.addWidget(simple)
        full = QWidget()
        full_form = QFormLayout(full)
        full_form.setContentsMargins(0, 10, 0, 10)
        self.full_url = QLineEdit(self.camera['url'])
        self.full_url.setEchoMode(QLineEdit.EchoMode.Password)
        self.full_url.setPlaceholderText('rtsp://아이디:비밀번호@도메인:포트/onvif1')
        full_form.addRow('전체 RTSP 주소', self.full_url)
        self.pages.addWidget(full)
        layout.addWidget(self.pages)
        self.show_secret = QCheckBox('비밀번호 / 전체 주소 표시')
        self.show_secret.toggled.connect(self.toggle_secret)
        layout.addWidget(self.show_secret)
        options = QFormLayout()
        self.quality = QComboBox()
        self.quality.addItems(['HD', 'SD'])
        self.quality.setCurrentText(self.camera['quality'])
        options.addRow('기본 화질', self.quality)
        self.sd_url = QLineEdit(self.camera.get('sd_url', ''))
        self.sd_url.setEchoMode(QLineEdit.EchoMode.Password)
        self.sd_url.setPlaceholderText('선택 사항 · 다른 기종의 SD 스트림 전체 주소')
        options.addRow('SD 전체 주소', self.sd_url)
        layout.addLayout(options)
        hint = QLabel('ipTIME 영상 경로는 HD: /onvif1, SD: /onvif2를 사용합니다.\n'
                      'IP / 도메인 방식에서는 비밀번호의 특수문자를 자동으로 처리합니다.\n'
                      '다른 기종은 기본 주소에 HD, SD 전체 주소에 저화질 주소를 입력하세요.')
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#96a9c3;padding:8px 0;')
        layout.addWidget(hint)
        self.error = QLabel('')
        self.error.setWordWrap(True)
        self.error.setStyleSheet('color:#ffad9f;')
        self.error.hide()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('저장')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self.switch_mode)
        if self.camera['url']:
            try:
                parts = urlsplit(self.camera['url'])
                self.host.setText(parts.hostname or '')
                self.port.setValue(parts.port or 554)
                self.username.setText(unquote(parts.username or ''))
                self.password.setText(unquote(parts.password or ''))
                self.path.setText((parts.path or '/onvif1') + ('?' + parts.query if parts.query else ''))
            except ValueError:
                pass
            self.mode.blockSignals(True)
            self.mode.setCurrentIndex(1)
            self.mode.blockSignals(False)
            self.pages.setCurrentIndex(1)

    def toggle_secret(self, enabled):
        mode = QLineEdit.EchoMode.Normal if enabled else QLineEdit.EchoMode.Password
        self.password.setEchoMode(mode)
        self.full_url.setEchoMode(mode)
        self.sd_url.setEchoMode(mode)

    def show_error(self, message):
        self.error.setText(message)
        self.error.show()

    def simple_url(self):
        return build_url(self.host.text(), self.port.value(), self.username.text(), self.password.text(), self.path.text())

    def switch_mode(self, index):
        self.error.hide()
        if index == 1:
            try:
                self.full_url.setText(self.simple_url())
            except ValueError:
                # Empty/unfinished simple fields may be replaced by a pasted URL.
                pass
        else:
            try:
                parts = validate_rtsp_url(self.full_url.text().strip())
                self.host.setText(parts.hostname or '')
                self.port.setValue(parts.port or 554)
                self.username.setText(unquote(parts.username or ''))
                self.password.setText(unquote(parts.password or ''))
                self.path.setText((parts.path or '/onvif1') + ('?' + parts.query if parts.query else ''))
            except ValueError as exc:
                self.mode.blockSignals(True)
                self.mode.setCurrentIndex(1)
                self.mode.blockSignals(False)
                self.show_error(str(exc))
                return
        self.pages.setCurrentIndex(index)

    def validate(self):
        try:
            url = self.simple_url() if self.mode.currentIndex() == 0 else self.full_url.text().strip()
            parts = validate_rtsp_url(url)
            sd_url = self.sd_url.text().strip()
            if sd_url:
                validate_rtsp_url(sd_url)
            if self.quality.currentText() == 'SD' and not supports_quality(dict(url=url, sd_url=sd_url)):
                raise ValueError('이 영상 경로는 SD 전체 주소를 추가해야 화질을 전환할 수 있습니다.')
            self.camera.update(name=self.name.text().strip() or parts.hostname, url=url,
                               sd_url=sd_url, quality=self.quality.currentText())
        except ValueError as exc:
            self.show_error(str(exc))
            return
        self.accept()


class CameraManager(QDialog):
    def __init__(self, cameras, parent=None, slots=None, layout_slots=None, layout=4):
        super().__init__(parent)
        self.cameras = copy.deepcopy(cameras)
        self.edit_layout = layout
        config = default_config()
        config.update(cameras=self.cameras, layout=layout, layout_slots=copy.deepcopy(layout_slots),
                      slots=list(slots) if slots is not None else [c['id'] for c in cameras[:4]])
        self.layout_slots = ensure_layout_slots(config)
        self.slots = self.layout_slots[str(layout)]
        self.assignment_changed = False
        self.setWindowTitle('등록된 카메라 관리')
        self.setStyleSheet(STYLE)
        self.resize(880, 580)
        root = QVBoxLayout(self)
        title = QLabel('등록된 카메라')
        title.setStyleSheet('font-size:19px;font-weight:600;padding:6px 0;')
        root.addWidget(title)
        hint = QLabel('카메라 번호는 SCREEN 번호와 별개입니다. 1·2·4분할의 카메라 배정을 각각 저장합니다.\n'
                      '사용 안 함은 모든 배정을 비우고, 다시 사용하면 각 분할의 빈 SCREEN부터 채웁니다.')
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#a0b0c6;padding-bottom:10px;')
        root.addWidget(hint)
        selector = QHBoxLayout()
        selector.addWidget(QLabel('배정 편집할 화면 구성'))
        self.layout_choice = QComboBox()
        for count in (1, 2, 4):
            self.layout_choice.addItem(f'{count}분할', count)
        self.layout_choice.setCurrentIndex(self.layout_choice.findData(layout))
        self.layout_choice.currentIndexChanged.connect(self.change_layout)
        selector.addWidget(self.layout_choice)
        selector.addStretch()
        root.addLayout(selector)
        assignments = QHBoxLayout()
        self.screen_choices = []
        self.screen_labels = []
        for index in range(4):
            column = QVBoxLayout()
            label = QLabel(f'SCREEN {index + 1}')
            label.setStyleSheet('color:#90baff;font-size:11px;font-weight:600;')
            choice = QComboBox()
            choice.setMinimumWidth(125)
            choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            choice.setMinimumContentsLength(9)
            choice.setToolTip(f'SCREEN {index + 1}에 표시할 카메라')
            choice.currentIndexChanged.connect(lambda _, i=index: self.assign_screen(i))
            self.screen_choices.append(choice)
            self.screen_labels.append(label)
            column.addWidget(label)
            column.addWidget(choice)
            assignments.addLayout(column)
        root.addLayout(assignments)
        self.search = QLineEdit()
        self.search.setPlaceholderText('별명 또는 접속 주소 검색 · 검색 중에는 순서 이동이 잠깁니다')
        self.search.textChanged.connect(self.filter_rows)
        root.addWidget(self.search)
        body = QHBoxLayout()
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['카메라', '별명', '접속 주소', '화질', 'SCREEN', '사용'])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 55)
        self.table.setColumnWidth(3, 85)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 70)
        self.table.itemDoubleClicked.connect(lambda *_: self.edit_camera())
        self.table.itemSelectionChanged.connect(self.update_buttons)
        body.addWidget(self.table, 1)
        actions = QVBoxLayout()
        self.buttons = {}
        for key, text, slot in [('add', '＋ 카메라 등록', self.add_camera), ('edit', '수정', self.edit_camera),
                                ('enable', '사용 안 함', self.toggle_enabled),
                                ('delete', '삭제', self.delete_camera), ('up', '↑ 위로', lambda: self.move_camera(-1)),
                                ('down', '↓ 아래로', lambda: self.move_camera(1))]:
            button = QPushButton(text)
            button.setIcon(icon({'add': 'add', 'edit': 'edit', 'enable': 'camera', 'delete': 'close', 'up': 'up', 'down': 'down'}[key]))
            button.clicked.connect(slot)
            self.buttons[key] = button
            actions.addWidget(button)
        actions.addStretch()
        body.addLayout(actions)
        root.addLayout(body)
        self.count_label = QLabel()
        root.addWidget(self.count_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('저장하고 적용')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.refresh()

    def refresh(self, selected=0):
        config = dict(cameras=self.cameras, layout=self.edit_layout, layout_slots=self.layout_slots)
        self.layout_slots = ensure_layout_slots(config)
        self.slots = self.layout_slots[str(self.edit_layout)]
        self.refresh_screen_choices()
        self.table.setRowCount(len(self.cameras))
        for row, camera in enumerate(self.cameras):
            screens = ', '.join(str(i + 1) for i, cid in enumerate(self.slots) if cid == camera['id']) or '—'
            for col, value in enumerate([str(camera['number']), camera['name'], address_label(camera['url']), camera['quality'],
                                         screens, '사용' if camera.get('enabled', True) else '사용 안 함']):
                self.table.setItem(row, col, QTableWidgetItem(value))
        if self.cameras:
            self.table.selectRow(max(0, min(selected, len(self.cameras) - 1)))
        self.update_buttons()
        self.filter_rows()

    def refresh_screen_choices(self):
        for index, choice in enumerate(self.screen_choices):
            choice.blockSignals(True)
            choice.clear()
            choice.addItem('비어 있음', None)
            for camera in self.cameras:
                if camera.get('enabled', True):
                    choice.addItem(f"{camera['number']}. {camera['name']}", camera['id'])
            choice.setCurrentIndex(max(0, choice.findData(self.slots[index])))
            choice.blockSignals(False)
            choice.setVisible(index < self.edit_layout)
            self.screen_labels[index].setVisible(index < self.edit_layout)

    def change_layout(self):
        self.edit_layout = self.layout_choice.currentData()
        self.slots = self.layout_slots[str(self.edit_layout)]
        self.refresh(max(0, self.table.currentRow()))

    def toggle_enabled(self):
        row = self.table.currentRow()
        if row < 0:
            return
        camera = self.cameras[row]
        camera['enabled'] = not camera.get('enabled', True)
        config = dict(cameras=self.cameras, layout=self.edit_layout, layout_slots=self.layout_slots)
        ensure_layout_slots(config)
        if camera['enabled']:
            fill_empty_slots(config, [camera['id']])
        self.layout_slots = config['layout_slots']
        self.assignment_changed = True
        self.refresh(row)

    def assign_screen(self, index):
        identifier = self.screen_choices[index].currentData()
        if identifier is not None and identifier in self.slots:
            other = self.slots.index(identifier)
            self.slots[other], self.slots[index] = self.slots[index], self.slots[other]
        else:
            self.slots[index] = identifier
        self.assignment_changed = True
        selected = self.table.currentRow()
        self.refresh(max(0, selected))

    def filter_rows(self):
        query = self.search.text().strip().casefold()
        visible = []
        for row, camera in enumerate(self.cameras):
            match = query in (str(camera['number']) + ' ' + camera['name'] + ' ' + address_label(camera['url'])).casefold()
            self.table.setRowHidden(row, not match)
            if match:
                visible.append(row)
        if self.table.currentRow() not in visible:
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
            if visible:
                self.table.selectRow(visible[0])
        self.count_label.setText(f'등록 {len(self.cameras)}대 · 검색 결과 {len(visible)}대 · 동시 재생 최대 4대')
        self.update_buttons()

    def update_buttons(self):
        row = self.table.currentRow()
        for key in ('edit', 'delete', 'enable'):
            self.buttons[key].setEnabled(row >= 0)
        if 0 <= row < len(self.cameras):
            self.buttons['enable'].setText('사용 안 함' if self.cameras[row].get('enabled', True) else '다시 사용')
        self.buttons['up'].setEnabled(row > 0 and not self.search.text().strip())
        self.buttons['down'].setEnabled(0 <= row < len(self.cameras) - 1 and not self.search.text().strip())

    def add_camera(self):
        dialog = CameraEditor(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.cameras.append(dialog.camera)
            config = dict(cameras=self.cameras, layout=self.edit_layout, layout_slots=self.layout_slots)
            fill_empty_slots(config, [dialog.camera['id']])
            self.layout_slots = config['layout_slots']
            self.search.clear()
            self.refresh(len(self.cameras) - 1)

    def edit_camera(self):
        row = self.table.currentRow()
        if row < 0:
            return
        dialog = CameraEditor(self.cameras[row], self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.cameras[row] = dialog.camera
            self.refresh(row)

    def delete_camera(self):
        row = self.table.currentRow()
        if row >= 0 and QMessageBox.question(self, '카메라 삭제', f"{self.cameras[row]['name']}을 목록에서 삭제할까요?") == QMessageBox.StandardButton.Yes:
            self.cameras.pop(row)
            self.refresh(row)

    def move_camera(self, delta):
        if self.search.text().strip():
            return
        row = self.table.currentRow()
        target = row + delta
        if row >= 0 and 0 <= target < len(self.cameras):
            self.cameras[row], self.cameras[target] = self.cameras[target], self.cameras[row]
            self.refresh(target)
