# 세종대 실제 도로 2~3개 교차로로 옮기기

현재 전달한 것은 합성 SUMO 네트워크와 중앙 DQN 실행 파이프라인입니다. 실제 교차로 위치·차로 연결·운영 현시·교통량 자료가 첨부되어 있지 않으므로 실제 도로의 검증 완료를 주장할 수 없습니다. 아래 순서로 자료를 채우면 환경 코드를 재사용할 수 있습니다.

## 1. 대상 교차로 선정과 도로망 생성

실제 제어할 연속 교차로 2개부터 선정하고 중심좌표, 연결도로 길이, 각 진입 차로의 좌회전·직진·우회전 허용을 기록합니다. OSM으로 구조를 가져온 뒤 netedit에서 현장 자료와 대조합니다. OSM의 차로 정보와 자동 생성 신호는 현장 운영값으로 간주하지 않습니다.

[SUMO OSMWebWizard 공식 안내](https://sumo.dlr.de/docs/Tutorials/OSMWebWizard.html)를 따라 영역을 선택하거나, 이미 확보한 OSM 파일을 변환합니다.

```powershell
# 지도에서 확보한 study_area.osm.xml을 입력할 때의 예시
netconvert --osm-files data/raw/study_area.osm.xml --output-file sumo/sejong/sejong.net.xml --tls.default-type static
python run.py inspect --net sumo/sejong/sejong.net.xml --out data/processed/sejong-inventory.json
netedit -s sumo/sejong/sejong.net.xml
```

위 명령 전에 `data/raw`, `data/processed`, `sumo/sejong` 폴더를 생성하세요. 명령의 `netconvert`, `netedit`가 PATH에 없으면 `doctor`가 출력한 실행파일 전체 경로를 사용하면 됩니다. 추후 관측·보상이 제어 구간을 대표하도록 네트워크 경계를 충분한 거리에서 자르고 외부 유입 대기 문제를 확인합니다.

`inspect`는 완성된 `.net.xml`의 실제 TLS ID, linkIndex, from/to 차로, 방향(dir), 저장된 프로그램과 현시를 JSON으로 추출합니다. **신호 상태 문자열의 각 글자는 이 최종 linkIndex에 대응**합니다. 차로 목록 순서와 신호 글자 순서를 같다고 가정하면 안 됩니다.

## 2. 현장 자료 수집

`data/templates/`의 CSV 3개를 복사해 작성하세요. 빈 양식이며 현장 값이나 가짜 측정값을 넣지 않았습니다.

- 교통량: 5~15분 단위, 진입방향별 직진·좌회전·우회전 수. 가능하면 실제 경로가 여러 교차로를 어떻게 통과하는지도 확인.
- 신호: 현시별 허용 움직임, 녹색·황색·전적색 시간, 주기와 교차로 간 Offset. 여러 주기를 같은 기준시각으로 관측.
- 보정: 도로별 진입·유출량, 최대 대기행렬과 평균 구간 이동시간, 조사 시각과 자료 출처.

공공자료는 조사 지점과 선정 교차로의 공간적 일치부터 확인해야 합니다. 계획서의 TOPIS·공공데이터 링크는 후보 출처이며 이번 구현에서 해당 교차로의 자료를 확보한 것은 아닙니다.

## 3. 실제 고정신호와 수요 먼저 실행

실제 신호는 `.net.xml` 안의 프로그램 또는 별도 `field-signals.add.xml`로 저장합니다. 후자는 manifest의 `additional_files`에 연결합니다. 실제 고정신호를 실행할 때는 `native`를 사용하세요. 단순한 30초 고정신호와 혼동하지 않도록 결과에 `native` 이름을 남깁니다.

수요는 명시적인 `<vehicle depart="초">`와 유효 route로 작성합니다. 이 버전의 정확한 차량 수 집계는 수치 출발시각이 있는 차량을 전제로 합니다. `<flow>`·`<trip>`·`depart="triggered"`는 먼저 route 생성기로 확정해야 합니다. 모든 출발시각은 0 이상 horizon 미만이어야 합니다. 학습·평가용 수요는 물리적으로 연결된 경로와 회전 수가 관측량을 재현하는지 검증합니다.

관측 회전량이 있는 경우 [SUMO routeSampler 안내](https://sumo.dlr.de/docs/Demand/Routes_from_Observation_Points.html)를 참고하세요. 이 프로젝트의 합성 수요 생성기는 실측 회전량을 자동 추정하지 않습니다.

## 4. 실제 시나리오 manifest 작성

`sumo/sejong/manifest.json` 예시 구조입니다. **아래 TLS·차로·상태 문자열과 시간은 설명용입니다. 실제 네트워크에 그대로 실행하지 마세요.** 필요하면 `sumo/corridor2/manifest.json`의 구조와 `inspect` 결과를 나란히 보며 작성합니다.

```json
{
  "name": "sejong-observed-period",
  "synthetic": false,
  "net_file": "sejong.net.xml",
  "route_file": "observed-period.rou.xml",
  "additional_files": ["field-signals.add.xml"],
  "demand_seconds": 3600,
  "horizon_seconds": 4200,
  "decision_seconds": 5,
  "signals": [
    {
      "id": "REPLACE_WITH_ACTUAL_TLS_ID",
      "lanes": ["REPLACE_WITH_ACTUAL_INCOMING_LANE_IDS"],
      "greens": ["GrGr", "rGrG"],
      "yellows": ["yryr", "ryry"],
      "all_red_state": "rrrr",
      "min_green": 10,
      "max_green": 60,
      "yellow": 3,
      "all_red": 2,
      "fixed_green": 30
    }
  ]
}
```

`signals`에 실제 2~3개의 객체를 넣습니다. `lanes`에는 해당 신호의 모든 제어 진입 차로를 빠짐없이 한 번씩 기록합니다. `greens`는 승인된 안전한 현시의 순서이며 두 개 이상 가능합니다. `yellows`는 각 녹색 상태에서 녹색이던 글자만 `y`로 바꾼 상태입니다. 전적색은 모두 `r`이어야 합니다. 차량 현시의 순서를 유지하며 `다음 현시`로만 넘어갑니다.

이 버전의 RL 안전기는 **교차로별 공통 최소·최대 녹색, 공통 황색·전적색**을 가정합니다. `fixed_green`은 연습용 고정신호의 공통 녹색시간이므로 실제 native 프로그램의 불균등 시간과 Offset을 표현하는 값이 아닙니다. 실제 현시마다 최소시간이 다르거나 전환 조합별 clearance가 다르면 `SafetySignal`과 스키마를 먼저 확장해야 합니다. 보행자와 permissive turn을 포함한 실도로 신호에 이 기본 설정을 그대로 적용하지 않습니다.

추가 신호 XML을 쓰지 않으면 `additional_files` 키를 삭제하세요. 문서의 예시가 아니라, 실제 SUMO 링크에 대응하고 현장 자료로 확인한 상태를 사용해야 합니다. 수동 상태 제어의 동작은 [SUMO 신호 제어 공식 문서](https://sumo.dlr.de/docs/Simulation/Traffic_Lights.html)를 참고하세요.

## 5. 보정과 학습 연결

```powershell
python run.py evaluate --scenario sumo/sejong --controllers native --seeds 1001 1002 1003 1004 1005 --out results/local/sejong-field-baseline
python run.py train --scenario sumo/sejong --episodes 100 --out results/local/sejong-train
python run.py evaluate --scenario sumo/sejong --model results/local/sejong-train/model.pt --controllers native queue dqn --seeds 1001 1002 1003 1004 1005 --out results/local/sejong-evaluation
```

native 실험의 수요는 주어진 실제 route 파일로 고정되며, seed를 바꾸면 주로 SUMO의 확률적 차량 거동이 바뀝니다. 서로 다른 관측 시간대의 수요 일반화는 파일·시나리오를 별도로 준비해야 합니다. 실제 수요에서 `--scale`은 지원하지 않습니다.

**중요:** 실제 route 파일 하나를 학습·평가에 같이 쓰면 SUMO seed가 달라도 독립된 교통 수요에 대한 일반화 검증은 아닙니다. 학습 시간대용 manifest와 평가 시간대용 manifest를 별도 폴더에 만들고 같은 네트워크·신호·관측 스키마를 유지하세요. 기본 loader는 네트워크·신호 스키마는 검사하지만 실측 데이터 분할까지 대신 결정하지는 않습니다.

실제 관측 교통량·대기행렬·통행시간과 native 시뮬레이션을 먼저 비교해 `calibration.csv`를 작성합니다. 허용 오차 기준과 근거를 문서에 남기고, 보정에 사용하지 않은 시간대도 확인합니다. 이 단계가 끝난 뒤 실제 도로에서의 DQN 개선 효과를 해석할 수 있습니다. 신호를 합성 기본값으로 둔 채 “실제 운영 대비 개선”이라고 쓰지 마세요.

## 실제 자료를 받으면 이어서 해야 할 코드 작업

1. 해당 지점의 좌·우회전과 보행자 연결을 반영한 네트워크 검증.
2. 관측량으로 보정한 route 파일 및 시간대 분할 구축.
3. 실제 현시별 시간·Offset을 보존한 native baseline 확정.
4. 현시별 최소 녹색·보행 횡단·전환별 clearance를 반영한 안전기 확장.
5. 필요하면 warm-up 이후 측정·교차로별 queue·구간 통행시간 계측 추가.
6. 독립 학습 반복과 강한 규칙·actuated 기준선 비교.

현재 자료만으로 이 작업을 완료했다고 표시하지 않았습니다. 대신 합성 실험으로 먼저 학습과 평가 연결을 확인할 수 있게 했습니다.
