# 주 실험: 가상 연속 교차로 2개와 중앙집중형 DQN

2026-11-12부터 주 실험은 직접 설계한 가상 도로망입니다. 세종대 OSM 사례와 기존 toy 실험은 보존합니다.
현장 방문·계수·촬영은 하지 않습니다. 아래 코드는 준비했으며 새 도로 생성·시뮬레이션·테스트·학습은 아직 실행하지 않았습니다.

## 실험 구성

서쪽 경계 ↔ 교차로 A ↔ 350m 연결도로 ↔ 교차로 B ↔ 동쪽 경계로 이어집니다.
각 교차로에는 북·남 경계 도로도 연결됩니다. 경계 도로는 250m, 방향마다 1차로, 제한속도는 13.89m/s입니다.
모든 차량은 직진합니다. 서·동쪽 차량은 두 교차로를 모두 지나고 북·남쪽 차량은 해당 교차로만 통과합니다.
좌우회전·보행자·버스 정류장·실제 지도는 이번 주 실험의 변수가 아닙니다.

차량은 지수분포 도착 간격으로 생성한 후 출발시각·경로를 XML에 고정합니다. 아래 유입률은 실험 설계값입니다.

| 수요 이름 | 서쪽 | 동쪽 | A 북/남 | B 북/남 |
|---|---:|---:|---:|---:|
| low | 240 | 240 | 240 / 240 | 240 / 240 |
| balanced | 450 | 450 | 450 / 450 | 450 / 450 |
| high | 650 | 650 | 650 / 650 | 650 / 650 |
| unbalanced | 650 | 200 | 300 / 150 | 300 / 150 |
| changing, 0–450초 | 650 | 200 | 150 / 150 | 150 / 150 |
| changing, 450–900초 | 200 | 650 | 150 / 150 | 150 / 150 |

단위는 대/시간이며 실제 생성 차량 수에는 시드에 따른 변동이 있습니다.
출발 예정시각은 0–900초, 900–1200초는 새 출발 없이 남은 차량을 처리하는 구간입니다.
`high`는 설정상의 높은 수요이며 과포화 여부와 300초 내 정체 해소 여부는 실행으로 확인해야 합니다.

## 상태·행동·보상

하나의 Gymnasium 환경과 하나의 SB3 vanilla DQN이 A/B를 함께 제어합니다.

| 항목 | 정의 |
|---|---|
| 관측 | 교차로마다 현시 One-hot 6 + 현시 경과시간 1 + 방향별 정지 차량 4 + 방향별 차량 수 4 = 15개. A/B 30개 + 에피소드 남은 시간 1개 = **31개** |
| 정규화 | 경과시간 / 60, 차량 수 / 차로 수용량(차로 길이 / 7.5m), 남은 시간 / 1080. 최종 값은 [0,1]로 제한 |
| 행동 | `Discrete(4)`: 아래의 A/B 유지·전환 요청 조합 |
| 결정 간격 | **두 교차로가 함께 시뮬레이션 5초** 진행 |
| 보상 | 그 5초 동안 매초 **전체 네트워크 정지 차량 수를 합한 값의 음수**, 내부 차로 포함, 연결 차로 중복 합산 없음 |
| 에피소드 | 0–1200초. 처음 120초는 기본 고정신호 Warm-up, 학습 제어는 120–1200초로 **216번 행동** |
| 종료 | 남은 시간이 상태에 포함된 유한 시간 문제. 1200초에 terminal, 다음 `reset()`에서 차량·시계 초기화 |

| 공동 행동 | A | B |
|---|---|---|
| 0 | 유지 | 유지 |
| 1 | 전환 요청 | 유지 |
| 2 | 유지 | 전환 요청 |
| 3 | 전환 요청 | 전환 요청 |

각 신호의 6개 현시는 남북 녹색 → 남북 황색 → 전적색 → 동서 녹색 → 동서 황색 → 전적색입니다.
최소 녹색 10초 전에는 전환 요청을 거부하고, 녹색 60초에는 강제 전환합니다.
황색 3초·전적색 1초는 SUMO의 현시 순서대로 진행합니다. 한쪽 신호가 전환 중이어도 다른 쪽은 자체 제약에 따라 움직입니다.
현재 구현은 실행 시 요청을 거부하는 방식입니다. DQN 학습 목표에 별도의 Action Mask를 적용하지 않습니다.
정규화 전 원시 차량 수는 `info.raw_observation`에 남지만 상한을 넘는 차이는 신경망 입력에서 구분하지 못합니다.

## 비교 방법과 데이터 분리

- **fixed:** 양쪽 모두 녹색 30초·황색 3초·전적색 1초, 주기 68초. A Offset 0초, B Offset 25초.
  25초는 연결도로 자유 주행시간 약 25.2초에 근거한 가정이며 최적화된 고정신호가 아닙니다.
- **queue:** 반대 축의 대기 차량이 현재 축보다 2대 초과하면 전환 요청. 동일한 최소/최대 녹색·전환 제약을 적용합니다.
  감응식 기준선의 한 종류이며 SUMO 내장 actuated 제어기 또는 논문의 Webster 기준선을 재현한 것은 아닙니다.
- **dqn:** 두 교차로의 관측을 입력받아 공동 행동 0–3을 선택합니다. 최종 평가에서는 탐색 없이 행동합니다.

학습 수요 시드는 100–109, 모델 선택용 검증은 1000–1002, 최종 평가는 2000–2004로 분리합니다.
기본 학습은 다섯 수요를 모두 사용합니다. 따라서 최종 평가의 의미는 **같은 수요 유형의 새 출발 목록에 대한 성능**입니다.
미학습 수요 유형에 대한 일반화를 주장하려면 유형 자체를 학습·검증에서 제외한 별도 실험이 필요합니다.

입력 사본과 SHA-256을 실험 폴더에 저장하며, 최종 평가는 해당 학습 실행에 저장된 동일 수요·SUMO 시드로 세 방법을 비교합니다.
검증 평균 에피소드 보상이 가장 큰 모델을 `best_model.zip`으로 선택하며 테스트 수요는 이 선택에 사용하지 않습니다.
초기 기능 점검은 검증 수요로 진행합니다. 최종 테스트를 보고 반복 튜닝하지 않습니다.

평균 대기시간은 출발 예정시각이 120초 이후인 차량 집단의 관측 대기시간입니다.
미완료 차량의 관측 대기도 포함하고, 미진입 차량 수와 미진입 대기는 별도로 기록합니다.
정지 차량-초·도착·미완료·미진입·이동시간을 함께 확인합니다. 양쪽 비교 집단이 모두 완료된 경우에만 대기시간 감소율을 계산합니다.
차량 집계·신호 현시 순서/시간·색상·보상 적분을 검사하며 충돌·텔레포트는 실행을 실패 처리합니다.

## 1. 원격 Linux 터미널: 생성과 기능 확인

VS Code의 **원격 Linux 터미널**에서 실행합니다. Mac과 SSH 터널은 필요 없습니다. 기존 `.venv`를 사용합니다.

```bash
cd "/path/to/RL/experiments/fourphase-dqn-comparison"
.venv/bin/python scripts/build_corridor2.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/evaluate_corridor2.py --profiles balanced --seeds 1000 --output results/corridor2/baseline_check
```

첫 명령은 netconvert로 도로를 생성합니다. 테스트는 SUMO를 시작하지 않는 모의 연결 검사이며,
마지막 명령은 서버의 화면 없는 SUMO에서 balanced 검증 수요 1개를 fixed/queue로 실제 실행합니다.
명령 하나씩 성공을 확인한 후 다음 명령을 입력합니다. 충돌 0·텔레포트 0·집계 및 신호 검사 통과를 확인합니다.
생성기는 기존 `sumo/corridor2/`를 덮어쓰지 않습니다. 재생성할 때는 `--output sumo/corridor2_v2`처럼 새 폴더를 지정합니다.
이후 명령에도 `--scenario sumo/corridor2_v2`를 붙입니다. 결과 폴더도 이미 존재하면 새 이름을 사용합니다.

## 2. 원격 Linux: 짧은 학습 → 본 학습 → 최종 평가

위 기능 점검 후 우선 학습 연결을 확인합니다.

```bash
.venv/bin/python scripts/train_corridor2_dqn.py --timesteps 5000 --output results/corridor2/smoke
```

짧은 실행은 학습이 작동하는지 확인하는 용도입니다. 본 실험은 아래처럼 진행합니다.

```bash
.venv/bin/python scripts/train_corridor2_dqn.py --seed 42 --output results/corridor2/main_seed42
.venv/bin/python scripts/train_corridor2_dqn.py --seed 43 --output results/corridor2/main_seed43
.venv/bin/python scripts/train_corridor2_dqn.py --seed 44 --output results/corridor2/main_seed44
```

독립 학습 시드별로 신경망 초기화·탐색·수요 추출이 달라지지만 세 실행의 고정된 수요 풀은 같습니다.
예산에 따라 시드를 추가할 수 있습니다. 같은 학습 예산과 설정을 사용합니다.
학습 예산을 정한 뒤 각 실행의 저장된 테스트 수요로 평가합니다.

```bash
.venv/bin/python scripts/evaluate_corridor2.py --run results/corridor2/main_seed42
.venv/bin/python scripts/evaluate_corridor2.py --run results/corridor2/main_seed43
.venv/bin/python scripts/evaluate_corridor2.py --run results/corridor2/main_seed44
```

실행당 수요 5종 × 테스트 시드 5개 × 제어기 3개를 평가합니다.
`evaluation/summary.json`의 표준편차는 **한 학습 실행 안에서 수요 시드 간 변동**입니다.
독립 학습 시드 간 변동은 세 실행 결과를 별도로 묶어서 보고해야 합니다. 자동 합산은 아직 제공하지 않습니다.
30초 고정신호 한 종류와의 비교이므로 DQN이 최적 고정신호보다 우수하다는 결론은 내리지 않습니다.
최종 보고서의 비교를 강화하려면 검증 수요만으로 고정신호의 녹색시간·Offset을 선택하는 실험을 추가합니다.

| DQN 설정 | 값 |
|---|---|
| 총 행동 수 / 신경망 | 50,000 / 31 → 64 → 64 → 4 |
| Replay buffer / 초기 경험 수집 | 50,000개 / 최초 1,000번 행동 동안 optimizer 업데이트 없음 |
| 학습 주기 / 배치 / Gradient steps | 행동 4번마다 무작위 경험 128개로 1회 업데이트 |
| 학습률 / 할인율 | 0.001 / 0.99 |
| Target 복사 | 전체 행동 1,000번마다 온라인 신경망 가중치를 복사 |
| 탐색 | 총 행동 예산의 처음 30%에 ε 1.0 → 0.05, 이후 0.05 |
| 검증 / 장치 | 행동 5,000번마다 + 마지막에 검증 / CPU |

Warm-up 120초는 매 에피소드 반복하고 replay에 넣지 않습니다.
최초 1,000번 경험 수집은 전체 학습에서 한 번만 적용하며 에피소드가 바뀌어도 버퍼·가중치·전체 행동 수는 유지됩니다.
버퍼가 50,000개에 도달하면 오래된 경험부터 덮어씁니다.

## 3. Mac: 화면 확인

먼저 위 1단계의 도로 생성이 성공해야 합니다. 아래 복사 명령은 **Mac 일반 터미널**에서 입력합니다.

```bash
mkdir -p "$HOME/rl-term-project/corridor2"
ssh USER@SERVER 'tar -C "/path/to/RL/experiments/fourphase-dqn-comparison/sumo/corridor2" -cf - .' \
  | tar -xf - -C "$HOME/rl-term-project/corridor2"
```

**Mac 터미널 A:** 기존 연결이 살아 있으면 재실행하지 않습니다. 아래 터널을 열어둡니다.

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -R 127.0.0.1:18813:127.0.0.1:8813 \
  USER@SERVER
```

**Mac 터미널 B:** 기존 toy SUMO 창을 종료한 뒤 새 시나리오를 실행합니다.

```bash
sumo-gui -c "$HOME/rl-term-project/corridor2/corridor2.gui.sumocfg" --remote-port 8813 --start
```

**원격 Linux 터미널:** 대기행렬 규칙을 먼저 관찰합니다.

```bash
cd "/path/to/RL/experiments/fourphase-dqn-comparison"
.venv/bin/python scripts/view_corridor2.py --controller queue
```

`sumo>` 입력창에서 원하는 명령을 입력합니다.

```text
view A
action 0
action 1
action 2
action 3
view overview
resume
```

`pause`는 정지, `step 10`은 현재 제어기의 행동 10번(50초) 진행, `status`는 원시 상태 확인입니다.
`view B`, `colors waiting`, `colors speed`, `delay 0.05`도 사용할 수 있습니다.
`reset`은 GUI를 닫지 않고 같은 수요·시드로 120초 Warm-up 후 다시 대기합니다.
1200초에도 연결을 유지합니다. `quit`으로 최종 연결을 닫습니다.

규칙 실험은 서버의 `src/traffic/corridor_controller.py`를 수정하고 `pause → 저장 → reload → resume`으로 반영합니다.
이 파일은 GUI 확인에만 사용하며 평가 기준선의 고정된 규칙에는 영향을 주지 않습니다.
환경·실행기·공통 모듈 변경은 Python 재시작이 필요합니다. XML이 바뀌면 Mac으로 다시 복사하고 SUMO도 다시 실행합니다.

학습 완료 후 DQN을 보려면 기존 콘솔에서 `quit`하고 Mac SUMO를 위 명령으로 다시 연 뒤 서버에서 실행합니다.

```bash
.venv/bin/python scripts/view_corridor2.py --controller dqn --model results/corridor2/main_seed42/best_model.zip
```

기존 toy 모델은 관측 16개·행동 2개라 사용할 수 없습니다. GUI 시연은 기본 balanced/42 수요이며 공식 테스트 결과와 구분합니다.
화면에는 도로·차량·기본 신호 표시만 사용하고 큰 정보 박스를 추가하지 않습니다.

## 주요 파일과 출력

- `configs/corridor2.json`: 도로·수요·신호·보상 시간 설정.
- `configs/corridor2_dqn.json`: 학습 설정과 데이터 분리.
- `src/envs/corridor_env.py`: 두 교차로 관측·공동 행동·안전 제어·보상.
- `src/agents/corridor_evaluation.py`: 동일 수요 비교·집계·신호 검사.
- 학습 폴더: `manifest.json`, `training_summary.json`, `episodes.csv`, `progress.csv`, `validation.csv`, 모델, 학습 그래프.
- 평가 폴더: `comparison.csv`, `summary.json`, `comparison.png/.svg`, 사례별 `metrics.json`, `tripinfo.xml`, `queues.csv`, `decisions.csv`.

이 구현은 논문의 중앙집중형 제어·가상 도로 실험 아이디어를 참고한 자체 설계입니다.
논문의 전체 알고리즘이나 수치 결과를 그대로 재현했다고 주장하지 않습니다.
