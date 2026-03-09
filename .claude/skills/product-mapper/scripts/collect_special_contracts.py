"""
collect_special_contracts.py — 동일 UPPER_OBJECT_CODE의 특약(type=02) 전체 수집

Usage:
    python collect_special_contracts.py \
        --mapping output/extracted/{run_id}_mapping.json \
        --db data/existing/판매중_상품구성정보.xlsx \
        --output output/extracted/{run_id}_special_contracts.json
"""

import argparse
import json
import os

try:
    import openpyxl
except ImportError:
    print("ERROR: openpyxl이 필요합니다. pip install openpyxl")
    exit(1)


def load_product_db(db_path: str) -> list:
    wb = openpyxl.load_workbook(db_path, read_only=True, data_only=True)
    ws = wb.active

    headers = []
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(row)]
        else:
            row_dict = {headers[j]: row[j] for j in range(min(len(headers), len(row)))}
            rows.append(row_dict)

    wb.close()
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.mapping, "r", encoding="utf-8") as f:
        mapping_data = json.load(f)

    # 주계약의 UPPER_OBJECT_CODE 목록 수집
    upper_codes = set()
    for pm in mapping_data.get("product_mappings", []):
        upper_codes.add(pm["upper_object_code"])

    print(f"Searching special contracts for UPPER_OBJECT_CODEs: {upper_codes}")

    rows = load_product_db(args.db)

    special_contracts = []
    for row in rows:
        upper = str(row.get("UPPER_OBJECT_CODE", "")).strip()
        prod_type = str(row.get("PROD_ADTO_DVSN_CODE", "")).strip()

        if upper in upper_codes and prod_type == "02":
            special_contracts.append({
                "upper_object_code": upper,
                "lower_object_code": str(row.get("LOWER_OBJECT_CODE", "")).strip(),
                "isrn_kind_dtcd": str(row.get("ISRN_KIND_DTCD", "")).strip(),
                "isrn_kind_itcd": str(row.get("ISRN_KIND_ITCD", "")).strip(),
                "prod_dtcd": str(row.get("PROD_DTCD", "")).strip(),
                "prod_itcd": str(row.get("PROD_ITCD", "")).strip(),
                "prod_type": "02",
                "sale_name": str(row.get("SALE_NM", ""))
            })

    result = {
        "related_special_contracts": special_contracts,
        "total_special_contracts": len(special_contracts)
    }

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Found {len(special_contracts)} special contracts → {args.output}")
    return 0


if __name__ == "__main__":
    exit(main())
