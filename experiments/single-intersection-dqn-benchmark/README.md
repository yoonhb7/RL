# 단일 교차로 DQN · 보상 · 혼잡도 공통 실험

현재 기준은 **Pálos & Huszák, SoftCOM 2020, Comparison of Q-Learning based Traffic Light Control Methods and Objective Functions**다. 이 폴더의 이전 IntelliLight/Vidali 검토 문서는 문헌 조사 기록이다. 현재 실행 명세는 이 README와 `configs/shared.json`, `METHOD_AND_REWARDS_KO.md`를 따른다.

## 2026-11-14 Windows 실행 오류 수정

일반 더블클릭 환경에서 SUMO의 GDAL 의존성이 `vcomp140.dll`을 못 찾아 종료되는 것을 재현했다. `start.py`가 이 PC의 기존 VC++ 런타임 경로를 현재 프로세스와 SUMO 자식 프로세스에만 연결한다. 시스템 PATH/레지스트리는 바꾸지 않는다. `RUN_HERE.ps1`은 이 실행기를 사용하고 GUI 시작 전에 `--version` 사전 검사를 한다.

**기존 실행 창을 닫고 `START_VIEW.cmd`를 새로 열어 1/2/3을 선택한다.** CMD는 ASCII+CRLF로 저장했고 안내·선택은 PowerShell에서 처리한다. `START_SIMULATION.cmd`도 같은 실행기로 연결된다. 자세한 원인과 검증은 [실행 오류 수정 기록](STARTUP_FIX_KO.md)을 참고한다.

## 지금 실행할 수 있는 것

- `START_VIEW.cmd` 또는 `START_SIMULATION.cmd`: 1=저, 2=중, 3=고를 골라 **학습된 Double DQN**의 SUMO GUI를 본다. `results/demo-models/` 모델이 없으면 콘솔에 고정 신호임을 표시하고 기준선을 보여준다.
- `START_TRAINING.cmd`: 3알고리즘 × 3교통량, WTMin 보상, 모델별 6에피소드의 짧은 파일럿. 완료된 작업은 건너뛴다.
- `results/pilot-report/index.html`: 파일럿 결과표와 그래프. **알고리즘 우열을 결론 내리는 본 실험 결과가 아니다.**
- `configs/team-plan.json`: 본 실험 162회 학습·810회 평가 작업표. A/B/C가 동일한 코드와 작업표로 분담한다.

`START_SIMULATION.cmd`에서 숫자를 고른 뒤에는 콘솔에 추가 입력하지 않는다. SUMO 창이 자동 실행되며 이미 학습된 모델이 신호를 제어한다. 창이 가려졌다면 Alt+Tab/작업표시줄에서 SUMO를 선택한다. 실행 중에는 콘솔이 조용하며 종료 후 결과가 출력된다. **이 버튼은 재학습하지 않는다.** 학습은 `START_TRAINING.cmd` 또는 Team 명령으로 실행한다.

공유 ZIP에는 코드·설정·데모 체크포인트·요약 보고서가 포함된다. 용량을 줄이기 위해 모든 학습 에피소드 원본과 논문 PDF는 포함하지 않는다. 이 PC의 원본 실행 기록은 `VERIFIED_RUNS_KO.md`에 연결했다. ZIP을 받은 사람은 `SHOW_RESULTS.cmd`로 포함된 결과를 확인하고, 새 실험의 원본은 본인 결과 폴더에 생성한다.

도로·신호·차량 생성·관측·학습·지표 코드는 공통이고 **혼잡도·알고리즘·보상·시드만 설정으로 변경**한다. 특정 보상의 전용 환경을 따로 만들지 않는다.

## Windows에서 실행

이 폴더에서 PowerShell을 연다. 현재 PC는 준비된 런타임을 자동 사용한다.

```powershell
# 설치·DLL·SUMO 확인
powershell -ExecutionPolicy Bypass -File .\RUN_HERE.ps1 -Mode Doctor

# GUI로 확인: 저 / 중 / 고 (fixed 기준선)
powershell -ExecutionPolicy Bypass -File .\RUN_HERE.ps1 -Mode View -Level low
powershell -ExecutionPolicy Bypass -File .\RUN_HERE.ps1 -Mode View -Level medium
powershell -ExecutionPolicy Bypass -File .\RUN_HERE.ps1 -Mode View -Level high

# 학습 모델 GUI: 모델과 학습 시 사용한 설정을 함께 지정
powershell -ExecutionPolicy Bypass -File .\RUN_HERE.ps1 -Mode View -Level high -ConfigPath configs/pilot.json -ModelPath results/demo-models/high/model.pt

# 한 조건 학습: 아래 명령은 100에피소드의 본 설정이다
powershell -ExecutionPolicy Bypass -File .\RUN_HERE.ps1 -Mode Train -Level medium -Algorithm double -Reward wtmin -Episodes 100 -OutputPath results/my-medium-double

# 같은 학습 모델을 저·중·고에서 모두 평가: 일반화 평가
powershell -ExecutionPolicy Bypass -File .\RUN_HERE.ps1 -Mode Evaluate -ModelPath results/my-medium-double/model.pt

# 고정/대기열 기준선으로 수요 단계 확인
powershell -ExecutionPolicy Bypass -File .\RUN_HERE.ps1 -Mode Calibrate
```

SUMO 창은 네트워크 XML만 연 것이 아니라 Python이 차량 경로를 불러오고 신호를 제어하는 실행이다. View는 자동 재생하며, 교차로 주변 확대 화면을 표시한다. 기본 70ms/초 지연으로 실제 관찰이 가능하다. 180초 부근의 실제 차량 좌표·현시로 `simulation.svg`를 저장하고, 종료 시 같은 장면의 PNG 미리보기도 만든다. GUI 픽셀 캡처와 구분한다. GUI를 중간에 닫으면 연결 종료 오류가 날 수 있으므로 콘솔 `Ctrl+C`로 중단한다.

현재는 **자동차 차체·창문·바퀴, 큰 3색 신호등, 건물·보도·주차장·공원**이 있는 도시형 화면이다. 차량 도형은 실제 SUMO 차량을 따라 움직이고 신호등은 실제 현시를 표시한다. 청록색 검지 영역은 화면에서 가리고 실제 검지는 유지했다. [화면 개선·검증 기록](CITY_VIEW_KO.md)을 참고한다. 마우스 휠로 확대·축소할 수 있다.

## 다른 컴퓨터 / Linux / RTX 서버

Python 3.10~3.13을 권장한다. 가상환경에서 의존성을 설치하고 doctor부터 실행한다.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python start.py doctor
.venv\Scripts\python start.py build
```

Linux는 `.venv/bin/python`을 사용한다. 로컬 작업 경로는 코드에 고정하지 않았다. `eclipse-sumo` 대신 시스템 SUMO를 사용할 때는 **SUMO 1.28.0**, 같은 `traci/sumolib`, `SUMO_HOME`을 맞춘다. GUI의 디스플레이 의존성은 운영체제별로 준비한다. 서버 학습에는 GUI가 필요 없다.

`device: auto`가 CUDA 사용 가능 여부를 확인한다. RTX 5080의 PyTorch/CUDA 설치는 해당 컴퓨터에서 공식 PyTorch 안내와 실제 장치 지원을 확인해서 구성한다. CUDA가 없어도 CPU로 실행된다. 실제 장치·torch·SUMO 버전은 결과에 기록된다. CPU/GPU 간 비트 단위 동일 결과를 보장하지 않으므로 최종 논문에 장치 차이를 기록한다.

의존성 범위는 설치 호환성을 위한 것이다. 실험 참가자들은 한 번 설치한 후 버전을 고정해 공유하고 실험 도중 업데이트하지 않는다. 현재 검증 런타임의 버전은 `VERIFIED_RUNS_KO.md`를 참고한다.

## 혼잡도 조절

`configs/shared.json`의 `scenario.loads_vph`는 **4개 방향 합계 요청 차량/시간**이다.

| 수준 | 합계 차량/시간 | 균형 수요에서 방향별 기대값 |
|---|---:|---:|
| low | 450 | 112.5 |
| medium | 1500 | 375 |
| high | 3000 | 750 |

실제 발생 대수는 무작위 표본이라 기대값과 다르다. `requested_vph`, `realized_vph`, `scheduled`를 함께 기록한다. 저·중·고는 관측 후 이름만 바꾸는 방식이 아니라 **사전 고정한 수요 조건**이다. 본 설정은 900초 발생+300초 정리, 파일럿은 600초 발생+180초 정리다. 고수요에서 완료율이 100%가 되지 않아도 잔여를 숨기지 않고 기록한다.

수요를 더 바꾸려면 설정 파일을 복사한 뒤 `loads_vph`를 수정하고 **새 작업표를 생성**한다. 설정 파일은 세 명이 같은 버전으로 공유한다.

```powershell
python start.py --config configs/my-demand.json plan --out configs/my-plan.json
python start.py --config configs/my-demand.json calibrate --out results/my-calibration
```

이미 학습한 모델의 시각화/평가에서만 한 수준을 임시 조절할 수도 있다.

```powershell
python start.py view --model results/my-medium-double/model.pt --levels high --vph 3600 --seeds 1001 --out results/high-3600-view
```

이는 훈련 조건 변경이 아니라 해당 수요로의 일반화 평가다. 같은 물리 환경의 모델만 허용하며, 도로·관측·신호 규칙이 다르면 체크포인트 로드를 거부한다.

## 세 명 분담

세 명 모두 같은 프로젝트·`shared.json`·`team-plan.json`을 복사한다. **각자 환경 코드를 수정하지 않는다.**

```powershell
# A: low, 3알고리즘 × 6보상 × 학습시드3 = 54모델
powershell -ExecutionPolicy Bypass -File .\RUN_HERE.ps1 -Mode Team -Owner A

# B: medium, 54모델
powershell -ExecutionPolicy Bypass -File .\RUN_HERE.ps1 -Mode Team -Owner B

# C: high, 54모델
powershell -ExecutionPolicy Bypass -File .\RUN_HERE.ps1 -Mode Team -Owner C
```

본 실험은 각 혼잡도에서 **독립 학습 후 같은 혼잡도의 미사용 차량 시드 5개로 평가**한다. 혼합 수요로 학습한 하나의 모델을 3수준에서 시험하는 실험과 구분한다. 선택 사항인 D3QN도 구현했으며 작업표에 `--algorithms dqn double dueling d3qn`을 지정하면 포함된다.

한 번에 162모델을 돌리기 전에 소규모 확인용 작업표를 만들 수 있다.

```powershell
python start.py --config configs/pilot.json plan --algorithms dqn double dueling --rewards wtmin --seeds 11 --out configs/small-plan.json
python start.py batch --plan configs/small-plan.json --out results/small-batch
```

작업 완료 후 `results/team-A`, `team-B`, `team-C` 폴더를 같은 컴퓨터에 모은다.

```powershell
python start.py report --roots results/team-A results/team-B results/team-C --out results/team-report
```

`runs.csv`는 개별 평가, `summary.csv`는 차량 시드 평균 후 학습 시드별 평균·표준편차다. 학습 시드 1개면 표준편차를 0으로 꾸미지 않고 빈칸으로 둔다. 서로 다른 코드·설정·SUMO·네트워크 또는 같은 평가 조건의 다른 차량 파일은 합치지 않는다. 모든 계획 작업이 끝났는지는 각 `complete.json` 수를 작업표와 대조한다.

## 중단·재실행·저장

- `batch`는 정상 완료 작업의 `complete.json`을 확인하고 건너뛴다.
- 실패·중단 작업은 다음 `attempt-002` 등 새 폴더에서 재시작한다. 이전 시도는 보존하며 replay까지 복원하는 학습 이어하기는 제공하지 않는다.
- 직접 `train`/`evaluate`는 완료 출력을 덮어쓰지 않는다. 새 `--out`을 지정한다.
- **같은 owner/출력 폴더를 두 프로세스에서 동시에 실행하지 않는다.** A/B/C는 기본적으로 다른 결과 폴더를 사용한다.
- 작업표를 만든 후 코드를 바꾸면 실행을 거부한다. 코드 수정 후 새 설정/작업표/결과 경로를 만들어야 한다.
- 준비된 파일럿·본 실험은 별도 프로토콜이므로 한 보고서로 합치지 않는다.

## 코드 위치

- `trafficbench/scenario.py`: 단일 교차로와 재현 가능한 차량 파일
- `trafficbench/env.py`: 13관측, 신호 제어, 미진입·잔여 포함 지표
- `trafficbench/rewards.py`: 6보상 정의
- `trafficbench/agent.py`: DQN / Double / Dueling / D3QN
- `trafficbench/experiment.py`: 학습·평가·분담 작업표
- `trafficbench/report.py`: 팀 결과 통합·CSV·그래프
- `tests/test_benchmark.py`: 수식·체크포인트·SUMO 통합 검사

검사 실행: `python run_tests.py`. 실제 SUMO를 실행하며 차량 삽입 불가·황색 전환·학습 저장 및 재평가까지 확인한다.

추가 아이디어인 최대 대기 보상·보행자·다중 교차로는 이번 기준 구현에 넣지 않았다. 기준 비교가 완료된 뒤 별도 확장 실험으로 다룬다.
