"""
compare_with_db.py — 기존 판매중_* 데이터와 행 단위 비교

Usage:
    python compare_with_db.py \
        --input output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json \
        --db data/existing/판매중_{table_name}정보.xlsx \
        --product-code 2258A01 \
        --output output/reports/{upper_obj}_{table_type}_{run_id}_report.json
"""

import argparse
import json
import os

try:
    import openpyxl
except ImportError:
    print("ERROR: openpyxl이 필요합니다. pip install openpyxl")
    exit(1)


# 테이블별 핵심 비교 필드
COMPARE_FIELDS = {
    "S00026": ["ISRN_TERM_INQY_CODE", "PAYM_TERM_INQY_CODE", "MINU_GNDR_CODE", "MIN_AG", "MAX_AG"],
    "S00027": ["ISRN_TERM_INQY_CODE", "PAYM_TERM_INQY_CODE"],
    "S00028": ["PAYM_CYCL_INQY_CODE"],
    "S00022": ["MIN_AG", "MAX_AG"],
}


def load_db_data(db_path: str, product_code: str) -> list:
    """기존 DB에서 특정 상품코드의 데이터 로드"""
    wb = openpyxl.load_workbook(db_path, read_only=True, data_only=True)
    ws = wb.active

    headers = []
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(row)]
        else:
            row_dict = {headers[j]: row[j] for j in range(min(len(headers), len(row)))}
            # 상품코드 필터링
            upper = str(row_dict.get("UPPER_OBJECT_CODE", "")).strip()
            if upper == product_code:
                rows.append(row_dict)

    wb.close()
    return rows


def make_row_key(row: dict, fields: list) -> tuple:
    """비교용 행 키 생성"""
    return tuple(str(row.get(f, "")).strip() for f in fields)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--product-code", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        coded_data = json.load(f)

    table_type = coded_data.get("table_type", "")
    coded_rows = coded_data.get("coded_rows", [])

    compare_fields = COMPARE_FIELDS.get(table_type, [])

    # DB 데이터 로드
    if not os.path.exists(args.db):
        print(f"WARNING: DB 파일 없음: {args.db}. NEW로 분류.")
        db_rows = []
    else:
        db_rows = load_db_data(args.db, args.product_code)

    # 행 키 셋 생성
    db_key_set = {make_row_key(r, compare_fields): r for r in db_rows}
    extracted_key_set = {make_row_key(r, compare_fields): r for r in coded_rows}

    match = []
    mismatch = []
    new_rows = []
    missing = []

    # 추출 결과 분류
    for key, row in extracted_key_set.items():
        if key in db_key_set:
            match.append({"key": key, "extracted": row, "db": db_key_set[key]})
        else:
            new_rows.append({"key": key, "extracted": row})

    # 누락 탐지 (DB에 있으나 추출 결과에 없는 것)
    for key, row in db_key_set.items():
        if key not in extracted_key_set:
            missing.append({"key": key, "db": row})

    # MISMATCH: 동일 키이지만 값이 다른 경우 (지금은 단순 키 비교이므로 추후 필요시 확장)

    summary = {
        "total_extracted": len(coded_rows),
        "total_db": len(db_rows),
        "match": len(match),
        "mismatch": len(mismatch),
        "new": len(new_rows),
        "missing": len(missing)
    }

    passed = len(mismatch) == 0 and len(missing) == 0

    result = {
        "table_type": table_type,
        "product_code": args.product_code,
        "summary": summary,
        "pass": passed,
        "fail_reason": f"MISMATCH {len(mismatch)}건, MISSING {len(missing)}건" if not passed else None,
        "mismatches": mismatch,
        "missing": missing,
        "new_rows": new_rows
    }

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    status = "PASS" if passed else "FAIL"
    print(f"{status}: match={len(match)}, mismatch={len(mismatch)}, new={len(new_rows)}, missing={len(missing)}")
    return 0 if passed else 1


if __name__ == "__main__":
    exit(main())
