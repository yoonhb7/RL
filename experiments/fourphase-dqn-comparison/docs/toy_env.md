# 단일 교차로 Gymnasium 환경

## 현재 구현 범위

`src/envs/toy_env.py`의 `ToyTrafficEnv`는 DQN을 연결하기 전의 학습 환경입니다.
Linux에서 화면 없는 SUMO를 실행하거나, Mac SUMO의 TraCI 연결을 받아 같은 상태·행동·보상을 사용합니다.
이 문서는 환경 자체의 확인 방법입니다. DQN 신경망·Replay Buffer·학습 실행은
[DQN 실행 안내](toy_dqn.md)를 따릅니다. 이 문서의 기본 규칙/수동 모드에서는 학습하지 않습니다.
현장 조사는 하지 않으며, 현재 toy 입력은 명시적으로 생성한 가상 도로와 수요입니다.

| 구성 | 파일 |
|---|---|
| 유지/전환 요청과 신호 제약 | `src/traffic/safety_controller.py` |
| Gymnasium `reset()` / `step()` | `src/envs/toy_env.py` |
| Mac 연결 상태에서 조작 | `scripts/view_toy_env.py` |
| 수정하고 다시 읽을 제어 코드 | `src/traffic/live_controller.py`의 `choose_action()` |
| DQN 없이 Linux에서 한 에피소드 확인 | `scripts/check_toy_env.py` |
| 환경 설정 | `configs/toy_env.json` 및 `configs/toy.json` |

## MDP 정의

- SUMO 스텝: 1초.
- 의사결정: 5초마다 한 번. 실제 화면의 재생 속도와는 별개입니다.
- 행동: `0=현재 녹색 유지`, `1=다음 녹색으로 전환 요청`.
- 최소 녹색 10초 이전의 전환 요청은 거부하고 유지합니다.
- 황색·전적색 중의 요청은 거부합니다. 다음 녹색까지 예약하는 행동은 아닙니다.
- 최대 녹색 60초에는 다음 황색으로 강제 전환합니다. 이 제약은 매 1초마다 검사합니다.
- 황색 3초 → 전적색 1초 → 반대 방향 녹색은 SUMO 프로그램이 처리합니다.
- 녹색을 유지할 때 기존 고정신호의 30초 타이머가 자동 전환하지 않도록 제어합니다.

보상은 한 제어 구간의 정지 차량-초를 음수로 계산합니다.
매초 네트워크의 모든 차로(내부 차로 포함)에서 정지 차량 수를 읽고 더합니다.
황색·전적색 동안의 정지도 포함합니다. 예를 들어 5초 동안 2,3,4,2,1대면 보상은 -12입니다.
차량별 평균 대기시간과는 다른 지표이며, 이 보상만으로 최종 정책 성능을 판단하지 않습니다.

관측은 `[0,1]` 범위의 `float32` 16차원 벡터입니다.

| 인덱스 | 내용 |
|---|---|
| 0–5 | 여섯 현시의 one-hot 표현. 두 전적색도 다음 녹색 방향에 따라 구분 |
| 6 | 현시 경과시간 / 최대 녹색시간 |
| 7–10 | 북·남·동·서의 대기 차량 수 / 차로 수용량 근사값 |
| 11–14 | 북·남·동·서의 차량 수 / 차로 수용량 근사값 |
| 15 | 학습 구간에서 남은 시뮬레이션 시간의 비율 |

수용량은 `차로 길이 / 7.5m`로 근사합니다. 7.5m는 toy 차량 길이 5m + 최소 간격 2.5m입니다.
정규화한 값은 `[0,1]`로 제한하고, 실제 차량 수와 밀도는 `info.raw_observation`에 별도로 제공합니다.
이 벡터는 논문의 State 3에 현시 경과시간과 남은 시간을 추가한 프로젝트 설계입니다.

기본 에피소드는 0초부터 1200초까지입니다. 처음 120초는 고정신호 Warm-up이며 보상에 포함하지 않습니다.
`reset()`은 Warm-up을 마친 120초의 상태를 반환합니다.
고정된 종료 시각까지의 누적 정지를 줄이는 유한 시간 문제이므로,
남은 시간을 관측에 넣고 1200초 도달 시 `terminated=True`, `truncated=False`로 반환합니다.
차량이 먼저 모두 도착해도 정해진 종료 시각까지 진행합니다.
마지막 제어 구간이 5초보다 짧으면 남은 시간만 진행·집계합니다.

## 처음 확인하는 순서

### 원격 Linux 터미널: 패키지 준비

```bash
cd "/path/to/RL/experiments/fourphase-dqn-comparison"
.venv/bin/python -m pip install -r requirements.txt
```

기존 `view_mac.py` 콘솔이 연결되어 있다면 `quit`으로 종료하고 기존 SUMO 창을 닫습니다.
새 환경 실행기로 교체할 때 한 번 필요한 절차입니다. SSH 터널은 유지합니다.
화면 설정을 처음 적용할 때는 [Mac 화면 설정 안내](toy_visuals.md)에 따라 toy 파일을 복사합니다.
이후 Python 제어 코드만 바꿀 때는 Mac으로 다시 복사할 파일이 없습니다.

### Mac 터미널: SUMO 실행

```bash
sumo-gui -c "$HOME/rl-term-project/toy/toy.gui.sumocfg" --remote-port 8813 --start
```

SSH 터널은 별도 Mac 터미널에서 기존 연결을 유지합니다.
새로 만들 때는 다음 명령을 사용합니다.

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -R 127.0.0.1:18813:127.0.0.1:8813 USER@SERVER
```

### 원격 Linux 터미널: 상태·행동·보상 콘솔

```bash
.venv/bin/python scripts/view_toy_env.py --warmup 0
```

첫 확인에는 `--warmup 0`으로 0초부터 시작합니다. 이 조건은 평가용 기본 Warm-up 120초와 다릅니다.
아래 명령을 `sumo>` 입력창에 **한 줄씩** 넣습니다.

```text
action 0
action 1
action 1
status
```

0초에 시작했다면 첫 행동 후 5초, 두 번째 후 10초, 세 번째 후 15초입니다.
5초에 요청한 전환은 최소 녹색 10초 미달이므로 `accepted=false, reason=min_green`이 출력됩니다.
10초의 요청은 허용되어 황색·전적색을 거쳐 동서 녹색으로 넘어갑니다.
보상은 실제 교통 상황에 따라 달라집니다.

## 콘솔 명령과 수정 방법

| 명령 | 동작 |
|---|---|
| `action 0` / `action 1` | 해당 행동으로 한 제어 구간 진행 후 대기 |
| `step` / `step 10` | 제어 파일의 행동으로 1회 / 10회 진행. 기본값에서 5초 / 50초 |
| `resume` / `pause` | 자동 진행 / 일시정지 |
| `reload` | 저장한 `live_controller.py`의 `choose_action` 다시 읽기, 일시정지 유지 |
| `reset` | 0초부터 재시작하고 설정한 Warm-up을 진행, 연결 유지 |
| `status` | 관측 벡터·원시 상태·직전 보상·누적 보상·차량 수 확인 |
| `delay 0.5` | 시뮬레이션 1초마다 실제 0.5초 대기 |
| `quit` | 최종 종료 |

현재 자동 정책은 `choose_action(observation, info)`에 있는 단순 녹색시간 기준 규칙입니다.
`NS_GREEN_SECONDS`, `EW_GREEN_SECONDS`를 사용하며 DQN은 아닙니다.
VS Code에서 이 함수나 값을 수정할 때는 `pause` → 수정·저장 → `reload` → `resume` 순서입니다.
문법 오류가 나거나 0/1 이외의 행동을 반환하면 새 코드를 채택하지 않고 이전 코드를 유지합니다.
종료 시각에는 연결을 닫지 않고 `reset`을 기다립니다.
Ctrl+C는 진행 중인 5초 구간을 마친 뒤 일시정지합니다.
GUI의 ▶는 켜두고 일시정지는 콘솔의 `pause`를 사용합니다.

`reload` 대상은 제어 파일만입니다. 환경 설정 JSON이나 환경·실행기 코드를 바꾸면 새로 실행해야 합니다.
원래의 `view_mac.py`는 녹색시간 조정 콘솔로 계속 사용할 수 있지만,
학습 환경의 상태·행동·보상을 확인할 때는 `view_toy_env.py`를 사용합니다.

## 결과와 검증 명령

Mac 콘솔은 Linux의 `results/env/mac_seed_.../`에 설정과 `transitions.jsonl`을 저장합니다.
각 기록에는 `(상태, 요청 행동, 보상, 다음 상태, 종료 여부)`, 실제 요청 적용 여부,
매초 정지 차량 수, 시드, 제어 코드 버전이 포함됩니다.
`vehicles_running`은 진행 중 차량, `vehicles_pending`은 출발 예정시각이 지났지만 미삽입인 차량입니다.
출발·도착 누적 수는 Warm-up을 포함하고, 보상 누적은 Warm-up 이후만 포함합니다.

별도 원격 Linux 터미널에서 SUMO에 접속하지 않는 단위 테스트를 실행할 수 있습니다.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Linux에서 무작위 행동 한 에피소드와 Gymnasium API를 확인하려면 다음 명령을 사용합니다.
이 명령은 Linux의 별도 headless SUMO를 사용하며 Mac 창은 제어하지 않습니다.

```bash
.venv/bin/python scripts/check_toy_env.py --seed 42 --check-api
```

검증 대상은 신호 최소·최대시간, 황색·전적색, 매초 보상 적분, Warm-up 제외,
종료 시각, 초기화 재현성, 제어 코드 다시 읽기입니다.
이 단계에서는 실행 환경의 정상 동작을 확인하고, 이후 DQN을 연결해 Fixed-time과 같은 조건으로 평가합니다.

## 참고

- [Gymnasium Env API](https://gymnasium.farama.org/api/env/)
- [유한 시간 문제의 종료와 외부 시간 제한 구분](https://gymnasium.farama.org/tutorials/gymnasium_basics/handling_time_limits/)
- [SUMO 신호 제어](https://sumo.dlr.de/docs/Simulation/Traffic_Lights.html#controlling-traffic-lights-via-traci)
