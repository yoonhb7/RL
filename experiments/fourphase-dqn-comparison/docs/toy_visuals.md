# Mac SUMO 도로 화면

화면은 교차로·차량·실제 신호와 주변 풍경을 중심으로 보여줍니다.
큰 정보 카드, 방향별 숫자 박스, 그래프, 건물 간판과 화면 위 글씨는 제거했습니다.
행동·보상·대기 차량 수는 기존 원격 Linux의 콘솔과 결과 파일에서 확인합니다.

남아 있는 요소는 세단 형태와 8색 차량, 실제 신호 상태를 따라 켜지는 작은 3색 신호등,
정지선·진행 화살표, 건물·나무·공원·주차 차량 장식입니다.
전구 바깥의 반투명 빛 번짐 원은 제거했으며, 켜진 전구만 밝은 신호 색상으로 표시합니다.
기본 시점은 교차로와 주변 블록이 잘 보이도록 이전보다 확대했습니다.
주변 건물과 주차 차량은 가상 장식이며 시뮬레이션 교통량에는 포함되지 않습니다.

## 이번 수정 적용

기존 **원격 Linux `sumo>`**에서 `quit`을 입력하고 Mac SUMO 창을 닫습니다.
화면 모듈을 바꿨으므로 Python도 재실행합니다. 연결된 SSH 터널은 계속 유지합니다.

**Mac 일반 터미널: 파일 복사**

```bash
mkdir -p "$HOME/rl-term-project/toy"
ssh USER@SERVER 'tar -C "/path/to/RL/experiments/fourphase-dqn-comparison/sumo/toy" -cf - .' \
  | tar -xf - -C "$HOME/rl-term-project/toy"
```

**Mac 터미널: SUMO 실행**

```bash
sumo-gui \
  -c "$HOME/rl-term-project/toy/toy.gui.sumocfg" \
  --remote-port 8813 \
  --start
```

SSH 터널이 없을 때만 다른 Mac 터미널에서 아래 명령으로 열고 유지합니다.

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -R 127.0.0.1:18813:127.0.0.1:8813 \
  USER@SERVER
```

**원격 Linux 터미널: 모델 연결**

```bash
cd "/path/to/RL/experiments/fourphase-dqn-comparison"
.venv/bin/python scripts/view_toy_env.py --model results/dqn/first_run/best_model.zip
```

연결 후 **`sumo>`**에서:

```text
resume
```

저장한 DQN으로 추론하며 학습 때와 같은 Warm-up을 사용합니다.
`--model`을 빼면 기존 규칙 제어 모드입니다.

## 조작

다음 명령은 **원격 Linux의 `sumo>`**에서 입력합니다.

| 명령 | 동작 |
|---|---|
| `view overview` | 교차로와 건물·공원이 함께 보이는 기본 시점 |
| `view junction` | 차량과 신호등을 더 크게 보기 |
| `colors fleet` | 8색 차량 팔레트 |
| `colors waiting` | 연속 대기시간: 0초 파랑 → 5초 청록 → 15초 노랑 → 30초 분홍 → 60초 빨강 |
| `colors speed` | 정지 분홍 → 10km/h 노랑 → 30km/h 청록 → 50km/h 파랑 |
| `status` | 콘솔에서 상태·행동·보상·방향별 차량 수 확인 |
| `pause` / `resume` | 일시정지 / 진행 |
| `step` / `step 5` | 행동 1회 / 5회 수행. 기본 행동 1회는 시뮬레이션 5초 |
| `delay 0.15` | 시뮬레이션 1초마다 실제 0.15초 대기. 통신·그리기 시간은 별도 |
| `reset` | 같은 연결에서 초기화. 선택한 색상·카메라는 유지 |
| `screenshot` | 다음 진행 때 Mac의 toy 폴더에 PNG 저장 요청 |

화면 저장은 `screenshot`을 입력한 뒤 `step` 또는 `resume`으로 진행해야 실행됩니다.
Mac에 존재하는 폴더의 절대 경로도 지정할 수 있습니다.

```text
pause
screenshot /Users/k2/Desktop/junction.png
step
```

카메라·색상 변경 자체는 시간을 진행시키지 않습니다. 마우스로 이동·확대할 수도 있습니다.

## 적용 범위와 확인

`src/traffic/gui_presentation.py`가 도로 장식과 실제 신호 연동을 담당합니다.
`toy.view.xml`에는 Fleet / Waiting / Speed의 화면 설정이 있습니다.
학습·평가는 기존 `toy.sumocfg`를 사용하며 시각화 관찰자는 연결하지 않습니다.
화면 코드는 GUI·polygon·차량 그림 속성만 바꾸며 시간·신호·속도·경로·물리 크기는 바꾸지 않습니다.
`--no-visuals`는 Python에서 추가하는 도로 장식을 끕니다.

서버 XML 수정은 Mac으로 다시 복사하고 `sumo>`에서 `reset`합니다.
Python 화면 모듈 수정은 Python과 SUMO 연결을 다시 시작해야 합니다.
기존 `reload`는 제어 코드나 모델만 다시 읽습니다.

사용자가 원격 Linux에서 실행할 수 있는 검증 명령:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

GUI 테스트는 가짜 TraCI 객체를 사용하며, 실제 현시별 램프 연결·도착 차량 처리·정보 박스 미생성·
화면 오류 복구·물리 제어 미호출·관찰 콜백 전후 같은 MDP 전이를 검사합니다.
이번 수정에서는 정적 검토만 했으며 Python·테스트·SUMO 실행과 실제 Mac 화면 확인은 하지 않았습니다.
