# 4현시 교차로 도시 배경과 실시간 신호등

기존 RL1114 도시 화면의 건물·공원·주차장·차량 표현을 새 도로 폭에 맞게 구성했다.
**방향마다 가로형 4색 신호등 하나씩, 총 4개**를 표시한다.
한 본체의 등화 순서는 **적색·황색·좌회전 화살표·직진 녹색**이다.
방향별 직진/좌회전 SUMO 제어 링크 두 개를 읽어서 하나의 신호등에 합친다.
직진 현시에는 녹색, 보호 좌회전 현시에는 적색+좌회전 화살표, 전환에는 황색,
전적색에는 적색을 표시한다. 흰색 강조 원은 사용하지 않는다.

주변에는 지붕 설비·창문·태양광 패널이 있는 건물, 분수·벤치가 있는 공원, 주차된 차량,
보도블록·가로수·가로등을 추가했다. 큰 정보 카드·텍스트 패널은 넣지 않았다.
기본 차량은 SUMO의 상세 승용차 표시로 그린다. 선택 옵션 `--detailed-cars`는 실제 차량에 연결한
별도 차체·유리·등화 도형을 사용하지만 원격 표시 작업이 늘어난다.

## 실행 상태와 실험 입력

Python·SUMO·netconvert·테스트는 코드 작성 과정에서 실행하지 않았다.
아래 생성 명령을 사용자가 실행하면 도시 표시 파일이 생성된다.

- 원본 `sumo/fourphase`는 수정하지 않는다.
- 새 `sumo/fourphase_city`에 **같은 도로·수요·고정신호**를 복사하고 SHA-256 일치를 검사한다.
- `run.sumocfg`는 원본과 동일하며, 화면용 `view.sumocfg`에만 그래픽 파일을 추가한다.
- 배경은 `poly`만 사용한다. 보행자·도로·신호 프로그램·장식용 차량 수요를 생성하지 않는다.
- 연구용 Fixed-time/무작위 파일럿 결과는 기존 결과 폴더에 그대로 둔다.

## 1. 원격 Linux VS Code 터미널: 도시 표시 입력 생성

```bash
cd "/path/to/RL/experiments/fourphase-dqn-comparison"
.venv/bin/python scripts/prepare_fourphase_city.py
```

netconvert나 SUMO를 실행하지 않고 기존 검증 입력을 복사하고 도형 XML을 작성한다.
이미 출력 폴더가 있으면 `--output sumo/fourphase_city_v2`처럼 새 경로를 사용한다.

## 2. Mac 로컬 터미널: 복사

```bash
mkdir -p "$HOME/rl-term-project/fourphase_city"
ssh USER@SERVER 'tar -C "/path/to/RL/experiments/fourphase-dqn-comparison/sumo/fourphase_city" -cf - .' \
  | tar -xf - -C "$HOME/rl-term-project/fourphase_city"
```

## 3. Mac 터미널 A: 기존 SSH 터널 사용

같은 터널이 켜져 있으면 다시 만들지 않고 계속 사용한다. 없으면 아래 명령을 실행하고 열어 둔다.

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -R 127.0.0.1:18813:127.0.0.1:8813 \
  USER@SERVER
```

## 4. Mac 터미널 B: 새 도시 화면 열기

이전 SUMO 창을 닫고 입력한다.

```bash
sumo-gui \
  -c "$HOME/rl-term-project/fourphase_city/cases/medium/seed_42/view.sumocfg" \
  --remote-port 8813 --start
```

연결 대기 중에는 시뮬레이션이 진행되지 않는다.

## 5. 원격 Linux VS Code 터미널: 세부 표시 연결 및 연속 재생

```bash
cd "/path/to/RL/experiments/fourphase-dqn-comparison"
.venv/bin/python scripts/view_fourphase.py \
  --scenario sumo/fourphase_city --autorun
```

건물·공원과 방향별 4색 신호등 4개, SUMO 상세 승용차가 표시된다.
현재 정책은 Fixed-time이며 신경망 학습은 하지 않는다. GUI 재생 버튼 대신 이 콘솔에서 진행을 제어한다.

[DQN 파일럿](fourphase_dqn.md)을 완료하면 같은 명령에 `--model results/fourphase_dqn/pilot_seed42/best_model.pt`를
추가해 학습된 정책을 볼 수 있다. 기본 모드는 DQN으로 바뀌고, 신경망 업데이트 없이 탐욕적 유효 행동을 선택한다.
`mode fixed` / `mode dqn`으로 같은 수요를 reset하여 비교할 수 있다.

**연결 후 Mac SUMO 상단 `Delay (ms)`를 직접 조절한다.** `1000`은 시뮬레이션 1초당 약 실제 1초,
`0`은 처리 가능한 최대 속도다. 계산·통신이 더 오래 걸리는 경우에는 그 처리 시간이 하한이 된다.
Python은 `sleep`이나 별도의 재생 지연을 넣지 않는다. 기존 `delay`/`--delay`는 속도를 바꾸지 않고
GUI 조절 안내만 표시한다. 새로 준비하는 도시 화면의 기본 GUI 지연은 1000ms다.

**원격 터미널의 `sumo>`에서:**

```text
pause
view junction
resume
```

- `view city`: 주변 도시 전체. `view junction`: 차로·신호등 확대. `view map`: 전체 도로망.
- `pause` 또는 `Ctrl+C`: 현재 1초 스텝을 마친 뒤 일시정지. `resume`: 연속 재생.
- `step 1`: 정확히 시뮬레이션 1초를 진행하고 정지. `step 15`는 15초다.
- 속도 조절은 Mac 상단 `Delay (ms)`만 사용한다. 이미 생성한 도시 XML도 보존하며 GUI에서 직접 조절한다.
- `reset`: 같은 SUMO 창을 0초로 초기화하고 일시정지. 이후 `resume`으로 재개.
- `reload`: 도시 표시 Python 코드를 다시 읽고 도형만 재구성. 현재 교통 상태·시간은 유지한다.
- 이전 8개 신호등 화면도 `pause → reload → resume`으로 4개로 갱신할 수 있다. 원래 8개 신호등이 들어 있는 Mac 파일로 reset해도 연결 시 표시를 자동 교체한다. Mac 단독 배경 파일에도 반영하려면 새 `--output sumo/fourphase_city_v2`로 준비하고 복사한다.
- `mode random`: 0초로 reset해 유효 무작위 행동 시연. `action 0/1`은 각각 15초.
- `quit`: 연결 종료. 터널은 Mac 터미널 A에서 `Ctrl+C`로 종료한다.

기본 실행은 차량을 SUMO에 맡긴다. `--detailed-cars`를 추가하면 별도 차체 도형을 사용한다.
`--native-cars`도 기존 명령 호환용으로 지원한다.

화면 루프는 매번 정확히 1초만 진행하고 콘솔 입력을 다시 확인한다.
차로·시각·신호·출발/도착·Pending·안전 정보는 TraCI subscription으로 해당 스텝 응답에서 함께 받는다.
연구용 행동 간격은 15초 그대로이며, 중간에 일시정지해도 행동을 바꾸거나 부분 보상을 Replay에 넣지 않는다.
원격 표시용 조회 방식만 변경하며 headless 검증의 기본 조회 방식은 유지한다.

이 재생 루프 변경은 `reload`만으로 적용되지 않는다. 기존 콘솔을 `quit`한 뒤 Mac SUMO와 Python을
한 번 재시작한다. SSH 터널과 도로·수요 파일은 그대로 사용할 수 있다.

## Mac 단독으로 배경만 확인

```bash
sumo-gui \
  -c "$HOME/rl-term-project/fourphase_city/cases/medium/seed_42/view.sumocfg" \
  --start
```

이 방식은 건물·공원·기본 차량·기본 정지선 신호를 표시한다.
**세부 신호등 도형의 점등은 Python 연결이 필요하다.** 연결 전에는 세부 신호등 전구를 모두 꺼 둬
실제와 다른 점등 상태를 표시하지 않는다. 차량이 중앙까지 접근하려면 약 35초가 걸릴 수 있다.

## 표시 코드 확인용 테스트

원격 Linux에서 사용자가 필요할 때 실행한다. SUMO 실행이나 SSH 연결 없이 가짜 TraCI로 검사한다.

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_fourphase*.py' -v
```

4색 신호등 4개의 12단계별 점등, 기존 8개 표시 교체, 원본 도로 위 장식 침범 여부, 장식 파일에 교통 객체가 없는지,
표시 코드가 신호·차량 동역학을 제어하지 않는지, 도착 차량의 도형 정리를 확인한다.

SUMO 표시 도형과 차량 추적 방식은 [Shapes](https://eclipse.dev/sumo/docs/Simulation/Shapes.html)와
[TraCI Polygon](https://eclipse.dev/sumo/docs/TraCI/Change_Polygon_State.html)을 따른다.
