"""
validate_codes.py — 변환된 코드값이 허용 코드에 포함되는지 검증

Usage:
    python validate_codes.py \
        --input output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json \
        --mappings .claude/skills/code-converter/references/code_mappings.json
"""

import argparse
import json
import sys


# 테이블별 검증 대상 컬럼
VALIDATE_FIELDS = {
    "S00026": ["ISRN_TERM_DVSN_CODE", "PAYM_TERM_DVSN_CODE", "MINU_GNDR_CODE"],
    "S00027": ["ISRN_TERM_DVSN_CODE", "PAYM_TERM_DVSN_CODE"],
    "S00028": ["PAYM_CYCL_DVSN_CODE"],
    "S00022": [],
}

DEFAULTS_KEY = "_defaults"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--mappings", required=True)
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        coded_data = json.load(f)

    with open(args.mappings, "r", encoding="utf-8") as f:
        mappings = json.load(f)

    table_type = coded_data.get("table_type", "")
    coded_rows = coded_data.get("coded_rows", [])

    fields_to_validate = VALIDATE_FIELDS.get(table_type, [])
    defaults = mappings.get(DEFAULTS_KEY, {})
    table_mappings = mappings.get(table_type, {})

    errors = []
    warnings = []

    for i, row in enumerate(coded_rows):
        for field in fields_to_validate:
            val = row.get(field)
            if val is None:
                warnings.append(f"행 {i}: {field}=None")
                continue

            # 허용값 조회 (테이블별 → 기본값 순서)
            allowed = table_mappings.get(field) or defaults.get(field)
            if allowed and str(val) not in [str(a) for a in allowed]:
                errors.append(f"행 {i}: {field}={val} 허용값 아님 ({allowed})")

        # None 값 경고
        for key in ["ISRN_TERM", "PAYM_TERM"] if table_type in ["S00026", "S00027"] else []:
            if row.get(key) is None:
                warnings.append(f"행 {i}: {key}=None (변환 오류 가능)")

    # 결과 출력
    if errors:
        print(f"FAIL: {len(errors)} 코드 오류")
        for e in errors:
            print(f"  ERROR: {e}")
        if warnings:
            for w in warnings:
                print(f"  WARN: {w}")
        return 1
    else:
        print(f"PASS: {len(coded_rows)}행 코드 유효성 검증 통과")
        for w in warnings:
            print(f"  WARN: {w}")
        return 0


if __name__ == "__main__":
    exit(main())
