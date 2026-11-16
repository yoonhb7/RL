# 최종 실험 설계서 — SUMO 4현시 단일 교차로 DQN 계열 신호제어 (근거 포함)

작성일 2026-11-16 · 코드 기준: `C:\RL\fourphase-dqn-comparison`

**근거 표시** ✅ 원문 직접 확인 · ⚠️ 서지만 확인, 세부는 원문 확인 필요 · 👥 팀 결정(근거 보유) · ✍️ 본 연구 설정

---

## 1. 연구 개요

| 항목 | 내용 |
|---|---|
| 연구 목적 | 같은 4현시 교차로·상태·행동·보상·학습 예산에서 **DQN · Double DQN · Dueling DQN**의 구조 차이를 비교 |
| 차별성 | 보호좌회전 4현시 환경 + **정지 차량과 주행 차량 밀도를 분리한 상태**로 세 모델 비교 |
| 데이터 | SUMO 미시 교통 시뮬레이션으로 생성(실측 데이터 없음), 시드로 완전 재현 |

배경 근거
- 연구마다 도로·상태·보상·지표가 달라 직접 비교가 어렵다는 문제의식 → ✅ LibSignal(Mei et al.), ✅ RESCO(Ault & Sharon)가 같은 이유로 통합 벤치마크를 제안
- 같은 3종 비교의 선행연구 → ⚠️ Pálos & Huszák (2020)

---

## 2. 시뮬레이션 환경

| 항목 | 값 | 근거 |
|---|---|---|
| 시뮬레이터 | SUMO 1.28.0 + TraCI (Python 3.10, PyTorch 2.9.1 CPU) | ✅ IntelliLight·RESCO·LibSignal 모두 SUMO 사용 |
| 시뮬레이션 간격 | 1초 | ✍️ |
| 교차로 | 단일 교차로, 4방향 | ⚠️ Li et al. (2020) |
| 차로 | 방향마다 진입 2차로: 직진 전용 1 + 좌회전 전용 1 (총 8개 진입 차로), 우회전 없음 | ✍️ |
| 도로 길이·속도 | 진입·진출 500m, 제한속도 50km/h (13.89m/s) | ✍️ (속도는 ✅ Liang et al.과 동일 50km/h) |
| 차량 | 승용차 1종, 길이 5m, 차간 최소간격 2.5m, Krauss 추종모형 (가속 2.6, 감속 4.5m/s²) | ✍️ (Krauss는 ✅ Liang et al.도 사용) |
| 안전 설정 | 텔레포트 비활성, 교차로 충돌 검사 → 충돌 시 실행 중단 | ✍️ |

### 신호 현시와 시간 제약

| 항목 | 값 | 근거 |
|---|---|---|
| 현시 순서 (고정 순환) | 남북 직진 → 남북 좌회전 → 동서 직진 → 동서 좌회전 | ⚠️ Li et al. (2020) |
| 황색 | 3초 | ✅ FHWA(MUTCD 인용) 3~6초 권장 · ✅ IntelliLight 3초 |
| 전적색 | 1초 | ✅ FHWA 실무 조사 범위 0.5~2초 |
| 최소 녹색 | 11초 | ✅ FHWA: 직진, 40mph 이하 간선 7~15초 |
| 최대 녹색 | 60초 | ✅ FHWA: 같은 도로 유형 40~60초 |

> 최소 녹색 11초 = 15초 결정 구간 − 황색 3 − 전적색 1. 전환 직후 다음 결정 시점에 최소 녹색이 이미 충족되도록 설계 (✍️, 값은 FHWA 범위 내).

---

## 3. 교통 수요 (데이터 생성)

| 항목 | 값 | 근거 |
|---|---|---|
| 도착 분포 | 포아송 도착 | ✅ IntelliLight도 포아송 분포로 생성 |
| 교통량 수준 | 저 1,200 / 중 1,800 / 고 2,400 대/시간 | 👥 V/C(교통량/용량) 비 기준 산정 |
| 방향·회전 비율 | 4방향 균등, 좌회전 25% · 직진 75% | ✍️ |
| 생성·관측 구간 | 3,660초까지 생성, 0~3,600초 관측 | ✍️ |
| 학습 수요 | 200개(수요 시드 10000~10199), 에피소드마다 다른 교통 | ✍️ |
| 학습 순서 | 저·중·고 3유형을 균등하게(66/67/67) 무작위로 섞어 학습 | 👥 ⚠️ Li et al. 수요 3유형, 본 연구는 이를 혼합 |
| 검증 수요 | 저·중·고 × 시드 3개(20000~20002) = 9개, 학습과 겹치지 않음 | ✍️ |
| 재현성 | 모든 수요 파일을 시드로 생성하고 해시(sha256)로 고정 | ✍️ |

---

## 4. MDP 설계

### 4-1. 상태 (21개)

| 위치 | 개수 | 내용 | SUMO 출처 | 근거 |
|---|---|---|---|---|
| 0~7 | 8 | 차로별 정지 차량 수 ÷ 차로 용량 | `lane.getLastStepHaltingNumber` (0.1m/s 미만) | ✅ IntelliLight 대기열 Lᵢ · ✅ RESCO · ✅ sumo-rl |
| 8~15 | 8 | 차로별 **주행** 차량 수 ÷ 차로 용량 | `getLastStepVehicleNumber − getLastStepHaltingNumber` | ✅ RESCO "정지하지 않은 접근 차량 수" · ✅ IntelliLight 차량 수 Vᵢ · ✅ sumo-rl 차로 밀도 |
| 16~19 | 4 | 현재 녹색 현시 one-hot | TraCI 신호 상태 | ✅ IntelliLight · ✅ sumo-rl · ✅ LibSignal |
| 20 | 1 | 녹색 경과시간 ÷ 60초 | `trafficlight.getSpentDuration`과 동일 값 | ✅ Maadi et al. (2022) · ✅ sumo-rl(최소 녹색 경과 여부) |

- 차로 용량 = 차로 길이 ÷ 7.5m (차 길이 5m + 최소간격 2.5m), 잘라내기(clipping) 없음 ✍️
- 상태 구성 전체가 ✅ sumo-rl 기본 상태(현시 one-hot + 차로 밀도 + 차로 대기열)와 같은 구조

### 4-2. 행동

| 항목 | 값 | 근거 |
|---|---|---|
| 행동 | 0 = 현재 녹색 유지, 1 = 다음 현시로 전환 | ✅ IntelliLight |
| 결정 간격 | 15초 (전환 시: 황색 3 + 전적색 1 + 다음 녹색 11) | ✅ IntelliLight: 5~25초에서 성능 영향 작음 · ⚠️ Li et al. 15초 |
| 행동 마스크 | 최소·최대 녹색을 어기는 행동은 선택 불가 (탐색·탐욕 선택·Q 타깃 모두 적용) | ✍️ (제약 값은 ✅ FHWA) |

### 4-3. 보상

- **r = −(15초 동안 진입 8차로 정지 차량 수 평균)**
- ✅ RESCO: "이전 연구들은 진입 차로 대기열 합의 음수를 보상으로 흔히 사용하며, 구현이 간단하고 혼잡 완화와 관련된다."
- ✅ RESCO가 지적한 한계(이동시간 관점 미반영) → 성능 평가·모델 선정은 ATT로 별도 수행(§7)

### 4-4. 에피소드와 시간 제한

| 항목 | 값 | 근거 |
|---|---|---|
| 에피소드 길이 | 3,600초 = 결정 240번 | ✅ LibSignal 3,600스텝 |
| 종료 처리 | 3,600초 종료는 진짜 종료가 아닌 **시간 제한(truncation)** → 마지막 상태에서도 다음 상태 가치를 이어서 계산 | ✅ Pardo et al. (ICML 2018) partial-episode bootstrapping |

---

## 5. 알고리즘

| 알고리즘 | 핵심 | 근거 |
|---|---|---|
| DQN | 경험 리플레이 + 타깃망 + ε-greedy, TD 타깃 r + γ·max Q_target(s′) | Mnih et al. (2015) |
| Double DQN | 다음 행동은 **온라인망**이 고르고, 그 가치는 타깃망이 평가 | van Hasselt et al. (2016) |
| Dueling DQN | Q = V + A − mean(A), 타깃은 DQN 방식 | Wang et al. (2016) |

공통 신경망: **입력 21 → 128 → 64 → 출력 2** (ReLU)
- 파라미터 수: DQN·Double 11,202개 / Dueling 11,267개 (V·A 헤드 차이)
- 128-64 근거: ✅ Genders & Razavi (2016), ✅ Gao et al. (2017)의 완전연결층 구조

---

## 6. 하이퍼파라미터

| 항목 | 값 | 근거 |
|---|---|---|
| 옵티마이저 | Adam | ✅ Liang et al., Mousavi et al., LibSignal |
| 학습률 | **0.001** | ✅ LibSignal IDQN (수치 상태·200 에피소드·3,600스텝으로 본 연구와 동일 조건). 영상(CNN) 입력 논문들은 0.00001~0.00025 |
| 할인율 γ | **0.95** (약 20결정 = 5분 앞까지 반영) | ✅ Genders & Razavi, Gao et al., LibSignal |
| 리플레이 버퍼 | **20,000** | ✅ Liang et al. (SUMO 단일 교차로, Double·Dueling) |
| 배치 | **64** | ✅ Liang et al., LibSignal |
| 학습 시작 | 1,000 결정 이후 | ✅ LibSignal |
| ε-greedy | 1.0 → **0.01**, 전체 결정의 70% 동안 선형 감소 | 선형 감소: Mnih et al. · 최종값: ✅ Liang et al., LibSignal |
| 타깃망 | 500 결정마다 통째로 복사 | ✅ RESCO IDQN (500스텝) |
| 손실 | Huber | Mnih et al. (2015) |
| 업데이트 빈도 | 결정 1번마다 1번 | ✅ LibSignal (`update_model_rate 1`) |
| 학습 에피소드 | 200 | ✅ LibSignal |

---

## 7. 학습 절차

1. **준비**: 도로망 복사, 학습 200·검증 9 수요 생성 및 해시 고정, 학습 순서(저·중·고 혼합) 결정
2. **에피소드 반복 (200회)**: SUMO 1시간 시뮬레이션마다 다음을 반복
   - 상태(21개) 관측 → 마스크 적용 ε-greedy로 행동 선택 → SUMO 15초 진행 → 보상 계산
   - (상태, 행동, 보상, 다음 상태, 다음 마스크)를 버퍼에 저장
   - 1,000 결정 이후: 매 결정마다 배치 64로 1회 업데이트, 500 결정마다 타깃망 복사
3. **모델 선정 (20 에피소드마다)**: 검증 수요 9개를 ε = 0으로 실행
   - **ATT**를 저·중·고 같은 비중으로 평균
   - 가장 낮은 시점의 모델을 `best_model.pt`로 저장 (동점이면 먼저 저장된 것)

| 학습 규모 (모델 1개) | 값 |
|---|---|
| 결정 | 48,000번 |
| 신경망 업데이트 | 47,000번 |
| 타깃망 복사 | 96번 |
| ε = 0.01 도달 시점 | 33,600번째 결정 |
| 검증 | 10회 × 9개 |
| 소요 시간 (이 PC) | 약 2시간 |

### 학습 시드

| 항목 | 값 | 근거 |
|---|---|---|
| 시드 | **42, 43, 44, 45, 46 (5개)** | ✅ RESCO: 5개 시드로 학습곡선 보고 · ✅ Henderson et al. (AAAI 2018): 시드 5개, 시드에 따른 결과 차이를 경고 |
| 시드가 바꾸는 것 | 신경망 초기값, 탐색 난수, 리플레이 샘플링, 에피소드 순서 | ✍️ |
| 시드와 무관하게 고정 | 학습·검증 교통 수요 (세 알고리즘이 같은 교통을 경험) | ✍️ |
| 전체 실행 | 3종 × 5시드 = 15회, 동시 5개 → 약 6~8시간 | `scripts/train_all_seeds.py` |

---

## 8. 성능 지표

| 지표 | 정의 | 근거 |
|---|---|---|
| **ATT** (평균 통행시간) | 출발한 **모든** 차량의 평균 통행시간. 미도착 차량은 "종료 시각 − 출발 시각" | ✅ TSCC 2019 (CityFlow), ✅ LibSignal |
| **AQL** (평균 대기열) | 진입 차로 정지 차량 수의 1초 단위 시간 평균 | ✅ LibSignal |
| **AWT** (평균 대기시간) | 차량당 누적 대기시간 평균 (미도착 차량 포함) | ✅ RESCO "Avg. Wait" |

- SUMO tripinfo는 미도착 차량의 `duration`을 정확히 "종료 − 출발"로 기록한다 (실측 확인).
- 모델 선정 기준 = ATT. ✅ LibSignal은 ATT를 반드시 보고할 지표로 권고한다.

---

## 9. 한계점

- 단일 교차로, 가상 수요, 우회전·보행자·대형차 없음
- 현시 순서 고정 (건너뛰기 불가)
- 하이퍼파라미터는 선행연구 값을 채택했고 별도 튜닝은 하지 않음 (세 모델에 동일 적용)
- 밀도를 진입로 500m 전체로 감지한다고 가정 (✅ RESCO는 감지 거리를 설정값으로 둠)
- ⚠️ 표시 문헌 2편(Li et al., Pálos & Huszák)은 원문 세부 확인 필요

---

## 10. 참고문헌

**교통신호 강화학습**
1. Wei, H., Zheng, G., Yao, H., & Li, Z. (2018). IntelliLight: A Reinforcement Learning Approach for Intelligent Traffic Light Control. *KDD 2018*. https://doi.org/10.1145/3219819.3220096 ✅
2. Li, D., Wu, J., Xu, M., Wang, Z., & Hu, K. (2020). Adaptive Traffic Signal Control Model on Intersections Based on Deep Reinforcement Learning. *Journal of Advanced Transportation*, 6505893. https://doi.org/10.1155/2020/6505893 ⚠️
3. Pálos, P., & Huszák, Á. (2020). Comparison of Q-Learning based Traffic Light Control Methods and Objective Functions. *IEEE SoftCOM 2020*. https://ieeexplore.ieee.org/document/9238290 ⚠️
4. Genders, W., & Razavi, S. (2016). Using a Deep Reinforcement Learning Agent for Traffic Signal Control. arXiv:1611.01142 ✅
5. Gao, J., Shen, Y., Liu, J., Ito, M., & Shiratori, N. (2017). Adaptive Traffic Signal Control: Deep Reinforcement Learning Algorithm with Experience Replay and Target Network. arXiv:1705.02755 ✅
6. Mousavi, S. S., Schukat, M., & Howley, E. (2017). Traffic Light Control Using Deep Policy-Gradient and Value-Function Based Reinforcement Learning. arXiv:1704.08883 ✅
7. Liang, X., Du, X., Wang, G., & Han, Z. (2018). Deep Reinforcement Learning for Traffic Light Control in Vehicular Networks. arXiv:1803.11115 (IEEE Transactions on Vehicular Technology 투고본) ✅
8. Maadi, S., Stein, S., Hong, J., & Murray-Smith, R. (2022). Real-Time Adaptive Traffic Signal Control in a Connected and Automated Vehicle Environment. *Sensors*, 22(19), 7501. https://doi.org/10.3390/s22197501 ✅

**벤치마크·평가**
9. Ault, J., & Sharon, G. (2021). Reinforcement Learning Benchmarks for Traffic Signal Control (RESCO). *NeurIPS 2021 Datasets and Benchmarks*. ✅
10. Mei, H., Lei, X., Da, L., Shi, B., & Wei, H. (2022). LibSignal: An Open Library for Traffic Signal Control. arXiv:2211.10649 ✅
11. TSCC 2019 Evaluation (CityFlow). https://traffic-signal-control.github.io/TSCC2019/evaluation.html ✅
12. Alegre, L. N. sumo-rl. https://github.com/LucasAlegre/sumo-rl ✅

**알고리즘·학습 방법**
13. Mnih, V., et al. (2015). Human-level control through deep reinforcement learning. *Nature*, 518, 529–533.
14. van Hasselt, H., Guez, A., & Silver, D. (2016). Deep Reinforcement Learning with Double Q-learning. *AAAI 2016*.
15. Wang, Z., et al. (2016). Dueling Network Architectures for Deep Reinforcement Learning. *ICML 2016*.
16. Pardo, F., Tavakoli, A., Levdik, V., & Kormushev, P. (2018). Time Limits in Reinforcement Learning. *ICML 2018*. ✅
17. Henderson, P., et al. (2018). Deep Reinforcement Learning that Matters. *AAAI 2018*. ✅

**신호 공학**
18. FHWA (2008). Traffic Signal Timing Manual, Chapter 5 (FHWA-HOP-08-024). https://ops.fhwa.dot.gov/publications/fhwahop08024/chapter5.htm ✅
