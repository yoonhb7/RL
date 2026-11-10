# SUMO 실험 실행 안내

이 문서는 `yoonhb7/RL` 저장소를 받은 사람이 **구현 내용을 이해하고, GUI 재생·새 학습·공정한 비교 평가까지 실행**하도록 작성했습니다. 아래 명령은 저장소 최상위에서 실행합니다.

## 1. 지금 만든 실험

사거리 1개 또는 가로로 연결한 사거리 2·3개에 차량을 보내고 신호 운영 방식만 바꿔 비교합니다. 두 교차로 설정 `corridor2`는 다음 구조입니다.

```text
          북 ↕                        북 ↕
서 ↔ [A: J0] ↔ 약 400m 연결 구간 ↔ [B: J1] ↔ 동
          남 ↕                        남 ↕
```

도로는 방향별 1차로이고 차량은 직진만 합니다. 동서 경계 유입은 방향별 평균 600대/시간, 교차로별 남북 유입은 방향별 평균 250대/시간입니다. 차량 출발 간격을 지수분포로 생성해 경로와 출발시각을 XML에 확정합니다. 비교 방법들이 동일한 차량 파일을 받도록 합니다.

가상 실험 한 번은 900초입니다. 첫 600초에 차량이 출발하도록 계획하고 마지막 300초 동안 남은 차량을 처리합니다. 실제 벽시계 15분이 아니라 SUMO 시간 15분입니다.

## 2. 신호와 세 제어 방법

녹색 현시는 `남북 통행/동서 정지`와 `동서 통행/남북 정지` 두 개입니다. 전환할 때는 기존 녹색 방향의 황색 3초와 모든 방향 적색 2초를 거칩니다.

| 방법 | 실제 동작 |
|---|---|
| `fixed` | 남북 녹색 30초 → 황색 3초 → 전적색 2초 → 동서도 같은 순서, 총 70초 주기 |
| `queue` | 각 교차로에서 다음 녹색 방향의 정지 차량 수가 현재 방향보다 많으면 전환 요청 |
| `dqn` | 모든 교차로의 관측을 받은 하나의 신경망이 공동 유지/전환 행동 선택 |

세 방법은 같은 최소 녹색 10초·최대 녹색 60초와 황색·전적색 제약을 사용합니다. `queue`는 직접 작성한 규칙이며 SUMO 검지기 기반 actuated를 구현한 것은 아닙니다. 30초 고정신호는 실험용 시간표이며 현장 신호나 최적화된 기준선이 아닙니다.

DQN의 입력은 진입 차로별 차량·정지 차량 수, 녹색 현시, 전환 단계, 경과시간과 에피소드 시간입니다. 두 교차로에서는 29차원이며 행동은 `(A 유지,B 유지)`, `(A 전환,B 유지)`, `(A 유지,B 전환)`, `(A 전환,B 전환)` 네 개입니다. 보상은 다음 5초 동안 모든 비내부 차로의 정지 차량 수를 매초 합한 값의 `-1/100`배입니다. 자세한 학습식은 [실험 설명](rl_experiment_explained.md)을 참고하세요.

## 3. 프로그램이 연결되는 방식

```text
PowerShell → Python(run.py) → DQN/신호 제약
                      ↕ TraCI, 127.0.0.1의 로컬 TCP 통신
                 SUMO 또는 SUMO-GUI
```

Python이 SUMO 실행파일을 시작하고 로컬 포트로 연결합니다. SUMO가 차량 움직임과 교통 상태를 계산하고 Python이 관측을 읽고 신호를 제어합니다. 시뮬레이션과 신호 제약은 1초, DQN의 의사결정은 5초 단위입니다. 외부 SUMO 서버를 별도로 준비하지 않습니다.

## 4. 새 컴퓨터에 설치: Windows

Python 3.12 64비트와 Git을 설치한 후 PowerShell에서 실행합니다.

```powershell
git clone https://github.com/yoonhb7/RL.git
cd RL
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-verified.txt
.\.venv\Scripts\python.exe run.py doctor
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__)"
```

`doctor`는 패키지 버전과 실행파일을 확인합니다. 실제 PyTorch DLL 로드는 다음 줄의 `import torch` 명령으로 별도 확인합니다. `.venv`를 활성화하지 않아도 전체 Python 경로로 실행할 수 있습니다.

`requirements-verified.txt`는 검증에 사용한 핵심 버전을 기록한 것입니다. 해당 플랫폼용 wheel이 없는 경우 지원되는 Python/운영체제를 사용하고, 필요한 버전 변경은 별도 실험으로 기록하세요. 일반 의존성 범위는 `requirements.txt`에 있습니다.

GUI가 DLL 누락으로 시작되지 않으면 [공식 SUMO Windows 설치 안내](https://sumo.dlr.de/docs/Installing/index.html)에 따라 Windows 배포판을 설치하거나 ZIP을 해제합니다. 실제 폴더에 맞춰 다음을 지정합니다.

```powershell
$env:SUMO_HOME = "C:\Tools\sumo-1.28.0"
$env:SUMO_GUI_BINARY = Join-Path $env:SUMO_HOME "bin\sumo-gui.exe"
& $env:SUMO_GUI_BINARY --version
```

`SUMO_HOME`은 `bin`의 부모 폴더입니다. 설치 경로는 컴퓨터마다 다릅니다. macOS의 `.pkg`와 Windows 실행파일을 혼용하지 않습니다.

macOS/Linux는 `python3 -m venv .venv`, `source .venv/bin/activate`, `python -m pip install -r requirements-verified.txt`로 환경을 만들고 이후 명령의 `.\.venv\Scripts\python.exe`를 `python`으로 바꿉니다. GUI 설치 조건은 해당 플랫폼의 SUMO 문서를 따릅니다.

## 5. 기존 작업 PC의 준비된 환경 사용

원래 작업 PC에는 Codex Python과 `work/runtime`이 있습니다. 해당 환경을 찾을 수 있는 위치에 프로젝트가 있으면 다음 명령도 사용할 수 있습니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\RUN_HERE.ps1 -Mode Doctor
powershell -ExecutionPolicy Bypass -File .\RUN_HERE.ps1 -Mode View -Scenario corridor2 -Controller dqn -ModelPath models/corridor2-100ep/model.pt -Delay 1000
```

`local_runtime.py`는 이 PC의 준비된 패키지와 Visual C++ DLL 검색 경로를 등록합니다. 새 컴퓨터에 Codex 환경까지 복사할 필요는 없습니다. 새 컴퓨터에서는 4절의 독립 `.venv`를 이용하세요.

## 6. 화면으로 보기: View

100회 학습한 두 교차로 모델을 재생합니다.

```powershell
.\.venv\Scripts\python.exe run.py view --scenario sumo/corridor2 --model models/corridor2-100ep/model.pt --controllers dqn --seeds 1001 --out results/local/corridor2-demo --delay 1000
```

같은 시드의 고정신호나 규칙을 보려면 `--controllers dqn`을 각각 `fixed`, `queue`로 바꿉니다. `--delay 1000`은 시뮬레이션 1초마다 약 1000ms를 지연시키므로 실행 계산시간까지 더해 실시간에 가까워집니다. `--delay 100`이면 빨라집니다. 화면 상단 Delay도 조절할 수 있습니다.

이 모드에서는 학습한 가중치를 변경하지 않습니다. 실제 신호 상태에 따라 3색 신호등 표시가 바뀌고 차량이 정지·출발합니다. 주변 건물과 확대된 신호 그래픽은 설명용이며 실측 지형이나 학습 입력이 아닙니다.

900초에 도달하면 기록을 저장하고 `--quit-on-end`와 연결 종료에 따라 창이 닫힙니다. 가상 시간이 빠르게 진행되면 현실에서는 더 빨리 닫힙니다. 종료 전에 일시정지해 화면을 확인할 수 있습니다. GUI를 중간에 닫으면 Python에 연결 종료 오류가 나타날 수 있습니다.

`.sumocfg`를 SUMO GUI로 직접 열면 네트워크에 저장한 고정신호가 실행됩니다. DQN을 보려면 위 Python 명령으로 재생해야 합니다.

## 7. 같은 조건으로 성적 비교: Evaluate

```powershell
.\.venv\Scripts\python.exe run.py evaluate --scenario sumo/corridor2 --model models/corridor2-100ep/model.pt --controllers fixed queue dqn --seeds 1001 1002 1003 1004 1005 --out results/local/corridor2-evaluation-100
```

화면 없는 SUMO로 세 방법 × 평가 시드 5개 = 15회 실행합니다. 학습에 쓰지 않은 수요 시드를 사용합니다. 100회 모델은 학습 시드 0~99를 사용했습니다. 같은 시드에서 수요 파일 해시·도로·신호 제약·종료시각을 맞춥니다.

```powershell
Invoke-Item .\results\local\corridor2-evaluation-100
Invoke-Item .\results\local\corridor2-evaluation-100\comparison.png
```

폴더 경로만 PowerShell에 입력하면 명령으로 해석됩니다. 폴더를 열 때는 `Invoke-Item` 또는 `explorer`를 사용하세요.

| 파일 | 볼 내용 |
|---|---|
| `summary.csv` | 시드 간 평균과 표본 표준편차 |
| `episodes.csv` | 제어기·시드별 결과 |
| `paired.csv` | 같은 수요의 고정신호 대비 감소율과 완료 차량 변화 |
| `comparison.png` | 대기시간·완료·미완료 차량 비교 |
| `evaluation.json` | 평가 시드·모델 정보·집계 |
| 제어기/시드 폴더 | 실제 신호 trace, TripInfo, 실행 명령·로그 |

주요 대기값은 `mean_wait_arrived_s`와 `mean_wait_departed_censored_s`입니다. 후자는 출발했으나 도착하지 못한 차량의 종료시점까지 관측한 대기를 포함하며 미래 대기는 제외합니다. 미출발 차량은 이 평균에 포함되지 않으므로 `arrived`, `unfinished`, `not_departed`, `pending_vehicle_seconds`를 같이 봅니다. 결과표의 P95 queue는 차로 길이(m)가 아니라 매초 네트워크 총 정지 차량 수의 95백분위입니다.

## 8. 새 모델 학습: Train

```powershell
.\.venv\Scripts\python.exe run.py train --scenario sumo/corridor2 --episodes 100 --seed 100 --out results/local/corridor2-new-train
```

학습 수요 시드는 100~199가 됩니다. 기존 0~99 학습과 구분하기 위한 예시이며, 같은 seed·설정으로 반복하려면 `--seed 0`을 사용하세요. 학습 결과는 `model.pt`, `training_config.json`, `training.csv`, `training.png`에 저장합니다.

**새로 학습한 파일을 평가·재생 명령에 직접 지정해야 합니다.** 다른 모델의 결과를 새 모델 성적으로 해석하지 않습니다.

```powershell
.\.venv\Scripts\python.exe run.py evaluate --scenario sumo/corridor2 --model results/local/corridor2-new-train/model.pt --controllers fixed queue dqn --seeds 1001 1002 1003 1004 1005 --out results/local/corridor2-new-evaluation
.\.venv\Scripts\python.exe run.py view --scenario sumo/corridor2 --model results/local/corridor2-new-train/model.pt --controllers dqn --seeds 1001 --out results/local/corridor2-new-view --delay 1000
```

`RUN_HERE.ps1`을 이용한다면 `-Mode Train -Episodes 100 -OutputPath results/local/corridor2-new-train`으로 학습하고 이후 `-ModelPath results/local/corridor2-new-train/model.pt`를 명시합니다. 기본 Evaluate 모델은 초기 `results/verified` 모델이므로 경로를 생략하지 마세요.

Double DQN은 학습 명령에 `--double`을 추가하고 별도 폴더에 저장합니다. Dueling/GNN/보행자/Split·Offset 최적화는 현재 구현 범위에 없습니다.

## 9. 다른 도로·수요·테스트

단일 교차로는 `sumo/toy`와 `results/verified/toy-train/model.pt`, 세 교차로는 `sumo/corridor3`와 `results/verified/corridor3-train/model.pt`를 함께 사용합니다. 모델과 도로를 섞으면 스키마 불일치 오류가 정상적으로 발생합니다.

네트워크를 직접 생성하려면 다음 명령을 사용합니다.

```powershell
.\.venv\Scripts\python.exe run.py build --config configs/corridor2.json --out sumo/corridor2
.\.venv\Scripts\python.exe run.py inspect --net sumo/corridor2/network.net.xml --out data/processed/corridor2-inventory.json
```

네트워크를 다시 생성해 파일 해시가 바뀌면 기존 모델과 호환되지 않을 수 있습니다. 기본 제공 모델부터 확인하려면 먼저 재생성하지 마세요. 수요를 20% 높인 합성 일반화 평가에는 Evaluate에 `--scale 1.2`를 추가합니다. 기존 결과를 보존하도록 출력 폴더를 바꾸세요.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

테스트는 신호 시간·행동 마스크·모델 호환성·차량 집계·실제 SUMO 통행과 연결 오류 처리를 확인합니다. `scripts/audit_results.py`는 3개 시나리오의 `results/verified/*-evaluation`에 매초 `trace.csv`까지 생성돼 있을 때 실행하는 별도 도구입니다. GitHub 배포본에는 결과 요약만 포함했으므로 원시 로그가 없는 상태에서 이 감사 스크립트가 바로 실행되지는 않습니다.

## 10. 기록된 성능과 해석 범위

`reports/corridor2-100ep/summary.csv`에서 5개 평가 수요의 대기는 고정신호 27.24초, 규칙 15.26초, 100회 DQN 12.02초입니다. 초기 20회 모델의 15.81초 결과와 구분하세요. 이 숫자는 합성 직진 도로·특정 수요·한 번의 학습 실행에서 나온 관측 결과입니다. 실제 도로 적용과 알고리즘 일반화에는 회전·보행·현장 수요 보정·독립 학습 반복 등 후속 실험이 필요합니다.

## 자주 만나는 오류

- `shm.dll`, `WinError 126`: PyTorch 자체 또는 의존 C++ DLL 로드 실패입니다. 기존 PC는 최신 `local_runtime.py`를 통해 실행하고, 독립 환경은 PyTorch와 운영체제의 공식 설치 요구사항을 확인하세요. 패키지 버전 표시 성공과 실제 import 성공은 다릅니다.
- `TraCI server already finished`, `Could not connect`: SUMO 실행파일이 먼저 종료됐는지 `sumo-startup.log`를 봅니다. GUI DLL 누락은 공식 SUMO 설치 경로를 지정해 확인합니다.
- `Checkpoint ... mismatch`: 모델이 다른 네트워크·차로 순서·신호 제약용입니다. 해당 도로의 모델을 사용하거나 새로 학습합니다.
- `Evaluation seed overlaps`: 학습 수요 시드와 겹치지 않는 평가 시드를 지정합니다.
- `FileNotFoundError model.pt`: 명령의 모델 경로가 실제 저장 위치와 일치하는지 확인합니다.
