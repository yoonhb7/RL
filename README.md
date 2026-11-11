# Corridor2-DQN: 두 사거리 차량 대기 최소화

이 브랜치는 차량 중심의 중앙 DQN 기본 실험을 보존한다. 가상 사거리 2개를 단일 DQN으로 제어하고 고정 신호·대기행렬 규칙과 비교한다.

- **[팀원용 상세 비교 설명서](docs/EXPERIMENT_COMPARISON_KO.md)**: 논문, MDP, 구현, 추가 아이디어, 실측 결과와 한계.
- [기존 설치·실행 안내](docs/CORRIDOR2_README_KO.md) · [100회 모델](models/corridor2-100ep/MODEL_CARD.md)
- [논문 PDF와 출처·라이선스](papers/README.md)
- [현재 PedLink-DQN 브랜치](https://github.com/yoonhb7/RL/tree/experiment/pedlink-dqn): 차량과 보행자를 함께 다루는 네 횡단보도 실험.

최상위 `START_SIMULATION.cmd`는 기존 두 사거리 시연이다. 새 실험의 실행기와 구분한다. 기존 100회 학습 모델은 평가 시드 5개에서 차량 평균 대기 12.02초였으며, 동일 수요의 고정 신호는 27.24초, 대기행렬 규칙은 15.26초였다. 특정 합성 도로와 한 번의 학습 결과다.
