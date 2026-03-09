# table-extractor 서브에이전트

## 역할
사업방법서 페이지에서 구조화된 테이블 데이터를 추출한다. 텍스트 기반 추출과 이미지 기반 추출을 병행하여 교차검증한다.

## 호출 조건
메인 에이전트가 STEP 3 진입 시 호출. S00022, S00026, S00027, S00028 — 4개를 병렬로 동시 호출.

## 입력 (메인 에이전트로부터)
- `table_type`: S00022 | S00026 | S00027 | S00028
- `run_id`: 실행 ID
- `product_code`: UPPER_OBJECT_CODE (예: 2258A01)
- `relevant_pages_json`: `output/extracted/{run_id}_keywords.json` 경로
- `pages_json`: `output/extracted/{run_id}_pages.json` 경로
- `sub_types`: 세부보험종목 목록
- `rules_exist`: `rules/extraction_rules.py` 존재 여부

## 처리 흐름

### Case A: 룰 파일 있음 (`rules_exist=true`)
```bash
python .claude/agents/table-extractor/scripts/run_extraction_rules.py \
  --table-type {table_type} \
  --product-code {product_code} \
  --input output/extracted/{run_id}_page_text.txt \
  --rules rules/extraction_rules.py \
  --output output/extracted/{product_code}_{table_type}_{run_id}.json
```
스크립트 오류 시 → Case B로 폴백

### Case B: 룰 파일 없음 (LLM 직접 추출)

**Phase 1 — 텍스트 기반 추출**:

관련 페이지 텍스트를 읽어 아래 테이블별 지시에 따라 구조화된 JSON 추출:

#### S00026 (가입가능나이)
```
이 사업방법서 텍스트에서 보험기간별, 납입기간별, 성별 가입 가능 나이 범위를 추출하세요.
세부보험종목(간편가입형/일반가입형/건강가입형 등)별로 다르면 각각 분리하세요.

출력 형식:
[{"sub_type": "간편가입형(0년)", "insurance_period": "90세만기", "payment_period": "10년납",
  "gender": "남자", "min_age": 15, "max_age": 79}]
```

#### S00027 (가입가능보기납기)
```
보험기간과 납입기간의 가능한 모든 조합을 추출하세요.
예: 90세만기+10년납, 90세만기+15년납, 종신+10년납 등

출력 형식:
[{"sub_type": "기본형", "insurance_period": "90세만기", "payment_period": "10년납"}]
```

#### S00028 (가입가능납입주기)
```
보험료 납입주기를 추출하세요.
예: 월납, 3월납, 6월납, 년납, 일시납

출력 형식:
[{"sub_type": "기본형", "payment_cycle": "월납"}]
```

#### S00022 (보기개시나이)
```
연금개시나이 등 보기개시나이 관련 정보를 추출하세요.
해당 내용이 없으면 빈 배열 반환.

출력 형식:
[{"sub_type": "기본형", "min_age": 45, "max_age": 80}]
```

**Phase 2 — 이미지 기반 추출 (조건부)**:

텍스트 추출 confidence가 "high"이고 스키마 검증 통과 시 → 이미지 추출 스킵.
그 외 → 동일한 지시로 이미지에서 추출.

**Phase 3 — 교차검증**:
- 텍스트 결과 = 이미지 결과 → 확정, confidence="high"
- 불일치 → 이미지 결과 우선 채택, discrepancies 기록
- 양쪽 모두 스키마 실패 → 자동 재시도 (최대 2회). 2회 실패 → 에스컬레이션

## 출력
`output/extracted/{product_code}_{table_type}_{run_id}.json`
```json
{
  "table_type": "S00026",
  "product_code": "2258A01",
  "run_id": "20260306_143022",
  "source": "cross_verified",
  "confidence": "high",
  "image_used": false,
  "raw_data": [
    {
      "sub_type": "간편가입형(0년)",
      "insurance_period": "90세만기",
      "payment_period": "10년납",
      "gender": "남자",
      "min_age": 15,
      "max_age": 79,
      "text_source": {"min_age": 15, "max_age": 79},
      "image_source": null,
      "match": true
    }
  ],
  "discrepancies": [],
  "page_texts": {"3": "...(페이지 텍스트)..."}
}
```

## 스키마 검증 기준
- `sub_type`: 문자열, 필수
- `min_age`, `max_age`: 정수, 0~120 범위 (S00026, S00022)
- `insurance_period`, `payment_period`: 문자열 (S00026, S00027)
- `payment_cycle`: 문자열 (S00028)
- min_age < max_age (나이 있을 때)

## Two-Phase 이미지 전략
- confidence "high" + 스키마 OK → image_used=false (비용 절감)
- confidence "medium" 이하 또는 스키마 실패 → 이미지 추출 실행 → image_used=true
