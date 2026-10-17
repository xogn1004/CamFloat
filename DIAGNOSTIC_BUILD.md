# 연결 당시 화면에서 멈추는 카메라 진단

## 확인된 사실

- 사용자는 특정 카메라에서 연결 당시 시각이 표시된 영상이 이후 갱신되지 않는다고 보고했습니다.
- 그 카메라만 1분할로 재생해도 발생하며 ipTIME 앱에서는 정상입니다.
- 0.5 원본 커밋 재빌드에서도 발생했습니다. 최근 UI 변경만으로 원인을 설명할 수 없습니다.
- 현재 설치된 VLC는 3.0.23, GPU는 RTX 3070입니다. 실행 중인 기존 앱에는 Direct3D11 출력 모듈이 로드되어 있었습니다. 이것이 오류를 증명하지는 않습니다.

## 실행 파일

먼저 기존 CamFloat를 종료합니다. 같은 설정에 대한 단일 실행 규칙을 유지하므로 실행 중이면 기존 창이 활성화되고 새 모드는 시작되지 않습니다.

| 파일 | 변경점 |
| --- | --- |
| CamFloat.exe | 기존 재생 경로 + 통계 기록 |
| CamFloat-CPU.exe | CPU 디코딩 + WinGDI 출력. 시각 처리와 네트워크 버퍼는 기존 설정 유지 |
| CamFloat-Clock.exe | 기존 디코딩·출력 유지. clock-jitter=0, clock-synchro=0 적용 |

CPU → 종료 → 시각 보정 순서로 문제 카메라를 비교할 수 있습니다. 호환 모드는 EXE 이름 또는 `--playback-profile=cpu`, `--playback-profile=clock`으로 선택합니다. 설정 파일의 하드웨어 가속 선택을 덮어쓰지 않습니다. CPU 모드에서만 가속 스위치를 비활성화합니다.

시각 보정은 원인을 구분하기 위한 선택지이며 모든 카메라에 권장하는 기본값이 아닙니다. 음성 동기화나 지연 특성이 달라질 수 있습니다.

## 진단 기록

`%LOCALAPPDATA%\CamFloat\diagnostics\playback-auto.jsonl`, `playback-cpu.jsonl`, `playback-clock.jsonl`에 2초마다 기록합니다. 프로필별 2MB, 이전 로그 2개로 제한합니다. CAMFLOAT_DATA_DIR을 별도로 지정한 경우 해당 폴더의 diagnostics 하위에 기록합니다.

- SCREEN 번호, 카메라 번호, HD/SD, 재연결 회차와 수명주기 단계
- VLC 상태, 미디어 시각, 입력·demux 바이트, 손상·불연속 수
- 비디오·오디오 디코딩 수, 표시·손실 프레임 수, 재생 오디오 버퍼 수
- 카메라 이름, IP, 주소, 계정, 비밀번호, 영상은 기록하지 않습니다.

수신 증가와 디코딩·출력 증가 여부를 함께 비교해야 합니다. 출력 카운터는 영상 내용이 실제로 바뀌는지 보장하지 않으며 바이트 수만으로 비디오 패킷 수신을 확정할 수 없습니다. 카메라 시각이 멈췄는데 출력 카운터가 계속 증가한다면 같은 이미지가 반복 전송되는 경우까지 검토해야 합니다.

## 범위와 근거

실제 문제 카메라의 수신 기록이 아직 없어 해결됐다고 판정하지 않았습니다. 이번 빌드는 원인 구분용이며 상단바 잔상 수정은 포함하지 않습니다. 0.5 복원 폴더와 기존 release/CamFloat 배포본은 보존합니다. 앱 자동 검사와 사용자 카메라 접속은 수행하지 않았습니다.

- VideoLAN Windows FAQ: https://docs.videolan.me/vlc-user/en/support/faq/faqwindows.html
- WinGDI 출력: https://github.com/videolan/vlc/blob/3.0.x/modules/video_output/win32/wingdi.c
- clock 옵션: https://github.com/videolan/vlc/blob/3.0.x/src/libvlc-module.c
- 통계 정의: https://github.com/videolan/vlc/blob/3.0.x/include/vlc/libvlc_media.h
