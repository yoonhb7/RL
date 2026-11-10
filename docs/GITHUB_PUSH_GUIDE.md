# GitHub 업로드 구성과 이후 푸시 방법

대상 저장소: [yoonhb7/RL](https://github.com/yoonhb7/RL). 이 문서는 무엇을 버전 관리하고, 수정한 코드를 어떻게 계속 올릴지 설명합니다. 명령은 저장소 최상위 폴더에서 실행합니다.

## 1. 무엇을 올리는가

| 경로 | 올리는 이유 |
|---|---|
| `src/traffic_rl/` | 중앙 DQN, 환경, 안전 상태기, SUMO 통신, GUI 표시, 평가 구현 |
| `src/traffic_rl/assets/` | GUI 설정 XML; Python 코드와 함께 필요 |
| `configs/` | 도로 수·수요·신호시간을 재현하는 설정 |
| `sumo/` | 실제 실행할 네트워크·연결·신호 프로그램·manifest |
| `sumo/*/demand/seed_1001_scale_1.rou.xml` | 제공 `.sumocfg`를 직접 열기 위한 최소 수요 예시 |
| `tests/`, `scripts/` | 코드 검증과 저장된 trace 감사 도구 |
| `models/corridor2-100ep/` | 직접 100회 학습한 모델과 학습 설정·로그·곡선 |
| `reports/corridor2-100ep/` | 해당 모델의 5개 시드 평가 요약과 비교 그림 |
| `results/verified/` | 초기 20회 모델과 기존 실험의 요약·그림 |
| `docs/`, `data/templates/` | 실행·실험·논문 설명, 실제 도로 조사 양식 |
| `run.py`, 실행 스크립트, requirements, `pyproject.toml` | 실행 진입점과 설치 의존성 |
| `.gitignore`, `.gitattributes`, `README.md` | 제외 기준, 네트워크 XML 줄바꿈 보존, 첫 실행 안내 |

학습 모델은 현재 각 100KB 미만으로 작으므로 함께 포함했습니다. 연구 근거가 되는 설정과 요약을 가중치와 함께 보관합니다. 원본 `results/local/corridor2-train`은 배포본에서 `models/corridor2-100ep`로, 평가 요약은 `reports/corridor2-100ep`로 복사해 로컬 결과와 구분했습니다.

## 2. 무엇을 제외하는가

- `.venv`, Python 설치 폴더, `work/runtime`, 다운로드한 패키지·SUMO 설치파일: requirements와 공식 배포판으로 설치합니다.
- `results/local`: 개인별 반복 학습과 GUI 실행 결과입니다.
- 매 실행의 `trace.csv`, `tripinfo.xml`, `run.json`, `.log`: 필요할 때 생성하는 원시 기록입니다. 공개할 실험의 작은 요약은 별도로 보관합니다.
- 학습 과정에서 생성되는 대량의 수요 XML: 생성 코드와 시드로 재현합니다.
- `__pycache__`, pytest 캐시, 임시 파일, `.env`.
- 첨부 논문 PDF와 macOS `.pkg`, 원본 Git 내부 데이터 ZIP, Finder `DS_Store`: 이 저장소의 실행 코드가 아닙니다.

공개 실험 데이터가 생기면 출처·측정 기간·보정 내역을 함께 정리합니다. API 키나 로그인 토큰은 코드·문서·명령 기록에 넣지 않습니다. `.gitignore`는 제외 기준을 공유하지만 이미 추적 중인 파일을 자동으로 지우지는 않습니다. [GitHub 공식 ignore 안내](https://docs.github.com/en/get-started/git-basics/ignoring-files)

## 3. Git 설치와 저장소 받기

```powershell
git --version
git clone https://github.com/yoonhb7/RL.git
cd RL
git status
git remote -v
```

`git` 명령이 없으면 [공식 Git for Windows](https://git-scm.com/install/windows)를 설치하고 PowerShell을 다시 엽니다. `git clone`은 파일과 변경 이력을 함께 받습니다. GitHub의 Download ZIP은 `.git` 이력을 포함하지 않으므로 계속 협업하려면 clone을 사용하세요.

처음 커밋할 때 이름과 이메일을 요구하면 현재 저장소에만 설정합니다. 아래 문자열을 본인 정보로 바꾸세요. GitHub의 이메일 설정에서 제공하는 noreply 주소도 사용할 수 있습니다.

```powershell
git config user.name "본인 이름 또는 GitHub 아이디"
git config user.email "본인의 커밋용 이메일"
```

## 4. 코드나 문서를 수정한 뒤 푸시

다른 사람이 올린 변경을 받기 전에 작업 폴더가 깨끗한지 확인합니다. 아직 로컬 변경이 있다면 먼저 정리·커밋하고 진행하세요.

```powershell
git status
git pull --ff-only
```

이제 필요한 코드·설정·문서를 수정하고, 수정 범위에 맞게 테스트나 짧은 실행을 확인합니다. 이후 다음 순서로 업로드합니다.

```powershell
git status --short
git diff
git add src configs tests docs README.md
git diff --cached --stat
git diff --cached
git commit -m "Update SUMO traffic signal experiment"
git push
```

`git add`에는 실제로 바꾼 경로를 지정합니다. `sumo`, `models`, `reports` 등을 의도적으로 바꿨다면 해당 경로도 추가하세요. 프로젝트 전체를 확인한 뒤 `git add .`를 사용할 수도 있지만, 위의 staged diff를 보고 실제로 올릴 파일이 맞는지 확인합니다.

`add`는 업로드할 변경 선택, `commit`은 내 컴퓨터에 변경 기록 저장, `push`는 그 기록을 GitHub로 전송하는 단계입니다. 실행만 했다고 GitHub의 파일이 바뀌지는 않습니다.

## 5. 새 학습 모델을 공유할 때

`results/local`은 무시하도록 되어 있습니다. 기존 검증 모델을 덮어쓰지 않고 의미 있는 이름의 폴더에 모델과 근거를 복사합니다.

```powershell
New-Item -ItemType Directory -Force .\models\corridor2-new-run | Out-Null
Copy-Item .\results\local\corridor2-new-train\model.pt .\models\corridor2-new-run\
Copy-Item .\results\local\corridor2-new-train\training_config.json .\models\corridor2-new-run\
Copy-Item .\results\local\corridor2-new-train\training.csv .\models\corridor2-new-run\
New-Item -ItemType Directory -Force .\reports\corridor2-new-run | Out-Null
Copy-Item .\results\local\corridor2-new-evaluation\summary.csv .\reports\corridor2-new-run\
Copy-Item .\results\local\corridor2-new-evaluation\episodes.csv .\reports\corridor2-new-run\
Copy-Item .\results\local\corridor2-new-evaluation\paired.csv .\reports\corridor2-new-run\
Copy-Item .\results\local\corridor2-new-evaluation\comparison.png .\reports\corridor2-new-run\
```

학습 횟수·초기화 시드·학습/평가 수요 시드·설정·모델 경로·실험 한계를 README 또는 별도 Markdown에 기록합니다. 그 뒤 해당 `models`, `reports`, 문서를 add/commit/push합니다. 모델이 커지면 반복 체크포인트를 모두 일반 Git에 넣기보다 Releases나 Git LFS 등 배포 방식을 검토하세요. [GitHub 대용량 파일 안내](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)

## 6. 팀 작업은 브랜치와 PR 사용

```powershell
git switch -c experiment/double-dqn
# 코드를 수정하고 검증한 뒤
git add src tests docs
git commit -m "Compare Double DQN controller"
git push -u origin experiment/double-dqn
```

GitHub에서 해당 브랜치의 Pull Request를 만들어 변경 내용과 검증 결과를 공유합니다. 여러 사람이 동시에 같은 파일을 바꿀 때 사용하면 됩니다.

## 7. 로그인·푸시 오류

- 브라우저 인증이 나타나면 쓰기 권한이 있는 GitHub 계정으로 로그인합니다. Windows Git Credential Manager나 GitHub CLI를 사용할 수 있습니다. `gh`가 이미 설치되어 있으면 `gh auth login` → HTTPS → 브라우저 인증으로 연결할 수 있습니다. [공식 인증 안내](https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git)
- `Permission denied`, `403`: 로그인 계정과 저장소 쓰기 권한을 확인합니다. 권한이 없는 저장소에 강제로 올릴 수는 없습니다.
- `non-fast-forward`: 다른 변경이 먼저 올라왔다는 뜻입니다. fetch 후 차이를 확인하고 pull/병합 또는 PR로 정리합니다. 기존 이력을 덮는 force push를 기본 해결책으로 사용하지 않습니다.
- `remote origin already exists`: `git remote -v`로 대상 URL을 확인합니다. URL이 잘못된 경우에만 `git remote set-url origin https://github.com/yoonhb7/RL.git`로 수정합니다.
- `Author identity unknown`: 3절의 저장소별 이름·이메일을 설정합니다.

## 8. 처음부터 비어 있는 저장소에 올리는 일반 절차

이 저장소를 이미 clone했다면 아래 초기화는 다시 할 필요 없습니다. 별도의 새 프로젝트를 처음 올릴 때의 참고입니다. GitHub에 빈 저장소를 만들고 해당 프로젝트 폴더에서 실행합니다.

```powershell
git init -b main
git add .
git diff --cached --stat
git commit -m "Initial project"
git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_REPOSITORY.git
git push -u origin main
```

원격 URL의 계정·저장소 이름을 실제 값으로 바꿉니다. 기존 Git 저장소의 이력이나 팀 작업이 있는 폴더에서는 새 저장소처럼 초기화하지 말고 해당 저장소의 브랜치·원격을 확인하세요. [GitHub 공식 초기 업로드 안내](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)
