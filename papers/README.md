# 사용 논문과 PDF 배포 기록

논문 PDF는 저자·발행처의 저작물이며, 프로젝트 코드의 라이선스가 적용되지 않는다. 제공받은 원본을 수정하지 않고 보존했다. 아래 저자·출처·라이선스를 함께 유지한다. 이 저장소의 논문 공유는 비상업적 수업·연구 자료 제공 목적이다.

원 논문 성능과 우리 실험 성능을 구분한 설명은 [실험 비교](../docs/EXPERIMENT_COMPARISON_KO.md)에 있다.

## Joint Pedestrian and Vehicle Traffic Optimization in Urban Environments using Reinforcement Learning

- 저자: Bibek Poudel, Xuan Wang, Weizi Li, Lei Zhu, Kevin Heaslip
- [원문·서지](https://arxiv.org/abs/2504.05018v2) · [원본 PDF](joint-pedestrian-vehicle-2025.pdf)
- 라이선스: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). arXiv v2 record: view license (checked 2026-11-11).
- PDF 변경 없음. 파일명만 저장소용으로 정리했다.

## Adaptive traffic signal control using deep reinforcement learning: A multi-objective approach for single and multi-intersection scenarios

- 저자: Marwa Elharoun, Sherif M. El-Badawy, Elsayed Abd-Elazem Shwaly, Usama Elrawy Shahdah
- [원문·서지](https://doi.org/10.1016/j.iatssr.2025.10.004) · [원본 PDF](adaptive-multi-objective-2025.pdf)
- 라이선스: [CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/). Publisher PDF, first page: CC BY-NC-ND 4.0.
- PDF 변경 없음. 파일명만 저장소용으로 정리했다.

## CenLight: Centralized traffic grid signal optimization via action and state decomposition

- 저자: Jia Wu, Yunchuan Ran, Yican Lou, Lingzhou Shu
- [원문·서지](https://doi.org/10.1049/itr2.12354) · [원본 PDF](cenlight-2023.pdf)
- 라이선스: [CC BY-NC-ND](https://creativecommons.org/licenses/by-nc-nd/4.0/). Publisher PDF, first page: Creative Commons Attribution-NonCommercial-NoDerivs License.
- PDF 변경 없음. 파일명만 저장소용으로 정리했다.

## Single-Agent Reinforcement Learning Model for Adaptive Traffic Signal Control in Urban Corridors

- 저자: Qiang Li, Xiya Zhuang, Lishan Liu, Bokui Chen, Yi Zhang, Yingping Zhao
- [원문·서지](https://doi.org/10.1155/atr/5134018) · [원본 PDF](single-agent-urban-corridors-2026.pdf)
- 라이선스: [CC BY](https://creativecommons.org/licenses/by/4.0/). Publisher PDF, first page: Creative Commons Attribution License; copyright 2026 Qiang Li et al..
- PDF 변경 없음. 파일명만 저장소용으로 정리했다.

## 링크로 제공하는 관련 논문

- 최석민·김선용, 「차량 및 보행자를 고려한 심층강화학습 기반 멀티 교차로 통합 신호 제어 기법」, 2026. [DOI](https://doi.org/10.13067/JKIECS.2026.21.2.807). 제공 PDF에서 공개 재배포 조건을 확인하지 못해 이 저장소에는 서지와 링크를 제공한다.
- Mnih 외, Human-level control through deep reinforcement learning, Nature, 2015. [DOI](https://doi.org/10.1038/nature14236). DQN의 replay·target network 배경 문헌.

## 저자 코드와 우리 구현

[Urban-Control](https://github.com/poudel-bibek/Urban-Control)은 저자 공개 구현이며 MIT 라이선스다. 검토 기준 커밋은 `3dd10f46b599e56cc2bab93cda58cf414caa9511`. 현재 네 횡단보도 배포는 직접 생성한 합성 도로와 자체 DQN 구현을 사용한다. 저자의 실제 수요·도로·PPO 모델 파일은 이 번들에 포함하지 않았다.

이 프로젝트는 원저자들의 공식 구현·보증·승인을 의미하지 않는다. 변경 없는 PDF의 해시는 [manifest.json](manifest.json)에서 확인한다.
