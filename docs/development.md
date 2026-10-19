# 개발 안내

현재 개발본은 **1.1.1-dev.1**입니다. 로컬 릴리즈 빌드 **1.1.0**은 보존하며 전체 QA/QC를 완료했습니다. GitHub 공개 배포본은 **1.0.0**이고 1.1.0 공개는 별도입니다.

## 환경과 빌드

Windows x64와 Python 3.14를 사용합니다. PySide6·python-vlc 등 의존성 버전은 `requirements.txt`에 고정되어 있습니다.

```powershell
git clone https://github.com/xogn1004/CamFloat.git
cd CamFloat
.\build.bat
.\.venv\Scripts\python.exe package_release.py --staged --archive
```

`build.bat`은 가상 환경·의존성 설치, 공식 LGPL libVLC 패키지 다운로드·체크섬 확인, 아이콘 확인과 PyInstaller 빌드를 수행합니다. 사용자 제공 `camfloat.ico`가 있으면 그대로 사용합니다. PNG에서 다시 만들 때만 `make_icon.py --force`를 실행합니다. VLC를 별도로 설치할 필요가 없습니다. 개발·RC 버전은 자동으로 별도 빌드 경로에 보관하며, 정식 버전의 기본 결과는 `release/CamFloat/`입니다.

앱을 실행 중이라면 `build.bat --staged`로 별도 빌드합니다. 실행할 개발본은 프로젝트의 `dist/CamFloat/CamFloat.exe`입니다. 버전별 폴더를 만들지 않고 이 경로에 최신 개발본 하나를 둡니다. Codex 등 패키지 앱 안에서는 AppData 경로가 탐색기에 보이는 경로와 다를 수 있으므로 실행 안내에는 프로젝트 경로를 사용합니다.

빌드·패키징 작업용 파일은 `%LOCALAPPDATA%/CamFloatBuild/current`에 보관합니다. `package_release.py --staged --archive`는 그 안의 결과를 압축합니다. `dist/`는 Git·정식 릴리즈에 포함하지 않습니다.

- 배포 ZIP에는 EXE·런타임·라이선스·시작 안내만 넣습니다.
- `release/`에는 최신 실행 폴더·ZIP·체크섬만 보관합니다. 외부 라이브러리 소스 자료는 `vendor/source-assets/`에 둡니다.
- 사용하지 않는 Qt PDF·QML·가상 키보드·소프트웨어 OpenGL 부품은 제외합니다. 라이선스와 소스 제공은 [외부 라이브러리 안내](../THIRD_PARTY.md)를 따릅니다.

## 코드 구조

| 파일 | 역할 |
| --- | --- |
| `onvif_control.py`, `ptz_control.py`, `ptz_metadata.py`, `direction_popup.py`, `ptz_transport.py`, `ptz_timing.py` | 방향 조작·제어 정보 보관·독립 응답 처리·취소/시간 제한·전송 간격 기록 |
| `main.py`, `playback.py` | 화면 배정·확대·전체화면과 비동기 재생 작업 |
| `chrome.py`, `native_window.py` | 상단 도구와 Windows 창·오버레이 처리 |
| `camera_manager.py`, `camera_editor.py`, `camera_draft.py` | 관리 초안·최종 저장과 연결 정보 입력·검증 |
| `privacy.py`, `windows_consent.py` | 항목별 가림·복사·공개 만료와 Windows 본인 확인 |
| `camera_model.py`, `camera_archive.py` | 로컬 설정·암호화 저장과 카메라 목록 파일 |
| `connection_probe.py` | 실제 재생과 분리된 연결 확인 자식 프로세스 |
| `startup_shortcuts.py`, `windows_shortcuts.py` | 첫 실행 안내와 Windows 바로가기·고정 요청 |
| `startup_window.py`, `startup_timing.py` | 재생 엔진의 비동기 초기화·시작 창·첫 화면 표시 시간 기록 |

### 시작 지연 확인

`check.bat startup`은 모듈 지연 로딩, 느린 엔진 초기화 중 UI 응답·종료·최소화·오류 처리와 시간 기록을 검사합니다. 실제 카메라에 연결하지 않습니다.

일반 실행의 `%LOCALAPPDATA%/CamFloat/diagnostics/startup.json`에는 Python 런타임 훅 이후 각 단계까지 걸린 밀리초만 기록합니다. `CAMFLOAT_DATA_DIR`을 지정하면 해당 폴더를 사용합니다. `startup_window_painted`는 시작 안내 표시, `engine_ready`는 재생 엔진 준비, `first_paint`는 실제 플레이어 창 그리기입니다. 프로세스 생성부터 Python 런타임 훅 이전의 지연은 포함하지 않습니다. 영상 연결 시간과도 다릅니다.

재생 엔진은 네이티브 DLL 로딩 중 안전하게 강제 중단할 수 없습니다. 초기화 중 종료하면 창은 닫히고, 진행 중 초기화가 반환한 뒤 엔진을 해제하며 끝납니다. 취소 후에는 플레이어나 카메라 연결을 만들지 않습니다.

영상 출력은 QWidget의 네이티브 창과 libVLC를 사용합니다. 재생 중 창 플래그 변경이나 부모 변경으로 영상 핸들을 다시 만들지 않도록 합니다. 화면 확대는 배치만 바꾸며 다른 화면의 연결·소리를 유지합니다.

관리창은 초안을 편집하고 최종 저장에 성공한 경우에만 플레이어에 반영합니다. 주소·아이디는 기본 가림, 비밀번호·RTSP 주소의 보기·복사는 필수 본인 확인 정책을 사용합니다. 형식·인증·저장 실패를 알릴 때 입력한 비밀을 오류 메시지에 넣지 않습니다. 사용자가 입력한 제어 포트는 목록 내보내기에 포함하며 자동 조회한 제어 경로·프로필은 제외합니다.

## 검사

일반 수정은 관련 기능만 확인하고, 전체 QC는 릴리즈 직전에 실행합니다. 문서만 바꾸면 문서·링크·민감 정보·diff를 확인하고 앱 전체 검사나 빌드를 반복하지 않습니다.

### 기능별 검사

기본 명령은 약 2초의 간단 검사입니다. 기본값·암호화 저장·등록 입력·목록 파일·버전 일치·빈 플레이어 시작/종료와 검사 선택 동작을 확인합니다.

```powershell
.\check.bat
# 사용 가능한 검사 목록:
.\check.bat --list
```

| 변경 영역 | 명령 |
| --- | --- |
| 기본 간단 검사 | `check.bat` 또는 `check.bat quick` |
| 화면별 소리 | `check.bat audio` |
| 등록·카메라 관리 | `check.bat cameras` |
| 목록 파일 | `check.bat files` |
| 분할·전체화면·도구 | `check.bat window` |
| 첫 실행·바로가기 | `check.bat shortcuts` |
| 방향 패널·작업 취소·카메라 대상·회전 프로토콜 (가상 기기로 검사) | `check.bat ptz` |
| 스피커 시험 도구·시간 설정 (가상 기기로 검사) | `check.bat talkback` |
| Android APK 조사 도구 (가상 ADB로 검사) | `check.bat android` |

여러 영역은 `check.bat files shortcuts`처럼 함께 지정합니다. 중복 영역은 한 번만 실행합니다. 전체 검사는 `full`을 명시할 때만 실행하며 다른 영역과 섞을 수 없습니다.

검사에는 임시 설정 폴더와 합성 카메라·영상을 사용합니다. 실제 사용자 설정이나 카메라에 접속하지 않습니다. 결과와 로그는 `verification/current/checks/<영역>/latest.json`, `latest.log`에 덮어써 기록합니다. 실행 범위·개수·시간·생략 범위를 확인할 수 있습니다. 개별 테스트 모듈은 기존 unittest 명령으로도 실행할 수 있습니다.

별도의 실제 카메라 회전 시험은 `camera-control-test.bat`입니다. 일반 검사 명령에 포함되지 않으며 사용자가 대상을 선택하고 이동을 요청할 때만 조작합니다. Enter/R은 좌우·U/D는 상하 시험입니다. `--delay 10`으로 이동 전 대기 시간을 지정할 수 있고(0~300초, 기본 3초), `--probe`는 기능 조회만 수행합니다. 사용자 수동 시험에서 상하좌우 이동과 멈춤을 확인했습니다. 기기 반전 설정에 따라 방향이 달라질 수 있고, 명시적 정지와 기기 시간 제한의 효과는 아직 분리 검증하지 않았습니다. [지원 조사와 시험 방법](post-release-plan.md#후속-onvif-조사와-시험-도구)을 먼저 확인하세요.

연속 이동 조사는 두 모드로 구분합니다. `camera-control-test.bat --continuous`는 기기 시간 제한 0.25초·1초·2초를 비교합니다. `camera-control-test.bat --compat`는 시간 제한·줌 항목을 생략한 최소 요청, 최소 `Stop`, 속도 0 정지, 좌표계 명시를 비교합니다. 후자는 이동 명령을 한 번 보내고 별도 스레드가 1초 뒤 정지를 요청합니다. 기기 시간 제한이 없으므로 렌즈를 직접 보며 시험하고, 멈추지 않으면 제조사 앱에서 멈춰야 합니다. `X`로 관찰 결과를 기록하면 추가 시험을 중단합니다. `1/2/3`은 방식 선택, `L/R/U/D`는 한 번 이동, `Q`는 종료입니다. 앱의 방향 패널에는 이 실험을 적용하지 않습니다. 기록은 로컬 `verification/current/camera-control/compat-manual-latest.json`에 보관합니다.

현재 개발본은 첫 클릭을 즉시 전송하고 이후 클릭을 최대 5개 대기시켜 600ms마다 처리합니다. 길게 누르기는 기존 대기열을 먼저 처리한 뒤 600ms마다 반복하며, 손을 떼면 반복만 중단하고 이미 접수한 수동 클릭은 계속 처리합니다. 방향 변경·패널 닫기·앱 전환은 남은 요청을 취소합니다. 지연된 타이머를 몰아서 실행하지 않습니다. 통신·전체 요청 제한은 1000ms, 진행 중 자원 상한은 4개이며 응답 내용으로 버튼 상태·제어 정보·다음 이동을 변경하지 않습니다. 전송 실패를 자동 재시도하지 않습니다.

앱 실행 후 첫 카메라 관리 진입에서 사용 중인 카메라의 제어 정보를 별도 컨트롤러로 조회합니다. 같은 실행 중 지원으로 확인된 카메라는 재사용하고 미확인·알 수 없음인 항목만 다음 진입에서 재조회합니다. 이 확인 이력은 저장하지 않아 재실행 후 첫 관리창에서 다시 조회합니다. 외부 IPv4와 DDNS도 허용하며, 등록한 호스트로만 접속합니다. 고급 설정의 `control_port`는 기본 5000이며 포트포워딩 환경에서는 외부 제어 포트를 지정합니다. 조회 응답이 내부 주소를 광고하더라도 그 주소로 접속하지 않고 경로만 검증해 사용합니다. 지정한 포트가 있으면 기기가 광고한 포트로 덮어쓰지 않습니다. 관련 없는 외부 호스트·자격증명·잘못된 경로를 담은 광고는 거부합니다. 미조회·조회 중·지원 정보 확인·불확실·앱 범위 밖을 구분하며, 실패 시 기존 경로를 유지하되 이번 조회 결과는 알 수 없음으로 표시합니다. 자동 조회 결과는 설정 안의 암호화된 제어 정보에 보관하고 목록 내보내기에서는 제외합니다. 직접 입력한 방향 조작 포트는 목록 내보내기·불러오기에 포함합니다. 백그라운드 조회만으로 편집 초안이 변경된 것으로 처리하거나 선택·정보 공개 상태를 초기화하지 않습니다.

입력 기록은 `%LOCALAPPDATA%/CamFloat/diagnostics/direction-timing.json`에 저장합니다. `CAMFLOAT_DATA_DIR`이 있으면 그 폴더를 사용합니다. `.venv/Scripts/python.exe -B -X utf8 tools/direction_timing.py`로 간격·응답 시간·해제 뒤 쓰기 시작 건수를 확인합니다. 해제 뒤 길게 누르기 쓰기와 접수한 클릭 대기열 처리를 구분합니다. 숫자 실패 단계는 연결 1·송신 순서 대기 2·최종 취소 검사 3·요청 쓰기 4·응답 헤더 5·응답 본문 6·SOAP 해석 7입니다. 최대 1,500개 사건만 보존하며 주소·계정·이름·원문 응답은 기록하지 않습니다.

스피커 시험은 `camera-speaker-test.bat`입니다. 카메라 선택 후 대기·전송 시간을 입력하거나 `--delay 20 --duration 5`로 지정할 수 있습니다. 마이크·실제 녹음 파일 대신 작은 합성음을 사용합니다. `--probe`는 열기·닫기만 요청합니다. 일반 검사와 실제 카메라 청취 시험을 구분하며 [말하기 조사](post-release-plan.md#말하기-전송-경로-조사)를 참고하세요.

Android 제조사 앱 조사 도구는 `android-app-check.bat`입니다. 공식 [Platform-Tools](https://developer.android.com/tools/releases/platform-tools)의 ADB·DLL을 `%LOCALAPPDATA%/CamFloatQA/android/platform-tools`에 준비하고, 휴대폰에서 USB 디버깅·PC 연결을 허용해야 합니다. 도구는 USB 기기 하나만 대상으로 `com.cctv.iptime` APK만 읽습니다. APK와 결과는 `verification/current/android-app`에 보관하고 실행·배포하지 않습니다. `check.bat android`는 가상 ADB와 합성 APK만 사용합니다.

APK 분석 상한은 파일당 512 MiB·ZIP 항목 30,000개·전체 원본 크기 768 MiB입니다. 개별 DEX·라이브러리는 64 MiB까지만 읽습니다. 실제 USB 기기에서 약 339 MiB APK 수집을 확인했으며, SDK 표식은 기기 호환성의 확정 판정에 사용하지 않습니다. 수집 이후에는 휴대폰을 분리해도 로컬 파일로 분석을 계속할 수 있습니다.

후속 네이티브 분석은 로컬 `%LOCALAPPDATA%/CamFloatQA/android/analysis-libs`의 pyelftools 0.33·Capstone 5.0.9로 수행했습니다. 제조사 ARM64 라이브러리를 데이터로 읽어 함수·호출 관계만 추적하며 해당 라이브러리를 로드하거나 실행하지 않습니다. 이 분석 패키지는 앱 의존성이나 배포 파일에 추가하지 않았습니다.

### 릴리즈 전체 검사

```powershell
.\check.bat full
```

`full`은 단위·회귀 검사 전체입니다. 네트워크 통합 검사와 최종 배포 EXE 점검은 아래 절차로 별도 실행합니다.

네트워크 통합 검사는 `tests/network_qa.py`입니다. 다음 자료를 로컬에 준비해야 합니다.

- 공식 MediaMTX 1.21.2 Windows amd64 실행 파일: `%LOCALAPPDATA%/CamFloatQA/mediamtx-1.21.2/mediamtx.exe`
- PATH에서 실행 가능한 FFmpeg
- `CAMFLOAT_QA_VIDEO`로 지정한 합성 영상. 소리 상태까지 검사하려면 음성 트랙을 넣고 `CAMFLOAT_QA_AUDIO=1`을 지정합니다.

네트워크 검사는 배포와 같은 엔진을 쓰도록 `VLC_HOME`을 `vendor/vlc`로 지정하고 `127.0.0.1:18554`에서 실행합니다. 재생·중단·복구·실제 영상 픽셀 갱신과 엔진 음량·음소거 값을 확인하며 결과는 `verification/current/network-qa.json`에 기록합니다.

```powershell
$env:VLC_HOME = Join-Path $PWD 'vendor/vlc'
.\.venv\Scripts\python.exe tests/network_qa.py
```

최종 ZIP을 별도 폴더에 풀고 다음 명령으로 배포 EXE를 점검합니다.

```powershell
.\CamFloat.exe --self-check --demo-video "합성-영상.mp4"
```

실제 사용자 설정과 분리된 점검 프로필을 사용합니다. 실제 카메라·마이크는 자동 검사에 사용하지 않습니다. 물리적 소리 청취·Windows Hello 입력·작업 표시줄 고정 승인처럼 자동 검사에서 확인하지 않은 범위는 따로 기록합니다.

## 설정과 보안

- 설정: `%LOCALAPPDATA%/CamFloat/settings.json`. 카메라 이름·연결 정보를 Windows DPAPI로 암호화합니다.
- 진단: `%LOCALAPPDATA%/CamFloat/diagnostics`. 크기를 제한한 재생 통계를 기록하며 주소·계정·카메라 이름·영상은 기록하지 않습니다.
- 목록 파일: [`.camfloat` 형식](camera-file-format.md). 공통 형식 키는 사용자 비밀키가 아니며 호환성을 위해 임의로 교체하지 않습니다.
- `.venv`, `vendor`, `release`, `verification`, 사용자 설정·내보내기 파일·검사 미디어는 Git에서 제외합니다.

정보 보호 범위와 제보 방법은 [보안 안내](../SECURITY.md)를 참고하세요.

## 버전과 릴리즈

| 단계 | 예시 |
| --- | --- |
| 정식 공개 | `1.0.0` |
| 다음 버전 개발 | `1.1.1-dev.1` |
| 공개 직전 후보 | `1.1.0-rc.1` |

같은 단계의 수정은 뒤 번호를 올립니다. 공개할 때는 접미사를 제거하고 `main.py`·`version_info.txt`·태그·배포 파일을 맞춥니다. 공개일은 `CHANGELOG.md`에서만 관리합니다.

1. 기능별 확인을 마치고 전체 QC와 최종 압축 해제 EXE를 검사합니다.
2. 소스·Git 이력의 민감 정보와 외부 라이브러리 고지·소스를 확인합니다.
3. Release 초안에 ZIP·체크섬·외부 소스 자료와 간단한 설명을 준비합니다.
4. 태그·소스·배포 파일의 대응 관계를 기록하고 검토 후 공개합니다. 공개된 정식 태그·배포 파일은 임의로 바꾸지 않고 다음 버전으로 수정합니다.
5. 저장소를 공개로 전환한 직후 **Private vulnerability reporting**을 켜고, **Security → Report a vulnerability** 경로가 열리는지 확인한 다음 릴리즈를 공개합니다.

공개 파일 검사는 아래 명령으로 실행합니다.

```powershell
.\.venv\Scripts\python.exe tools/publication_check.py
# 로컬 배포 ZIP과 외부 소스 자료까지 확인:
.\.venv\Scripts\python.exe tools/publication_check.py --assets
```

접속 주소·토큰 패턴·개인 경로·문서 링크를 확인합니다. 모든 비밀 정보 탐지를 보장하는 검사는 아니며 앱 재생 검사와 별개입니다.

문서만 변경해 실행 파일을 다시 만들지 않았다면 문서 커밋과 기존 실행 코드의 커밋을 구분해 기록합니다. 현재 후보의 결과는 [검토·검사 요약](../CODE_REVIEW.md), 남은 기능 검토는 [후속 개발 계획](post-release-plan.md)에 정리했습니다.
