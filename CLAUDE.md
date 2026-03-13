# 보험 사업방법서 속성 추출 자동화 에이전트

## 프로젝트 개요

한화생명 보험 상품의 사업방법서(ZIP 형식)에서 가입 가능 연령, 보험기간/납입기간, 납입주기, 보기개시나이 정보를 자동 추출하여 시스템 업로드 양식(xlsx)으로 변환한다.

### 핵심 원칙
- **Ground Truth**: 기존 DB(판매중_* 파일)가 정답. 추출 결과가 불일치하면 DB 기준으로 룰을 수정한다.
- **무영향 원칙**: 특정 상품을 위한 룰 변경이 다른 상품의 추출 정확도에 영향을 주면 안 된다.
- **교차검증 필수**: PDF 내 txt(텍스트)와 jpeg(이미지)를 모두 활용하여 교차검증한다.

### 입력 파일 위치
- 사업방법서: `data/pdf/*.pdf`
- **PDF→상품 매핑**: `data/existing/판매중_상품구성_사업방법서_매핑.xlsx` ← 핵심 참조 파일
- 검증 Ground Truth: `data/existing/판매중_가입나이정보.xlsx` 등
- 업로드 양식 템플릿: `data/templates/*.xlsx`
- 모델상세: `data/models/*.xlsx`

### 출력 파일 위치
- 추출 중간 결과: `output/extracted/`
- 최종 업로드 양식: `output/upload/`
- 검증 리포트: `output/reports/`
- 로그: `output/logs/`

---

## 실행 컨텍스트 관리

**워크플로우 시작 전 반드시 실행**:
```bash
python .claude/skills/run-manager/scripts/init_run.py
```
반환된 `run_id`(형식: `YYYYMMDD_HHMMSS`)를 이후 모든 스크립트에 `--run-id` 인자로 전달한다.

**워크플로우 성공 완료 후**:
```bash
python .claude/skills/run-manager/scripts/manage_registry.py --action register \
  --run-id {run_id} --product-code {upper_object_code} --tables {table_list}
```

---

## 워크플로우 (7단계)

### STEP 1: 문서 전처리

```bash
# 1-1. ZIP 해체 + 페이지별 텍스트/이미지 추출
python .claude/skills/pdf-preprocessor/scripts/extract_pdf.py \
  --input data/pdf/{파일명}.zip --output output/extracted/ --run-id {run_id}

# 1-2. 키워드 기반 관련 페이지 식별
python .claude/skills/pdf-preprocessor/scripts/scan_keywords.py \
  --input output/extracted/{run_id}_pages.json --output output/extracted/{run_id}_keywords.json

# 1-3. 보험종목명 + 세부보험종목 파싱
python .claude/skills/pdf-preprocessor/scripts/parse_sub_types.py \
  --input output/extracted/{run_id}_pages.json --output output/extracted/{run_id}_subtypes.json
```

`fallback_needed=true` 반환 시: 전체 텍스트를 LLM에게 제공하여 관련 페이지 번호 판단 요청 (자동 재시도 1회). 실패 시 사용자에게 관련 페이지 번호 질문.

### STEP 2: 상품 매핑

`data/existing/판매중_상품구성_사업방법서_매핑.xlsx`에서 PDF 파일명으로 직접 조회한다.
키워드 추론·LLM 판단 불필요. 파일명이 정확히 일치해야 한다.

파일 구조:
| 컬럼 | 설명 |
|------|------|
| `ISRN_KIND_DTCD` | 보종코드 (상품코드) |
| `ISRN_KIND_ITCD` | 보종세부코드 |
| `ISRN_KIND_SALE_NM` | 보험종목 판매명 |
| `PROD_DTCD` / `PROD_ITCD` | 상품구성 코드 |
| `사업방법서 파일명` | PDF 파일명 (매핑 키) |

**주의사항**:
- 하나의 PDF → 복수 DTCD 가능 (예: `노후실손의료비` → DTCD 1808+1946)
- 하나의 DTCD → 복수 PDF 가능 (예: DTCD 2126 → 상생친구PDF(A04~A06) + 진심가득HPDF(A01~A03))
- PDF 파일명이 매핑 파일에 없으면 처리 스킵

```python
# batch_run.py 내 구현 (직접 조회)
mapping_db = load_mapping_db()   # 판매중_상품구성_사업방법서_매핑.xlsx 로드
entries = get_pdf_entries(pdf_path, mapping_db)  # 파일명으로 바로 조회
dtcd_groups = get_dtcd_groups(entries)           # DTCD별 그룹화
```

매핑 파일에 없는 PDF: 처리 스킵 후 로그 기록.

### STEP 3: 테이블 추출 (LLM 핵심 단계)

**4개 테이블(S00022, S00026, S00027, S00028)을 병렬로 table-extractor 서브에이전트에 위임.**

각 서브에이전트 호출 시 전달 정보:
- 관련 페이지 텍스트 파일 경로
- 관련 페이지 이미지 경로
- 추출 대상 테이블 종류
- run_id
- 세부보험종목 목록
- extraction_rules.py 존재 여부

`extraction_rules.py`가 `rules/` 디렉토리에 존재하면:
```bash
python .claude/agents/table-extractor/scripts/run_extraction_rules.py \
  --table-type {S00026|S00027|S00028|S00022} \
  --product-code {upper_object_code} \
  --input output/extracted/{run_id}_page_text.txt \
  --rules rules/extraction_rules.py \
  --output output/extracted/{upper_obj}_{table_type}_{run_id}.json
```

없으면 LLM이 직접 추출 (AGENT.md 지침 참조).

**Two-Phase 이미지 전략**: 텍스트 추출 confidence가 "high"이고 스키마 검증 통과 시 이미지 추출 스킵.

### STEP 4: 코드 변환

```bash
# 4-1. 자연어 → 시스템코드 변환
python .claude/skills/code-converter/scripts/convert_codes.py \
  --input output/extracted/{upper_obj}_{table_type}_{run_id}.json \
  --mappings .claude/skills/code-converter/references/code_mappings.json \
  --output output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json

# 4-2. 특약 코드 적용
python .claude/skills/code-converter/scripts/apply_special_contract_codes.py \
  --coded output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json \
  --special-contracts output/extracted/{run_id}_special_contracts.json \
  --output output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json

# 4-3. 코드 유효성 검증
python .claude/skills/code-converter/scripts/validate_codes.py \
  --input output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json \
  --mappings .claude/skills/code-converter/references/code_mappings.json
```

변환 불가 항목: 로그 + 사용자에게 코드 매핑 확인 요청 (자동 재시도 없음).

### STEP 5: 검증

```bash
# 5-1. 기존 DB 대조
python .claude/skills/validator/scripts/compare_with_db.py \
  --input output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json \
  --db data/existing/판매중_{table_name}정보.xlsx \
  --output output/reports/{upper_obj}_{table_type}_{run_id}_report.json

# 5-2. 정합성 검증
python .claude/skills/validator/scripts/check_integrity.py \
  --input output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json

# 5-3. 조합 완전성 검증 (S00026 전용)
python .claude/skills/validator/scripts/check_combination_completeness.py \
  --input output/extracted/{upper_obj}_S00026_{run_id}_coded.json \
  --output output/reports/{upper_obj}_S00026_{run_id}_completeness.json
```

**비교키 기준 (5-1)**:
- `data/models/{테이블}_모델상세.xlsx`에서 ROW번호 ~ 생성일시 사이 컬럼을 동적 로드
  (`model_key_loader.py` → `load_model_key_cols()`)
- **상품세목별 활성 컬럼**: GT·EX 양쪽에 non-None 값이 있는 컬럼만 비교키로 사용
  (`get_active_key_cols()` — 상품에 따라 사용 컬럼이 다르므로 DTCD별 동적 결정)
- NULL 정규화: NaN/None→None, 숫자→문자열 통일 (Excel int ↔ JSON str 타입 불일치 처리)

**분기 조건**:
- `MISMATCH = 0, MISSING = 0` → STEP 7로 진행
- `MISSING > 0` → STEP 3 재실행 (누락 항목 힌트 포함, 최대 2회). 2회 실패 시 사용자에게 에스컬레이션
- `MISMATCH > 0` → STEP 6 (rule-optimizer 서브에이전트) 호출
- `NEW > 0` → 정상 (신규 상품), 로그만 기록

### STEP 6: 룰 고도화

**rule-optimizer 서브에이전트에 위임.** 입력:
- 불일치 리포트: `output/reports/{upper_obj}_{table_type}_{run_id}_report.json`
- 현재 추출 룰: `rules/extraction_rules.py`
- 원본 텍스트/이미지
- 기존 DB 정답 데이터

룰 수정 후 STEP 3~5 재실행. **최대 고도화 반복 3회**. 초과 시 사용자에게 수동 처리 요청.

### STEP 7: 양식 생성

```bash
# 7-1. 유효시작일 파싱
python .claude/skills/xlsx-generator/scripts/parse_valid_date.py \
  --pdf-name {파일명}.zip --output output/extracted/{run_id}_valid_date.json

# 7-2. 업로드 양식 생성
python .claude/skills/xlsx-generator/scripts/generate_upload.py \
  --input output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json \
  --template data/templates/{table_type}_업로드양식.xlsx \
  --valid-date output/extracted/{run_id}_valid_date.json \
  --output output/upload/{table_type}_{upper_obj}_{run_id}.xlsx
```

완료 후 `manage_registry.py`로 성공 run 등록.

---

## 작업현황 리포트

전체 PDF × 테이블별 추출 결과를 한눈에 확인하는 엑셀 리포트를 생성한다.

```bash
python scripts/generate_report.py
# 또는 출력 경로 지정
python scripts/generate_report.py --output output/reports/작업현황.xlsx
```

### 참조 파일
- 매핑 기준: `data/existing/판매중_상품구성_사업방법서_매핑.xlsx`
- GT 데이터: `data/existing/판매중_가입나이정보.xlsx` (S00026), `판매중_보기납기정보.xlsx` (S00027), `판매중_납입주기정보.xlsx` (S00028), `판매중_보기개시나이정보.xlsx` (S00022)
- 추출 결과: `output/extracted/*_coded.json`

### 출력 형식
- 파일: `output/reports/작업현황_{YYYYMMDD_HHMMSS}.xlsx`
- 행: 사업방법서 파일명 × ISRN_KIND_DTCD (1행 = 1 PDF-DTCD 조합)
- 컬럼 (테이블별 6개씩): `{테이블명}_추출건수`, `_GT건수`, `_일치건수`, `_미일치건수`, `_추가건수`, `_결과`

### 결과 코드
| 코드 | 색상 | 의미 |
|------|------|------|
| PASS | 연두 | S00026 키셋 완전 일치 (miss=0) |
| FAIL | 연빨강 | S00026 키셋 불일치 (miss>0) |
| 일치 | 연두 | S00027/28/22 행 수 일치 |
| 불일치 | 연빨강 | S00027/28/22 행 수 불일치 |
| 미추출 | 노랑 | GT 있으나 추출 결과 없음 |
| 신규 | 연파랑 | GT 없고 추출 결과 있음 (신규 상품) |
| - | 회색 | GT·추출 모두 없음 |

---

## 세션 종료 절차

세션 종료 전 반드시 아래 순서로 실행하여 구조적 문제 상태를 최신화한다.

```bash
# 1. 배치 재실행 (룰 변경이 있었을 때만)
python scripts/batch_run.py --no-skip

# 2. 작업현황 리포트 생성
python scripts/generate_report.py

# 3. 구조적 문제 상태 자동 업데이트 (data/structural_issues.xlsx 갱신)
python scripts/update_structural_issues.py
```

`update_structural_issues.py` 동작:
- S00026 **PASS** → 상태 `해결` (연두)
- S00026 **FAIL** + 문제유형 `GT_NaN` → 상태 `미해결` (노랑)
- S00026 **FAIL** + 문제유형 `ITCD불일치` → 상태 `처리불가` (회색)
- S00026 결과 없음 (`-`) → 상태 변경 없음

---

## 서브에이전트 호출 규칙

### table-extractor
- **호출 시점**: STEP 3 진입 시 4종 테이블 동시 병렬 호출
- **지침 파일**: `.claude/agents/table-extractor/AGENT.md`
- **출력**: `output/extracted/{upper_obj}_{table_type}_{run_id}.json`

### rule-optimizer
- **호출 시점**: STEP 5에서 MISMATCH > 0일 때
- **지침 파일**: `.claude/agents/rule-optimizer/AGENT.md`
- **수정 범위**: `rules/extraction_rules.py`의 메서드 **내부 로직만** 수정 가능 (시그니처 변경 금지)
- **출력**: 수정된 `rules/extraction_rules.py` + `rules/rule_history.json`

---

## 사용자 인터랙션 규칙

다음 상황에서 AskUserQuestion 사용:
1. STEP 1: 키워드 스캔 2회 실패 → 관련 페이지 번호 질문
2. STEP 2: 상품 매핑 불가 → 유사 후보 제시 후 확인
3. STEP 5/6: 불일치 원인 모호 → 구체적 사례 제시 후 해석 확인
4. STEP 7: 파일명에서 날짜 파싱 불가 → 유효시작일 직접 입력 요청
5. STEP 6: 3회 고도화 후에도 실패 → 해당 건 수동 처리 요청

---

## 파일 경로 규약

- `run_id` 형식: `YYYYMMDD_HHMMSS`
- 모든 중간 결과에 `run_id` 포함
- `output/extracted/`의 성공 건 JSON은 회귀 테스트 셋으로 보관 (삭제 금지)
- 실행 레지스트리: `output/logs/run_registry.json`

---

## 초기화 (최초 1회 실행)

```bash
python .claude/skills/code-converter/scripts/init_code_mappings.py \
  --templates data/templates/ \
  --output .claude/skills/code-converter/references/code_mappings.json
```
