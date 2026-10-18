"""Camera registry drafts and layout assignments, with private connection details."""
import copy
from urllib.parse import unquote, urlsplit

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog,
    QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
    QMessageBox, QPushButton, QScrollArea, QSplitter, QTableView, QTabWidget,
    QVBoxLayout, QWidget)

from camera_model import (camera_display_name, camera_url, default_config,
                          ensure_layout_slots, fill_empty_slots, supports_quality)
from camera_editor import CameraEditor
from icons import icon
from privacy import PrivacyController, SensitiveField
from ui_theme import STYLE


class CameraListModel(QAbstractTableModel):
    def __init__(self, cameras, parent):
        super().__init__(parent)
        self.cameras = cameras

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.cameras)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 5

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return ['번호', '카메라', '화질', '사용', ''][section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        camera = self.cameras[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return camera['id']  # Only stable identifiers, never connection URLs.
        if role == Qt.ItemDataRole.DisplayRole:
            return [f"{camera['number']:02}", camera_display_name(camera), camera['quality'],
                    '사용' if camera.get('enabled', True) else '사용 안 함', '⋯'][index.column()]
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() != 1:
            return Qt.AlignmentFlag.AlignCenter
        return None

    def refresh(self, cameras):
        self.beginResetModel()
        self.cameras = cameras
        self.endResetModel()


class CameraTable(QTableView):
    def currentRow(self):
        return self.currentIndex().row()


class CameraManager(QDialog):
    def __init__(self, cameras, parent=None, slots=None, layout_slots=None, layout=4,
                 *, verify_connection_info=None, commit_callback=None, statuses=None):
        super().__init__(parent)
        self.cameras = copy.deepcopy(cameras)
        self.edit_layout = layout
        self.commit_callback = commit_callback
        host_config = getattr(parent, 'config', {})
        # Required disclosure is enforced per sensitive field, including old profiles.
        self.verify_connection_info = True
        self.split_orientation = host_config.get('split_orientation', 'horizontal')
        config = default_config()
        config.update(cameras=self.cameras, layout=layout, layout_slots=copy.deepcopy(layout_slots),
                      slots=list(slots) if slots is not None else [c['id'] for c in cameras[:4]])
        self.layout_slots = ensure_layout_slots(config)
        self.slots = self.layout_slots[str(layout)]
        self.assignment_changed = False
        self.setWindowTitle('카메라 관리')
        self.setStyleSheet(STYLE)
        self.resize(960, 640)
        self.setMinimumSize(760, 520)
        self.privacy = PrivacyController(self)
        self.buttons = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12)
        header = QHBoxLayout()
        title = QLabel('카메라 관리')
        title.setStyleSheet('font-size:21px;font-weight:600;')
        header.addWidget(title)
        header.addStretch()
        add = self.action_button('add', '카메라 추가', self.add_camera, 'add')
        add.setObjectName('primary')
        header.addWidget(add)
        root.addLayout(header)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.build_registry_tab()
        self.build_assignments_tab()
        self.tabs.currentChanged.connect(lambda *_: self.privacy.hide_all())
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet('color:#9fb9db;font-size:11px;')
        self.notice.hide()
        root.addWidget(self.notice)
        self.privacy.notice.connect(self.show_notice)
        footer = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setStyleSheet('color:#96a9c3;')
        footer.addWidget(self.count_label)
        footer.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('저장하고 적용')
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName('primary')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        root.addLayout(footer)
        self.refresh()
        self._baseline = self.snapshot()
        area = QApplication.primaryScreen().availableGeometry()
        self.resize(min(self.width(), area.width()), min(self.height(), area.height()))

    def action_button(self, key, text, callback, symbol):
        button = QPushButton(text)
        button.setIcon(icon(symbol))
        button.clicked.connect(callback)
        self.buttons[key] = button
        return button

    def build_registry_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('카메라 번호·별명 검색')
        self.search.textChanged.connect(self.filter_rows)
        filters.addWidget(self.search, 1)
        self.filter = QComboBox()
        self.filter.addItems(['전체', '사용', '사용 안 함'])
        self.filter.currentIndexChanged.connect(self.filter_rows)
        filters.addWidget(self.filter)
        layout.addLayout(filters)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.table = CameraTable()
        self.model = CameraListModel(self.cameras, self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 50), (2, 46), (3, 80), (4, 30)):
            self.table.setColumnWidth(col, width)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self.update_buttons())
        self.table.doubleClicked.connect(lambda index: self.edit_camera() if index.column() != 4 else None)
        self.table.clicked.connect(lambda index: self.row_menu(index) if index.column() == 4 else None)
        left_layout.addWidget(self.table, 1)
        self.empty_label = QLabel('등록된 카메라가 없습니다. 상단에서 카메라를 추가하세요.')
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet('color:#96a9c3;padding:10px;')
        left_layout.addWidget(self.empty_label)
        order = QHBoxLayout()
        order.addWidget(self.action_button('up', '위로', lambda: self.move_camera(-1), 'up'))
        order.addWidget(self.action_button('down', '아래로', lambda: self.move_camera(1), 'down'))
        order.addStretch()
        left_layout.addLayout(order)
        splitter.addWidget(left)
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setMinimumWidth(300)
        detail = QFrame()
        detail.setObjectName('detail')
        details = QVBoxLayout(detail)
        details.setContentsMargins(16, 16, 16, 16)
        details.setSpacing(8)
        self.detail_title = QLabel('카메라를 선택하세요')
        self.detail_title.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_title.setWordWrap(True)
        self.detail_title.setStyleSheet('font-size:17px;font-weight:600;')
        details.addWidget(self.detail_title)
        self.details = {}
        for key, label in [('host', '주소'), ('username', '아이디'), ('password', '비밀번호'),
                            ('url', 'RTSP 주소'), ('sd_url', 'RTSP 주소2 (SD)')]:
            caption = QLabel(label)
            caption.setStyleSheet('color:#b7c8de;font-size:11px;')
            details.addWidget(caption)
            field = SensitiveField(self.privacy, label, required=key not in ('host', 'username'),
                                   public=key in ('host', 'username'))
            self.details[key] = field
            details.addWidget(field)
        description = QLabel('비밀번호·RTSP 주소는 본인인증 후 30초 동안 확인할 수 있습니다.')
        description.setWordWrap(True)
        description.setStyleSheet('color:#96a9c3;font-size:11px;')
        details.addWidget(description)
        details.addStretch()
        self.buttons['edit'] = QAction(icon('edit'), '카메라 수정', self)
        self.buttons['edit'].triggered.connect(self.edit_camera)
        self.buttons['enable'] = QAction(icon('camera'), '사용 안 함', self)
        self.buttons['enable'].triggered.connect(self.toggle_enabled)
        self.buttons['delete'] = QAction(icon('close'), '카메라 삭제', self)
        self.buttons['delete'].triggered.connect(self.delete_camera)
        detail_scroll.setWidget(detail)
        splitter.addWidget(detail_scroll)
        splitter.setSizes([520, 350])
        layout.addWidget(splitter, 1)
        self.tabs.addTab(page, '카메라 목록')

    def build_assignments_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel('편집할 화면 구성'))
        self.layout_choice = QComboBox()
        for count in (1, 2, 4):
            self.layout_choice.addItem(f'{count}분할', count)
        self.layout_choice.setCurrentIndex(self.layout_choice.findData(self.edit_layout))
        self.layout_choice.currentIndexChanged.connect(self.change_layout)
        row.addWidget(self.layout_choice)
        row.addStretch()
        layout.addLayout(row)
        hint = QLabel('카메라 번호와 SCREEN 번호는 별개입니다. 분할마다 배정을 저장합니다.\n'
                      '2분할 좌우·상하는 같은 배정을 사용합니다.')
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#96a9c3;padding:4px 0 8px;')
        layout.addWidget(hint)
        self.assignments = QGridLayout()
        self.screen_choices, self.screen_labels, self.screen_cards = [], [], []
        for index in range(4):
            card = QFrame(page)
            card.setObjectName('screenCard')
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 18, 18, 18)
            label = QLabel(f'SCREEN {index + 1}')
            label.setStyleSheet('color:#90baff;font-size:12px;font-weight:600;')
            card_layout.addWidget(label)
            choice = QComboBox()
            choice.setMinimumContentsLength(12)
            choice.setToolTip(f'SCREEN {index + 1}에 표시할 카메라')
            choice.currentIndexChanged.connect(lambda _, i=index: self.assign_screen(i))
            card_layout.addWidget(choice)
            clear = QPushButton('화면 비우기')
            clear.clicked.connect(lambda _, i=index: self.clear_screen(i))
            card_layout.addWidget(clear, 0, Qt.AlignmentFlag.AlignRight)
            self.screen_labels.append(label)
            self.screen_choices.append(choice)
            self.screen_cards.append(card)
        layout.addLayout(self.assignments, 1)
        note = QLabel('사용 안 함: 모든 분할에서 해제 · 다시 사용: 각 분할의 빈 SCREEN부터 채움')
        note.setWordWrap(True)
        note.setStyleSheet('color:#96a9c3;font-size:11px;')
        layout.addWidget(note)
        self.tabs.addTab(page, '화면 배정')

    def snapshot(self):
        return copy.deepcopy((self.cameras, self.layout_slots, self.verify_connection_info))

    def selected_camera(self):
        row = self.table.currentRow()
        return self.cameras[row] if 0 <= row < len(self.cameras) else None

    def refresh(self, selected=0):
        config = dict(cameras=self.cameras, layout=self.edit_layout, layout_slots=self.layout_slots)
        self.layout_slots = ensure_layout_slots(config)
        self.slots = self.layout_slots[str(self.edit_layout)]
        self.refresh_screen_choices()
        self.model.refresh(self.cameras)
        if self.cameras:
            self.table.selectRow(max(0, min(selected, len(self.cameras) - 1)))
        self.filter_rows()

    def refresh_screen_choices(self):
        for card in self.screen_cards:
            self.assignments.removeWidget(card)
        columns = 1 if self.edit_layout == 1 or (self.edit_layout == 2 and self.split_orientation == 'vertical') else 2
        for index, choice in enumerate(self.screen_choices):
            choice.blockSignals(True)
            choice.clear()
            choice.addItem('비어 있음', None)
            for camera in self.cameras:
                if camera.get('enabled', True):
                    choice.addItem(f"{camera['number']}. {camera_display_name(camera)}", camera['id'])
                    if camera.get('connection_locked'):
                        choice.model().item(choice.count() - 1).setEnabled(False)
            choice.setCurrentIndex(max(0, choice.findData(self.slots[index])))
            choice.blockSignals(False)
            visible = index < self.edit_layout
            self.screen_cards[index].setVisible(visible)
            if visible:
                self.assignments.addWidget(self.screen_cards[index], index // columns, index % columns)

    def change_layout(self):
        self.privacy.hide_all()
        self.edit_layout = self.layout_choice.currentData()
        self.slots = self.layout_slots[str(self.edit_layout)]
        self.refresh(max(0, self.table.currentRow()))

    def filter_rows(self):
        query = self.search.text().strip().casefold()
        visible = []
        state = self.filter.currentIndex()
        for row, camera in enumerate(self.cameras):
            matches = query in f"{camera['number']} {camera_display_name(camera)}".casefold()
            matches = matches and (state == 0 or camera.get('enabled', True) == (state == 1))
            self.table.setRowHidden(row, not matches)
            if matches:
                visible.append(row)
        if self.table.currentRow() not in visible:
            self.table.clearSelection()
            self.table.setCurrentIndex(QModelIndex())
            if visible:
                self.table.selectRow(visible[0])
        used = sum(c.get('enabled', True) for c in self.cameras)
        if hasattr(self, 'count_label'):
            self.count_label.setText(f'등록 {len(self.cameras)}대 · 사용 {used}대 · 표시 {len(visible)}대')
        self.empty_label.setText('검색 결과가 없습니다.' if self.cameras else
                                '등록된 카메라가 없습니다. 상단에서 카메라를 추가하세요.')
        self.empty_label.setVisible(not visible)
        self.update_buttons()

    def update_buttons(self):
        if not hasattr(self, 'details') or 'edit' not in self.buttons:
            return
        row = self.table.currentRow()
        camera = self.selected_camera()
        valid = camera is not None
        for key in ('edit', 'enable', 'delete'):
            self.buttons[key].setEnabled(valid)
        locked = bool(camera and camera.get('connection_locked'))
        self.buttons['edit'].setEnabled(valid)
        self.buttons['edit'].setText('연결 정보 다시 입력' if locked else '카메라 수정')
        filtered = bool(self.search.text().strip()) or self.filter.currentIndex() != 0
        self.buttons['up'].setEnabled(row > 0 and not filtered)
        self.buttons['down'].setEnabled(0 <= row < len(self.cameras) - 1 and not filtered)
        for key in ('up', 'down'):
            self.buttons[key].setToolTip('검색·필터 중에는 순서를 바꿀 수 없습니다.' if filtered else '카메라 목록 순서 변경')
        self.privacy.hide_all()
        if not camera:
            self.detail_title.setText('카메라를 선택하세요')
            for field in self.details.values():
                field.set_value('')
            return
        self.buttons['enable'].setText('사용 안 함' if camera.get('enabled', True) else '다시 사용')
        self.detail_title.setText(f"CAMERA {camera['number']:02} · {camera_display_name(camera)}")
        try:
            p = urlsplit(camera['url'])
            host = ('[' + p.hostname + ']' if p.hostname and ':' in p.hostname else p.hostname or '')
            host = f'{host}:{p.port or 554}' if host else ''
            values = dict(host=host, username=unquote(p.username or ''), password=unquote(p.password or ''),
                          url=camera['url'], sd_url=camera_url(dict(camera, quality='SD')) if supports_quality(camera) else '')
        except ValueError:
            values = {}
        for key, field in self.details.items():
            field.set_value(values.get(key, ''))

    def show_notice(self, text):
        self.notice.setText(text)
        self.notice.show()

    def add_camera(self):
        number = max([c.get('number', 0) for c in self.cameras] + [0]) + 1
        dialog = CameraEditor(parent=self, privacy=self.privacy, others=self.cameras, number=number)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.cameras.append(dialog.camera)
            config = dict(cameras=self.cameras, layout=self.edit_layout, layout_slots=self.layout_slots)
            fill_empty_slots(config, [dialog.camera['id']])
            self.layout_slots = config['layout_slots']
            self.search.clear()
            self.filter.setCurrentIndex(0)
            self.refresh(len(self.cameras) - 1)
            self.show_notice('카메라를 목록에 추가했습니다. 저장하고 적용을 눌러 완료하세요.')
        dialog.deleteLater()

    def edit_camera(self):
        camera = self.selected_camera()
        if not camera:
            return
        identifier = camera['id']
        def edit():
            if self.selected_camera() is None or self.selected_camera()['id'] != identifier:
                return
            row = self.table.currentRow()
            locked = self.cameras[row].get('connection_locked', False)
            if locked and QMessageBox.question(self, '연결 정보 다시 입력',
                    '기존 연결 정보를 다시 입력할까요? 원래 암호화 정보는 최종 저장 시 백업에 보존합니다.',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            dialog = CameraEditor(None if locked else self.cameras[row], self, privacy=self.privacy,
                                  others=self.cameras, number=self.cameras[row]['number'])
            if dialog.exec() == QDialog.DialogCode.Accepted:
                if locked:
                    for key in ('id', 'number', 'volume', 'muted', 'enabled'):
                        dialog.camera[key] = self.cameras[row][key]
                self.cameras[row] = dialog.camera
                self.refresh(row)
                self.show_notice('변경을 반영했습니다. 저장하고 적용을 눌러 완료하세요.')
            dialog.deleteLater()
        self.privacy.authorize(edit)

    def toggle_enabled(self):
        camera = self.selected_camera()
        if camera is None:
            return
        row = self.table.currentRow()
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
        self.refresh(max(0, self.table.currentRow()))

    def clear_screen(self, index):
        self.screen_choices[index].setCurrentIndex(0)

    def delete_camera(self):
        camera = self.selected_camera()
        if camera is None:
            return
        row = self.table.currentRow()
        if QMessageBox.question(self, '카메라 삭제', f'{camera_display_name(camera)}을 목록에서 삭제할까요?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.cameras.pop(row)
            self.refresh(row)

    def move_camera(self, delta):
        if self.search.text().strip() or self.filter.currentIndex() != 0:
            return
        row = self.table.currentRow()
        target = row + delta
        if 0 <= row < len(self.cameras) and 0 <= target < len(self.cameras):
            self.cameras[row], self.cameras[target] = self.cameras[target], self.cameras[row]
            self.refresh(target)

    def build_row_menu(self):
        if not self.selected_camera():
            return None
        menu = QMenu(self)
        menu.addAction(self.buttons['edit'])
        menu.addAction(self.buttons['enable'])
        menu.addSeparator()
        available = not self.selected_camera().get('connection_locked')
        menu.addAction(icon('copy'), 'RTSP 주소 복사', lambda: self.copy_rtsp('HD')).setEnabled(available)
        menu.addAction(icon('copy'), 'RTSP 주소2 (SD) 복사', lambda: self.copy_rtsp('SD')).setEnabled(
            available and supports_quality(self.selected_camera()))
        menu.addSeparator()
        menu.addAction(self.buttons['delete'])
        return menu

    def row_menu(self, index):
        menu = self.build_row_menu()
        if menu is None:
            return
        menu.exec(self.table.viewport().mapToGlobal(self.table.visualRect(index).bottomLeft()))
        menu.deleteLater()

    def copy_rtsp(self, quality=None):
        camera = self.selected_camera()
        if not camera or camera.get('connection_locked'):
            return
        # Only explicit HD / SD override the configured quality.
        selected_quality = quality if quality in ('HD', 'SD') else camera['quality']
        if selected_quality == 'SD' and not supports_quality(camera):
            self.show_notice('이 카메라는 SD 주소가 설정되지 않았습니다.')
            return
        value = camera_url(dict(camera, quality=selected_quality))
        self.privacy.copy(value, 'RTSP 주소를 복사했습니다. 30초 후 클립보드에서 지웁니다.', required=True)

    def accept(self):
        self.privacy.hide_all()
        if self.commit_callback and not self.commit_callback(self.cameras, self.layout_slots, self.verify_connection_info):
            self.show_notice('설정을 저장하지 못했습니다. 변경 내용은 유지됩니다. 저장 위치와 접근 권한을 확인하세요.')
            return
        super().accept()

    def reject(self):
        if hasattr(self, '_baseline') and self.snapshot() != self._baseline:
            box = QMessageBox(self)
            box.setWindowTitle('저장하지 않은 변경')
            box.setText('변경한 카메라 설정을 저장할까요?')
            save = box.addButton('저장하고 적용', QMessageBox.ButtonRole.AcceptRole)
            discard = box.addButton('버리기', QMessageBox.ButtonRole.DestructiveRole)
            box.addButton('계속 편집', QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is save:
                self.accept()
                return
            if box.clickedButton() is not discard:
                return
        super().reject()
