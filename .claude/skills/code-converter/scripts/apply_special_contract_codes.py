"""
apply_special_contract_codes.py — 주계약 코드 변환 결과를 특약에 복사 + OBJECT_CODE 교체

Usage:
    python apply_special_contract_codes.py \
        --coded output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json \
        --special-contracts output/extracted/{run_id}_special_contracts.json \
        --output output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json
"""

import argparse
import copy
import json
import os


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coded", required=True, help="주계약 코드 변환 결과")
    parser.add_argument("--special-contracts", required=True, help="특약 목록")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.coded, "r", encoding="utf-8") as f:
        coded_data = json.load(f)

    with open(args.special_contracts, "r", encoding="utf-8") as f:
        special_data = json.load(f)

    special_contracts = special_data.get("related_special_contracts", [])

    if not special_contracts:
        print("특약 없음. 원본 그대로 출력.")
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(coded_data, f, ensure_ascii=False, indent=2)
        return 0

    # 주계약 코드 변환 행
    main_coded_rows = coded_data.get("coded_rows", [])

    # 특약별로 주계약 행을 복사하여 OBJECT_CODE 교체
    special_contract_rows = []
    for sc in special_contracts:
        for row in main_coded_rows:
            new_row = copy.deepcopy(row)
            new_row["_upper_object_code"] = sc["upper_object_code"]
            new_row["_lower_object_code"] = sc["lower_object_code"]
            new_row["_prod_type"] = "02"
            new_row["_special_contract"] = True
            new_row["_sale_name"] = sc.get("sale_name", "")
            special_contract_rows.append(new_row)

    print(f"특약 {len(special_contracts)}개 × 주계약 {len(main_coded_rows)}행 = {len(special_contract_rows)}행 생성")

    # 결과 통합
    result = {
        **coded_data,
        "special_contract_rows": special_contract_rows,
        "special_contract_count": len(special_contracts)
    }

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"특약 코드 적용 완료 → {args.output}")
    return 0


if __name__ == "__main__":
    exit(main())
