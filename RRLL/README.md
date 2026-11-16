# SUMO 4현시 단일 교차로 — DQN · Double DQN · Dueling DQN 학습

보호좌회전 4현시 교차로에서 세 DQN 계열 모델을 같은 조건으로 학습합니다.
설계와 근거 문헌은 [docs/FINAL_DESIGN_KO.md](docs/FINAL_DESIGN_KO.md)에 있습니다.

## 설치 (최초 1회)

```bash
conda create -n fourphase-py310 python=3.10
conda activate fourphase-py310
python -m pip install -r requirements.txt
python -m pip install torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-dqn.txt
```

Windows에서는 경로 길이 제한(260자) 때문에 프로젝트 안에 `.venv`를 만들면 SUMO 설치가 실패할 수 있습니다. conda 환경처럼 짧은 경로를 사용하세요.

## 실행

모든 명령은 환경을 활성화한 뒤 이 폴더에서 실행합니다 (`conda activate fourphase-py310`).

```bash
python scripts/check_env.py                # SUMO·패키지 설치 확인
python scripts/train_all_seeds.py          # 3종 × 시드 5개 = 15회, 동시 5개 (약 6~8시간)
```

모델 하나만 학습할 때:

```bash
python scripts/train_fourphase_dqn.py --algorithm double_dqn --seed 42 --output results/fourphase_dqn/double_dqn_seed42
```

테스트:

```bash
python -m unittest discover -s tests -p "test_fourphase*.py"
```

## 구성

| 경로 | 내용 |
|---|---|
| `configs/fourphase_dqn.json` | 학습 하이퍼파라미터, 학습 시드 5개, 수요 시드 |
| `configs/fourphase.json` | 교차로·신호·수요 설정 (시나리오 생성용) |
| `sumo/fourphase/` | 해시로 고정한 SUMO 도로망·신호 (`scripts/build_fourphase.py`로 생성) |
| `src/envs/fourphase_env.py` | Gymnasium 환경: 상태 21개, 행동 2개, 보상 |
| `src/agents/fourphase_dqn.py` | DQN · Double DQN · Dueling DQN, 리플레이 버퍼 |
| `src/agents/fourphase_data.py` | 학습 200 · 검증 9 수요 생성과 학습 순서 |
| `src/agents/fourphase_evaluation.py` | 에피소드 실행, ATT·AQL·AWT 계산, 검증 ATT로 모델 선정 |
| `src/traffic/fourphase/` | SUMO 실행·신호 제어·계측 |
| `scripts/train_fourphase_dqn.py` | 모델 1개 학습 |
| `scripts/train_all_seeds.py` | 전체 15회 병렬 학습 |

## 학습 결과 폴더

`results/fourphase_dqn/<알고리즘>_seed<시드>/`

| 파일 | 내용 |
|---|---|
| `best_model.pt` | 검증 ATT가 가장 낮은 모델 |
| `last_model.pt` | 마지막 모델 |
| `episodes.jsonl` | 에피소드별 보상·ε·손실·ATT·AQL·AWT |
| `updates.jsonl` | 신경망 업데이트별 손실·Q값 |
| `validations.jsonl` | 20 에피소드마다 검증 ATT |
| `selection.json` | 선정된 모델 정보 |
| `training.png` | 학습 곡선 |
