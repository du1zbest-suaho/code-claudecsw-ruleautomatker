"""
check_combination_completeness.py — S00026 전용: 보험기간×납입기간×성별 카테시안 곱 vs 추출 행 수

Usage:
    python check_combination_completeness.py \
        --input output/extracted/{upper_obj}_S00026_{run_id}_coded.json \
        --output output/reports/{upper_obj}_S00026_{run_id}_completeness.json
"""

import argparse
import json
import os
from itertools import product


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        coded_data = json.load(f)

    table_type = coded_data.get("table_type", "")
    if table_type != "S00026":
        print(f"WARNING: S00026 전용 스크립트. 현재 테이블: {table_type}")
        return 0

    coded_rows = coded_data.get("coded_rows", [])

    # 고유 보험기간, 납입기간, 성별 목록 추출
    insurance_periods = sorted(set(str(r.get("ISRN_TERM_INQY_CODE", "")) for r in coded_rows if r.get("ISRN_TERM_INQY_CODE")))
    payment_periods = sorted(set(str(r.get("PAYM_TERM_INQY_CODE", "")) for r in coded_rows if r.get("PAYM_TERM_INQY_CODE")))
    genders = sorted(set(str(r.get("MINU_GNDR_CODE", "")) for r in coded_rows if r.get("MINU_GNDR_CODE")))

    # 실제 추출된 조합
    extracted_combos = set(
        (str(r.get("ISRN_TERM_INQY_CODE", "")),
         str(r.get("PAYM_TERM_INQY_CODE", "")),
         str(r.get("MINU_GNDR_CODE", "")))
        for r in coded_rows
    )

    # 카테시안 곱으로 기대 조합 계산
    expected_combos = set(product(insurance_periods, payment_periods, genders))

    missing_combos = expected_combos - extracted_combos
    extra_combos = extracted_combos - expected_combos

    is_complete = len(missing_combos) == 0

    result = {
        "table_type": "S00026",
        "insurance_periods": insurance_periods,
        "payment_periods": payment_periods,
        "genders": genders,
        "expected_count": len(expected_combos),
        "extracted_count": len(extracted_combos),
        "missing_count": len(missing_combos),
        "extra_count": len(extra_combos),
        "is_complete": is_complete,
        "missing_combinations": [
            {"ISRN_TERM_INQY_CODE": c[0], "PAYM_TERM_INQY_CODE": c[1], "MINU_GNDR_CODE": c[2]}
            for c in sorted(missing_combos)
        ],
        "extra_combinations": [
            {"ISRN_TERM_INQY_CODE": c[0], "PAYM_TERM_INQY_CODE": c[1], "MINU_GNDR_CODE": c[2]}
            for c in sorted(extra_combos)
        ]
    }

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if is_complete:
        print(f"COMPLETE: {len(extracted_combos)}개 조합 = 기대값 {len(expected_combos)}개")
    else:
        print(f"INCOMPLETE: 누락 {len(missing_combos)}개 조합:")
        for c in sorted(missing_combos):
            print(f"  - 보험기간={c[0]}, 납입기간={c[1]}, 성별={c[2]}")

    return 0 if is_complete else 1


if __name__ == "__main__":
    exit(main())
