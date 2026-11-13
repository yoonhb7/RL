# 세 명이 같은 실험을 돌리는 방법

## 목표

SUMO 단일 교차로에서 **알고리즘 3종 × 보상 6종 × 교통량 3수준**을 비교한다. 동일한 환경·차량 생성·모델 크기·학습량·평가 지표를 사용한다. 현재 저장된 짧은 파일럿은 실행 확인용이다.

## 역할

| 담당 | 수준 | 학습 수 | 평가 수 |
|---|---|---:|---:|
| A | low 450 veh/h | 54 | 270 |
| B | medium 1500 veh/h | 54 | 270 |
| C | high 3000 veh/h | 54 | 270 |

각 담당은 3알고리즘×6보상×학습시드3을 수행한다. 모델당 별도 차량 시드5로 평가한다. 합계 162학습·810평가다. 이때 **54조건**은 알고리즘×보상×교통량이고, **162모델**은 여기에 학습시드3을 적용한 수다.

## 실행 전

1. 같은 프로젝트 ZIP을 풀고 가상환경을 준비한다. README의 설치 절차를 따른다.
2. `python start.py doctor`로 SUMO·PyTorch를 확인한다. 준비된 런타임 PC는 `RUN_HERE.ps1 -Mode Doctor`를 사용한다.
3. `configs/shared.json`, `configs/team-plan.json`, `trafficbench/`를 임의 수정하지 않는다. 작업표가 코드 해시를 검사한다.
4. RTX 5080 서버의 CUDA/PyTorch 조합은 그 컴퓨터에서 확인한다. 같은 설정의 `device:auto`가 실제 사용 장치를 선택하고 기록한다.
5. 같은 owner를 여러 컴퓨터에서 중복 실행하지 않는다. CPU/GPU 차이는 최종 보고서에 기록한다.

## 각자 실행

```powershell
# 이 컴퓨터 담당에 맞는 명령 하나만 실행
powershell -ExecutionPolicy Bypass -File .\RUN_HERE.ps1 -Mode Team -Owner A
powershell -ExecutionPolicy Bypass -File .\RUN_HERE.ps1 -Mode Team -Owner B
powershell -ExecutionPolicy Bypass -File .\RUN_HERE.ps1 -Mode Team -Owner C
```

다른 서버에서 일반 Python 사용 시:

```text
python start.py batch --plan configs/team-plan.json --owner A --out results/team-A
```

완료된 작업은 재실행해도 건너뛴다. 실패하면 오류를 확인하고 같은 명령으로 재시도한다. 실패 시도는 보존되며 다음 attempt에서 처음부터 재학습한다. 본 실험은 실행 시간이 길 수 있으므로 먼저 소규모 파일럿을 완료한다.

## 합치기

각자 `results/team-A`, `team-B`, `team-C` 폴더 전체를 전달한다. 모델만 보내지 말고 `complete.json`, `training.json`, `evaluation.json`, 개별 metrics도 포함한다.

```text
python start.py report --roots results/team-A results/team-B results/team-C --out results/team-report
```

완료 작업 확인:

```powershell
(Get-ChildItem results/team-A -Recurse -Filter complete.json).Count
```

각 담당은 54개가 되어야 한다. 1개 학습 시드를 여러 번 평가한 것을 독립 학습 반복으로 세지 않는다. 미완료 작업은 끝난 작업과 구분해서 보고한다. 보고서는 설정·코드·SUMO·네트워크·동일 평가 시드의 차량 파일이 다른 결과를 섞지 않는다.

## 분석할 질문

- 교통량이 달라지면 알고리즘·보상 순위가 달라지는가?
- 대기 감소와 완료율·처리량 사이에 교환관계가 있는가?
- 특정 보상이 잦은 전환이나 긴 대기를 만드는가?
- 학습 시드 간 변동이 고교통량에서 커지는가?

평가 결과를 본 뒤 유리한 수요·평가 시드만 골라 교체하지 않는다. 조건을 바꾸는 실험은 새 작업표로 분리한다. 논문의 원본 자료와 우리의 수요 확장·구현 선택은 `METHOD_AND_REWARDS_KO.md`를 통해 구분한다.
