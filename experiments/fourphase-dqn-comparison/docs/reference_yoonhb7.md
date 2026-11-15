# yoonhb7/RL 비교와 실행 안내

확인일: 2026-11-11 (Asia/Seoul).
원본: <https://github.com/yoonhb7/RL>.
확인 커밋: `64098aa019fcd846ab553a7a4593c3b1d68dd58a` (`main`).
서버 다운로드 위치: `/path/to/RL/experiments/fourphase-dqn-comparison/.tools/references/yoonhb7-RL`.

Git clone과 소스·저장 결과 확인을 완료했다. 패키지 설치, Python, 학습, 평가, 테스트,
SUMO 실행은 하지 않았다. 아래 명령은 사용자가 직접 실행한다.
기존 프로젝트 구현과 다운로드한 원본 코드는 수정하지 않았다.

## 서로 다른 세 실험

| 항목 | 기존 RL Term Project | 참고 저장소 Corridor2 | 참고 저장소 PedLink |
|---|---|---|---|
| 제어 대상 | 가상 사거리 1개, 직진 차량 | 가상 사거리 2개, 직진 차량; 1·3개도 지원 | 한 도로 위 신호 횡단보도 4개, 차량·보행자 |
| 에이전트 | 중앙 DQN 1개 | 중앙 DQN 1개 | 중앙 DQN 1개 |
| 환경 | Gymnasium `ToyTrafficEnv` | Gymnasium `CentralizedTrafficEnv` | 별도 Python 환경 클래스 |
| DQN | Stable-Baselines3 | 직접 구현한 PyTorch DQN | Corridor2와 같은 `DQNAgent`를 사용 |
| 관측 / 행동 | 16차원 / 2개 | 29차원 / 공동 행동 4개 | 62차원 / 공동 행동 16개 |
| 신경망 | 은닉층 64–64, ReLU | 은닉층 128–128, ReLU | 은닉층 128–128, ReLU |
| 의사결정 / 물리 시간 | 5초 / 1초 | 5초 / 1초 | 5초 / 1초 |
| 에피소드 | 1,200초; 처음 120초 고정신호 Warm-up | 900초; Warm-up 0초; 600초 수요 + 300초 배출 | 420초; 별도 Warm-up 없음; 300초 수요 + 120초 배출 |
| 첫 학습 기록 | 행동 5,000회, 업데이트 1,000회 | 제공 100에피소드 모델: 행동 18,000회, 업데이트 4,437회 | 각 변형 30에피소드: 행동 2,520회, 업데이트 1,197회 |
| Replay 용량 / Batch | 50,000 / 128 | 50,000 / 64 | 50,000 / 64 |
| 학습 시작 | 최초 1,000회 경험 수집 후; 첫 업데이트 1,004회 | 256개 경험부터; 첫 업데이트 256회 | 128개 경험부터; 첫 업데이트 128회 |
| 업데이트 주기 | 행동 4회마다 1회 | 행동 4회마다 1회 | 행동 2회마다 1회 |
| Target 복사 주기 | **행동 1,000회마다** | **경사 업데이트 250회마다** | **경사 업데이트 250회마다** |
| 탐험 확률 | 1.0 → 0.05, 전체 행동의 처음 30%에서 감소; 초기 1,000회 강제 무작위 | 1.0 → 0.05, 예정 행동의 처음 70%에서 감소 | 1.0 → 0.05, 예정 행동의 처음 70%에서 감소 |
| 학습률 / 할인율 | 0.001 / 0.99 | 0.001 / 0.99 | 0.001 / 0.99 |
| 유효 행동 | 요청을 받은 뒤 최소 녹색·전환 중 여부에 따라 거부 | 탐험·추론·TD 목표값 계산 모두 행동 마스크 적용 | 공통 제약과 변형별 보행 우선 마스크 적용 |
| 모델 선택 | 별도 검증 수요 3개의 보상으로 `best_model.zip` 선택 | 기본 학습기는 마지막 에피소드의 모델 저장; 별도 검증 선택 없음 | 에피소드마다 최신 모델 저장; 별도 검증 선택 없음 |
| 모델 형식 | SB3 `.zip` | 자체 `.pt` | 자체 `.pt`; Corridor2 모델과도 호환되지 않음 |
| 추가 알고리즘 | vanilla DQN | `--double`로 Double DQN 선택 가능 | 현재 학습기는 기본 DQN 사용 |
| 화면 실행 | 서버 Python + SSH 터널 + Mac GUI; 연결 유지 콘솔 | Python이 같은 컴퓨터의 GUI를 자동 실행 | Python이 같은 컴퓨터의 GUI를 자동 실행 |

세 학습기는 모두 CPU, Adam, Huber Loss, gradient norm 제한 10을 사용한다.
Target 주기의 단위를 혼동하면 안 된다. Corridor2는 정상적인 학습 구간에서 대략
행동 1,000회에 업데이트 250회가 대응하지만, 초기 경험 수집과 복사 시점은 기존 코드와 다르다.
참고 구현은 Batch를 Buffer에서 **비복원 추출**하고, 기존 SB3 구현은 복원 추출한다.

### 보상과 신호 제약

- 기존: 5초 동안 **내부 차로를 포함한 네트워크 전체** 정지 차량·초의 음수.
  녹색 최소 10초·최대 60초, 황색 3초, 전적색 1초.
- Corridor2: **내부 차로를 제외한 전체 차로** 정지 차량·초의 음수에 `1/100`을 곱함.
  녹색 최소 10초·최대 60초, 황색 3초, 전적색 2초.
- PedLink: `-(정지 차량·초 + 미진입 차량·초 + 2 × 정지 보행자·초) / 100`.
  `adaptive`에는 보행 대기에 연동한 전환 비용이 추가된다.
  차량 녹색 최소 15초, 보행 녹색 최소 10초, 황색 4초, 전적색 1초,
  차량 복귀 전 보행 정리 최소 10초 및 횡단보도 점유 확인을 사용한다.
  보행자가 기다릴 때 차량 녹색 최대 60초, 차량이 기다릴 때 보행 녹색 최대 30초를 적용한다.

PedLink의 `basic`, `priority`, `adaptive`는 각각 기본형, 30초 보행 대기 우선 마스크 추가형,
우선 마스크에 대기 연동 전환 비용을 추가한 변형이다. 네 곳은 사거리 4개가 아니라
**차량 도로 위 횡단보도 4개**다.

기존 관측과 Corridor2 관측은 모두 `[0, 1]`에서 클리핑한다. PedLink는 `[0, 2]`다.
따라서 앞서 논의한 상한 초과 관측의 정보 손실을 완전히 제거한 구현은 아니다.

### 저장된 결과를 해석하는 범위

- 기존 `first_run`: 평가 수요 5개에서 Fixed 11.08초, DQN 6.94초, 감소율 37.32%.
- Corridor2의 제공된 100에피소드 모델: 같은 실험 내부의 평가 수요 5개에서
  Fixed 27.24초, Queue 규칙 15.26초, DQN 12.02초.
  해당 표에서는 미완료·미출발 차량이 모두 0이다.
- 두 프로젝트는 도로·교통량·Warm-up·전적색·분석 차량 집단·학습량이 다르다.
  37.32%와 Corridor2의 감소율을 직접 비교해 구현의 우열을 정할 수 없다.
- PedLink 원본 기록에는 일부 평가에서 종료 시 차량이 남았다. 보행 평균·P95와 차량 완료율을
  함께 해석해야 한다. 문서도 전환 비용을 추가한 모델이 전환 수를 줄였다고 결론 내리지 않는다.
- 원본 저장소의 테스트·평가 통과 기록은 **저장소 작성자의 기록**이며 여기서 재실행하지 않았다.
- 현재 세 도로는 합성 도로·수요다. 실제 세종대 도로나 운영 신호를 재현한 자료가 아니다.
  원본의 현장 조사 문서는 참고 템플릿이며 우리 프로젝트의 현장 조사 제외 방침은 유지한다.

## Mac에서 제공 모델을 화면으로 보기

원본 실행기의 GUI는 **같은 Mac에서 Python과 SUMO를 함께 실행**하는 방식이다.
기존 프로젝트의 서버 Python + Mac SUMO 방식을 대체하도록 수정한 것은 아니다.
현재 다운로드본에는 원격 TraCI 서버로 연결하는 `--host` / `--port` 옵션이 없다.
Mac에서 아래 명령을 실행하면 Python이 SUMO GUI를 시작하므로 별도의
`sumo-gui --remote-port 8813` 명령이나 SSH 터널은 이 실행 경로에 필요하지 않다.

### Mac 최초 설치

Mac 로컬 터미널에서 실행한다. Python 3.10 이상이 필요하며 패키지는 Python 버전에 맞게 설치된다.
Mac에 이미 설치되어 있는 SUMO 1.28과 XQuartz를 사용한다.

```bash
git clone https://github.com/yoonhb7/RL.git "$HOME/rl-yoonhb7"
cd "$HOME/rl-yoonhb7"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py doctor
```

`requirements-verified.txt`는 원 작업 PC의 Windows/Python 3.12 버전 기록이다.
현재 Mac/Linux의 Python에 그대로 맞는다고 확인한 파일이 아니므로 여기서는 저장소가 제공한
일반 설치 파일 `requirements.txt`를 사용한다. 설치가 성공해도 모델 로드와 GUI 실행은
실제 사용자 실행으로 확인해야 한다.

### 두 사거리 DQN 재생

Mac에서 저장소 최상위 폴더로 이동한 뒤 실행한다. 제공 모델을 사용하므로 재학습이 필요하지 않다.

```bash
cd "$HOME/rl-yoonhb7"
.venv/bin/python run.py view \
  --scenario sumo/corridor2 \
  --model models/corridor2-100ep/model.pt \
  --controllers dqn \
  --seeds 1001 \
  --out results/local/corridor2-mac-first \
  --delay 100
```

`--delay 100`은 시뮬레이션 1초마다 GUI에서 약 100ms 지연을 준다.
`--delay 1000`으로 바꾸면 실시간에 가깝게 느리게 볼 수 있다.
차량 형태·색상, 배경, 건물, 실제 신호 상태와 연동한 확대 신호등과 상태 표시가 들어 있다.
900초에 도달하면 GUI가 닫힌다. 기존 `sumo>` 연결 유지 콘솔은 이 실행기에 없다.

### 네 횡단보도 PedLink 재생

같은 Mac 가상환경에서 실행한다.

```bash
cd "$HOME/rl-yoonhb7"
.venv/bin/python experiments/pedlink-dqn/run.py view \
  --model experiments/pedlink-dqn/results/train-adaptive/model.pt \
  --profiles ped-burst \
  --seeds 1001 \
  --out results/local/pedlink-mac-first \
  --delay 100
```

420초까지 진행한다. 다른 변형을 보려면 모델 경로의 `train-adaptive`를
`train-basic` 또는 `train-priority`로 바꾸고 `--out`도 새 폴더로 바꾼다.
PedLink 출력 폴더가 이미 있으면 오류가 나므로 반복 실행 때 새 이름을 사용한다.

제공 모델을 먼저 확인할 때는 `build` 명령으로 네트워크를 다시 생성하지 않는다.
네트워크 해시가 모델의 저장된 스키마와 달라지면 로드가 거부될 수 있다.
`.sumocfg`를 직접 여는 것은 고정 신호 시나리오를 여는 경로다.
DQN과 Python에서 추가하는 화면 장식은 위 `view` 명령으로 실행한다.

## 원격 Linux에서 학습·평가

서버에 내려받은 복제본을 사용한다. 이 경로는 화면 없는 SUMO를 실행하며 Mac 창을 제어하지 않는다.
원본 Windows용 `.cmd`와 `.ps1` 대신 Python 진입점을 사용한다.

### 별도 실행 환경 설치

기존 프로젝트의 `.venv`는 유지하고 복제본 내부에 전용 `.venv`를 만든다.
현재 서버는 Python 3.10이고 기존 pip는 26.3이다. 이전 환경의 `ensurepip` 제약을 피하려고
`venv --without-pip`와 기존 pip의 `--python` 옵션을 사용한다.
이는 pip가 공식 지원하는 별도 가상환경 설치 방식이다.

```bash
cd "/path/to/RL/experiments/fourphase-dqn-comparison"
.venv/bin/python -m venv --without-pip .tools/references/yoonhb7-RL/.venv
.venv/bin/python -m pip --python .tools/references/yoonhb7-RL/.venv install torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip --python .tools/references/yoonhb7-RL/.venv install -r .tools/references/yoonhb7-RL/requirements.txt
cd .tools/references/yoonhb7-RL
.venv/bin/python run.py doctor
```

PyTorch 2.9.1 CPU는 원본 일반 요구사항 `torch>=2.3,<3`에 해당하는 설치 선택이다.
원본 제공 모델의 작성 환경은 PyTorch 2.15.0이므로 이 서버 조합에서의 로드·실행은
직접 확인해야 한다. 이 안내를 작성하며 설치나 모델 로드를 실행하지 않았다.

### 제공 두 교차로 모델 평가

```bash
cd "/path/to/RL/experiments/fourphase-dqn-comparison/.tools/references/yoonhb7-RL"
.venv/bin/python run.py evaluate \
  --scenario sumo/corridor2 \
  --model models/corridor2-100ep/model.pt \
  --controllers fixed queue dqn \
  --seeds 1001 1002 1003 1004 1005 \
  --out results/local/corridor2-server-first
```

세 제어기 × 수요 시드 5개 = 15회 실행한다.
출력은 지정 폴더의 `summary.csv`, `paired.csv`, `comparison.png`, `evaluation.json`과
제어기별 원시 기록에 저장된다. 반복 실행은 새 `--out` 폴더를 사용한다.

### 새 학습과 새 모델 평가

```bash
.venv/bin/python run.py train \
  --scenario sumo/corridor2 \
  --episodes 100 \
  --out results/local/corridor2-server-train-first

.venv/bin/python run.py evaluate \
  --scenario sumo/corridor2 \
  --model results/local/corridor2-server-train-first/model.pt \
  --controllers fixed queue dqn \
  --seeds 1001 1002 1003 1004 1005 \
  --out results/local/corridor2-server-trained-eval-first
```

Double DQN은 `train` 명령에 `--double`을 추가하고 새 출력 폴더를 사용한다.
독립 학습 반복에는 겹치지 않는 학습·평가 수요 시드를 정한다.

### PedLink 평가와 학습

```bash
.venv/bin/python experiments/pedlink-dqn/run.py evaluate \
  --model experiments/pedlink-dqn/results/train-adaptive/model.pt \
  --out results/local/pedlink-server-first

.venv/bin/python experiments/pedlink-dqn/run.py train \
  --variant adaptive \
  --episodes 30 \
  --out results/local/pedlink-server-train-first
```

평가는 기본 3개 수요 유형 × 3개 평가 시드로 진행한다.
학습은 `balanced`, `vehicle-heavy`, `ped-burst`를 순환한다.

## 이 프로젝트에서 참고할 부분

현재 프로젝트 목표와 가장 가까운 것은 **Corridor2의 단일 에이전트·공동 행동·행동 마스크**다.
기존 단일 교차로 환경과 평가 결과는 기준선으로 보존하고 별도 2개 교차로 환경에서 비교하는 편이 명확하다.
PedLink는 보행자를 포함하는 별도 연구 문제이며, 도로·관측·행동·보상을 한 번에 변경하므로
기존 결과와 직접 성능 비교하거나 단순 교체하지 않는다.

기존의 서버 Python + Mac GUI 구조를 참고 저장소에도 적용하려면,
외부 TraCI 연결, Mac의 입력 경로·수요 파일 배치, GUI 설정, 결과 파일 수집과
연결 유지/종료 처리를 별도로 구현해야 한다. 단순히 기존 `18813` 포트를 넘길 수 있는 CLI는 없다.

## 확인한 원본과 공식 자료

- [Corridor2 환경](https://github.com/yoonhb7/RL/blob/64098aa019fcd846ab553a7a4593c3b1d68dd58a/src/traffic_rl/env.py)
- [DQN·Replay·Target 구현](https://github.com/yoonhb7/RL/blob/64098aa019fcd846ab553a7a4593c3b1d68dd58a/src/traffic_rl/dqn.py)
- [CLI](https://github.com/yoonhb7/RL/blob/64098aa019fcd846ab553a7a4593c3b1d68dd58a/src/traffic_rl/cli.py)
- [SUMO 실행기](https://github.com/yoonhb7/RL/blob/64098aa019fcd846ab553a7a4593c3b1d68dd58a/src/traffic_rl/launch.py)
- [PedLink 실행기](https://github.com/yoonhb7/RL/blob/64098aa019fcd846ab553a7a4593c3b1d68dd58a/experiments/pedlink-dqn/run.py)
- [PedLink 공통 구현](https://github.com/yoonhb7/RL/blob/64098aa019fcd846ab553a7a4593c3b1d68dd58a/experiments/pedlink-dqn/core.py)
- [pip: 다른 가상환경 관리](https://pip.pypa.io/en/stable/topics/python-option/)
