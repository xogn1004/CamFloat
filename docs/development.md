# 개발 안내

## 버전 표기

- 정식 공개: `1.0.0`처럼 접미사 없이 표시합니다.
- 정식 공개 후 다음 버전 개발: `1.0.1-dev.1`처럼 `-dev`를 붙입니다.
- 공개 직전 릴리즈 후보: `1.0.1-rc.1`처럼 `-rc`를 붙입니다.
- 같은 단계의 수정은 뒤 번호를 올립니다. 정식 공개 전에는 접미사를 제거하고 소스·EXE·ZIP·태그를 맞춥니다.
- 아직 공개하지 않은 최초 `1.0.0`의 잔여 수정은 이번 배포에 반영합니다.

## 환경과 빌드

Windows x64, Python 3.14가 필요합니다. PySide6 6.12와 python-vlc를 사용합니다.

```powershell
git clone https://github.com/xogn1004/CamFloat.git
cd CamFloat
.\build.bat
```

`build.bat`은 가상 환경 생성, 고정한 의존성 설치, 공식 LGPL libVLC 패키지 다운로드·SHA-256 확인, 아이콘 생성과 PyInstaller 빌드를 수행합니다.
결과는 `release/CamFloat/`에 생성됩니다. VLC 별도 설치는 필요하지 않습니다.

앱을 실행 중이라면 `build.bat --staged`로 별도 빌드합니다. 결과는 `%LOCALAPPDATA%/CamFloatBuild/current/dist/CamFloat`입니다.

```powershell
.venv/Scripts/python.exe package_release.py --archive
# 별도 빌드 결과로 ZIP을 만들려면:
.venv/Scripts/python.exe package_release.py --staged --archive
```

ZIP에는 EXE, 런타임, 라이선스, 시작 안내만 들어갑니다. 사용자 설정과 개발 문서는 포함하지 않습니다.
`release/`는 최신 `CamFloat/` 실행 폴더·ZIP·체크섬만 보관하는 것을 원칙으로 합니다. GitHub 배포에 따로 첨부할 외부 라이브러리 소스 자료는 `vendor/source-assets/`에 보관합니다.
Qt의 PDF·QML·가상 키보드 등 사용하지 않는 부품은 제외합니다. 앱은 QWidget과 libVLC의 네이티브 영상 출력을 사용합니다.

## 검사 원칙

**일반 수정은 관련 기능만 짧게 확인하고, 전체 QC는 릴리즈 직전에 실행합니다.** 문서만 바꾸면 앱을 다시 빌드하거나 전체 검사를 실행하지 않습니다.

```powershell
# 음성 관련 집중 검사 (약 5~6초)
.venv/Scripts/python.exe -m unittest discover -s tests -p test_audio_isolation.py -v

# 최종 릴리즈 전체 회귀 검사
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" -v
```

네트워크 검사는 `tests/network_qa.py`입니다. 로컬 MediaMTX·FFmpeg와 합성 검사 영상이 필요합니다.
`CAMFLOAT_QA_VIDEO`에 영상 경로, 음성까지 확인할 때 `CAMFLOAT_QA_AUDIO=1`을 지정합니다.
배포 EXE는 `CamFloat.exe --self-check --demo-video <합성 로컬 영상>`으로 별도 프로필에서 점검할 수 있습니다.

실제 카메라나 마이크는 자동 검사에 사용하지 않습니다. 테스트에는 `127.0.0.1` 등 합성 주소와 합성 미디어만 사용해주세요.
물리적 소리 청취·Windows Hello 입력 등 자동 검사에 포함되지 않은 범위는 결과에 따로 표시합니다.

## 설정과 보안

- 설정: `%LOCALAPPDATA%/CamFloat/settings.json`. Windows DPAPI로 연결 정보를 암호화합니다.
- 진단: `%LOCALAPPDATA%/CamFloat/diagnostics`. 주소·계정·카메라 이름·영상은 기록하지 않습니다.
- `.camfloat`는 다른 PC에서도 여는 공유 파일이며, 공통 형식 키는 사용자 비밀키가 아닙니다. 호환성을 위해 임의로 교체하지 않습니다.
- `.venv`, `vendor`, `release`, `verification`, 설정·카메라 내보내기 파일·테스트 미디어는 Git에서 제외합니다.

## 공개 릴리즈

1. 코드 변경은 기능별 확인을 먼저 마치고 릴리즈 직전에 전체 QC를 수행합니다.
2. 소스와 Git 이력의 민감 정보, 외부 라이브러리의 라이선스·소스 제공을 확인합니다.
3. 최종 ZIP을 별도 폴더에 풀어 번들 엔진·실제 재생·음성 분리를 점검하고 SHA-256을 확인합니다.
4. 소스 태그, EXE 원본과 ZIP의 대응 관계를 기록합니다. 문서/포장만 바꾸면 재생 코드의 기존 검사 기록과 새 포장 검사 결과를 구분합니다.
5. GitHub Release 초안에 ZIP·체크섬·외부 라이브러리 소스와 고지를 첨부하고 검토 후 공개합니다.

공개 파일 확인은 `python tools/publication_check.py`로 실행합니다. Git 이력의 접속 주소·토큰 패턴·개인 경로와 문서 링크를 확인합니다. `--assets`를 붙이면 준비된 ZIP·체크섬·외부 소스 자료도 확인합니다. 이 검사는 모든 형태의 비밀 정보 탐지를 보장하지 않으며, 앱 재생 검사와 별개입니다.

공개일은 `CHANGELOG.md`에서만 관리합니다. 버전은 `version_info.txt`와 `main.py`를 함께 확인합니다.
과거 검사 기록은 [CODE_REVIEW.md](../CODE_REVIEW.md), 후속 계획은 [post-release-plan.md](post-release-plan.md) 참고.
