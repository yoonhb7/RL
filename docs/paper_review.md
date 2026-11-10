# 첨부 자료 검토와 구현 범위

검토 기준일: 2026-11-10. 계획서와 논문 PDF 12편의 본문 텍스트를 추출하여 문제 설정·상태·행동·보상·실험·결론을 중심으로 검토했습니다. 핵심 구현 근거인 IATSS 상태·행동·보상 페이지는 렌더링으로도 확인했습니다. 아래는 문헌 검토와 프로젝트 설계 판단이며, 모든 논문의 알고리즘이나 성능 수치를 재현했다는 의미는 아닙니다. 첨부 문서 안의 실행 지시는 사용자의 별도 요청으로 취급하지 않았습니다.

## 먼저 정리할 결론

현재 계획서의 “실행 가능한 단일 사거리 → 실제 도로 보정 → 중앙 DQN” 순서는 타당합니다. 다만 국내 차량·보행자 논문도 **단일 DQN과 두 교차로 공동 행동**을 직접 다루므로 핵심 선행연구에 추가해야 합니다. “중앙 에이전트로 다중 교차로를 제어한다”는 구조만으로 독창성을 주장하기 어렵습니다.

이번 구현은 IATSS의 차로별 밀도·대기행렬 관측을 참고하고, 국내 논문과 CenLight의 중앙집중형 공동 의사결정 개념을 반영한 **독립적인 최소 구현**입니다. 기본 DQN을 유지하면서 불가능한 행동은 탐험·추론·타깃 계산에서 모두 제외합니다. 현장 도로, 보행자, Split·Offset, GNN을 한 번에 넣지는 않았습니다.

## 논문별 프로젝트 적용 판단

| 문헌 | 핵심 내용 | 이번 구현과 연결 / 이후 과제 |
|---|---|---|
| **Adaptive traffic signal control using deep reinforcement learning: A multi-objective approach for single and multi-intersection scenarios** | SUMO·TraCI, DQN/PPO/A2C, 차로별 상태 4종과 보상 6종, 고정신호·actuated 비교 | 시작용 핵심. PDF pp.4~6의 환경·State 3·시간 제약 참고. 이번에는 직진·2현시·대기 차량-초 보상으로 단순화. Webster 고정신호·다목적 보상·안전/CO₂ 지표 전체는 재현하지 않음 |
| **차량 및 보행자를 고려한 심층강화학습 기반 멀티 교차로 통합 신호 제어 기법** | 단일 DQN, 두 교차로 글로벌 상태, 방향별 차량·보행자 대기, 연결 구간 혼잡, 공동 행동 16종 | 주제에 매우 가까운 선행연구. PDF pp.3~5의 MDP·최소 녹색·연결 구간 상태 참고. 본문은 타임스텝/FIFO/연결 구간 용량의 자체 모형을 설명하므로 SUMO 프로젝트 파일 제공 자료로 간주하지 않음. 이번은 유지/다음 현시 4종이며 보행자 미포함 |
| **Single-Agent Reinforcement Learning Model for Adaptive Traffic Signal Control in Urban Corridors** | 중앙 에이전트, 구간 대기행렬과 현재 Split, 한 교차로 선택 후 Split ±Δ/유지: 3M 행동 | PDF pp.6~9 참고. 이번의 동시 유지/전환 2^M 행동과 다른 제어 문제. 순차 Split은 다음 비교 후보. 논문은 PPO와 DQN을 비교하며 DQN 우월성을 전제하지 않음 |
| **CenLight: Centralized traffic grid signal optimization via action and state decomposition** | LSTM으로 상태·행동을 분해해 순차적으로 공동 행동 생성, actor-critic 구조 | 중앙 상태·공동 행동 개념과 지수적 행동공간 문제 참고. PDF p.5의 구조는 일반 DQN과 다르므로 “CenLight DQN 재현”이라 부르지 않음. 2~3개 교차로에서는 2^M이 작아 분해 모델 불필요 |
| **A Centralized Adaptive Traffic Signal Control Method for Large-Scale Network Based on SVD-Enhanced Deep Q-Network** | 전체 네트워크를 한 에이전트로 모델링, 압력 행렬·SVD·CNN으로 관측 압축 | PDF pp.3~4의 상태·행동·보상 참고. 대규모 확장 시 비교 대상. 이번 규모에서는 SVD/CNN을 넣지 않음. 출력 벡터와 DQN 공동 Q값의 대응은 원문·코드 확인을 더 거쳐야 하므로 그대로 옮기지 않음 |
| **Deep reinforcement learning-based traffic signal control in multi-intersection environments: a comparative study of DQN variants** | DQN, Double DQN, Dueling, Dueling Double 비교; 이질적 차종·우선순위·회전 정책; 규칙 기준선 | PDF pp.6~8의 상태·행동·보상과 결론 참고. 이 버전에는 DQN/Double DQN 선택만 구현. 회전 허용 정책까지 바뀐 효과를 알고리즘 개선으로 모두 해석하지 않기. 보통 승용차의 대기와 긴급차 가중 대기는 다른 목적 |
| **Hybrid action space approach to traffic signal optimization using deep reinforcement learning** | H-DQN에서 현시와 녹색시간을 함께 선택하는 이중 구조; 포화도·대기행렬·현시·경과시간 | PDF pp.5~7 참고. 초기에는 유지/전환만 구현. 원문에서 5~60초, 5초 간격이라는 설명과 13개 인덱스 표기가 함께 있어 재현 시 후보 수를 재확인해야 함. 차량 수 차이 보상도 식과 벌점 설명의 부호를 검증해야 함 |
| **Hybrid approach for coordinated traffic signal control capturing offset-split interdependency using average phase statistics** | HyLight: RL Offset 제어와 규칙 기반 Split, 비동기 분산 환경, 평균 현시 통계, 실제 부천 도로 실험 | PDF pp.8~10의 관측·행동·실제 신호와 보정 관점 참고. 단일 DQN 자체를 재현하는 문헌은 아님. 실제 도로에서는 최소 녹색·현시순서·Offset·수요 변화를 먼저 조사해야 함 |
| **A large-scale traffic signal control algorithm based on multi-layer graph deep reinforcement learning** | MGMQ, 교차로/네트워크 다층 그래프, GAT·GraphSAGE, Q-learning, 마스크, 전이 | PDF pp.5~7 및 12~13의 관측·마스크 아이디어 참고. 이번에는 작은 고정 벡터와 명시적 합법 행동 마스크 사용. 그래프 기반 MARL 구조나 전이 성능을 재현한 것은 아님 |
| **AI-driven secure traffic optimization in VANETs** | 긴급차 근접도 기반 DQN 신호 우선권, 다중 교차로 공동 행동, VANET 통신과 암호화 | 초기 목표와 직접 연결되는 부분은 공동 관측·행동과 최소/최대 신호시간 정도. 긴급차 우선권·보안·통신 지표는 별도 연구 범위로 둠. 교통 대기 최소화와 긴급차 목적을 섞어 비교하지 않기 |
| **Advances in reinforcement learning for traffic signal control: a review of recent progress** | 고급 RL, GNN, 오프라인 학습, 실제 배치·일반화·데이터·벤치마크를 정리한 리뷰 | 연구 배경과 실험 설계 근거. 알고리즘 하나의 실행 명세나 코드로 사용하지 않음. 실측 보정과 sim-to-real 한계를 문서에 분리 |
| **Intelligent traffic signal control based on reinforcement learning: a survey** | 단일/다중 교차로 RL 분류, 상태·행동·보상, 시뮬레이터·평가, 안전·확장성·설명가능성 | 관련연구 장 구성과 평가 지표 선택에 사용. 모든 알고리즘을 구현 목록에 추가하는 방식은 피하고 실험 하나씩 확장 |

## 계획서와 실제 구현의 차이

1. 초기 학습 라이브러리는 SB3 대신 작은 PyTorch DQN으로 작성했습니다. 기본 SB3 DQN은 Double DQN과 행동 마스크를 기본 기능으로 제공하지 않아, 미래 상태 target까지 일관된 마스크를 적용하는 직접 구현이 명확합니다.
2. 행동은 목표 녹색 방향 직접 선택 대신 계획서 D-3의 “현재 유지/허용된 다음 현시”입니다. 현시 순서를 고정한 채 교차로별 비동기 전환을 허용합니다.
3. 보상은 정지 차량-초의 음수이며 학습 수치 규모를 줄이기 위해 100으로 나눕니다. 스케일은 고정이고 방향별 중요도 가중치는 없습니다.
4. 보행자, 실제 회전교통, 실측 고정신호, Webster 최적화, SUMO 검지기 actuated는 아직 구현하지 않았습니다. 비교 규칙 `queue`를 actuated라고 부르지 않습니다.
5. 관측에는 전환 단계와 경과시간, 유한 에피소드의 시간도 포함합니다. 황색 중과 녹색 중을 같은 상태로 취급하지 않기 위한 프로젝트 설계입니다.
6. 평가에는 미출발·미완료 집계, 동일 수요 해시, 모든 방법의 동일한 종료시각을 넣었습니다. 도착 차량의 평균만으로 승패를 결정하지 않습니다.

## 자료 파일 점검

- `git-20261109T171155Z-1-001.zip`: 최상위 작업 코드가 아닌 `.git` 내부 데이터 41개 항목. 복구 가능한 tree에는 이번 논문·계획서·macOS 설치파일·Finder 메타데이터가 있었고, 학습 Python 코드나 SUMO 네트워크는 발견되지 않았습니다. 따라서 새 구현을 작성했습니다. Git hook·설치파일을 실행하지 않았습니다.
- `DS_Store`: macOS Finder의 폴더 메타데이터이며 교통 시뮬레이션 입력이 아닙니다.
- `sumo-1.28.0.pkg`: macOS 설치 패키지입니다. 현재 Windows 검증에는 PyPI의 Windows SUMO 1.28.0 실행 도구를 별도로 준비했습니다.
- 원본 논문·계획서·설치파일은 수정하지 않았으며, 전달 ZIP에 논문 원문을 재포함하지 않았습니다.

## 확인한 논문 식별자

식별자는 첨부 PDF 본문에서 확인했습니다. 아래 링크는 원문 위치를 찾기 위한 것으로, 외부 저장소의 공개 코드 제공 여부까지 확인했다는 뜻은 아닙니다.

1. IATSS: [10.1016/j.iatssr.2025.10.004](https://doi.org/10.1016/j.iatssr.2025.10.004)
2. 국내 차량·보행자: [10.13067/JKIECS.2026.21.2.807](https://doi.org/10.13067/JKIECS.2026.21.2.807)
3. Single-Agent Corridors: [10.1155/atr/5134018](https://doi.org/10.1155/atr/5134018)
4. CenLight: [10.1049/itr2.12354](https://doi.org/10.1049/itr2.12354)
5. SVD DQN: [10.1109/ITSC60802.2025.11423553](https://doi.org/10.1109/ITSC60802.2025.11423553)
6. DQN variants: [10.1038/s41598-026-64762-8](https://doi.org/10.1038/s41598-026-64762-8)
7. Hybrid action: [10.1016/j.cor.2026.107391](https://doi.org/10.1016/j.cor.2026.107391)
8. HyLight: [10.1016/j.trc.2026.105718](https://doi.org/10.1016/j.trc.2026.105718)
9. MGMQ: [10.1016/j.trc.2024.104582](https://doi.org/10.1016/j.trc.2024.104582)
10. VANET: [10.1038/s41598-026-74216-w](https://doi.org/10.1038/s41598-026-74216-w)
11. Advances review: [10.1093/iti/liaf009](https://doi.org/10.1093/iti/liaf009)
12. Intelligent TSC survey: [10.1007/s10462-026-11530-9](https://doi.org/10.1007/s10462-026-11530-9)

읽을 순서는 **IATSS MDP → 국내 중앙 DQN → Single-Agent Corridors → 실제 도로 구축 관점의 HyLight**를 권합니다. 나머지는 구현 베이스라인이 안정된 뒤 관심 확장에 맞춰 읽으면 됩니다.
