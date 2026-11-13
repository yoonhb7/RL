# RL1114 업로드 검증

검증일: 2026-11-14. 현재 실험 경로는 `experiments/single-intersection-dqn-benchmark`다.

- 배포본 63개 파일을 기존 릴리스에서 복사하고 `RELEASE_MANIFEST.json`의 SHA-256과 대조했다.
- Git에 저장되는 파일 바이트도 해시와 대조했다. 코드·네트워크·작업표의 재현성을 위해 현재 실험 폴더의 줄바꿈 자동 변환을 끄고 원래 바이트를 보존한다.
- 새 저장소 위치에서 `run_tests.py`의 검사 8개가 모두 통과했다. 보상 6종, Double 타깃, Dueling 결합, 4모델 학습·체크포인트, 차량 파일 재현성, 황색 시간·차량 보존, 학습→저장→평가를 포함한다.
- 이 PC에서 테스트할 때 설치된 의존성은 기존 준비 런타임을 `PYTHONPATH`로 연결했다. 다른 컴퓨터는 실험 README대로 가상환경에 의존성을 설치한다. 새로운 하드웨어·CUDA 실행을 검증했다는 의미는 아니다.
- 릴리스의 텍스트 자료에서 GitHub 토큰·개인키 패턴을 검사했다. 설치 런타임·임시 파일·모든 학습 에피소드 원본은 올리지 않았다.
- 최상위 `START_SIMULATION.cmd`, `START_VIEW.cmd`, `START_TRAINING.cmd`, `SHOW_RESULTS.cmd`는 현재 실험의 실행기로 연결했다. 예전 Python CLI와 팀 실행기는 이전 연구용으로 유지하고 README에 구분했다.

도시형 화면의 교통 결과 동일성·차량 위치·신호 검증은 [화면 검증 기록](../experiments/single-intersection-dqn-benchmark/CITY_VIEW_KO.md)을 참고한다. 과거 파일럿의 코드 해시와 현재 표시 코드의 해시는 구분한다. 본 실험 162모델·810평가는 이번 업로드에서 실행하지 않았다.
