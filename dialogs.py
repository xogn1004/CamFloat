from __future__ import annotations

from html import escape
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTabWidget, QTextBrowser, QVBoxLayout
from camera_model import APP_TITLE
from ui_theme import STYLE


class UsageDialog(QDialog):
    def __init__(self, version, playback_mode, parent=None):
        super().__init__(parent)
        self.setWindowTitle(APP_TITLE)
        self.setStyleSheet(STYLE + '''
QTabWidget::pane{border:1px solid #354155;border-radius:8px;background:#202734;}
QTabBar::tab{background:#202734;color:#9eafc6;padding:9px 22px;margin-right:4px;border-radius:5px;}
QTabBar::tab:selected{background:#324e74;color:#f0f6ff;}
QTextBrowser{background:transparent;color:#d8e2f0;border:0;padding:12px;}
''')
        self.resize(650, 570)
        self.setMinimumSize(460, 380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        title = QLabel(APP_TITLE)
        title.setWordWrap(True)
        title.setStyleSheet('font-size:18px;font-weight:600;color:#edf4ff;')
        layout.addWidget(title)
        subtitle = QLabel(f'버전 {version}')
        subtitle.setStyleSheet('color:#96a9c3;padding-bottom:8px;')
        layout.addWidget(subtitle)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        usage = '''
<h3>창과 화면 조작</h3>
<p>화면을 드래그해 창을 옮기고, 가장자리·모서리를 드래그해 크기를 조절합니다.<br>
클릭하면 화면을 선택하며, 선택한 화면을 다시 클릭하면 선택이 해제됩니다.
다른 앱에서 돌아오는 첫 클릭은 선택을 유지합니다.</p>
<p>상단 중앙에 마우스를 올리면 앱 도구가 나타나고, 영역을 벗어나면 약 1.6초 후 숨겨집니다.
화면 우클릭이나 화면의 카메라 아이콘으로 카메라를 지정할 수 있습니다.</p>
<h3>화면 구성과 확대</h3>
<p>1·2·4분할을 지원합니다. 2분할 버튼이나 단축키 2를 누르면 마지막 방향으로 전환하고,
이미 2분할이면 좌우 ↔ 상하로 바뀝니다. 좌우는 SCREEN 1이 왼쪽, 상하는 위입니다.<br>
2분할의 두 방향은 카메라 배정을 공유하며, 방향을 바꿔도 연결을 유지합니다.</p>
<p>분할 화면 더블클릭: 해당 SCREEN 확대·복원. 다른 SCREEN의 연결은 유지됩니다.<br>
분할 화면 트리플클릭: 해당 SCREEN 확대 + 전체화면.<br>
기본 1분할 더블클릭: 전체화면 켜기·끄기.<br>
Esc: 확대 전 분할로 복원한 뒤, 한 번 더 누르면 전체화면을 해제합니다.
기본 1분할 전체화면에서는 한 번에 해제합니다.</p>
<h3>카메라와 소리</h3>
<p><b>카메라 이동</b> 아이콘을 누르고 화살표를 짧게 누르면 조금 이동하고, 길게 누르면 반복해서 이동을 요청합니다.
빠른 연속 클릭은 0.5초 간격으로 받습니다. 손을 떼면 추가 요청을 멈추지만 카메라가 이미 받은 요청은 실행될 수 있습니다.
작은 화면에서는 네 방향 버튼이 한 줄로 표시됩니다. Esc나 바깥 클릭으로 닫습니다.
현재는 내부망 IP로 등록한 카메라를 대상으로 하며, C500GS에서 동작을 확인했습니다.</p>
<p>카메라 번호와 SCREEN 번호는 별개이며 1·2·4분할의 카메라 배정을 각각 저장합니다.
사용 안 함으로 바꾸면 모든 배정을 비우고, 다시 사용하면 각 분할의 빈 SCREEN부터 채웁니다.</p>
<p>카메라 관리에서 추가·수정한 뒤 <b>저장</b>을 누르면 재생에 적용됩니다.
화면별 카메라 탭에서 각 SCREEN에 표시할 카메라를 고릅니다.</p>
<p>주소·아이디는 눈 아이콘으로 확인합니다. 비밀번호·RTSP 주소의 보기·복사는 Windows 본인 확인이 필요합니다.
확인한 정보는 30초 후 또는 다른 앱으로 이동하면 숨깁니다.
복사한 정보는 30초 후 클립보드에서 지웁니다. 다른 내용을 복사했다면 지우지 않습니다.</p>
<p>관리창 상단 ⋯에서 카메라 목록을 내보내거나 불러올 수 있습니다.
.camfloat 파일에는 로그인 정보가 포함됩니다. 파일 비밀번호 없이 다른 PC의 CamFloat에서도 열 수 있으므로 공유할 사람을 확인하세요.
불러온 목록은 추가할 카메라를 확인한 뒤 저장합니다.</p>
<p>같은 ⋯ 메뉴의 <b>카메라 전체 삭제</b>에서 목록을 비우거나 <b>설정 초기화</b>로 카메라 목록을 유지한 채
설정을 처음 상태로 되돌립니다. 확인 후 관리창에서 저장하면 적용됩니다.</p>
<p>음량과 음소거는 카메라별로 저장합니다. 전체 음소거를 해제해도 개별 음소거 설정은 유지합니다.
작은 화면에서는 스피커에 마우스를 올려 세로 음량 슬라이더를 열고, 휠로 5%씩 조절합니다.</p>
<h3>투명도와 연결</h3>
<p>전체화면은 투명도 0%로 표시합니다. 전체화면에서도 투명도 설정은 바꿀 수 있고,
창 모드로 돌아오면 변경한 값을 적용합니다.</p>
<p>최초 연결 실패는 다시 연결 버튼으로 재시도합니다.
정상 재생 후 끊긴 경우에만 2~30초 간격으로 자동 재연결합니다.
다시 연결 버튼을 누르면 즉시 재시도할 수 있습니다.</p>'''
        shortcuts = [
            ('1 / 4', '1분할 / 4분할'),
            ('2', '마지막 2분할 방향으로 전환 / 이미 2분할이면 좌우·상하 전환'),
            ('F11', '선택 화면 전체화면 / 선택 없으면 현재 화면 구성 전체화면'),
            ('F11 · 전체화면에서', '이전 창 상태 복원'),
            ('Esc', '확대 전 분할 복원 → 전체화면 해제'),
            ('← / →', '분할 확대 중 SCREEN 이동 / 기본 1분할에서 카메라 이동'),
            ('M', '선택 영상 음소거 / 해제'),
            ('Ctrl+Shift+M', '전체 음소거 / 해제'),
            ('Ctrl+R', '선택 영상 다시 연결'),
            ('Ctrl+M', '카메라 관리'),
            ('Ctrl+T', '항상 위에 / 해제'),
            ('Ctrl+0', '창 모드에 사용할 투명도를 0%로 복원'),
            ('Alt / Alt+A', '상단 앱 도구 표시'),
            ('F1', '사용법 / 정보'),
            ('Alt+F4', '종료'),
        ]
        keys = '<h3>단축키</h3><table width="100%" cellspacing="7">' + ''.join(
            f'<tr><td width="150"><b>{escape(key)}</b></td><td>{escape(text)}</td></tr>'
            for key, text in shortcuts) + '''</table>
<p>단축키는 CamFloat가 활성화되어 있을 때 동작합니다.
선택이 없으면 M·Ctrl+R은 동작하지 않습니다.<br>
카메라 관리·등록 등의 대화상자에서는 앱 단축키를 사용하지 않습니다.</p>'''
        info = f'''<h3>{APP_TITLE}</h3>
<p>버전: {escape(version)}<br>Windows용 RTSP 스트림 뷰어</p>
<h3>용도</h3><p>네트워크 카메라 영상을 1·2·4분할로 동시에 재생하며,
다른 작업 중에도 항상 위에 두고 볼 수 있는 프레임 없는 플레이어입니다.</p>
<h3>재생 방식</h3><p>등록한 RTSP 주소에 연결해 VLC 엔진으로 영상과 소리를 재생합니다.
재생 엔진이 포함되어 있어 별도 설치가 필요하지 않습니다.<br>현재 재생 모드: {escape(playback_mode)}<br>
화질 전환은 카메라에서 제공하는 HD·SD 스트림 주소를 사용합니다.
하드웨어 가속은 지원되는 영상의 디코딩에 GPU를 사용합니다.</p>
<h3>설정 보관</h3><p>%LOCALAPPDATA%\\CamFloat\\settings.json<br>
카메라 이름·주소·로그인 정보는 Windows 계정에 연결해 암호화해 저장합니다.</p>
<h3>구성 요소</h3><p>Python · PySide6 / Qt · python-vlc · VLC<br>
라이선스 안내는 배포 폴더의 licenses 폴더에 있습니다.</p>'''
        for name, content in [('사용법', usage), ('단축키', keys), ('기본 정보', info)]:
            browser = QTextBrowser()
            browser.setOpenExternalLinks(False)
            browser.setHtml('<html><head><style>h3{color:#edf4ff;} p{line-height:150%;}</style></head>'
                            f'<body>{content}</body></html>')
            tabs.addTab(browser, name)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText('닫기')
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


from camera_editor import CameraEditor
from camera_manager import CameraManager
