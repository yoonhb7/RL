# RL1114 도시형 SUMO 화면 복제

2026-11-14, [yoonhb7/RL의 RL1114 브랜치](https://github.com/yoonhb7/RL/tree/RL1114)에서 가져왔습니다.
고정한 커밋은 `7fd00d77598da932f6f5130ffc8fd37a8f478492`입니다.
원본 위치는 `experiments/single-intersection-dqn-benchmark/`입니다.

## 복제한 범위

- 단일 교차로 J, 방향마다 1차로, 직진과 우회전 연결. 북/동/남/서 길이 300/350/400/450m.
- 건물·옥상·보도·주차장·가로수·공원·분수·벤치·횡단보도 도색.
- 실제 SUMO 차량에 부착되어 위치·회전을 따라가는 차체·창문·바퀴·전조등·후미등 도형.
- 실제 SUMO 신호 색상을 표시하는 큰 신호등 4개.
- 원본의 차량 생성 코드와 GUI 설정, PNG/SVG 미리보기.

`network/`의 XML, `gui.xml`, 서버의 `src/traffic/rl1114_scene/appearance.py`와 `scenario.py`는 원본 바이트를 유지했습니다.
복사 출처와 SHA-256은 `source_manifest.json`에 기록했습니다.
[원본 미리보기](preview/original.png)는 원본 저장소에 있던 차량 좌표 기반 그림입니다. 여기서 새로 실행해 캡처한 화면은 아닙니다.

DQN·Double·Dueling 학습기, 체크포인트, 보상 및 실험 작업표는 가져오지 않았습니다.
기존 toy·corridor2·세종대 네트워크와 학습 결과는 그대로 둡니다.

풍경과 자동차 세부 모양은 Python의 TraCI polygon 명령으로 그립니다. XML만 열면 이 장식이 생기지 않습니다.
아래 연결을 하면 Mac SUMO 화면에 원본 표시 코드가 적용됩니다. 큰 정보 카드나 대시보드는 추가하지 않습니다.
주차 차량·건물·횡단보도는 장식이며 물리 차량·보행 수요를 추가하지 않습니다.

## 실행 상태와 제어 방식

파일 복제와 정적 확인만 했습니다. **Python·SUMO·테스트·수요 생성은 여기서 실행하지 않았습니다.**
원본 저장소는 수요 XML을 실행 시 생성하므로 아래 준비 명령을 한 번 실행해야 합니다.
원본 pilot 설정의 환경 부분만 사용합니다. 출발 600초 + 잔여 처리 180초, 우회전 20%, 시드 1001입니다.
low/medium/high는 네 방향 합계 450/1500/3000대/시간이며 실제 표본 대수는 달라집니다.
차량 발생 알고리즘은 복사한 원본 `prepare_demand()`를 그대로 호출합니다.

이번 시연은 **복사한 net.xml의 기본 고정신호**로 움직입니다.
남북 녹색 42초 → 황색 3초 → 동서 녹색 42초 → 황색 3초입니다.
원본의 학습된 Double DQN 정책이나 Python 고정신호 제어기(녹색 30초)를 재생하는 것은 아닙니다.
화면·도로 구성 확인용이며 알고리즘 성능 평가 결과로 사용하지 않습니다.

## 1. 원격 Linux 터미널: 차량 파일 준비

VS Code의 원격 Linux 터미널에서 실행합니다. SUMO나 학습은 시작하지 않고 XML만 생성합니다.

```bash
cd "/home/oper/osh/RL Term Project"
.venv/bin/python scripts/prepare_rl1114_city.py
```

완료하면 `cases/low`, `cases/medium`, `cases/high`에 다음 파일이 생깁니다.
`view.sumocfg`, `demand.rou.xml`, `detectors.add.xml`, `demand.json`, `scene.json`.
상대 경로로 도로·차량·GUI 설정을 연결하므로 전체 `rl1114_city` 폴더를 Mac으로 복사합니다.
기존 `cases/`는 덮어쓰지 않습니다. 새 수요를 만들 때는 새 출력 폴더를 지정합니다.

```bash
.venv/bin/python scripts/prepare_rl1114_city.py --seed 1002 --output sumo/rl1114_city/cases_seed1002
```

이 경우 Mac 실행 경로의 `cases`도 `cases_seed1002`로 바꿉니다.

## 2. Mac 일반 터미널: 파일 복사

Linux에서 준비 명령이 성공한 뒤 Mac의 일반 터미널에서 입력합니다.

```bash
mkdir -p "$HOME/rl-term-project/rl1114_city"
ssh USER@SERVER 'tar -C "/home/oper/osh/RL Term Project/sumo/rl1114_city" -cf - .' \
  | tar -xf - -C "$HOME/rl-term-project/rl1114_city"
```

Python 표시 코드는 서버에서 실행하므로 Mac에 복사할 필요가 없습니다.

## 3. Mac 터미널 A: 기존 SSH 터널 유지

이미 아래 터널이 실행 중이면 그대로 사용합니다. 없다면 새 Mac 터미널에서 실행해 열어둡니다.

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -R 127.0.0.1:18813:127.0.0.1:8813 \
  USER@SERVER
```

## 4. Mac 터미널 B: SUMO 실행

기존 포트 8813을 사용하는 SUMO는 먼저 해당 창/터미널에서 종료합니다.

```bash
sumo-gui \
  -c "$HOME/rl-term-project/rl1114_city/cases/medium/view.sumocfg" \
  --remote-port 8813 \
  --start
```

## 5. 원격 Linux: 도시 장면 연결

```bash
cd "/home/oper/osh/RL Term Project"
.venv/bin/python scripts/view_rl1114_city.py
```

연결하면 원본 풍경과 자동차 모양을 적용하고 0초에서 기다립니다.
`sumo>` 입력창에 아래를 입력합니다.

```text
resume
```

이후 사용할 수 있는 명령은 다음과 같습니다.

| 명령 | 동작 |
|---|---|
| `pause`, Ctrl+C | 일시정지, 연결 유지 |
| `resume` | 자동 진행 |
| `step 10` | 시뮬레이션 10초 진행 후 정지 |
| `reset` | 같은 창·같은 수요/시드로 0초부터 재시작 |
| `level high` | 고수요로 바꾸고 0초에서 대기. 이어 `resume` |
| `level low`, `level medium` | 저·중 수요로 바꾸고 초기화 |
| `view city` | 건물과 공원을 포함하는 도시 화면 |
| `view junction` | 교차로 확대 |
| `view map` | 물리 도로망 전체 |
| `status` | 시간·신호·차량 수 확인 |
| `delay 0.03` | 진행 속도 조정 |
| `reload` | 저장한 표시 코드를 다시 읽기, 차량·시각 유지 |
| `quit` | 연결 최종 종료 |

780초에 도달해도 창과 연결을 유지하므로 `reset` 또는 `level high`로 다시 볼 수 있습니다.
차량 색상은 북쪽 빨강·동쪽 파랑·남쪽 노랑·서쪽 초록입니다.

화면을 수정하려면 서버의 `src/traffic/rl1114_scene/appearance.py`를 편집하고
`pause → 저장 → reload → resume` 순서로 반영합니다. 도로·수요 XML을 바꿨다면 Mac으로 다시 복사해야 합니다.
현재 카메라는 Mac에서 도시 장면을 보기 위해 조정했습니다. 원본 장식 도형과 물리 도로는 유지했습니다.

원본 표시 코드에 따라 180초의 장면 JSON/SVG를 서버의 `results/rl1114_city/view_<시각>/episode_<번호>_<수요>/`에 저장합니다.
이 저장 파일은 실제 시뮬레이션 좌표의 벡터 장면이며 Mac GUI 픽셀 캡처가 아닙니다.

## 파일 위치

- `sumo/rl1114_city/network/`: 원본 도로 XML.
- `sumo/rl1114_city/gui.xml`: 원본 GUI 설정. 상세 도형과 겹치지 않도록 기본 차량은 작게 표시합니다.
- `sumo/rl1114_city/scene_settings.json`: 원본 pilot의 환경 설정만 추출한 값.
- `src/traffic/rl1114_scene/appearance.py`: 원본 도시·차량 표시 코드.
- `src/traffic/rl1114_scene/scenario.py`: 원본 SUMO 입력/차량 생성 코드.
- `src/traffic/rl1114_scene/common.py`, `session.py`: 현재 프로젝트 경로 및 Mac 지속 연결을 위한 어댑터.
- `scripts/prepare_rl1114_city.py`, `scripts/view_rl1114_city.py`: 사용자가 실행하는 준비/시연 명령.
- `source/CITY_VIEW_KO.md`: 원본 작성자의 화면 설명 및 검증 기록. 여기서 재검증한 결과와 구분합니다.
