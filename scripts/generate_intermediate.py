"""
generate_intermediate.py — coded JSON → GT 형식 중간 Excel 생성

coded JSON과 매핑 파일을 읽어 GT 파일과 동일한 컬럼 구조
(식별컬럼 + 데이터컬럼)의 중간 Excel 파일을 생성한다.
시스템 컬럼(OBJECT_ID, SET_ATTR_VAL_ID, VALD_STAR_DATE, VALD_END_DATE,
ROW_NO, CREATE_DATE, CREATOR_ID, MODIFIER_ID, UPDATE_DATE, 생성여부)은 제외.

Usage:
    # 전체 처리 (output/extracted/ 스캔)
    python scripts/generate_intermediate.py

    # 특정 DTCD + 테이블
    python scripts/generate_intermediate.py --dtcd 2258 --table S00026

    # 단일 파일
    python scripts/generate_intermediate.py \\
        --input output/extracted/2258A01_S00026_run_coded.json \\
        --mapping output/extracted/run_2258_mapping.json \\
        --output output/extracted/2258_S00026_intermediate.xlsx
"""

import argparse
import glob
import json
import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import openpyxl
    from openpyxl.styles import PatternFill, Font, Alignment
except ImportError:
    print("ERROR: openpyxl 필요. pip install openpyxl")
    sys.exit(1)

_VALIDATOR_SCRIPTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", ".claude", "skills", "validator", "scripts",
)
sys.path.insert(0, _VALIDATOR_SCRIPTS)
from model_key_loader import load_model_key_cols, load_identity_cols  # noqa: E402

EXTRACT_DIR = "output/extracted"

# coded_rows 컬럼 → 중간파일(GT형식) 컬럼 변환
# S00026: ISRN_TERM(단일값) → MIN_ISRN_TERM + MAX_ISRN_TERM (동일값 복제)
EX_COL_RENAMES = {
    "S00026": {
        "ISRN_TERM": ("MIN_ISRN_TERM", "MAX_ISRN_TERM"),
        "PAYM_TERM": ("MIN_PAYM_TERM", "MAX_PAYM_TERM"),
    },
    "S00027": {},
    "S00028": {},
    "S00022": {},
}

_TS_PAT = re.compile(r"_\d{8}_\d{6}_coded\.json$")


# ─── 파일 탐색 ────────────────────────────────────────────────────────────────

def find_coded_file(dtcd: str, table_type: str) -> str | None:
    """dtcd + table_type 기준 coded JSON 파일 탐색 (primary 우선)."""
    candidates = glob.glob(f"{EXTRACT_DIR}/{dtcd}*_{table_type}_*_coded.json")
    named = [f for f in candidates if not _TS_PAT.search(os.path.basename(f))]
    chosen = named or candidates
    return chosen[0] if chosen else None


def find_mapping_file(run_id: str, dtcd: str) -> str | None:
    """run_id + dtcd 기준 mapping JSON 탐색."""
    if run_id:
        path = f"{EXTRACT_DIR}/{run_id}_{dtcd}_mapping.json"
        if os.path.exists(path):
            return path
    # fallback: dtcd만으로 glob
    candidates = glob.glob(f"{EXTRACT_DIR}/*_{dtcd}_mapping.json")
    return candidates[0] if candidates else None


def extract_run_id(coded_path: str, table_type: str) -> str:
    """coded JSON 경로에서 run_id 추출."""
    bn = os.path.basename(coded_path).replace("_coded.json", "")
    parts = bn.split(f"_{table_type}_", 1)
    return parts[1] if len(parts) > 1 else ""


def extract_dtcd(coded_path: str) -> str:
    """coded JSON 경로에서 DTCD(4자리) 추출."""
    bn = os.path.basename(coded_path)
    m = re.match(r"(\d{4})", bn)
    return m.group(1) if m else ""


# ─── 행 변환 ──────────────────────────────────────────────────────────────────

def rename_row_cols(row: dict, table_type: str) -> dict:
    """coded_row 컬럼명을 GT 형식으로 변환 (EX_COL_RENAMES 적용).
    내부 컬럼(_로 시작)과 sub_type은 제거."""
    renames = EX_COL_RENAMES.get(table_type, {})
    result = {}
    for k, v in row.items():
        if k.startswith("_") or k == "sub_type":
            continue
        if k in renames:
            for new_col in renames[k]:
                result[new_col] = v
        else:
            result[k] = v
    return result


def build_intermediate_rows(coded_path: str, mapping_path: str | None,
                             table_type: str) -> list[dict]:
    """coded JSON + mapping → 중간파일 행 리스트 (식별컬럼 + 데이터컬럼)."""
    with open(coded_path, encoding="utf-8") as f:
        data = json.load(f)

    coded_rows = data.get("coded_rows", [])
    regular_rows = [r for r in coded_rows if not r.get("_upper_object_code")]

    # product_mappings 로드
    product_mappings = []
    if mapping_path and os.path.exists(mapping_path):
        with open(mapping_path, encoding="utf-8") as f:
            product_mappings = json.load(f).get("product_mappings", [])

    # mapping entry × 매칭 행 확장
    expanded: list[tuple[dict, dict]] = []
    if not product_mappings:
        for row in regular_rows:
            expanded.append((row, {}))
    else:
        for pm in product_mappings:
            sub_type_key = pm.get("sub_type", "")
            matched = [r for r in regular_rows
                       if not r.get("sub_type") or r.get("sub_type") in sub_type_key]
            if not matched:
                matched = regular_rows   # fallback
            for row in matched:
                expanded.append((row, pm))

    # 식별컬럼 추가 + 컬럼명 변환 + dedup
    data_cols = load_model_key_cols(table_type)
    seen: set = set()
    result: list[dict] = []

    for row, pm in expanded:
        upper = pm.get("upper_object_code", "")
        lower = pm.get("lower_object_code", "")

        identity: dict = {}
        if upper and len(upper) > 4:
            identity["ISRN_KIND_DTCD"] = upper[:4]
            identity["ISRN_KIND_ITCD"] = upper[4:]
        if lower and len(lower) > 4:
            identity["PROD_DTCD"] = lower[:4]
            identity["PROD_ITCD"] = lower[4:]  # 이미 3자리 zero-pad (mapping에서)

        renamed = rename_row_cols(row, table_type)
        combined = {**identity, **renamed}

        dedup_key = (
            identity.get("ISRN_KIND_DTCD"), identity.get("ISRN_KIND_ITCD"),
            identity.get("PROD_DTCD"), identity.get("PROD_ITCD"),
            tuple(combined.get(c) for c in data_cols),
        )
        if dedup_key not in seen:
            seen.add(dedup_key)
            result.append(combined)

    return result


# ─── Excel 출력 ───────────────────────────────────────────────────────────────

def write_intermediate_excel(rows: list[dict], table_type: str, output_path: str):
    """중간파일 Excel 저장. 컬럼순서: 식별4개 + 모델상세 데이터컬럼."""
    identity_cols = load_identity_cols(table_type)
    data_cols = load_model_key_cols(table_type)
    all_cols = identity_cols + data_cols

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = table_type

    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=10)

    for col_idx, col_name in enumerate(all_cols, 1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for row_idx, row in enumerate(rows, 2):
        for col_idx, col_name in enumerate(all_cols, 1):
            ws.cell(row=row_idx, column=col_idx, value=row.get(col_name))

    ws.freeze_panes = "A2"

    # 컬럼 너비
    id_cols_set = set(identity_cols)
    for col_idx, col_name in enumerate(all_cols, 1):
        from openpyxl.utils import get_column_letter
        ws.column_dimensions[get_column_letter(col_idx)].width = (
            18 if col_name in id_cols_set else 14
        )

    os.makedirs(
        os.path.dirname(output_path) if os.path.dirname(output_path) else ".",
        exist_ok=True,
    )
    wb.save(output_path)


# ─── 메인 ─────────────────────────────────────────────────────────────────────

TABLE_TYPES = ["S00026", "S00027", "S00028", "S00022"]


def _process_one(coded_path: str, mapping_path: str | None,
                 table_type: str, output_path: str) -> int:
    rows = build_intermediate_rows(coded_path, mapping_path, table_type)
    write_intermediate_excel(rows, table_type, output_path)
    print(f"  중간파일 생성: {len(rows)}행 → {output_path}")
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="coded JSON → GT형식 중간 Excel")
    parser.add_argument("--input", help="coded JSON 파일 경로")
    parser.add_argument("--mapping", help="product mapping JSON 경로")
    parser.add_argument("--dtcd", help="DTCD (자동 파일 탐색용)")
    parser.add_argument("--table", help="테이블 타입 (S00026 등)")
    parser.add_argument("--output", help="출력 xlsx 경로")
    args = parser.parse_args()

    if args.input:
        # 단일 파일 모드
        coded_path = args.input
        table_type = args.table
        if not table_type:
            m = re.search(r"_(S00\d{3})_", os.path.basename(coded_path))
            table_type = m.group(1) if m else "S00026"

        dtcd = args.dtcd or extract_dtcd(coded_path)
        run_id = extract_run_id(coded_path, table_type)
        mapping_path = args.mapping or find_mapping_file(run_id, dtcd)
        output_path = args.output or f"{EXTRACT_DIR}/{dtcd}_{table_type}_intermediate.xlsx"

        _process_one(coded_path, mapping_path, table_type, output_path)

    elif args.dtcd:
        # DTCD 지정 모드 (--table 있으면 1개, 없으면 4개 테이블)
        dtcd = args.dtcd
        tables = [args.table] if args.table else TABLE_TYPES
        for tt in tables:
            coded_path = find_coded_file(dtcd, tt)
            if not coded_path:
                print(f"  [SKIP] {dtcd} {tt}: coded JSON 없음")
                continue
            run_id = extract_run_id(coded_path, tt)
            mapping_path = find_mapping_file(run_id, dtcd)
            output_path = f"{EXTRACT_DIR}/{dtcd}_{tt}_intermediate.xlsx"
            _process_one(coded_path, mapping_path, tt, output_path)

    else:
        # 전체 처리 모드: output/extracted/ 스캔
        # 같은 DTCD가 여러 PDF에 분산된 경우 모든 coded files를 누적
        all_coded = sorted(glob.glob(f"{EXTRACT_DIR}/*_S00*_*_coded.json"))
        all_coded = [f for f in all_coded if not _TS_PAT.search(os.path.basename(f))]

        # (dtcd, table_type) → [(coded_path, mapping_path), ...] 그룹화
        groups: dict = {}
        for coded_path in all_coded:
            m = re.match(r"(\d{4})\w+_(S00\d{3})_", os.path.basename(coded_path))
            if not m:
                continue
            dtcd, table_type = m.group(1), m.group(2)
            run_id = extract_run_id(coded_path, table_type)
            mapping_path = find_mapping_file(run_id, dtcd)
            groups.setdefault((dtcd, table_type), []).append((coded_path, mapping_path))

        for (dtcd, table_type), file_pairs in sorted(groups.items()):
            # 여러 coded files → 모든 행 누적 후 dedup
            all_rows: list[dict] = []
            for coded_path, mapping_path in file_pairs:
                all_rows.extend(build_intermediate_rows(coded_path, mapping_path, table_type))

            # 전체 dedup
            data_cols = load_model_key_cols(table_type)
            seen: set = set()
            deduped: list[dict] = []
            for r in all_rows:
                key = (
                    r.get("ISRN_KIND_DTCD"), r.get("ISRN_KIND_ITCD"),
                    r.get("PROD_DTCD"), r.get("PROD_ITCD"),
                    tuple(r.get(c) for c in data_cols),
                )
                if key not in seen:
                    seen.add(key)
                    deduped.append(r)

            output_path = f"{EXTRACT_DIR}/{dtcd}_{table_type}_intermediate.xlsx"
            write_intermediate_excel(deduped, table_type, output_path)
            print(f"  중간파일 생성: {len(deduped)}행 → {output_path}")

        print(f"\n총 {len(groups)}개 (DTCD×테이블) 중간파일 생성 완료")

    return 0


if __name__ == "__main__":
    sys.exit(main())
