# Windows 일반 실행 오류 수정

수정일: 2026-11-14 (한국 시간).

## 원인

사용자 실행에서는 TraCI가 포트를 바꿔 재시도했지만 SUMO 프로세스가 이미 종료되어 있었다. 포트 충돌로 판단하지 않고, Codex 도구의 PATH와 실제 Explorer/일반 콘솔 PATH를 분리해서 비교했다.

- Codex PATH: `sumo-gui --version` 종료 코드 0.
- 레지스트리에서 재구성한 일반 Windows PATH: 종료 코드 `0xC0000135`, stdout/stderr 없음.
- node DLL 경로만 추가: 같은 실패.
- 기존 런타임의 `vcomp140.dll`만 테스트 폴더에 두고 PATH에 추가: 종료 코드 0.
- SUMO 패키지의 `gdal.dll`에서 `vcomp140.dll` 의존성 확인.

따라서 이 PC에서는 Microsoft OpenMP DLL을 찾지 못해 SUMO가 TraCI 서버를 열기 전에 종료되는 것이 직접 원인이었다. 학습 모델의 상태·행동·보상 계산과는 별도 실행 환경 문제다.

## 변경

1. `start.py`: 설치된 기존 런타임에서 VC++ DLL 경로를 찾아 **자식 SUMO도 상속하는 프로세스 PATH**에 추가. Python의 `add_dll_directory`도 유지한다.
2. `runtime_check.py`: SUMO `--version`을 먼저 실행해 실제 종료 코드·stderr·DLL 경로를 `results/runtime-check.json`에 기록. 실패하면 포트 재시도 전에 중단한다.
3. `RUN_HERE.ps1`: 모든 모드를 `start.py`를 통해 실행. View는 사전 검사를 수행한다.
4. `START_VIEW.cmd`, `START_SIMULATION.cmd`: ASCII·CRLF 형식의 짧은 실행기로 통일. 숫자 선택과 안내는 `VIEW_SIMULATION.ps1`에서 처리한다. 실행 중인 예전 CMD는 닫고 새 파일을 연다.

단일 교차로 환경, 학습 코드, 보상 정의, 기존 모델 파일 및 연구 코드 해시는 바꾸지 않았다. Windows에서 직접 CLI를 사용할 때는 `python start.py ...`를 권장한다. Linux에서도 같은 명령을 사용할 수 있다.

## 확인

- Codex 전용 PATH를 제거하고 일반 Explorer PATH로 새 CMD를 실행해 중교통량 GUI 평가를 끝까지 검사했다. 실행 기록: `results/desktop-cmd-launch.log`.
- 같은 일반 PATH에서 분석·SUMO 통합 검사 8개 통과: `results/desktop-runtime-tests.log`.
- GUI가 시작되기 전 `Native runtime OK.`가 출력되어 초기 실행 성공 여부를 알 수 있다.
- 기존 파일럿의 실패한 GUI 기록을 성공 기록으로 덮어쓰지 않았다. 재학습하지 않았다.

Codex 준비 런타임이 없는 다른 Windows PC에서는 공식 [Microsoft Visual C++ x64 재배포 패키지 안내](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)를 확인한다. 임의의 DLL 다운로드 사이트는 사용하지 않는다. 이 수정은 설치 프로그램 실행이나 전역 환경 변경 없이 현재 PC의 기존 라이브러리를 사용했다.
