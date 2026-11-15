> **Repository:** `yoonhb7/RL`, branch `experiment/fourphase-dqn-results-20261116`.
> **Project directory:** `experiments/fourphase-dqn-comparison`.
> Run all project commands from this directory. Replace `/path/to/RL/experiments/fourphase-dqn-comparison` and `USER@SERVER` in examples with your checkout and SSH account.
> Includes the source, SUMO inputs, selected checkpoints, learning-curve logs, held-out evaluation results, figures, and report.
> Virtual environments, authentication files, downloaded paper PDFs, full per-episode raw logs, and unselected checkpoints are omitted. Training-demand XML is regenerated from recorded seeds; frozen validation/test inputs are included.
> JSON provenance keeps original server paths as historical metadata. Scripts resolve the project root dynamically.
> This snapshot was also published in `7ONALDO/RL-Term-Project` at commit `4af8b6f010f674654039ada91cebea1c15f671b1`.

# SUMO 교통신호 제어 — RL Term Project

**SUMO 4현시 단일 교차로에서 DQN·Double DQN·순수 Dueling DQN을 교통량별로 비교하는 연구**입니다.
2026-11-15에 13차원 관측, R1 보상, J 검증 점수, 3,600초 Truncation 규칙을 확정했습니다.
현장 방문·직접 계수·촬영은 하지 않습니다. 기존 toy·corridor2·세종대 OSM 실험은 보존합니다.
연구 설계는 [4현시 연구계획서](SUMO_DQN_4phase_traffic_signal_research_plan_2026-11-15.md),
현재 환경 생성·검증·Mac 화면 확인은 [4현시 실행 안내](docs/fourphase.md)를 따릅니다.

주변 건물·공원·방향별 4색 신호등 4개·상세 차량을 적용한 별도 화면은
[4현시 도시 화면 안내](docs/fourphase_city.md)에 생성·Mac 복사·연결 명령을 정리했습니다.

2026-11-14에 GitHub `yoonhb7/RL`의 새 `RL1114` 브랜치에서 단일 교차로의 도시형 SUMO 화면을 별도 복제했습니다.
건물·공원·신호등·자동차 표시와 도로 구성만 가져왔으며, 준비·Mac 연결은 [RL1114 도시 화면 안내](sumo/rl1114_city/README.md)를 따릅니다.
해당 시연은 원본 도로의 기본 고정신호를 사용합니다. 기존 학습 코드·모델·결과는 보존합니다.

## 지금 진행할 작업

사용자가 4현시 환경 검사, DQN 파일럿, **DQN·Double DQN·순수 Dueling DQN의 200에피소드 학습(시드 42)**을 완료했습니다.
모델마다 48,000개 행동·47,000회 신경망 업데이트, 학습 200회·검증 90회 검사를 통과했습니다.
검증 평균 J는 DQN 32.7863, Double 33.8332, Dueling 38.0401, Fixed-time 35.0916입니다.
위 수치는 모델 선정에 사용한 검증 결과입니다. 독립 테스트는 별도로 완료했습니다.

2026-11-16 사용자가 **독립 평가 60회도 정상 완료**했습니다. 비정상·미실행 0회이며 모델과 입력 해시도 유지됐습니다.
독립 평가 평균 J는 Fixed-time **34.2252**, DQN **30.2173**, Double **31.5691**, Dueling **37.2622**입니다.
Fixed-time 대비 DQN은 11.71%, Double은 7.76% 낮았고 Dueling은 8.87% 높았습니다.
저교통량은 Dueling, 중교통량은 Double, 고교통량과 전체 평균은 DQN의 J가 가장 낮았습니다.
이는 단일 학습 시드의 예비 결과이며 **시드 43·44 추가 학습은 나중으로 미룹니다.** 상세 결과·해석·실행 방법은
[DQN 계열 학습 안내](docs/fourphase_dqn.md)를 따릅니다.
보고서에 사용할 **실험 결과 및 고찰 본문**은 같은 문서의 앞부분에 작성했습니다.
교통량별 성능, 잔여 차량, 신호 운영, 학습곡선과 해석 범위를 원본 자료·그림 링크와 함께 정리했습니다.
**에이전트는 코드 작성 중 Python·netconvert·SUMO·테스트·학습을 실행하지 않았습니다.**

현재는 저장된 결과를 확인합니다. VS Code에서 아래 결과 폴더의 CSV·PNG를 열면 됩니다.

```text
results/fourphase_dqn/test_seed42/
```

Fixed-time과 세 모델을 저·중·고 × 배차 시드 5개에서 **총 60회** 실행한 결과입니다.
학습 시드는 42를 유지하고 모델 가중치를 고정했으며, 사용자가 Linux headless SUMO로 평가했습니다.
결과 폴더의 `traffic_metrics.png`는 독립 수요 성능, `signal_operation.png`는 신호별 시간 배분과 전환 횟수입니다.
`comparison.csv`, `improvement.csv`에 비교 수치를 저장하고 `protocol.json`에 평가 전 선정 모델과 입력 해시를 고정합니다.
한 학습 시드의 예비 독립 평가이며 테스트로 모델이나 설정을 다시 고르지 않습니다.
기존 검증 보고서 `preview_seed42`, 학습곡선 `learning_seed42`, 입력·모델·결과는 보존합니다.
기존 환경 검사 결과는 `results/fourphase/check_실행시각/summary.json`에서 확인합니다.
교통량 1,200/1,800/2,400 veh/h는 파일럿 후보이며 검증 후 최종 수준을 정합니다.
Mac 앱으로 보기와 SSH 연결 콘솔은 [4현시 실행 안내](docs/fourphase.md)에 있습니다.
이전 두 교차로 실험은 [기존 실행 안내](docs/corridor2.md)를 참고합니다.

R1 보상, 마스크 적용 Q-target, Truncation bootstrap과 검증 J 기반 모델 선정은 세 모델에 공통입니다.
학습은 Linux headless SUMO이며, 기존 DQN 모델과 입력·결과는 보존합니다.

## 기존에 확인한 작업

- Python 3.10.12, SUMO/TraCI/sumolib 1.28.0의 프로젝트 전용 `.venv`.
- 방향별 1개 진입 차로, 직진 전용 4개 경로, 250m 진입/유출 도로.
- 남북 녹색 30초 → 황색 3초 → 전적색 1초 → 동서 녹색 30초 → 황색 3초 → 전적색 1초.
- 시드로 생성하고 파일에 고정한 출발시각과 경로. 기본 시드 42에서 433대.
- 매초 대기행렬, 차량별 TripInfo, 차량 집계, 신호 제약 및 충돌 검사.
- Mac SUMO에 연결을 유지하는 개발 콘솔과 제어 Python 파일 다시 읽기 기능.
- 유지/전환 요청의 이산 행동, 최소/최대 녹색시간 제약, 누적 정지 차량-초 보상.
- 학습/검증/최종 평가 수요 분리, DQN 모델 저장, Fixed-time 비교표와 그래프 생성.
- Mac 도로 화면: 실제 신호 연동 램프, 자동차 형태·색상, 교차로 확대와 주변 풍경.
- 화양삼거리–어린이대공원역 수정본 `sejong2_v2`: 724대 전부 진입, 637대 도착, 87대 미완료, 충돌·텔레포트·신호 위반 0. 차량 집계·안전 검사 통과.

단일 교차로 첫 학습은 5,000회 행동을 완료했고, 저장된 평가 수요 5개 결과는 평균 대기시간
Fixed 11.08초, DQN 6.94초입니다. 여러 학습 시드에 대한 성능 검증은 아직 하지 않았습니다.
세종대 사례는 OSM 도로 형상에 가정 수요·신호를 적용한 선택 실험이며 실제 신호 운영을 재현·보정한 것은 아닙니다.

## 선택 사례: 지도 기반 두 교차로 고정신호

`sumo/sejong2_v2` 생성과 고정신호 실행은 사용자가 완료했습니다. 새 실행 결과를 저장하려면 원격 Linux에서 입력합니다.

```bash
.venv/bin/python scripts/run_sejong2_fixed.py --scenario sumo/sejong2_v2
```

OSM 도로 형상을 사용하고 수요·누락 차로 수·신호시간은 가정으로 기록합니다.
기존 입력·결과를 보존합니다. Mac 복사·화면 확인과 출력 해석은
[두 교차로 고정신호 안내](docs/sejong2_fixed.md)에 있습니다.

## 기존 단일 교차로 DQN 학습 절차

아래 명령은 원격 Linux 터미널에서 실행합니다. 학습은 Linux의 headless SUMO를 사용합니다.

```bash
.venv/bin/python -m pip install torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r requirements-dqn.txt
.venv/bin/python scripts/train_toy_dqn.py --timesteps 5000 --output results/dqn/first_run
```

완료 후 동일한 최종 평가 수요로 Fixed-time과 DQN을 비교합니다.

```bash
.venv/bin/python scripts/evaluate_toy_dqn.py --run results/dqn/first_run
```

Mac SUMO와 SSH 터널을 열어둔 상태에서 학습한 모델을 확인합니다.
개선된 화면은 [Mac 화면 설정 안내](docs/toy_visuals.md)에 따라 파일을 복사하고
`toy.gui.sumocfg`로 SUMO를 엽니다.

```bash
.venv/bin/python scripts/view_toy_env.py --model results/dqn/first_run/best_model.zip
```

연결 후 `sumo>`에 `resume`을 입력합니다. 이 모드에서는 가중치를 고정하고 DQN의 행동을 관찰합니다.
설정·데이터 분리·출력 파일·검증 명령은 [DQN 실행 안내](docs/toy_dqn.md)에 있습니다.

## 상태·행동·보상 수동 확인

원격 Linux에 추가 의존성을 설치한 뒤, Mac SUMO와 기존 SSH 터널을 연결해 실행합니다.

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/view_toy_env.py --warmup 0
```

`sumo>`에서 `action 0`은 유지, `action 1`은 전환 요청이며 **각각 시뮬레이션 5초**를 진행합니다.
실제 적용 여부, 보상, 대기행렬을 출력하고 `results/env/.../transitions.jsonl`에 기록합니다.
기본 Warm-up은 120초이며, 위 `--warmup 0`은 첫 시각 확인을 위한 설정입니다.
`--model` 없이 실행한 콘솔의 `resume`은 제어 파일의 간단한 규칙으로 자동 진행하며 학습하지 않습니다.

상태 정의, 사용 순서, 검증 명령은 [ToyTrafficEnv 안내](docs/toy_env.md)에 있습니다.

## 기존 녹색시간 조정 콘솔

Mac SUMO와 SSH 터널을 실행해 둔 뒤 원격 Linux 터미널에서 실행합니다.

```bash
.venv/bin/python scripts/view_mac.py
```

연결 후 `sumo>` 입력창에서 `resume`으로 시작합니다.
VS Code에서 `src/traffic/live_controller.py`를 수정할 때는
**`pause` → 파일 저장 → `reload` → `resume`** 순서로 반영합니다.
GUI와 연결은 유지됩니다. `reset`은 같은 창에서 처음부터 다시 시작하도록 초기화합니다.
1200초에 도달하거나 Ctrl+C를 눌러도 종료 대신 일시정지합니다. 종료 명령은 `quit`입니다.

Mac/Linux별 실행 명령과 조작 방법은 [Mac 개발 콘솔 안내](docs/mac_live_control.md)에 있습니다.
현재 개발 콘솔은 toy 사거리 전용이며, 아래 `run_fixed.py`의 재현 가능한 평가 실행과 별개입니다.
제어 파일 이외의 실행기 코드 변경은 Python 재시작이 필요합니다.

## 실행

프로젝트 폴더 안에서 실행합니다. 아래 명령은 기존 `.venv`를 사용합니다.

```bash
.venv/bin/python scripts/check_env.py
.venv/bin/python scripts/build_toy.py
.venv/bin/python scripts/run_fixed.py
.venv/bin/python -m unittest discover -s tests -v
```

`run_fixed.py`는 매 실행마다 `results/fixed/seed_<시드>_<UTC시각>/`을 만듭니다.
결과 위치를 정하려면 `--output results/fixed/my_run`을 붙입니다.
이미 파일이 있는 결과 폴더는 덮어쓰지 않습니다.
기존 검증 결과는 `results/fixed/validated_seed_42/metrics.json`에 있습니다.

새 환경에서는 Python 3.10 이상으로 가상환경을 만든 뒤 설치합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Ubuntu에서 `ensurepip`가 없어 가상환경 생성에 실패하면 `python3-venv`가 필요합니다.
이번 환경은 해당 패키지가 없어 Python 기본 `venv`가 만든 격리 환경에
PyPA의 공식 `https://bootstrap.pypa.io/get-pip.py`로 pip를 설치했습니다.
시스템 Python 패키지는 수정하지 않았습니다.

TraCI는 Python과 SUMO 사이에 로컬 TCP 연결이 필요합니다.
로컬 소켓 생성이 차단된 실행 환경에서는 권한을 허용한 후 실행해야 합니다.

## 시나리오와 평가

`configs/toy.json`에서 기본 시드·시간·교통량을 설정합니다.
최소 예제이므로 외부 YAML 라이브러리 없이 JSON을 사용합니다.

| 항목 | 기본값 |
|---|---|
| 시뮬레이션 | 0–1200초, 1초 간격 |
| Warm-up | 0–120초 |
| 차량 출발 예정 구간 | 0–1080초 |
| 남북 교통량 | 방향별 450대/시간 |
| 동서 교통량 | 방향별 300대/시간 |
| 차량 발생 | 지수분포의 도착 간격을 미리 생성한 명시적 차량 목록 |

`scripts/build_toy.py --seed 7`은 수요 파일을 새로 생성합니다.
반면 `scripts/run_fixed.py --seed 7`은 기존 수요를 유지하고 SUMO 내부 무작위 시드만 바꿉니다.
향후 Fixed-time과 DQN 비교 시 같은 수요 파일과 SUMO 시드를 사용해야 합니다.

시뮬레이션은 차량이 먼저 모두 도착해도 정해진 종료시각까지 실행합니다.
후반 120초는 수요가 없는 관측 구간이며, 모든 차량의 완료를 보장하는 조건은 아닙니다.
미완료 차량은 TripInfo에 포함하고, 출발 예정시각이 지났지만 도로에 삽입되지 못한 차량은 별도 집계합니다.

## 결과 파일

| 파일 | 내용 |
|---|---|
| `metrics.json`, `metrics.csv` | 요약 지표, 차량 수, 시드, 입력 해시, 검사 결과 |
| `queues.csv` | 매초 현시·신호 상태·방향별/전체 정지 차량 수 |
| `tripinfo.xml` | 도착 및 미완료 차량의 대기시간·통행시간 |
| `sumo_summary.xml`, `sumo.log` | SUMO 원시 집계와 실행 로그 |
| `toy.net.xml`, `toy.rou.xml`, `toy.sumocfg`, `demand.json`, `config.json` | 실행 시점 입력 사본 |

평균 대기시간의 대상은 **출발 예정시각이 Warm-up 이후이며 종료시각 이전인 차량 집단**입니다.
`cohort_mean_waiting_observed_s`는 그중 실제 출발한 차량의 관측 누적 대기시간 평균으로,
미완료 차량도 현재까지의 대기를 포함합니다. 미출발 차량의 삽입 전 대기는 포함하지 않습니다.
따라서 미완료·미출발 차량이 있으면 이 평균만으로 정책을 순위 매기면 안 됩니다.
완료 차량만의 평균, 출발 지연, 미출발 차량의 누적 삽입 전 대기도 따로 제공합니다.
통행시간 평균은 완료 차량 기준입니다.

대기행렬 지표는 `(120, 종료시각]`의 매초 네트워크 전체 정지 차량 수로 계산합니다.
차량별 대기시간 집계와 대기행렬 적분은 대상 차량 및 시간 범위가 다릅니다.
`network_queue_p95_vehicles`는 매초 전체 대기행렬의 nearest-rank 95백분위수입니다.
`arrived`는 전체 실행에서 도착한 차량 수이며, 측정 구간의 도착 수는 `arrived_during_measurement`입니다.

## 검증과 다음 단계

생성 직후와 TraCI 연결 직후에 실제 신호 인덱스가 의도한 진입 차로를 가리키는지 확인합니다.
실행 중 현시 순서·지속시간, 충돌, 텔레포트를 검사하며 차량 수를 TripInfo와 교차 확인합니다.
회귀 검사는 미완료·미출발·미래 출발 차량 구분, Warm-up 제외, 신호 방향 매핑 및 유효 경로를 다룹니다.

검증 결과와 한계는 [첫 실행 기록](docs/baseline_run.md)에 있습니다.
다음 작업은 **지도 기반 두 교차로 생성 → 고정신호 통행·집계 확인 → 중앙집중형 DQN 구현**입니다.
추가한 환경과 테스트는 사용자가 직접 실행해 확인합니다.

## 구현 참고

- [SUMO 가상환경 설치](https://sumo.dlr.de/docs/Downloads.php#python_packages__virtual_environments)
- [PlainXML 및 신호 연결 인덱스](https://sumo.dlr.de/docs/Networks/PlainXML.html)
- [Python TraCI 연결](https://sumo.dlr.de/docs/TraCI/Interfacing_TraCI_from_Python.html)
- [TripInfo 및 미완료 차량 기록](https://sumo.dlr.de/docs/Simulation/Output/TripInfo.html)
