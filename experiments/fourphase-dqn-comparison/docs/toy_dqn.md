# 첫 DQN 학습과 고정신호 비교

## 실행 범위

Python 3.10의 원격 Linux에서 학습·검증·최종 평가를 수행합니다.
Mac SUMO는 저장한 모델의 행동을 눈으로 확인할 때 사용합니다.
코드는 사용자가 직접 실행하며, 모델 성능이나 검사 통과 여부는 실제 출력으로 확인해야 합니다.
데이터는 합성 toy 시나리오입니다. 현장 방문·계수·신호 측정은 하지 않습니다.

## 설치와 첫 실행: 원격 Linux 터미널

현재 `sumo>` 입력창이 아닌 별도의 Linux 쉘 터미널에서 실행합니다.
작은 MLP의 첫 베이스라인은 CPU로 설정했습니다. PyTorch는 공식 CPU 패키지를 먼저 설치합니다.

```bash
cd "/path/to/RL/experiments/fourphase-dqn-comparison"
.venv/bin/python -m pip install torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r requirements-dqn.txt
```

설치 후 SUMO를 시작하지 않는 회귀 검사를 실행할 수 있습니다.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

처음에는 5,000번의 행동 선택으로 학습·저장·평가 과정이 작동하는지 확인합니다.

```bash
.venv/bin/python scripts/train_toy_dqn.py --timesteps 5000 --output results/dqn/first_run
```

`timesteps`는 시뮬레이션 초나 에피소드 수가 아니라 **에이전트가 행동을 선택한 횟수**입니다.
기본 한 에피소드는 Warm-up 120초 후 1200초까지이므로 216번의 행동 선택으로 구성됩니다.
5,000번은 약 23개의 완료 에피소드와 마지막 일부 에피소드입니다.
이 짧은 실행만으로 학습 수렴이나 Fixed-time보다 좋은 성능을 보장하지 않습니다.

정상 동작을 확인한 뒤 설정 파일의 기본 50,000번으로 실행하려면 새로운 출력 폴더를 사용합니다.

```bash
.venv/bin/python scripts/train_toy_dqn.py --output results/dqn/full_run
```

기존 결과 폴더는 덮어쓰지 않습니다. 학습 중인 파일을 수정해도 실행 중인 학습 설정이 바뀌지는 않습니다.

## 학습 방식과 주기

Stable-Baselines3의 vanilla DQN을 사용합니다. Double DQN이나 행동 마스킹은 추가하지 않았습니다.
행동은 유효한 두 요청이며, 최소 녹색시간 미달·전환 중의 요청은 환경에서 거부하고 유지로 처리합니다.
황색·전적색과 최대 녹색시간은 같은 `SafetyController`가 강제합니다.

| 항목 | 기본 설정 |
|---|---|
| 입력 / 출력 | 16차원 관측 / 유지·전환 요청 2개 행동 |
| 신경망 | 은닉층 64 → 64, ReLU |
| 의사결정 간격 | SUMO 시간 5초 |
| 초기 경험 수집 | 1,000번의 행동 선택 |
| 가중치 학습 | 이후 행동 4번마다 미니배치 128개로 업데이트 1회 |
| 목표 네트워크 갱신 | 행동 1,000번마다 |
| Replay Buffer | 50,000개 |
| 학습률 / 할인율 | 0.001 / 0.99 |
| 탐험 확률 | 1.0에서 0.05로 감소, 전체 학습의 처음 30%에서 감쇠 |
| 검증 | 5,000번마다, 그리고 마지막 가중치 업데이트 후 |

설정은 `configs/toy_dqn.json`에 있습니다.
학습 중 `[학습] step=... updates=... epsilon=...`를 출력합니다.
`updates`는 신경망 업데이트 횟수이며 초기 경험 수집 중에는 0입니다.
SB3의 rollout 단위 때문에 요청한 행동 횟수가 `train_freq` 배수가 아니면 실제 횟수가 조금 커질 수 있습니다.
실제 횟수는 `training_summary.json`에 기록합니다.

## 수요와 평가 분리

실행할 때 `results/dqn/<실행>/scenarios/`에 네트워크·설정 사본과 다음 수요를 생성합니다.
기존 `sumo/toy/toy.rou.xml`과 `results/fixed/`는 변경하지 않습니다.

| 구분 | 수요 생성 시드 | 사용 목적 |
|---|---|---|
| 학습 | 100–109 | 에피소드마다 학습 수요 중 하나를 선택 |
| 검증 | 1000–1002 | 같은 3개 사례의 평균 보상으로 모델 선택 |
| 최종 평가 | 2000–2004 | 선택한 모델과 Fixed-time의 최종 비교 |

학습·검증·평가 수요 생성 시드는 겹칠 수 없습니다.
수요 시드는 출발시각/차량 목록을 정하고, SUMO 시드는 운전자 행동 등 내부 난수를 정합니다.
학습 실행의 난수 시드는 기본 42이며 에피소드의 수요 선택과 SUMO 난수는 그로부터 생성됩니다.
검증과 최종 평가에서는 사례별 SUMO 시드도 고정해 매번 같은 조건으로 실행합니다.
수요/입력 해시와 설정은 `manifest.json`에 저장하며 평가 전에 입력 변경 여부를 검사합니다.

`best_model.zip`은 검증 수요의 평균 보상이 가장 높은 시점의 모델입니다.
`model.zip`은 마지막 학습 모델입니다. 최종 평가 수요는 모델 선택이나 가중치 학습에 사용하지 않습니다.
현재는 학습 난수 시드 1개의 첫 베이스라인이며, 여러 학습 시드에 대한 반복 실험은 다음 확장입니다.

## Fixed-time 비교: 원격 Linux 터미널

학습이 정상 완료된 후 실행합니다.

```bash
.venv/bin/python scripts/evaluate_toy_dqn.py --run results/dqn/first_run
```

5개 최종 평가 사례 각각에서 **같은 네트워크·차량 경로·SUMO 시드·Warm-up·종료시각**으로
native Fixed-time과 DQN을 따로 실행합니다.
Fixed-time은 SUMO 파일에 정의된 녹색 30초·황색 3초·전적색 1초의 기존 프로그램입니다.
5초마다 강제로 전환하는 규칙으로 대체하지 않으며 실제 신호 프로그램을 그대로 진행합니다.
각 고정신호의 녹색시간도 비교 실험의 최소/최대 제약 안에 있는지 확인합니다.

평균 대기시간은 출발 예정시각이 Warm-up 이후인 차량 집단을 대상으로 합니다.
완료 차량과 미완료 차량의 현재까지의 대기를 포함하고 미출발 차량은 별도 집계합니다.
완료 차량만의 대기시간·통행시간, 측정 구간 도착 수, 대기행렬, 미완료/미출발 수도 함께 기록합니다.
요약 평균과 표준편차는 5개 수요 사례의 평균 대기시간을 기준으로 계산합니다.
분석 집단의 미완료·미출발 차량이 남으면 대기시간 감소율을 `null`로 남깁니다.
원시 관측 평균만으로 미완료 차량이 많은 방법을 더 좋다고 판단하지 않습니다.

매초 신호 순서와 녹색·황색·전적색 시간을 검사하고, 차량 수를 TripInfo와 대조합니다.
보상 합계와 매초 정지 차량-초 집계도 비교합니다. 검사 실패 시 해당 사례의 `metrics.json`을 확인합니다.
평가 결과를 다시 만들려면 새로운 `--output`을 지정합니다.

```bash
.venv/bin/python scripts/evaluate_toy_dqn.py --run results/dqn/first_run --output results/dqn/first_run/evaluation_repeat
```

## Mac에서 학습 모델 확인

학습/평가를 하는 동안 Mac 창이나 SSH 터널이 필요하지는 않습니다.
모델을 화면으로 확인할 때는 기존 SSH 터널을 유지하고, 기존 Python 콘솔은 `quit`으로 종료합니다.
Mac에서 기존 SUMO 창을 닫은 뒤 다음 명령으로 새 연결을 기다립니다.
화면 설정 파일은 [Mac 화면 설정 안내](toy_visuals.md)에 따라 먼저 복사합니다.

Mac 터미널:

```bash
sumo-gui -c "$HOME/rl-term-project/toy/toy.gui.sumocfg" --remote-port 8813 --start
```

원격 Linux 터미널:

```bash
.venv/bin/python scripts/view_toy_env.py --model results/dqn/first_run/best_model.zip
```

새 `sumo>` 입력창에서:

```text
resume
```

Python과 모델 파일은 Linux에 남고 TraCI 제어만 Mac SUMO로 전달됩니다.
학습 때의 환경 설정을 모델 옆 `manifest.json`에서 읽으므로 이 명령에 `--warmup 0`을 붙이지 않습니다.
이 모드는 탐험을 끄고 저장한 가중치로 행동을 선택합니다. 추가 학습은 하지 않습니다.
`pause`, `step`, `status`, `reset`을 사용할 수 있고, `reload`는 같은 모델 파일을 다시 읽습니다.
규칙 모드의 `reload`는 기존처럼 `live_controller.py`를 다시 읽습니다.
Mac에 이미 복사한 시드 42의 수요는 시각 확인용이며 공식 비교 수치는 Linux 최종 평가 결과입니다.

## 생성 파일

| 파일 | 내용 |
|---|---|
| `manifest.json` | 학습 설정, 환경 설정, 데이터 분할과 입력 해시 |
| `training_summary.json` | 완료/중단/실패 상태, 실제 행동/업데이트 수, 소프트웨어 버전 |
| `episodes.csv`, `monitor.csv` | 에피소드 보상·길이·완료/미완료 차량 수 |
| `progress.csv` | 탐험 확률, Replay Buffer 크기, 업데이트 횟수의 진행 기록 |
| `validation.csv` | 검증 보상과 모델 선택 기록 |
| `training_curve.png`, `.svg` | 에피소드 보상과 이동평균 |
| `best_model.zip`, `model.zip` | 검증 선택 모델 / 마지막 모델 |
| `evaluation/comparison.csv` | 사례별 Fixed-time / DQN 지표 |
| `evaluation/summary.json`, `comparison.png`, `.svg` | 평가 요약과 그래프 |
| `evaluation/seed_.../<방법>/tripinfo.xml`, `queues.csv`, `decisions.csv`, `metrics.json` | 원시 평가 결과와 검사 |

학습 스크립트의 Ctrl+C는 학습을 중단하고 가능한 경우 `interrupted_model.zip`을 저장합니다.
이는 가중치 체크포인트이며 Replay Buffer를 포함한 동일 상태 재개 기능은 아직 제공하지 않습니다.
GUI 콘솔의 Ctrl+C가 일시정지인 것과 구분합니다.

## 공식 참고

- [SB3 DQN: vanilla 구현과 학습 주기 인자](https://stable-baselines3.readthedocs.io/en/stable/modules/dqn.html)
- [SB3 사용자 환경 API](https://stable-baselines3.readthedocs.io/en/stable/guide/custom_env.html)
- [PyTorch 버전별 CPU 설치](https://pytorch.org/get-started/previous-versions/#v291)
