# 4현시 단일 교차로: 환경 검증과 Mac 화면

2026-11-15 확정한 DQN / Double DQN / 순수 Dueling DQN 비교 연구의 새 환경이다.
이 단계는 **도로·안전 전환·관측·보상·집계 검증**이며 신경망을 학습하지 않는다.
기존 toy/corridor2/sejong2/rl1114_city 입력과 결과는 유지한다.

건물·공원·방향별 4색 신호등 4개·상세 차량을 갖춘 새 화면은 [4현시 도시 화면 안내](fourphase_city.md)를 따른다.

## 현재 구현 범위와 실행 상태

- 각 방향 진입 2차로(오른쪽 직진 0 / 왼쪽 보호 좌회전 1), 진출 2차로.
- P0 남북 직진 → P1 남북 좌회전 → P2 동서 직진 → P3 동서 좌회전.
- 네트워크의 12개 내부 phase와 8개 제어 연결을 생성 직후 검사.
- Fixed-time 30/15/30/15초 녹색, 황색 3초·전적색 1초, 주기 106초.
- 무작위 정책은 유효 행동 중 선택한다. 0=유지, 1=다음 현시 전환, 매 행동 15초.
- 13차원 관측, Clipping 없음, R1·J·Pending·차량 집계 및 3,600초 Truncation.
- 충돌·Teleport 또는 코드 오류는 별도 비정상 실행으로 저장. 혼잡은 결과로 유지.
- Mac GUI를 닫지 않고 reset 가능한 확인 콘솔.

**코드 작성 과정에서는 Python·netconvert·SUMO·테스트를 실행하지 않았다.**
아래 명령을 사용자가 실행한 뒤에만 도로와 실행 결과가 생성된다.
새 환경용 DQN / Double DQN / 순수 Dueling DQN의 Replay·Q-target·학습/체크포인트 선택 코드를 작성했다.
사용자가 시드 42에서 세 모델의 200에피소드 학습을 완료했다. 추가 학습 시드 반복은 나중으로 미루고,
검증 비교표와 학습곡선을 확인했고, 사용자가 선정 모델 3개와 Fixed-time의 독립 수요 예비 평가 60회를 완료했다.
비정상·미실행은 0회이며 결과와 그래프는 `results/fourphase_dqn/test_seed42`에 보존한다.
실행 명령은 [DQN 계열 학습 안내](fourphase_dqn.md)를 따른다. 기존 toy/corridor2 학습 모델은 이 환경에 사용하지 않는다.

## 1. 원격 Linux VS Code 터미널: 입력 생성

```bash
cd "/path/to/RL/experiments/fourphase-dqn-comparison"
.venv/bin/python scripts/build_fourphase.py
```

생성 위치는 `sumo/fourphase/`이다. 도로 변환 도구 netconvert를 사용하며 차량 시뮬레이션은 하지 않는다.
이미 같은 폴더가 있으면 덮어쓰지 않는다. 수정본은 `--output sumo/fourphase_v2`처럼 새 경로에 생성한다.

`configs/fourphase.json`의 총 수요율 **1,200/1,800/2,400 veh/h는 파일럿 후보값**이다.
실제 저·중·고 혼잡 수준으로 확정된 값이 아니다. 방향 비율은 1:1:1:1,
직진/좌회전 기대 비율은 75:25이며 Poisson 출발을 1초 격자로 내림한다.
같은 도착 과정으로 3,660초까지 배차를 만들고, 평가는 `[0,3600)` 예정 차량만 센다.
파일럿 시드 42를 향후 독립 검증·테스트 시드로 재사용하지 않는다.

## 2. 원격 Linux VS Code 터미널: 환경 검사

SUMO를 실행하지 않는 가짜 TraCI 테스트:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_fourphase.py' -v
```

실제 SUMO에서 Fixed-time과 유효 무작위 정책을 저·중·고 각각 3,600초 검사:

```bash
.venv/bin/python scripts/check_fourphase.py
```

이 명령은 Linux의 화면 없는 SUMO로 총 6회 실행한다. Mac 앱·SSH 터널은 필요 없다.
먼저 고정신호만 확인하려면:

```bash
.venv/bin/python scripts/check_fourphase.py --controllers fixed
```

새 시나리오 버전을 만들었다면 `--scenario sumo/fourphase_v2`를 추가한다.

결과는 `results/fourphase/check_실행시각/`에 저장한다.

| 파일 | 확인 내용 |
|---|---|
| `summary.json` | 6회 실행 상태, 각 지표, 비정상 횟수, `all_passed` |
| `inputs.json` | 설정·입력 파일 해시·실행 명령 |
| `medium_fixed/metrics.json` 등 | 차량 집계·J·ATT·AQL·검사 결과 |
| `seconds.jsonl` | 매초 원시 큐·Pending·신호 상태 |
| `transitions.jsonl` | random 정책의 관측·행동·보상·다음 관측·다음 마스크 |
| `tripinfo.xml` | 완료/미완료 차량의 실제 주행 기록 |
| `sumo_warnings.log` | SUMO 경고와 충돌 원인 조사 자료 |

정상 판정은 **3,600초 실행, 차량 수 보존, 올바른 마스크·관측·신호,
충돌/Teleport 없음, random의 보상 검산 일치**다.
ATT가 Fixed-time보다 좋다는 것은 통과 조건이 아니다. 마지막 순간 진입 차량이 남거나
혼잡으로 Pending이 생기는 것도 그 자체로 오류가 아니다.

충돌 시 최초 이벤트의 시각·차량·차로·현시를 기록하고 해당 실행을 중단한다.
minGap 위반/실제 차체 충돌/환경 오류를 로그로 분류한다. 중단된 실행을 3,600초 정상 결과로
비교하지 않으며 성공한 시드만 골라 보고하지 않는다.

## 3. Mac 로컬 터미널: 파일 복사

Linux에서 입력 생성을 마친 다음 **Mac의 로컬 터미널**에서 입력한다.

```bash
mkdir -p "$HOME/rl-term-project/fourphase"
ssh USER@SERVER 'tar -C "/path/to/RL/experiments/fourphase-dqn-comparison/sumo/fourphase" -cf - .' \
  | tar -xf - -C "$HOME/rl-term-project/fourphase"
```

도로와 Fixed-time만 직접 보려면 Mac에서 아래 명령으로 열고 SUMO 재생 버튼을 누른다.
이 경우 Python 제어·지표 수집·터널은 사용하지 않는다.

```bash
sumo-gui -c "$HOME/rl-term-project/fourphase/cases/medium/seed_42/view.sumocfg"
```

## 4. Mac GUI와 Linux Python을 연결해서 확인

**Mac 터미널 A — SSH 터널을 켜 두기:** 이미 같은 터널이 열려 있으면 기존 것을 사용한다.

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -R 127.0.0.1:18813:127.0.0.1:8813 \
  USER@SERVER
```

**Mac 터미널 B — 이전 SUMO 창을 닫고 새 환경 열기:**

```bash
sumo-gui \
  -c "$HOME/rl-term-project/fourphase/cases/medium/seed_42/view.sumocfg" \
  --remote-port 8813 --start
```

**원격 Linux VS Code 터미널 — 화면 연결:**

```bash
cd "/path/to/RL/experiments/fourphase-dqn-comparison"
.venv/bin/python scripts/view_fourphase.py
```

**같은 원격 터미널의 `sumo>` 입력창:**

```text
resume
pause
status
reset
mode random
action 0
action 1
step 4
```

- 처음은 Fixed-time. `mode random`은 0초로 reset하고 유효 무작위 행동을 사용한다.
- `action 0`은 15초 유지. 이어 `action 1`은 황색 3초+전적색 1초+P1 녹색 11초를 진행한다.
- 초기 0초에서는 최소 녹색 미달로 `action 1`을 거부한다. 녹색 56초에서 `action 0`도 거부한다.
- `step 4`는 시뮬레이션 4초다. 재생 속도는 Mac SUMO 상단 `Delay (ms)`에서 조절한다.
- `Ctrl+C`는 진행 중인 1초 스텝을 마친 뒤 일시정지한다. 행동 결정 간격은 15초 그대로다.
- 3,600초에 도달해도 GUI와 연결을 유지한다. `reset`으로 같은 창에서 다시 시작한다.
- `quit`은 Python 연결을 닫고 SUMO 시뮬레이션을 종료한다. 터널 종료는 Mac 터미널 A에서 `Ctrl+C`.

다른 수요를 보려면 Mac에서 해당 `low` 또는 `high` 설정을 열고 Linux에도 `--level low` 또는
`--level high`를 지정한다. 현재 콘솔은 파일에 고정한 동일 수요의 reset을 제공한다.
Python 파일을 저장하는 것만으로 실행 중 코드가 교체되지는 않는다.

## 확정 계산 규칙

관측 순서: N직진, N좌회전, S직진, S좌회전, E직진, E좌회전, W직진, W좌회전,
P0/P1/P2/P3 One-hot, 녹색 경과시간/60.

`C_hat=max(1, 차로길이/(차량길이+minGap))` 고정 스케일을 사용한다.
앞 8개 관측의 범위는 `[0,∞)`, 나머지 5개는 `[0,1]`이며 Clipping하지 않는다.

`r=-Σ(15초 × 진입 8차로 정지차량 수)/15`이고 `W_stop,in=-15×Σr`를 검산한다.
네트워크 전체 정지차량-초는 별도 진단 값이다.

`J=(W_stop,in+W_pending)/N_due`, `W_pending=Σ초 Pending_due`.
ATT는 완료 차량의 `tripinfo.duration` 평균으로만 계산하며 완료 차량 선택 편향을 함께 설명한다.

모든 RL 행동은 15초이며 끝의 관측·마스크는 실제 reset 이전 상태다.
3,600초는 `terminated=False, truncated=True`이며 다음 학습 구현에서 bootstrap을 유지한다.

환경 파일럿 다음에는 [DQN 20에피소드 파일럿](fourphase_dqn.md)을 실행한다.
그 결과를 확인한 뒤 같은 학습 루프에 Double target과 순수 Dueling 헤드를 추가한다.
