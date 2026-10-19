# 개발 안내

현재 개발 버전은 **1.0.1-dev.1**, 공개 배포본은 **1.0.0**입니다.

## 환경과 빌드

Windows x64와 Python 3.14를 사용합니다. PySide6·python-vlc 등 의존성 버전은 `requirements.txt`에 고정되어 있습니다.

```powershell
git clone https://github.com/xogn1004/CamFloat.git
cd CamFloat
.\build.bat
.\.venv\Scripts\python.exe package_release.py --staged --archive
```

`build.bat`은 가상 환경·의존성 설치, 공식 LGPL libVLC 패키지 다운로드·체크섬 확인, 아이콘 생성과 PyInstaller 빌드를 수행합니다. VLC를 별도로 설치할 필요가 없습니다. 개발·RC 버전은 자동으로 별도 빌드 경로에 보관하며, 정식 버전의 기본 결과는 `release/CamFloat/`입니다.

앱을 실행 중이라면 `build.bat --staged`로 별도 빌드합니다. 결과는 `%LOCALAPPDATA%/CamFloatBuild/current/dist/CamFloat`이며, `package_release.py --staged --archive`로 해당 결과를 압축할 수 있습니다.

- 배포 ZIP에는 EXE·런타임·라이선스·시작 안내만 넣습니다.
- `release/`에는 최신 실행 폴더·ZIP·체크섬만 보관합니다. 외부 라이브러리 소스 자료는 `vendor/source-assets/`에 둡니다.
- 사용하지 않는 Qt PDF·QML·가상 키보드·소프트웨어 OpenGL 부품은 제외합니다. 라이선스와 소스 제공은 [외부 라이브러리 안내](../THIRD_PARTY.md)를 따릅니다.

## 코드 구조

| 파일 | 역할 |
| --- | --- |
| `main.py`, `playback.py` | 화면 배정·확대·전체화면과 비동기 재생 작업 |
| `chrome.py`, `native_window.py` | 상단 도구와 Windows 창·오버레이 처리 |
| `camera_manager.py`, `camera_editor.py`, `camera_draft.py` | 관리 초안·최종 저장과 연결 정보 입력·검증 |
| `privacy.py`, `windows_consent.py` | 항목별 가림·복사·공개 만료와 Windows 본인 확인 |
| `camera_model.py`, `camera_archive.py` | 로컬 설정·암호화 저장과 카메라 목록 파일 |
| `connection_probe.py` | 실제 재생과 분리된 연결 확인 자식 프로세스 |
| `startup_shortcuts.py`, `windows_shortcuts.py` | 첫 실행 안내와 Windows 바로가기·고정 요청 |

영상 출력은 QWidget의 네이티브 창과 libVLC를 사용합니다. 재생 중 창 플래그 변경이나 부모 변경으로 영상 핸들을 다시 만들지 않도록 합니다. 화면 확대는 배치만 바꾸며 다른 화면의 연결·소리를 유지합니다.

관리창은 초안을 편집하고 최종 저장에 성공한 경우에만 플레이어에 반영합니다. 주소·아이디는 기본 가림, 비밀번호·RTSP 주소의 보기·복사는 필수 본인 확인 정책을 사용합니다. 형식·인증·저장 실패를 알릴 때 입력한 비밀을 오류 메시지에 넣지 않습니다.

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
| 수동 회전 시험 도구 (가상 기기로 검사) | `check.bat ptz` |
| 스피커 시험 도구·시간 설정 (가상 기기로 검사) | `check.bat talkback` |
| Android APK 조사 도구 (가상 ADB로 검사) | `check.bat android` |

여러 영역은 `check.bat files shortcuts`처럼 함께 지정합니다. 중복 영역은 한 번만 실행합니다. 전체 검사는 `full`을 명시할 때만 실행하며 다른 영역과 섞을 수 없습니다.

검사에는 임시 설정 폴더와 합성 카메라·영상을 사용합니다. 실제 사용자 설정이나 카메라에 접속하지 않습니다. 결과와 로그는 `verification/current/checks/<영역>/latest.json`, `latest.log`에 덮어써 기록합니다. 실행 범위·개수·시간·생략 범위를 확인할 수 있습니다. 개별 테스트 모듈은 기존 unittest 명령으로도 실행할 수 있습니다.

별도의 실제 카메라 회전 시험은 `camera-control-test.bat`입니다. 일반 검사 명령에 포함되지 않으며 사용자가 대상을 선택하고 이동을 요청할 때만 조작합니다. Enter/R은 좌우·U/D는 상하 시험입니다. `--delay 10`으로 이동 전 대기 시간을 지정할 수 있고(0~300초, 기본 3초), `--probe`는 기능 조회만 수행합니다. 사용자 수동 시험에서 상하좌우 이동과 멈춤을 확인했습니다. 기기 반전 설정에 따라 방향이 달라질 수 있고, 명시적 정지와 기기 시간 제한의 효과는 아직 분리 검증하지 않았습니다. [지원 조사와 시험 방법](post-release-plan.md#후속-onvif-조사와-시험-도구)을 먼저 확인하세요.

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

네트워크 검사는 `127.0.0.1:18554`에서 실행합니다. 재생·중단·복구·실제 영상 픽셀 갱신과 엔진 음량·음소거 값을 확인하며 결과는 `verification/current/network-qa.json`에 기록합니다.

```powershell
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
| 다음 버전 개발 | `1.0.1-dev.1` |
| 공개 직전 후보 | `1.0.1-rc.1` |

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

문서만 변경해 실행 파일을 다시 만들지 않았다면 문서 커밋과 기존 실행 코드의 커밋을 구분해 기록합니다. 최종 1.0.0 결과는 [검토·검사 요약](../CODE_REVIEW.md), 남은 기능 검토는 [후속 개발 계획](post-release-plan.md)에 정리했습니다.
