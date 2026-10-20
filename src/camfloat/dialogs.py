from __future__ import annotations

from html import escape
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTabWidget, QTextBrowser, QVBoxLayout
from camfloat.camera_model import APP_TITLE
from camfloat.ui_theme import STYLE


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
        connection_usage = '''
<h3>집 안에서 연결하기</h3>
<p>카메라와 PC를 같은 공유기에 연결하세요. 카메라가 RTSP 연결을 지원해야 하며,
제품에 따라 제조사 앱에서 RTSP 사용 설정이나 접속 계정을 먼저 만들어야 합니다.</p>
<p><b>1. 카메라 IP 주소 찾기</b><br>
제조사 앱의 ‘기기 정보·네트워크’ 또는 공유기 관리 화면의 ‘연결된 기기’에서 확인하세요.
메뉴 이름은 제품마다 다릅니다.</p>
<p><b>2. 카메라 등록</b><br>카메라 관리 → 카메라 추가에서 입력하세요.</p>
<table width="100%" cellspacing="6">
<tr><th align="left">입력 항목</th><th align="left">입력할 내용</th><th align="left">기본값</th></tr>
<tr><td>IP / 도메인</td><td>찾은 카메라 IP 주소</td><td>없음</td></tr>
<tr><td>포트</td><td>RTSP 영상 포트</td><td>554</td></tr>
<tr><td>아이디</td><td>카메라 접속 아이디</td><td>admin</td></tr>
<tr><td>비밀번호</td><td>카메라에 설정한 비밀번호</td><td>없음</td></tr>
<tr><td>영상 경로 (HD)</td><td>고급 설정 · 고화질 영상 경로</td><td>/onvif1</td></tr>
<tr><td>영상 경로 (SD)</td><td>고급 설정 · 필요할 때 입력</td><td>/onvif2</td></tr>
<tr><td>방향 조작 포트</td><td>고급 설정 · ONVIF 제어 포트</td><td>5000</td></tr>
</table>
<p>기본값은 ipTIME 홈캠 기준이며 모델·설정에 따라 다를 수 있습니다.
SD 경로는 필요할 때 입력하세요. 제어 포트 5000은 C500GS에서 확인했습니다.</p>
<p>RTSP 주소가 있다면 ‘RTSP 주소’ 입력 방식으로 붙여넣어도 됩니다.
제조사 앱 로그인 계정과 카메라 접속 계정은 다를 수 있습니다.</p>
<p><b>3. 연결 확인</b><br>연결 확인 → 추가 → 관리창에서 저장을 누르세요.
‘연결 확인’은 영상 연결을 확인하며 방향 조작 성공까지 확인하지는 않습니다.</p>
<h3>집 밖에서 연결하기</h3>
<p>집 안에서 연결되는 것을 먼저 확인하세요. 외부 PC에서는 집 안의 카메라 IP 대신
집의 <b>공인 IP 또는 DDNS 주소</b>를 입력합니다. 공인 IP는 인터넷에서 집의 공유기에 접속하는 주소이며,
DDNS는 변경될 수 있는 공인 IP 대신 사용하는 이름입니다. 제조사 앱의 외부 연결 방식과는 다를 수 있습니다.</p>
<p><b>포트포워딩</b>은 외부에서 들어온 연결을 집 안의 카메라로 전달하는 공유기 설정입니다.
영상용 포트를 연결하고, 방향 조작도 쓰려면 제어용 포트도 연결하세요.</p>
<table width="100%" cellspacing="6">
<tr><th align="left">용도</th><th align="left">포트포워딩 예시 · TCP</th><th align="left">앱에 입력</th></tr>
<tr><td>영상</td><td>외부 15554 → 카메라 554</td><td>포트 15554</td></tr>
<tr><td>방향 조작</td><td>외부 25554 → 카메라 5000</td><td>방향 조작 포트 25554</td></tr>
</table>
<p>카메라가 여러 대면 각각 다른 외부 포트를 사용하세요. 공유기가 두 단계라면
상위 공유기 → 하위 공유기 → 카메라까지 각 단계에 포트포워딩이 필요합니다.</p>
<p>예: 상위 공유기 25554 → 하위 공유기의 WAN 주소:25554 → 카메라 주소:5000.</p>
<p>공유기·모뎀 구성에 따라 설정 방법이 다릅니다. 장비별 ‘포트포워딩’ 안내를 확인하고,
설정한 뒤 외부 네트워크의 PC에서 연결을 확인하세요.</p>
'''
        usage = '''
<h3>창과 도구</h3>
<p>영상을 드래그해 창을 옮기고, 창 가장자리를 드래그해 크기를 조절합니다.<br>
상단 중앙에 마우스를 올리면 앱 도구가 나타납니다. 영상별 도구는 마우스를 올리거나 우클릭해 엽니다.
아이콘에 마우스를 잠시 올리면 설명을 볼 수 있습니다.</p>
<p>영상을 클릭하면 선택하고, 다시 클릭하면 해제합니다. 다른 앱으로 이동하면 선택을 해제합니다.</p>
<h3>분할과 확대</h3>
<p>상단의 1·2·4 버튼으로 분할을 바꿉니다. 2분할에서 2를 다시 누르면 좌우·상하 배치가 바뀝니다.<br>
분할 화면을 더블클릭하면 해당 화면을 크게 보고, 다시 더블클릭하면 돌아옵니다.
기본 1분할에서는 더블클릭으로 전체화면을 켜고 끕니다.</p>
<p>화면을 선택하고 F11을 누르거나 트리플클릭하면 해당 화면을 전체화면으로 봅니다.
상단 전체화면 버튼은 현재 분할 그대로 표시합니다.<br>
Esc는 확대를 먼저 해제하고, 한 번 더 누르면 전체화면을 종료합니다.</p>
<p>확대해도 다른 화면의 영상과 소리는 유지됩니다. 좌우 버튼이나 방향키로 화면을 넘길 수 있습니다.<br>
1분할은 사용할 카메라를 자동 지정합니다. 2·4분할의 빈 화면은 확대와 좌우 이동에서 건너뜁니다.</p>
<h3>영상과 창 맞춤</h3>
<p>영상 우클릭 → <b>영상 맞춤</b>에서 전체 보기·꽉 채우기를 선택합니다.
꽉 채우기는 영상의 가장자리가 잘릴 수 있습니다.<br>
앱 메뉴의 <b>창을 영상에 맞추기</b>는 여백만큼 창을 줄입니다.
분할에서는 선택한 화면, 선택이 없으면 첫 재생 영상이 기준입니다.</p>
<h3>스크린샷</h3>
<p>영상 아래의 사진 아이콘이나 우클릭 메뉴의 <b>스크린샷 저장</b>으로 영상을 PNG로 저장합니다.
화면의 메뉴와 배지는 포함하지 않습니다.<br>
앱 메뉴의 <b>스크린샷 폴더 열기</b> 또는 저장 알림을 누르면 사진 → CamFloat 폴더를 엽니다.</p>
<h3>카메라 이동</h3>
<p><b>카메라 이동</b> 아이콘을 열고 화살표를 누릅니다. 길게 누르면 이동을 이어갑니다.
Esc나 바깥 클릭으로 닫으며, 다른 앱으로 이동해도 조작을 멈춥니다.<br>
지원 여부는 카메라 관리에서 확인할 수 있습니다. 외부 조작은 카메라 연결 안내를 참고하세요.</p>
<h3>카메라 관리</h3>
<p><b>Ctrl+M</b>으로 관리창을 엽니다. 카메라를 추가·수정한 뒤 <b>저장</b>을 누르면 적용됩니다.
<b>화면별 카메라</b> 탭에서 각 화면에 표시할 카메라를 고릅니다.</p>
<p>주소·아이디는 눈 아이콘으로 확인합니다. 비밀번호·RTSP 주소를 보거나 복사할 때는 Windows 본인 확인이 필요합니다.
확인한 정보와 복사한 내용은 잠시 후 자동으로 숨기거나 지웁니다.</p>
<p>상단 ⋯에서 목록 내보내기·불러오기, 카메라 전체 삭제, 설정 초기화를 선택합니다.<br>
<b>.camfloat 파일에는 접속 정보가 들어 있으니 신뢰하는 사람에게만 전달하세요.</b></p>
<h3>소리·화질·투명도</h3>
<p>스피커 버튼은 해당 영상만 음소거합니다. 음량을 조절하면 개별 음소거가 풀립니다.
전체 음소거를 해제해도 개별 음소거 설정은 유지됩니다.<br>
작은 화면은 스피커에 마우스를 올려 음량을 조절합니다. 마우스 휠도 사용할 수 있습니다.</p>
<p>HD·SD는 카메라가 제공하는 화질을 선택합니다. 항상 위에와 전체 투명도는 앱 메뉴에서 바꿉니다.<br>
전체화면은 불투명하게 표시합니다. 전체화면에서 바꾼 투명도는 창 모드로 돌아오면 적용됩니다.</p>
<h3>다시 연결</h3>
<p>처음 연결에 실패했다면 다시 연결 버튼을 누르세요. 재생 중 연결이 끊기면 자동으로 다시 연결합니다.</p>'''
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
<p>버전 {escape(version)} · Windows용 무료 RTSP 뷰어</p>
<p>카메라 영상을 여러 화면으로 띄우고 다른 작업과 함께 볼 수 있습니다.
재생 엔진이 포함되어 있어 VLC를 따로 설치할 필요가 없습니다.</p>
<h3>화질과 하드웨어 가속</h3>
<p>화질은 카메라에서 제공하는 HD·SD 영상을 사용합니다.
하드웨어 가속은 지원되는 영상의 재생에 GPU를 사용합니다.</p>
<h3>카메라 정보 보호</h3>
<p>설정은 이 PC의 Windows 계정에 연결해 암호화하여 보관합니다.
내보낸 목록 파일에는 접속 정보가 포함되므로 공유할 사람을 확인하세요.</p>
<h3>라이선스</h3>
<p>CamFloat는 MIT 라이선스입니다. 외부 라이브러리 안내는 배포 폴더의 licenses에서 확인할 수 있습니다.</p>'''
        for name, content in [('카메라 연결', connection_usage), ('사용법', usage), ('단축키', keys), ('기본 정보', info)]:
            browser = QTextBrowser()
            browser.setOpenExternalLinks(False)
            browser.setHtml('<html><head><style>h3{color:#edf4ff;} p{line-height:150%;}</style></head>'
                            f'<body>{content}</body></html>')
            tabs.addTab(browser, name)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText('닫기')
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def __getattr__(name):
    # Keep the public imports used by existing callers without loading both
    # editors, archive encryption and authentication just to open the help page.
    if name == 'CameraEditor':
        from camfloat.camera_editor import CameraEditor
        value = CameraEditor
    elif name == 'CameraManager':
        from camfloat.camera_manager import CameraManager
        value = CameraManager
    else:
        raise AttributeError(name)
    globals()[name] = value
    return value
