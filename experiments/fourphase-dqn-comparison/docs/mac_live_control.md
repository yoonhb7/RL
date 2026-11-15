# Mac SUMO와 원격 Linux Python 개발 콘솔

## 실행 위치와 수정할 파일

- Mac: SUMO GUI 및 차량 시뮬레이션.
- 원격 Linux: Python과 제어 코드. VS Code의 원격 프로젝트를 편집합니다.
- `scripts/view_mac.py`: 연결 및 콘솔 실행 진입점.
- `src/traffic/live_session.py`: 연결 유지, 명령 처리, 신호 전환 제약.
- **`src/traffic/live_controller.py`: 일상적으로 수정하고 `reload`할 파일.**

이 문서의 `view_mac.py`는 녹색시간 조정용 개발 콘솔입니다.
DQN 학습과 학습 모델을 사용하는 GUI 실행은 [DQN 실행 안내](toy_dqn.md)를 따릅니다.
기존 Fixed-time 평가기 `scripts/run_fixed.py`는 별도의 실행 경로이며 그대로 유지합니다.
개발 콘솔은 실험 결과 CSV나 최종 성능표를 저장하지 않습니다.

## 처음 실행 / 기존 예제에서 교체

기존 자동 실행 예제가 돌고 있다면 원격 Linux에서 Ctrl+C로 종료하고,
Mac에서 기존 SUMO 창을 닫습니다. 새 콘솔로 전환할 때 한 번 필요한 절차입니다.
아래 3개 터미널을 구분합니다.

### Mac 터미널 A: SSH 터널

이미 연결해 둔 SSH 터널을 유지합니다. 새 연결을 만들 때 쓰는 명령은 다음과 같습니다.

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -R 127.0.0.1:18813:127.0.0.1:8813 \
  USER@SERVER
```

출력 없이 대기하는 상태로 열어둡니다.

### Mac 터미널 B: SUMO 앱

처음 화면 개선을 적용할 때는 [화면 설정 안내](toy_visuals.md)에 따라 toy 파일을 Mac으로 복사합니다.
Python 제어 코드만 바꿀 때는 Mac으로 다시 복사할 파일이 없습니다.

```bash
sumo-gui \
  -c "$HOME/rl-term-project/toy/toy.gui.sumocfg" \
  --remote-port 8813 \
  --start
```

### 원격 Linux 터미널: Python 콘솔

```bash
cd "/path/to/RL/experiments/fourphase-dqn-comparison"
.venv/bin/python scripts/view_mac.py
```

연결 성공 메시지와 `sumo>`가 나오면 **그 입력창**에 아래를 입력합니다.
쉘 명령이나 Python `>>>` 문법이 아닌, 개발 콘솔 전용 명령입니다.

```text
resume
```

기본 시작 상태는 일시정지입니다. `step 10`으로 조금씩 진행할 수도 있습니다.
터미널에서 명령을 입력하고 Enter를 눌러야 적용됩니다.

## 코드 변경 반영

1. `sumo>`에서 `pause`.
2. VS Code에서 `src/traffic/live_controller.py` 수정 후 저장.
3. `sumo>`에서 `reload`.
4. `sumo>`에서 `resume`.

예를 들어 제어 파일의 두 값을 다음처럼 수정하면 남북 40초, 동서 20초의 녹색을 요청합니다.

```python
NS_GREEN_SECONDS = 40.0
EW_GREEN_SECONDS = 20.0
```

`reload`는 현재 시각과 차량을 유지하며, 성공 후에도 일시정지 상태입니다.
실제 제어는 다음 `step` 또는 `resume`에서 적용됩니다.
현재 녹색 도중이라면 **해당 녹색이 시작된 이후의 총 지속시간**을 새 값에 맞춥니다.
이미 새 목표시간을 넘겼다면 다음 진행에서 황색으로 넘어가며 경과시간을 되돌리지는 않습니다.
황색·전적색 중에는 녹색 목표만 갱신되고 현재 전환 현시의 시간은 바꾸지 않습니다.

처음부터 변경 효과를 확인하려면 다음 순서로 입력합니다.

```text
reload
reset
resume
```

`reset`은 Mac에서 읽었던 `.sumocfg`를 같은 연결로 다시 불러옵니다.
시각과 차량은 초기화하고, 다시 읽은 Python 제어 코드는 유지합니다.
`reset` 자체는 Python 파일을 다시 읽지 않으므로 파일 변경 시 `reload`를 먼저 사용합니다.

문법 오류, 누락된 함수, 잘못된 녹색시간이면 교체하지 않고 기존 제어 코드를 유지합니다.
실행 중 제어 함수에서 오류가 나면 일시정지합니다. 파일을 고친 뒤 다시 `reload`합니다.
제어 모듈은 다시 읽을 때 전역변수가 초기화됩니다.
외부 파일 쓰기나 TraCI 연결 같은 동작은 제어 모듈의 최상위 코드에 넣지 않습니다.

## 명령어

| 명령 | 동작 |
|---|---|
| `resume` | 자동 진행 시작/재개 |
| `pause` | 일시정지, 연결 유지 |
| `step` | 한 스텝 진행 후 대기 |
| `step 10` | 10개 스텝 진행 후 대기. 현재 시나리오는 1스텝=1초 |
| `reload` | 제어 파일 다시 읽기, 현재 시각/차량 유지, 일시정지 |
| `reset` | 같은 GUI/연결에서 시나리오 초기화, 일시정지 |
| `status` | 시각, 현재 현시와 경과시간, 방향별 대기 차량 수, 코드 버전 |
| `delay 0.5` | 스텝 사이의 실제 대기시간을 0.5초로 변경 |
| `delay 0` | Python 대기시간 없이 최대 속도로 진행 |
| `help` | 명령어 목록 |
| `quit` | 연결 종료. Mac SUMO에 정상 종료 요청 |

새 콘솔에서 **Ctrl+C는 종료가 아닌 일시정지**입니다.
Ctrl+D 또는 입력 터미널이 닫히면 정상 종료를 요청합니다.
기본 한계인 1200초에 도달해도 자동으로 연결을 닫지 않고 `reset`을 기다립니다.
시뮬레이션 한계는 실행 시 `--end 1800` 등으로 정할 수 있습니다.

SUMO 앱의 `Delay` 값도 속도에 영향을 줍니다.
이 콘솔의 일시정지는 터미널의 `pause`를 사용합니다.
GUI의 정지 버튼으로 멈추면 진행 중인 TraCI 응답도 대기할 수 있으므로,
명령 처리가 멈춘 것처럼 보이면 GUI의 ▶로 대기 중인 진행을 풀어줍니다.
Ctrl+C도 진행 중인 TraCI 응답을 받은 뒤 일시정지하도록 처리합니다.

## 제어 함수와 신호 제약

`green_seconds(observation)`은 현재 녹색의 **전체 목표 지속시간**을 반환합니다.
입력의 `queues`와 `vehicles`는 `north`, `south`, `east`, `west` 방향별 차량 수입니다.
연결 객체를 제어 함수에 전달하지 않으며, 시간 진행과 전환 처리는 실행기가 담당합니다.

- 현시 0: 남북 녹색. 현시 3: 동서 녹색.
- 허용 녹색시간: 10–60초. 범위를 벗어나면 오류로 일시정지합니다.
- 황색 3초와 전적색 1초는 기존 SUMO 프로그램이 순서대로 처리합니다.
- 남은 시간을 `목표 총시간 - 경과시간`으로 계산해 매번 녹색이 연장되는 문제를 방지합니다.

## 변경 범위와 연결 문제

다시 읽기는 `live_controller.py`만 대상입니다.
`view_mac.py`, `live_session.py`, 또는 제어 파일이 import한 다른 모듈까지 자동으로 갱신하지 않습니다.
그 파일들을 바꾸면 Python과 SUMO 연결을 다시 시작해야 합니다.
도로망·차량 경로 등 SUMO 입력을 바꾸면 재생성된 파일을 Mac에도 복사한 뒤 `reset`합니다.
SSH 터널이나 Mac SUMO 프로세스가 종료되면 연결을 다시 만들어야 합니다.

Mac의 시나리오 경로는 연결된 SUMO의 `configuration-file` 옵션에서 얻습니다.
자동 확인이 되지 않을 때는 `--mac-config`에 Mac에서 존재하는 경로를 지정합니다.
이 경로를 Linux의 `$HOME`이나 프로젝트 경로로 바꾸면 안 됩니다.

## 검증 명령

사용자가 원격 Linux 터미널에서 실행합니다.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

`test_live_session.py`는 SUMO에 접속하지 않는 테스트입니다.
다시 읽기 실패 시 기존 정책 유지, 초기화 시 Mac 경로 사용, 종료 시각의 연결 유지,
황색·전적색 보존, 총 녹색시간 처리와 콘솔 입력 버퍼 처리를 검사합니다.
실제 Mac 연결에서는 `step 10` → `status` → 파일 수정 → `reload` → `step 10` → `reset`을
직접 실행해 같은 GUI 창과 연결이 유지되는지 확인합니다.

## 공식 참고

- [TraCI load / close](https://sumo.dlr.de/docs/TraCI/Control-related_commands.html)
- [신호 제어와 남은 현시 시간](https://sumo.dlr.de/docs/Simulation/Traffic_Lights.html#controlling_traffic_lights_via_traci)
