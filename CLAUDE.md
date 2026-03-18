# 보험 사업방법서 속성 추출 자동화 에이전트

## 프로젝트 개요

한화생명 보험 상품의 사업방법서(ZIP 형식)에서 가입 가능 연령, 보험기간/납입기간, 납입주기, 보기개시나이 정보를 자동 추출하여 시스템 업로드 양식(xlsx)으로 변환한다.

### 핵심 원칙
- **Ground Truth**: 기존 DB(판매중_* 파일)가 정답. 추출 결과가 불일치하면 DB 기준으로 룰을 수정한다.
- **무영향 원칙**: 특정 상품을 위한 룰 변경이 다른 상품의 추출 정확도에 영향을 주면 안 된다.
- **교차검증 필수**: PDF 내 txt(텍스트)와 jpeg(이미지)를 모두 활용하여 교차검증한다.
- **일반화 원칙**: 사업방법서별 하드코딩 금지. 모든 추출 로직은 다양한 양식에 대해 일반화된 방식으로 동작해야 한다.

### 기준정보 용어 및 구조

| 약칭 | 정식명 | DB 컬럼 | 설명 |
|------|--------|---------|------|
| 보종세 | 보험종류세코드 | `ISRN_KIND_DTCD` | 하나의 보험종류를 관리하는 코드 |
| 보종목 | 보험종류목코드 | `ISRN_KIND_ITCD` | 보험종류 유형별 분류 코드 |
| 상품세 | 상품코드세 | `PROD_DTCD` | 보험종류세목 하위 주계약/특약 코드 |
| 상품목 | 상품코드목 | `PROD_ITCD` | 상품세 유형별 분류 코드 (3자리 zero-pad) |

#### 기준정보 관리 테이블 계층

| Level | 관리 키 | 해당 테이블 |
|-------|---------|-----------|
| 1 | 보종세 | — |
| 2 | 보종세 + 보종목 | — |
| **3** | **보종세 + 보종목 + 상품세 + 상품목** | **S00022, S00026, S00027, S00028** |
| 4 | 상품세 + 상품목 | — |

> S00022/26/27/28은 4개 키 조합으로 GT 행이 식별된다. 비교 및 GT 건수 필터링 시 반드시 4개 키를 모두 사용해야 한다.

### 입력 파일 위치
- 사업방법서: `data/pdf/*.pdf`
- **PDF→상품 매핑**: `data/existing/판매중_상품구성_사업방법서_매핑.xlsx` ← 핵심 참조 파일
- 검증 Ground Truth: `data/existing/판매중_가입나이정보_0312.xlsx` 등
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

> **보종목 추출 원칙**: 사업방법서 "1. 보험종목에 관한 사항"에서
> - **가. 보험종목의 명칭** → 보종세(`ISRN_KIND_DTCD`) 매핑 근거
> - **나. 보험종목의 구성** → 보종목(`ISRN_KIND_ITCD`) 매핑 근거
>
> 보종명은 `보험종목의 명칭 + " " + 보험종목의 구성 명칭`으로 생성된다.
> 신규 사업방법서 처리 시 이 섹션에서 보종목을 **정확히** 추출해야
> 4개 키 매핑 및 GT 비교가 올바르게 동작한다.

`fallback_needed=true` 반환 시: 전체 텍스트를 LLM에게 제공하여 관련 페이지 번호 판단 요청 (자동 재시도 1회). 실패 시 사용자에게 관련 페이지 번호 질문.

### STEP 2: 상품 매핑

`data/existing/판매중_상품구성_사업방법서_매핑.xlsx`에서 PDF 파일명으로 직접 조회한다.
키워드 추론·LLM 판단 불필요. 파일명이 정확히 일치해야 한다.

파일 구조:
| 컬럼 | 설명 |
|------|------|
| `ISRN_KIND_DTCD` | **보종세** — 보험종류세코드 |
| `ISRN_KIND_ITCD` | **보종목** — 보험종류목코드 (추출의 핵심 매핑 키) |
| `ISRN_KIND_SALE_NM` | 보험종목 판매명 |
| `PROD_DTCD` / `PROD_ITCD` | **상품세 / 상품목** — GT 비교 4개 키의 나머지 2개, `PROD_ITCD`는 3자리 zero-pad |
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

**GT 행 필터링 기준 (4개 키)**:
- 매핑 파일에서 해당 PDF-DTCD에 속한 `(ISRN_KIND_ITCD, PROD_ITCD)` 쌍 목록으로 GT 행 필터
- S00026: 추가로 `MAX_AG ≠ 999` umbrella 행 제외 (시스템 내부 처리용 전연령 공통 행)
- 구현: `generate_report.py`의 `get_gt_row_count(itcd_pairs=…)`, `update_gt_generation_status.py`의 `build_dtcd_cache()`

**일치 판정 기준** (고유키 기준, raw 행수 아님):
- `len(gt_keys) == len(ex_keys)` (고유키 건수 동일) **AND** `miss_cnt == 0` (GT 키 전부 추출) → **일치**
  > GT는 ITCD별 중복 raw 행 포함 가능. 비교는 active_key_cols로 생성한 고유 키셋 기준.
- 위 두 조건 중 하나라도 불충족 → **불일치**
  - `len(ex_keys) ≠ len(gt_keys)`: 건수 상이 → 세부보험종목 목록 추출 오류 가능
  - `miss_cnt > 0` (건수 같으나 내용 다름): 테이블 정보 추출 오류 가능
  - 두 조건 모두 불충족: 복합 사유

**분기 조건**:
- 전 테이블 `len(gt_keys) == len(ex_keys) AND miss_cnt == 0` → STEP 7로 진행
- `len(ex_keys) ≠ len(gt_keys)` (건수 상이) → STEP 3 재실행 (세부보험종목 목록 힌트 포함, 최대 2회). 2회 실패 시 사용자에게 에스컬레이션
- `miss_cnt > 0` (내용 불일치) → STEP 6 (rule-optimizer 서브에이전트) 호출
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
- GT 데이터: `data/existing/판매중_가입나이정보_0312.xlsx` (S00026), `판매중_보기납기정보_0312.xlsx` (S00027), `판매중_납입주기정보_0312.xlsx` (S00028), `판매중_보기개시나이정보_0312.xlsx` (S00022)
- 추출 결과: `output/extracted/*_coded.json`

### 출력 형식
- 파일: `output/reports/작업현황_{YYYYMMDD_HHMMSS}.xlsx`
- 행: 사업방법서 파일명 (1행 = 1 PDF, 복수 DTCD는 ISRN_KIND_DTCD에 콤마 구분으로 표시)
- 컬럼 (테이블별 7개씩): `{테이블명}_추출건수`, `_GT건수`, `_일치건수`, `_미일치건수`, `_추가건수`, `_결과`, `_불일치사유`

### 결과 코드
| 코드 | 색상 | 조건 | 의미 |
|------|------|------|------|
| 일치 | 연두 | ex_cnt == gt_cnt AND miss_cnt == 0 | 건수·내용 모두 완전 일치 |
| 불일치 | 연빨강 | ex_cnt ≠ gt_cnt OR miss_cnt > 0 | 건수 상이 또는 내용 불일치 (불일치사유 컬럼 참조) |
| 미추출 | 노랑 | ex_cnt == 0, gt_cnt > 0 | GT 있으나 추출 결과 없음 |
| 신규 | 연파랑 | ex_cnt > 0, gt_cnt == 0 | GT 없고 추출 결과 있음 (신규 상품) |
| - | 회색 | ex_cnt == 0, gt_cnt == 0 | GT·추출 모두 없음 |

### 불일치사유 패턴 (4가지)

| 패턴 | 조건 | 불일치사유 | 원인 분석 |
|------|------|-----------|---------|
| 과잉추출 | extra>0, miss==0 | `추출과잉(GT:N건/추출:M건, 초과K건) — 추출 룰이 비대상 구간 포함 또는 세부보험종목 범위 오류 가능` | 룰이 비대상 체형/특약 구간을 포함하거나 sub-type 범위가 너무 넓음 |
| 순수 누락 | miss>0, extra==0 | `추출누락(GT:N건/추출:M건, 누락K건) — 추출 룰이 일부 조합 패턴 미처리 가능` | 룰이 특정 나이/기간 중간값 조합을 처리 못함 |
| 내용 불일치 | ex==gt, miss>0 | `내용불일치(건수동일N건, 누락K/초과K건) — 추출 룰이 잘못된 값 산출 가능` | 건수는 같으나 나이/기간 값이 잘못 파싱됨 |
| 복합 오류 | miss>0, extra>0, ex≠gt | `추출오류(GT:N건/추출:M건, 누락K/초과K건) — 추출 룰 전반 확인 필요` | 룰 구조 파악 실패 등 전반적 오류 |

---

## 세션 종료 절차

세션 종료 전 반드시 아래 순서로 실행하여 구조적 문제 상태를 최신화한다.

```bash
# 1. 배치 재실행 (룰 변경이 있었을 때만)
python scripts/batch_run.py --no-skip
# ※ 완료 시 update_gt_generation_status.py 자동 실행
#   → data/existing/판매중_*정보.xlsx 마지막 열 "생성여부" 컬럼 갱신

# 2. 작업현황 리포트 생성
python scripts/generate_report.py

# 3. 구조적 문제 상태 자동 업데이트 (data/structural_issues.xlsx 갱신)
python scripts/update_structural_issues.py
```

`update_structural_issues.py` 동작:
- S00026 **일치** → 상태 `해결` (연두)
- S00026 **불일치** + 문제유형 `GT_NaN` → 상태 `미해결` (노랑)
- S00026 **불일치** + 문제유형 `ITCD불일치` → 상태 `처리불가` (회색)
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
