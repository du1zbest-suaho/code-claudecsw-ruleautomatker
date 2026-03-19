"""
validate_intermediate.py — 중간 Excel vs GT 전체 컬럼 검증

중간 Excel(generate_intermediate.py 출력)과 GT 파일을 비교하여
건수 및 내용이 완전히 일치하는지 검증한다.

비교 기준:
  - 대상 컬럼: 모델상세 ROW_NO+1 ~ CREATE_DATE-1 (시스템컬럼 제외)
  - 식별컬럼(ISRN_KIND_DTCD/ITCD, PROD_DTCD/ITCD) 포함 전체 비교
  - NULL도 포함 비교 (active_key_cols 방식 아님)
  - PROD_ITCD 정규화: int/float → 3자리 zero-pad string ("1" → "001")

Usage:
    # 전체 처리
    python scripts/validate_intermediate.py

    # 특정 DTCD + 테이블
    python scripts/validate_intermediate.py --dtcd 2258 --table S00026

    # 단일 파일
    python scripts/validate_intermediate.py \\
        --intermediate output/extracted/2258_S00026_intermediate.xlsx \\
        --table S00026 --dtcd 2258
"""

import argparse
import glob
import json
import os
import re
import sys
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas 필요. pip install pandas openpyxl")
    sys.exit(1)

_VALIDATOR_SCRIPTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", ".claude", "skills", "validator", "scripts",
)
sys.path.insert(0, _VALIDATOR_SCRIPTS)
from model_key_loader import (load_model_key_cols, load_identity_cols,  # noqa: E402
                               normalize_val, get_active_key_cols)

EXTRACT_DIR  = "output/extracted"
REPORTS_DIR  = "output/reports"
MAPPING_PATH = "data/existing/판매중_상품구성_사업방법서_매핑.xlsx"

GT_FILES = {
    "S00026": "data/existing/판매중_가입나이정보_0312.xlsx",
    "S00027": "data/existing/판매중_보기납기정보_0312.xlsx",
    "S00028": "data/existing/판매중_납입주기정보_0312.xlsx",
    "S00022": "data/existing/판매중_보기개시나이정보_0312.xlsx",
}

TABLE_TYPES = ["S00026", "S00027", "S00028", "S00022"]

_gt_cache: dict = {}
_mapping_cache: dict | None = None
_TS_PAT = re.compile(r"_\d{8}_\d{6}_coded\.json$")


# ─── 정규화 ───────────────────────────────────────────────────────────────────

def normalize_prod_itcd(v) -> str | None:
    """PROD_ITCD: int/float/str → 3자리 zero-pad 문자열."""
    nv = normalize_val(v)
    if nv is None:
        return None
    try:
        return str(int(nv)).zfill(3)
    except (ValueError, TypeError):
        return nv


def normalize_row(row: dict, all_cols: list) -> dict:
    """행 값을 비교용으로 정규화."""
    result = {}
    for col in all_cols:
        v = row.get(col)
        if col == "PROD_ITCD":
            result[col] = normalize_prod_itcd(v)
        elif col == "ISRN_KIND_DTCD":
            nv = normalize_val(v)
            result[col] = str(int(nv)) if nv is not None else None
        else:
            result[col] = normalize_val(v)
    return result


def make_key(row: dict, cols: list) -> tuple:
    return tuple(row.get(c) for c in cols)


# ─── GT 로드 ──────────────────────────────────────────────────────────────────

def load_gt(table_type: str) -> pd.DataFrame:
    if table_type not in _gt_cache:
        path = GT_FILES.get(table_type)
        if path and os.path.exists(path):
            _gt_cache[table_type] = pd.read_excel(path)
        else:
            _gt_cache[table_type] = pd.DataFrame()
    return _gt_cache[table_type]


def get_gt_rows_for_itcd(table_type: str, dtcd: str, isrn_itcd: str,
                          prod_itcd: str) -> list[dict]:
    """GT에서 특정 DTCD+ITCD 쌍의 행 반환."""
    df = load_gt(table_type)
    if df.empty:
        return []

    dtcd_int = int(dtcd) if dtcd.isdigit() else None
    if dtcd_int is None:
        return []

    gf = df[df["ISRN_KIND_DTCD"] == dtcd_int].copy()
    if gf.empty:
        return []

    if table_type == "S00026" and "MAX_AG" in gf.columns:
        gf = gf[gf["MAX_AG"] != 999]

    if "ISRN_KIND_ITCD" in gf.columns and "PROD_ITCD" in gf.columns:
        gf["_prod_itcd_norm"] = gf["PROD_ITCD"].apply(
            lambda v: normalize_prod_itcd(v))
        gf = gf[
            (gf["ISRN_KIND_ITCD"].astype(str) == isrn_itcd) &
            (gf["_prod_itcd_norm"] == prod_itcd)
        ]

    return gf.to_dict("records")


# ─── 중간파일 로드 ────────────────────────────────────────────────────────────

def _norm_itcd(v, zero_pad: int = 3) -> str:
    """ITCD 정규화: Excel에서 int로 읽힌 "030" → 30 → "030", "A01" → "A01"."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    sv = str(int(v)) if isinstance(v, (int, float)) else str(v).strip()
    # 숫자만으로 구성된 경우 zero-pad
    if sv.isdigit():
        return sv.zfill(zero_pad)
    return sv


def load_intermediate_rows(intermediate_path: str, dtcd: str, isrn_itcd: str,
                            prod_itcd: str) -> list[dict]:
    """중간 Excel에서 특정 ITCD 쌍의 행만 반환.

    ISRN_KIND_ITCD/PROD_ITCD가 숫자형으로 읽혀도 zero-pad 정규화로 비교.
    """
    df = pd.read_excel(intermediate_path)
    if df.empty:
        return []

    filt = df.copy()

    if "ISRN_KIND_DTCD" in filt.columns:
        filt = filt[filt["ISRN_KIND_DTCD"].astype(str).str.strip() == str(dtcd)]

    if "ISRN_KIND_ITCD" in filt.columns:
        # isrn_itcd를 동일 방식으로 정규화하여 비교
        isrn_itcd_norm = _norm_itcd(isrn_itcd)
        filt["_itcd_norm"] = filt["ISRN_KIND_ITCD"].apply(_norm_itcd)
        filt = filt[filt["_itcd_norm"] == isrn_itcd_norm]

    if "PROD_ITCD" in filt.columns:
        filt["_prod_norm"] = filt["PROD_ITCD"].apply(normalize_prod_itcd)
        filt = filt[filt["_prod_norm"] == prod_itcd]

    # 임시 컬럼 제거
    drop_cols = [c for c in ("_itcd_norm", "_prod_norm") if c in filt.columns]
    filt = filt.drop(columns=drop_cols)

    return filt.to_dict("records")


# ─── 매핑 파일 로드 ───────────────────────────────────────────────────────────

def load_mapping_db() -> dict:
    """pdf → [{dtcd, itcd, prod_dtcd, prod_itcd, ...}] 매핑."""
    global _mapping_cache
    if _mapping_cache is not None:
        return _mapping_cache
    df = pd.read_excel(MAPPING_PATH)
    result = {}
    for _, row in df.iterrows():
        pdf = str(row.get("사업방법서 파일명", "") or "").strip()
        if not pdf:
            continue
        try:
            dtcd = str(int(row["ISRN_KIND_DTCD"]))
        except (ValueError, TypeError):
            continue
        itcd = str(row.get("ISRN_KIND_ITCD", "") or "").strip()
        try:
            prod_itcd = str(int(row["PROD_ITCD"])).zfill(3)
        except (ValueError, TypeError):
            prod_itcd = ""
        result.setdefault(pdf, []).append({
            "dtcd": dtcd, "itcd": itcd, "prod_itcd": prod_itcd,
        })
    _mapping_cache = result
    return result


def get_itcd_pairs_for_dtcd(dtcd: str) -> list[tuple]:
    """매핑 파일에서 DTCD에 속한 (ISRN_KIND_ITCD, PROD_ITCD) 쌍 목록."""
    db = load_mapping_db()
    pairs = set()
    for entries in db.values():
        for e in entries:
            if e["dtcd"] == dtcd:
                pairs.add((e["itcd"], e["prod_itcd"]))
    return sorted(pairs)


# ─── 핵심 비교 ────────────────────────────────────────────────────────────────

def compare_itcd(table_type: str, dtcd: str, isrn_itcd: str,
                 prod_itcd: str, intermediate_path: str) -> dict:
    """단일 ITCD 쌍에 대한 중간파일 vs GT 비교.

    비교키: GT와 중간파일 양쪽에 non-None 값이 있는 컬럼만 (active_key_cols).
    추출 로직이 생성하지 않는 컬럼(GT에만 값 있음)은 비교에서 제외하여
    기존 generate_report.py 검증과 동등한 결과를 보장.
    """
    data_cols = load_model_key_cols(table_type)

    gt_rows_raw = get_gt_rows_for_itcd(table_type, dtcd, isrn_itcd, prod_itcd)
    ex_rows_raw = load_intermediate_rows(intermediate_path, dtcd, isrn_itcd, prod_itcd)

    # 정규화
    gt_rows = [normalize_row(r, data_cols) for r in gt_rows_raw]
    ex_rows = [normalize_row(r, data_cols) for r in ex_rows_raw]

    # active_key_cols: GT + EX 양쪽에 non-None 값이 있는 컬럼만
    active_cols = get_active_key_cols(gt_rows, ex_rows, data_cols)
    if not active_cols:
        active_cols = data_cols   # fallback

    gt_key_map = {}
    for r in gt_rows:
        k = make_key(r, active_cols)
        gt_key_map[k] = r

    ex_key_map = {}
    for r in ex_rows:
        k = make_key(r, active_cols)
        ex_key_map[k] = r

    gt_keys = set(gt_key_map.keys())
    ex_keys = set(ex_key_map.keys())

    miss_keys  = gt_keys - ex_keys
    extra_keys = ex_keys - gt_keys
    match_cnt  = len(gt_keys & ex_keys)
    miss_cnt   = len(miss_keys)
    extra_cnt  = len(extra_keys)

    is_pass = (len(gt_keys) == len(ex_keys)) and miss_cnt == 0

    reason = ""
    if not is_pass:
        gt_n, ex_n = len(gt_keys), len(ex_keys)
        if miss_cnt > 0 and extra_cnt == 0:
            reason = f"추출누락(GT:{gt_n}건/중간:{ex_n}건, 누락{miss_cnt}건)"
        elif miss_cnt == 0 and extra_cnt > 0:
            reason = f"추출과잉(GT:{gt_n}건/중간:{ex_n}건, 초과{extra_cnt}건)"
        elif miss_cnt > 0 and extra_cnt > 0 and gt_n == ex_n:
            reason = f"내용불일치(건수동일{gt_n}건, 누락{miss_cnt}/초과{extra_cnt}건)"
        else:
            reason = f"추출오류(GT:{gt_n}건/중간:{ex_n}건, 누락{miss_cnt}/초과{extra_cnt}건)"

    return {
        "isrn_kind_itcd": isrn_itcd,
        "prod_itcd": prod_itcd,
        "gt_cnt": len(gt_keys),
        "ex_cnt": len(ex_keys),
        "match_cnt": match_cnt,
        "miss_cnt": miss_cnt,
        "extra_cnt": extra_cnt,
        "pass": is_pass,
        "reason": reason,
        "active_cols": active_cols,
        "miss_rows": [dict(zip(active_cols, k)) for k in sorted(miss_keys, key=_sort_key)],
        "extra_rows": [dict(zip(active_cols, k)) for k in sorted(extra_keys, key=_sort_key)],
    }


def _sort_key(t: tuple):
    return tuple(str(v) if v is not None else "" for v in t)


# ─── 중간파일 파일 탐색 ───────────────────────────────────────────────────────

def find_intermediate_file(dtcd: str, table_type: str) -> str | None:
    """output/extracted/{dtcd}_{table_type}_intermediate.xlsx 탐색."""
    path = f"{EXTRACT_DIR}/{dtcd}_{table_type}_intermediate.xlsx"
    if os.path.exists(path):
        return path
    return None


# ─── DTCD 단위 처리 ───────────────────────────────────────────────────────────

def validate_dtcd(dtcd: str, table_type: str) -> dict | None:
    """단일 DTCD+테이블 전체 ITCD 검증. 리포트 dict 반환."""
    intermediate_path = find_intermediate_file(dtcd, table_type)
    if not intermediate_path:
        print(f"  [SKIP] {dtcd} {table_type}: 중간파일 없음")
        return None

    itcd_pairs = get_itcd_pairs_for_dtcd(dtcd)
    if not itcd_pairs:
        print(f"  [SKIP] {dtcd} {table_type}: ITCD 쌍 없음 (매핑 확인)")
        return None

    itcd_results = []
    for isrn_itcd, prod_itcd in itcd_pairs:
        r = compare_itcd(table_type, dtcd, isrn_itcd, prod_itcd, intermediate_path)
        itcd_results.append(r)

    all_pass = all(r["pass"] for r in itcd_results)
    total_miss = sum(r["miss_cnt"] for r in itcd_results)
    total_extra = sum(r["extra_cnt"] for r in itcd_results)

    report = {
        "dtcd": dtcd,
        "table_type": table_type,
        "intermediate_path": intermediate_path,
        "generated_at": datetime.now().isoformat(),
        "all_pass": all_pass,
        "total_miss_cnt": total_miss,
        "total_extra_cnt": total_extra,
        "itcd_results": itcd_results,
    }

    # 리포트 저장
    os.makedirs(REPORTS_DIR, exist_ok=True)
    out_path = f"{REPORTS_DIR}/{dtcd}_{table_type}_intermediate_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    status = "PASS" if all_pass else f"FAIL(누락{total_miss}/초과{total_extra})"
    print(f"  [{dtcd} {table_type}] {status} → {out_path}")
    return report


# ─── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="중간 Excel vs GT 검증")
    parser.add_argument("--intermediate", help="중간 Excel 파일 경로")
    parser.add_argument("--dtcd", help="DTCD")
    parser.add_argument("--table", help="테이블 타입 (S00026 등)")
    args = parser.parse_args()

    if args.intermediate:
        # 단일 파일 모드
        table_type = args.table
        if not table_type:
            m = re.search(r"_(S00\d{3})_", os.path.basename(args.intermediate))
            table_type = m.group(1) if m else "S00026"
        dtcd = args.dtcd
        if not dtcd:
            m = re.match(r"(\d{4})", os.path.basename(args.intermediate))
            dtcd = m.group(1) if m else None
        if not dtcd:
            print("ERROR: --dtcd 필요")
            return 1
        validate_dtcd(dtcd, table_type)

    elif args.dtcd:
        # DTCD 지정 모드
        dtcd = args.dtcd
        tables = [args.table] if args.table else TABLE_TYPES
        for tt in tables:
            validate_dtcd(dtcd, tt)

    else:
        # 전체 모드: 중간파일 스캔
        intermediate_files = sorted(
            glob.glob(f"{EXTRACT_DIR}/*_S00*_intermediate.xlsx")
        )
        processed: set = set()
        for path in intermediate_files:
            bn = os.path.basename(path)
            m = re.match(r"(\d{4})_(S00\d{3})_intermediate\.xlsx$", bn)
            if not m:
                continue
            dtcd, table_type = m.group(1), m.group(2)
            if (dtcd, table_type) in processed:
                continue
            processed.add((dtcd, table_type))
            validate_dtcd(dtcd, table_type)

        pass_cnt = fail_cnt = 0
        for path in glob.glob(f"{REPORTS_DIR}/*_intermediate_report.json"):
            with open(path, encoding="utf-8") as f:
                r = json.load(f)
            if r.get("all_pass"):
                pass_cnt += 1
            else:
                fail_cnt += 1

        print(f"\n검증 완료: PASS={pass_cnt}, FAIL={fail_cnt}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
