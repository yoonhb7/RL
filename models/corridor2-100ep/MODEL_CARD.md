# 두 교차로 중앙 DQN: 100회 학습 모델

- 입력: 두 교차로 합계 29차원 요약 관측.
- 출력: 유지/다음 현시 공동 행동 4개. 정책 에이전트는 하나.
- 구조: 29 → 128 ReLU → 128 ReLU → 4, CPU PyTorch DQN.
- 학습: 100에피소드, 수요 시드 0~99, 18,000회 의사결정, 4,437회 경사 업데이트.
- 평가: 수요 시드 1001~1005, 고정신호·대기행렬 규칙과 동일 수요 비교.
- 결과: `reports/corridor2-100ep/`의 CSV·JSON·그림.
- 기존 작업 PC의 `results/local/corridor2-train`에서 파일을 복사해 보존함.
- `model.pt`는 추론 가중치와 환경 스키마/학습 메타데이터를 포함함.
  optimizer와 replay를 포함한 중단 시점 학습 재개 파일은 아님.
- 합성 직진 도로·특정 수요·한 번의 독립 학습 실행에서 나온 모델.
  실제 도로·보행자·회전 교통의 현장 성능을 검증한 모델은 아님.

독립 설치 후 저장소 최상위에서 재생:

```powershell
.\.venv\Scripts\python.exe run.py view --scenario sumo/corridor2 --model models/corridor2-100ep/model.pt --controllers dqn --seeds 1001 --out results/local/corridor2-demo --delay 1000
```
