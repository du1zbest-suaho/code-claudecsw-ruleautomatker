# 다른 PC 셋업 가이드

## 1. 필수 환경

- **Python 3.12** 이상 (https://www.python.org/downloads/)
- **Git** (https://git-scm.com/download/win)

---

## 2. 저장소 클론

```bash
# 작업 폴더 생성 및 이동
cd C:\Users\{사용자명}\Documents   # 또는 원하는 경로

# 룰 개발 프로젝트
git clone https://github.com/du1zbest-suaho/code-claudecsw-ruleautomatker.git ruleautomatker

# 웹앱 프로젝트
git clone https://github.com/du1zbest-suaho/insurance-web.git insurance-web
```

---

## 3. 패키지 설치

```bash
# ruleautomatker 패키지
cd ruleautomatker
pip install -r requirements.txt

# insurance-web 패키지 (웹앱 개발 시)
cd ..\insurance-web
pip install -r requirements.txt
```

> **오프라인 환경이라면** 현재 PC에서 패키지를 미리 다운로드하여 USB로 전달:
> ```bash
> pip download -r requirements.txt -d packages/
> # 다른 PC에서:
> pip install --no-index --find-links=packages/ -r requirements.txt
> ```

---

## 4. 데이터 파일 복사 (USB 또는 공유드라이브)

아래 폴더는 git에 일부만 포함됩니다. **수동으로 복사** 필요:

```
ruleautomatker/
├── data/
│   ├── pdf/          ← PDF 파일 (용량 큼, git 미포함)
│   ├── existing/     ← GT 파일 (git 포함)
│   └── templates/    ← 업로드 양식 템플릿 (git 포함)
```

> `data/pdf/` 폴더의 PDF 파일들을 USB로 복사하거나 공유드라이브에서 가져옵니다.

---

## 5. 동작 확인

```bash
cd ruleautomatker

# 단일 PDF 테스트 (배치 전체 실행)
python scripts/batch_run.py --no-skip

# 작업현황 리포트 생성
python scripts/generate_report.py
```

정상 실행 시 `output/reports/작업현황_*.xlsx` 파일이 생성됩니다.

---

## 6. Claude Code 연결 (선택)

```bash
# Claude Code CLI 설치
npm install -g @anthropic-ai/claude-code

# 프로젝트 폴더에서 실행
cd ruleautomatker
claude
```

---

## 빠른 요약

```
1. Python 3.12 설치
2. git clone (2개 저장소)
3. pip install -r requirements.txt
4. data/pdf/ 폴더 복사
5. python scripts/batch_run.py --no-skip  (확인)
```
