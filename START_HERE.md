# 먼저 읽어주세요

1. [README: 구현 내용과 빠른 시작](README.md)
2. [SUMO 설치·재생·학습·평가 안내](docs/SUMO_SIMULATION_GUIDE.md)
3. [GitHub 구성과 푸시 방법](docs/GITHUB_PUSH_GUIDE.md)

새 컴퓨터에서는 README에 따라 Python 가상환경과 requirements를 설치하세요.
환경이 준비되면 `START_SIMULATION.cmd`를 더블클릭해 두 교차로 DQN을 재생할 수 있습니다.
기본 재생 모델은 `models/corridor2-100ep/model.pt`이며, 새로 학습한
`results/local/corridor2-train/model.pt`가 있으면 해당 로컬 모델을 우선합니다.

`RUN_HERE.ps1 -Mode Evaluate`의 기본 모델은 초기 검증 모델입니다.
100회 모델 또는 새 모델을 평가할 때에는 `-ModelPath`를 명시하세요.
구체적인 명령은 실행 안내서에 있습니다.
