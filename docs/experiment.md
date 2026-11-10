# 실험 조건과 해석

## 비교 단위

한 번의 실험은 고정된 도로망, 명시적 차량 경로·출발시각 파일, SUMO seed, 제어기, 900초 종료시각으로 정의합니다. 현재 합성 설정은 첫 600초에 수요가 발생하고 이후 300초 동안 추가 출발 생성 없이 잔여 차량을 처리합니다. 완전히 비어도 동일한 900초까지 진행합니다. warm-up은 0초이며, 초기 신호는 남북 녹색입니다. 실제 교통에 적용할 때는 warm-up과 측정 구간을 별도로 구현·고정해야 합니다.

동서 경계 유입은 방향별 평균 600대/시간, 각 교차로 남북 유입은 방향별 평균 250대/시간의 지수분포 도착 간격으로 생성합니다. 차량 경로와 출발시각을 먼저 XML에 확정하고 모든 방법이 같은 파일을 사용합니다. 무작위 SUMO flow를 제어기별로 따로 생성하지 않습니다. 실제 차종 비율·회전교통·유입 패턴을 나타내는 수요는 아닙니다.

평가 시드 1001~1005는 학습 시드 0~19와 분리했습니다. 각 정책의 학습 모델은 마지막 학습 에피소드의 모델이며, 평가 시드로 최상의 모델을 고르지 않았습니다. 현재는 네트워크당 **한 번의 학습 실행**입니다. 여러 평가 시드의 표준편차가 학습 초기화 변동성까지 설명하지는 않습니다. 연구 결과를 주장하려면 독립된 학습 시드도 여러 번 사용해야 합니다.

## 같은 제약으로 비교하기

`fixed`는 30초 녹색과 3초 황색·2초 전적색을 순환합니다. `queue`는 현재와 다음 녹색에서 서비스할 차로의 정지 차량 수를 비교하는 간단한 규칙입니다. SUMO의 검지기 기반 actuated와는 다릅니다. `dqn`은 하나의 중앙 신경망으로 공동 행동을 선택합니다. 세 방법 모두 같은 최소·최대 녹색과 동일한 전환 상태기를 사용합니다.

`native`는 네트워크 또는 additional XML의 SUMO 프로그램을 그대로 실행합니다. 실제 고정신호의 불균등 현시시간과 Offset을 보존하기 위한 별도 실행 모드입니다. 자체 안전 상태기를 덮어쓰지 않으므로, 실제 신호와 RL에 허용한 운영 제약을 수동으로 대조해야 합니다. 현재 RL은 유지/다음 현시 제어라서 기존 Offset·주기를 보존하지 않습니다. 이것을 Offset 보존 방식과 동등한 제어 권한으로 간주하지 않습니다.

## 지표 정의

| 필드 | 의미 / 주의 |
|---|---|
| `mean_wait_arrived_s` | 도착 차량의 SUMO `waitingTime` 평균. 완료 차량만 보면 선택 편향 가능 |
| `mean_wait_departed_censored_s` | 미완료 출발 차량까지 포함한 종료시점 관측 대기 평균. 미래 대기를 제외한 하한값 |
| `mean_travel_arrived_s` | 도착 차량 통행시간 평균 |
| `mean_depart_delay_departed_s` | 실제 출발 차량의 삽입 지연 평균. 미출발 차량은 여기에 없음 |
| `scheduled` | 명시적 route 파일에 예정된 전체 차량 수 |
| `departed` | SUMO에 실제 삽입된 차량 수 |
| `arrived` | 목적지까지 완료한 차량 수. 개별 교차로 통과량과 다름 |
| `unfinished` | 종료시점 네트워크에 남아 있는 차량 수 |
| `not_departed` | 예정됐으나 종료시점까지 삽입되지 않은 차량 수 |
| `queue_vehicle_seconds` | 매초 모든 비내부 차로 정지 차량 수의 합. 보상의 원래 물리량 |
| `pending_vehicle_seconds` | 매초 출발 예정시각을 지났으나 삽입되지 않은 차량 수의 합 |
| `mean_queue_vehicles`, `p95_queue_vehicles` | 매초 네트워크 총 정지 차량 수의 평균·95백분위. 차로별 P95 또는 길이(m)가 아님 |
| `switches` | 전환 요청이 실제 황색을 시작한 횟수. native에는 집계하지 않음 |
| `collision_events`, `teleports` | SUMO에서 보고한 사건 집계. 고유 차량/사고 수와 동일한 정의는 아님 |

대기의 정의와 미완료 기록은 [SUMO TripInfo](https://sumo.dlr.de/docs/Simulation/Output/TripInfo.html)를 따릅니다. `--tripinfo-output.write-unfinished true`를 사용합니다. 이 값으로 미출발 차량까지 자동으로 평균에 포함했다고 주장하지 않습니다. 미출발은 XML의 예정 수와 실시간 departed 수를 대조해 따로 집계합니다.

차량 수 보존식은 `scheduled = arrived + unfinished + not_departed`입니다. 충돌 제거·teleport 같은 예외가 없는지 확인하고, TripInfo의 완료/미완료 출발 행 수와 실시간 집계를 대조합니다. 평가 함수는 불일치 또는 충돌·teleport가 있으면 실패합니다.

보상은 모든 비내부 차로를 대상으로 하며, 진입 차로 관측보다 넓은 범위를 봅니다. 내부 교차로 차로의 정지 차량과 경계 바깥 대기는 보상에서 제외됩니다. 미출발이 증가하는 과포화 실험은 `pending_vehicle_seconds`까지 함께 해석해야 합니다. 이 버전은 교차로별 CSV 대기행렬 분해·보행자·배출량·TTC를 별도로 집계하지 않습니다.

## 결과 집계

`summary.csv`는 각 평가 시드에 동등한 가중치를 부여한 평균과 표본 표준편차(ddof=1)입니다. 전체 차량을 합쳐 가중평균한 결과와는 다릅니다. `paired.csv`는 같은 시드의 고정신호 값과 비교한 감소율을 기록합니다. 고정신호 대기가 0이면 감소율을 비워 둡니다.

감소율은 `100 × (고정신호 대기 - 비교방법 대기) / 고정신호 대기`입니다. “시드별 감소율 평균”과 “두 방법의 평균 대기값으로 계산한 감소율”은 다를 수 있으므로 보고서에서 사용한 방식을 표시하세요.

동일 파일 여부는 SHA-256으로 확인합니다. 네트워크 내용·진입 차로 순서·신호 상태/제약·의사결정 간격이 다른 모델은 로드하지 않습니다. 모델은 추론 가중치이며 optimizer·replay를 포함한 중단 시점 학습 재개 파일은 아닙니다.

## 확장 실험 예시

```powershell
# 수요를 20% 높인 합성 일반화 평가. 기본 평가와 다른 결과 폴더 사용.
python run.py evaluate --scenario sumo/corridor2 --model results/verified/corridor2-train/model.pt --controllers fixed queue dqn --seeds 2001 2002 2003 2004 2005 --scale 1.2 --out results/local/corridor2-demand120

# 별도 학습 초기화·수요 시드로 독립된 학습 반복
python run.py train --scenario sumo/corridor2 --episodes 100 --seed 100 --out results/local/corridor2-train-seed100

# Double DQN 비교
python run.py train --scenario sumo/corridor2 --episodes 100 --seed 100 --double --out results/local/corridor2-double-seed100
```

시드만 바꾸면 교통량 규모·회전 비율이 다른 시간대로 일반화한 것이 아닙니다. `--scale`은 합성 유입률만 바꿉니다. 실제 자료에는 시간대별로 별도 보정한 route 파일을 준비합니다. 최종 연구에서는 적절히 조정한 고정신호, 검지기 기반 actuated, 강한 규칙 기준선과 비교하고, 개선이 제어 권한 차이 때문인지도 검토해야 합니다.
