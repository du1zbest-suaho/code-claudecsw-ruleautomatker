"""
generate_upload.py — 업로드 양식 xlsx 생성 (헤더 1~6행 보존, 7행부터 데이터)

Usage:
    python generate_upload.py \
        --input output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json \
        --template data/templates/{table_type}_업로드양식.xlsx \
        --valid-date output/extracted/{run_id}_valid_date.json \
        --product-mapping output/extracted/{run_id}_mapping.json \
        --output output/upload/{table_type}_{upper_obj}_{run_id}.xlsx
"""

import argparse
import json
import os
import shutil

try:
    import openpyxl
except ImportError:
    print("ERROR: openpyxl이 필요합니다. pip install openpyxl")
    exit(1)


# 테이블별 컬럼 매핑 (xlsx_컬럼명 → coded_row 키)
# S00026 템플릿: MIN_ISRN_TERM/MAX_ISRN_TERM, MIN_PAYM_TERM/MAX_PAYM_TERM (단일값 → MIN=MAX)
COLUMN_MAPPINGS = {
    "S00026": {
        "MIN_ISRN_TERM": "ISRN_TERM",
        "MAX_ISRN_TERM": "ISRN_TERM",
        "ISRN_TERM_DVSN_CODE": "ISRN_TERM_DVSN_CODE",
        "MIN_PAYM_TERM": "PAYM_TERM",
        "MAX_PAYM_TERM": "PAYM_TERM",
        "PAYM_TERM_DVSN_CODE": "PAYM_TERM_DVSN_CODE",
        "MINU_GNDR_CODE": "MINU_GNDR_CODE",
        "MIN_AG": "MIN_AG",
        "MAX_AG": "MAX_AG",
    },
    "S00027": {
        "ISRN_TERM_INQY_CODE": "ISRN_TERM_INQY_CODE",
        "PAYM_TERM_INQY_CODE": "PAYM_TERM_INQY_CODE",
        "ISRN_TERM_DVSN_CODE": "ISRN_TERM_DVSN_CODE",
        "ISRN_TERM": "ISRN_TERM",
        "PAYM_TERM_DVSN_CODE": "PAYM_TERM_DVSN_CODE",
        "PAYM_TERM": "PAYM_TERM",
    },
    "S00028": {
        "PAYM_CYCL_INQY_CODE": "PAYM_CYCL_INQY_CODE",
        "PAYM_CYCL_VAL": "PAYM_CYCL_VAL",
        "PAYM_CYCL_DVSN_CODE": "PAYM_CYCL_DVSN_CODE",
    },
    "S00022": {
        "MIN_AG": "MIN_AG",
        "MAX_AG": "MAX_AG",
    },
}

DEFAULT_SALE_CHNL_CODE = "1,2,3,4,7"


def load_product_mapping(mapping_path: str) -> dict:
    """sub_type → (upper, upper_name, lower, lower_name) 매핑 로드.
    첫 번째 항목을 '__default__' 키로도 저장 (sub_type 불일치 fallback용).
    """
    if not os.path.exists(mapping_path):
        return {}
    with open(mapping_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = {}
    for pm in data.get("product_mappings", []):
        entry = {
            "upper": pm["upper_object_code"],
            "upper_name": pm.get("upper_object_name", ""),
            "lower": pm["lower_object_code"],
            "lower_name": pm.get("lower_object_name", ""),
        }
        result[pm["sub_type"]] = entry
        if "__default__" not in result:
            result["__default__"] = entry
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--valid-date", required=True)
    parser.add_argument("--product-mapping", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        coded_data = json.load(f)

    with open(args.valid_date, "r", encoding="utf-8") as f:
        date_data = json.load(f)

    product_mapping = load_product_mapping(args.product_mapping)

    table_type = coded_data.get("table_type", "")
    coded_rows = coded_data.get("coded_rows", [])
    special_rows = coded_data.get("special_contract_rows", [])
    all_rows = coded_rows + special_rows

    valid_start = date_data.get("valid_start_date", "")
    valid_end = date_data.get("valid_end_date", "9999-12-31")

    # 템플릿 복사
    if not os.path.exists(args.template):
        print(f"WARNING: 템플릿 없음: {args.template}. 빈 xlsx 생성.")
        wb = openpyxl.Workbook()
        ws = wb.active
    else:
        shutil.copy2(args.template, args.output)
        wb = openpyxl.load_workbook(args.output)
        ws = wb.active

    # 4행에서 컬럼 헤더 위치 파악 (템플릿 구조: 1~3행=설명, 4행=컬럼명, 5~6행=설명, 7행~=데이터)
    HEADER_ROW = 4
    col_index = {}
    for cell in ws[HEADER_ROW]:
        if cell.value:
            col_index[str(cell.value).strip()] = cell.column

    # 기존 예시 데이터(7행~) 삭제
    DATA_START_ROW = 7
    for row in ws.iter_rows(min_row=DATA_START_ROW, max_row=ws.max_row):
        for cell in row:
            cell.value = None

    for row_idx, coded_row in enumerate(all_rows):
        excel_row = DATA_START_ROW + row_idx

        # sub_type으로 OBJECT_CODE 조회 (불일치 시 __default__ fallback)
        sub_type = coded_row.get("sub_type", "")
        mapping = product_mapping.get(sub_type) or product_mapping.get("__default__", {})

        # _upper/lower_object_code 우선 (특약은 이미 세팅됨)
        upper      = coded_row.get("_upper_object_code") or mapping.get("upper", "")
        upper_name = coded_row.get("_upper_object_name") or mapping.get("upper_name", "")
        lower      = coded_row.get("_lower_object_code") or mapping.get("lower", "")
        lower_name = coded_row.get("_lower_object_name") or mapping.get("lower_name", "")

        # 컬럼별 값 세팅
        def set_cell(col_name, value):
            if col_name in col_index:
                ws.cell(row=excel_row, column=col_index[col_name], value=value)

        set_cell("UPPER_OBJECT_CODE", upper)
        set_cell("UPPER_OBJECT_NAME", upper_name)
        set_cell("LOWER_OBJECT_CODE", lower)
        set_cell("LOWER_OBJECT_NAME", lower_name)
        set_cell("SET_CODE", table_type)
        set_cell("VALID_START_DATE", valid_start)
        set_cell("VALID_END_DATE", valid_end)
        set_cell("SALE_CHNL_CODE", DEFAULT_SALE_CHNL_CODE)

        # 테이블 타입별 컬럼 매핑 적용
        col_map = COLUMN_MAPPINGS.get(table_type, {})
        for xlsx_col, data_key in col_map.items():
            val = coded_row.get(data_key)
            if val is not None:
                set_cell(xlsx_col, val)

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    wb.save(args.output)

    print(f"업로드 양식 생성 완료: {len(all_rows)}행 → {args.output}")
    return 0


if __name__ == "__main__":
    exit(main())
