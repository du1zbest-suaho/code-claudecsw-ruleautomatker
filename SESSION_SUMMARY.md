# 세션 작업 완료 요약
> 최종 업데이트: 2026-03-07

---

## 현재 시스템 상태: ✅ 셋업 완료 + 초기 추출 완료

---

## 1. 시스템 구조 (셋업 완료)

```
ruleautomatker/
├── CLAUDE.md                          ← 메인 오케스트레이터 지침
├── rules/
│   ├── extraction_rules.py            ← 추출 룰 (수정 가능)
│   ├── product_exceptions.json        ← 상품별 예외 룰
│   └── rule_history.json              ← 룰 변경 이력
├── data/
│   ├── pdf/                           ← 사업방법서 PDF (51개)
│   ├── existing/                      ← 판매중_* Ground Truth DB
│   ├── templates/                     ← 업로드 양식 템플릿 4종 (S00022~S00028)
│   └── models/                        ← 모델상세 원본
├── .claude/
│   ├── skills/
│   │   ├── run-manager/               ← init_run.py, manage_registry.py
│   │   ├── pdf-preprocessor/          ← extract_pdf.py, scan_keywords.py, parse_sub_types.py
│   │   ├── product-mapper/            ← search_products.py, map_codes.py, collect_special_contracts.py
│   │   ├── code-converter/            ← convert_codes.py, validate_codes.py, init_code_mappings.py
│   │   │   └── references/code_mappings.json
│   │   ├── validator/                 ← compare_with_db.py, check_integrity.py, check_combination_completeness.py
│   │   └── xlsx-generator/            ← generate_upload.py, parse_valid_date.py
│   └── agents/
│       ├── table-extractor/AGENT.md   ← LLM 테이블 추출 에이전트 지침
│       └── rule-optimizer/AGENT.md    ← 룰 고도화 에이전트 지침
└── output/
    ├── extracted/                     ← 추출 중간 결과 JSON + 텍스트
    ├── upload/                        ← 최종 업로드 xlsx (140개 생성됨)
    ├── reports/                       ← 검증 리포트
    └── logs/                          ← run_registry, batch 로그
```

---

## 2. 업로드 파일 생성 현황 (output/upload/)

| 테이블 | 파일 수 | 비고 |
|--------|---------|------|
| S00022 (보기개시나이) | 8개 | 연금 상품만 해당 (정상) |
| S00026 (가입가능나이) | 33개 | 32개 상품 커버 |
| S00027 (가입가능보기납기) | 47개 | 전체 상품 대부분 커버 |
| S00028 (가입가능납입주기) | 52개 | 전체 상품 커버 |
| **합계** | **140개** | |

---

## 3. extraction_rules.py 현재 지원 패턴

### S00022 (보기개시나이)
- `연금개시나이\n- N세 ~ N세` (실제 형식 - 개행 포함)
- `연금개시나이: N세~N세` (같은 줄)
- `연금개시나이: N세` (단일 나이)

### S00026 (가입가능나이)
- **인라인 범위**: `5년납 만15세~80세 만15세~80세` (H간병보험 등)
- **분리형**: `가입최저나이: 15세` + 최고나이 테이블 (H종신보험 등)
- **갱신형 실손**: `1년\n50세~90세\n전기납` (노후실손 등)
- **세부보험종목별**: `종신연금형(개인형)\n45~85세` (연금보험 등)

### S00027 (가입가능보기납기)
- 보험기간 × 납입기간 조합 (전체 텍스트에서 추출)

### S00028 (가입가능납입주기)
- `납입주기: 월납, 3월납` 패턴
- 단순 키워드 탐색 폴백

---

## 4. 미처리 항목 (후속 작업 필요)

### S00026 미추출 상품 (~19개)
- 바로연금보험, 스마트V연금보험, Wealth단체/직장인연금보험 등
- 원인: 나이표 형식이 독특 (연금개시나이 기준 동적 계산 등)
- 대응: rule-optimizer 서브에이전트 호출 (STEP 6) 또는 product_exceptions.json에 고정값 추가

### S00022 바로연금보험 (1개)
- `라. 피보험자 가입나이 및 연금개시나이` 섹션에 S00022 데이터 있음
- 현재 S00022로 추출되지 않음 (연금개시나이 섹션이 별도)

---

## 5. 다음 작업 시 실행 방법

### 새 PDF 처리 (7단계 워크플로우)
```bash
# 1. run_id 생성
python .claude/skills/run-manager/scripts/init_run.py

# 2. PDF 전처리 (ZIP 형식이어야 함)
python .claude/skills/pdf-preprocessor/scripts/extract_pdf.py \
  --input data/pdf/{파일명}.zip --output output/extracted/ --run-id {run_id}

# ... CLAUDE.md 워크플로우 참조
```

### 기존 combined.txt로 재추출
```bash
cd d:/code/claudecsw/ruleautomatker
python -c "
from rules.extraction_rules import ExtractionRules
rules = ExtractionRules()
with open('output/extracted/{상품명}_combined.txt', encoding='utf-8') as f:
    text = f.read()
print(rules.extract_age_table(text, '{상품코드}'))
"
```

### 룰 고도화 후 배치 재처리
```bash
# extraction_rules.py 수정 후
python -c "from rules.extraction_rules import ExtractionRules; ..."
# 위의 배치 추출 → 코드변환 → xlsx생성 스크립트 순서로 실행
```

---

## 6. 주요 파일 경로

| 용도 | 경로 |
|------|------|
| 추출 룰 | `rules/extraction_rules.py` |
| 상품별 예외 | `rules/product_exceptions.json` |
| 코드 매핑 | `.claude/skills/code-converter/references/code_mappings.json` |
| 실행 레지스트리 | `output/logs/run_registry.json` |
| Ground Truth | `data/existing/판매중_*.xlsx` |
| 업로드 템플릿 | `data/templates/S0002{2,6,7,8}_업로드양식.xlsx` |

---

## 7. 알려진 이슈

1. **data/pdf/*.pdf**: 현재 PDF는 ZIP 형식이 아닌 일반 PDF. `extract_pdf.py`는 ZIP을 기대함.
   - 실제 사업방법서가 ZIP 형식(`manifest.json` + `{n}.jpeg` + `{n}.txt`)으로 제공될 때 사용
   - 현재는 `pdfminer`/`PyMuPDF`로 직접 PDF 파싱하는 방식으로 운영됨

2. **인코딩**: Windows 환경에서 터미널 출력 일부 깨짐. 파일 자체는 UTF-8 정상.

3. **S00026 일부 미추출**: 연금보험류 19개 상품은 현재 룰로 미추출. product_exceptions.json으로 고정값 지정 가능.
