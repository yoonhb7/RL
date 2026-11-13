# RL1114 시작 안내

현재 실험은 **단일 교차로 DQN·보상·저중고 교통량 비교**다.

1. [프로젝트 개요](README.md)와 [설치·실행 안내](experiments/single-intersection-dqn-benchmark/README.md)를 읽는다.
2. 환경 설치 후 최상위 `START_VIEW.cmd` 또는 `START_SIMULATION.cmd`를 실행하고 1/2/3을 선택한다.
3. `SHOW_RESULTS.cmd`로 짧은 파일럿의 결과를 확인한다. `START_TRAINING.cmd`는 새 파일럿을 학습한다.
4. 본 실험 분담은 [팀 실행 안내](experiments/single-intersection-dqn-benchmark/TEAM_HANDOFF_KO.md)를 따른다.

현재 Python 명령은 `experiments/single-intersection-dqn-benchmark`에서 실행한다. 최상위의 옛 `run.py`, `RUN_HERE.ps1`, `TRAIN_TEAM_EXPERIMENT.cmd`는 이전 연구용이다.

포함된 데모는 학습 6에피소드의 실행 확인용 모델이다. 중·고교통량에서는 충분히 수렴하지 않았다. 시연은 재학습하지 않으며 162모델 본 실험은 아직 실행하지 않았다.
