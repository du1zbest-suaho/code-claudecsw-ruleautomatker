"""
compare_with_db.py — 기존 판매중_* 데이터와 행 단위 비교

비교키: data/models/{테이블}_모델상세.xlsx의 ROW_NO ~ CREATE_DATE 사이 전체 컬럼
        (model_key_loader.py에서 동적 로드)

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
import sys
import warnings

warnings.filterwarnings("ignore")

try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas가 필요합니다. pip install pandas openpyxl")
    sys.exit(1)

# model_key_loader는 같은 디렉토리에 있음
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from model_key_loader import load_model_key_cols, make_row_key, get_active_key_cols  # noqa: E402


def load_db_data(db_path: str, product_code: str) -> list:
    """기존 DB에서 특정 UPPER_OBJECT_CODE 행 로드 (pandas 사용)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_excel(db_path)
    # UPPER_OBJECT_CODE 컬럼이 없으면 ISRN_KIND_DTCD+ITCD 조합으로 필터
    if "UPPER_OBJECT_CODE" in df.columns:
        filtered = df[df["UPPER_OBJECT_CODE"].astype(str).str.strip() == str(product_code)]
    elif "ISRN_KIND_DTCD" in df.columns:
        # product_code = dtcd+itcd (예: "2061A01") → DTCD 4자리 앞부분으로 필터
        dtcd_str = product_code[:4]
        filtered = df[df["ISRN_KIND_DTCD"].astype(str) == dtcd_str]
    else:
        filtered = df
    return filtered.to_dict("records")


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

    # 모델상세에서 전체 비교키 컬럼 로드
    all_key_cols = load_model_key_cols(table_type)
    if not all_key_cols:
        print(f"WARNING: {table_type} 모델상세 파일 없음 또는 키 컬럼 없음. 빈 비교로 처리.")

    # DB 데이터 로드
    if not os.path.exists(args.db):
        print(f"WARNING: DB 파일 없음: {args.db}. NEW로 분류.")
        db_rows = []
    else:
        db_rows = load_db_data(args.db, args.product_code)

    # DTCD별 활성 컬럼: GT에 non-None 값이 있는 컬럼 (GT 기준)
    compare_fields = get_active_key_cols(db_rows, coded_rows, all_key_cols)

    # 행 키셋 생성
    db_key_set = {make_row_key(r, compare_fields): r for r in db_rows}
    extracted_key_set = {make_row_key(r, compare_fields): r for r in coded_rows}

    match = []
    mismatch = []
    new_rows = []
    missing = []

    for key, row in extracted_key_set.items():
        if key in db_key_set:
            match.append({"key": key, "extracted": row, "db": db_key_set[key]})
        else:
            new_rows.append({"key": key, "extracted": row})

    for key, row in db_key_set.items():
        if key not in extracted_key_set:
            missing.append({"key": key, "db": row})

    summary = {
        "total_extracted": len(coded_rows),
        "total_db": len(db_rows),
        "match": len(match),
        "mismatch": len(mismatch),
        "new": len(new_rows),
        "missing": len(missing),
        "compare_fields": compare_fields,
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
        "new_rows": new_rows,
    }

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    status = "PASS" if passed else "FAIL"
    print(f"{status}: match={len(match)}, mismatch={len(mismatch)}, new={len(new_rows)}, missing={len(missing)}")
    print(f"  비교키 {len(compare_fields)}개: {compare_fields[:5]}{'...' if len(compare_fields) > 5 else ''}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
