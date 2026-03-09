# validator 스킬

## 역할
추출된 데이터를 기존 DB와 비교하고 정합성을 검증한다. 룰 변경 후 전체 회귀 테스트를 실행한다.

## 검증 기준
- **MATCH**: 기존 데이터와 완전 일치
- **MISMATCH**: 기존 데이터와 값이 다름 → STEP 6 진행
- **NEW**: 기존 데이터에 없는 행 (신규 상품이면 정상)
- **MISSING**: 기존 데이터에 있으나 추출에서 누락 → STEP 3 재실행 (최대 2회)

## 스크립트

### compare_with_db.py
- **용도**: 기존 판매중_* 데이터와 행 단위 비교
- **STEP 5 시작 시 호출**

```bash
python .claude/skills/validator/scripts/compare_with_db.py \
  --input output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json \
  --db data/existing/판매중_{table_name}정보.xlsx \
  --output output/reports/{upper_obj}_{table_type}_{run_id}_report.json
```

### check_integrity.py
- **용도**: 나이범위/기간 정합성 검증

```bash
python .claude/skills/validator/scripts/check_integrity.py \
  --input output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json
```

### check_combination_completeness.py
- **용도**: S00026 전용 - 보험기간×납입기간×성별 카테시안 곱 vs 추출 행 수

```bash
python .claude/skills/validator/scripts/check_combination_completeness.py \
  --input output/extracted/{upper_obj}_S00026_{run_id}_coded.json \
  --output output/reports/{upper_obj}_S00026_{run_id}_completeness.json
```

### regression_test.py
- **용도**: 룰 변경 후 전체 성공 상품 재검증
- **STEP 6 룰 수정 후 호출**

```bash
python .claude/skills/validator/scripts/regression_test.py \
  --rules rules/extraction_rules.py \
  --registry output/logs/run_registry.json \
  --output output/reports/regression_{run_id}.json
```

## 성공 기준
- `MISMATCH = 0, MISSING = 0` → PASS
- `NEW > 0` → 정상 (신규 상품), 로그만 기록
