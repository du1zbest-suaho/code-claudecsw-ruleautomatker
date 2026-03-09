"""
check_integrity.py — 나이범위/기간 정합성 검증

Usage:
    python check_integrity.py \
        --input output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json
"""

import argparse
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        coded_data = json.load(f)

    table_type = coded_data.get("table_type", "")
    coded_rows = coded_data.get("coded_rows", [])

    errors = []
    warnings = []

    for i, row in enumerate(coded_rows):
        # 나이 범위 검증
        min_ag = row.get("MIN_AG")
        max_ag = row.get("MAX_AG")
        if min_ag is not None and max_ag is not None:
            try:
                min_ag = int(min_ag)
                max_ag = int(max_ag)
                if min_ag >= max_ag:
                    errors.append(f"행 {i}: MIN_AG({min_ag}) >= MAX_AG({max_ag})")
                if min_ag < 0 or min_ag > 120:
                    errors.append(f"행 {i}: MIN_AG({min_ag}) 범위 초과 (0~120)")
                if max_ag < 0 or max_ag > 120:
                    errors.append(f"행 {i}: MAX_AG({max_ag}) 범위 초과 (0~120)")
            except (ValueError, TypeError):
                warnings.append(f"행 {i}: 나이값 숫자 변환 실패 (min={min_ag}, max={max_ag})")

        # 납입기간 ≤ 보험기간 검증 (S00026, S00027)
        if table_type in ["S00026", "S00027"]:
            isrn_term = row.get("ISRN_TERM")
            paym_term = row.get("PAYM_TERM")
            isrn_dvsn = row.get("ISRN_TERM_DVSN_CODE", "")
            paym_dvsn = row.get("PAYM_TERM_DVSN_CODE", "")

            if isrn_term is not None and paym_term is not None:
                try:
                    isrn_val = int(isrn_term)
                    paym_val = int(paym_term)

                    # 종신(A)이면 납입기간 제한 없음
                    if isrn_dvsn != "A" and paym_dvsn != "A":
                        # 동일 단위일 때만 비교 (년 기준)
                        if isrn_dvsn == paym_dvsn and paym_val > isrn_val:
                            errors.append(
                                f"행 {i}: 납입기간({paym_val}{paym_dvsn}) > 보험기간({isrn_val}{isrn_dvsn})"
                            )
                except (ValueError, TypeError):
                    warnings.append(f"행 {i}: 기간값 숫자 변환 실패")

    if errors:
        print(f"FAIL: {len(errors)} 정합성 오류")
        for e in errors:
            print(f"  ERROR: {e}")
        for w in warnings:
            print(f"  WARN: {w}")
        return 1
    else:
        print(f"PASS: {len(coded_rows)}행 정합성 검증 통과")
        for w in warnings:
            print(f"  WARN: {w}")
        return 0


if __name__ == "__main__":
    exit(main())
