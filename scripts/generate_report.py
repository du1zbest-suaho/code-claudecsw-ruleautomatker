"""
generate_report.py — 추출 결과 vs GT DB 비교 리포트 생성

판매중_상품구성_사업방법서_매핑.xlsx 형식을 기반으로
각 PDF × 테이블별 추출건수 / GT건수 / 일치건수 / 미일치건수 / 전체일치여부를
엑셀 파일로 출력한다.

Usage:
    python scripts/generate_report.py
    python scripts/generate_report.py --output output/reports/작업현황.xlsx
"""

import argparse
import glob
import json
import os
import sys
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

MAPPING_PATH = "data/existing/판매중_상품구성_사업방법서_매핑.xlsx"
EXTRACT_DIR = "output/extracted"

GT_FILES = {
    "S00026": "data/existing/판매중_가입나이정보.xlsx",
    "S00027": "data/existing/판매중_보기납기정보.xlsx",
    "S00028": "data/existing/판매중_납입주기정보.xlsx",
    "S00022": "data/existing/판매중_보기개시나이정보.xlsx",
}

TABLE_LABELS = {
    "S00026": "가입가능나이",
    "S00027": "보기납기",
    "S00028": "납입주기",
    "S00022": "보기개시나이",
}


# ─── GT 로드 ──────────────────────────────────────────────────────────────────

_gt_cache: dict = {}

def load_gt(table_type: str) -> pd.DataFrame:
    if table_type not in _gt_cache:
        path = GT_FILES.get(table_type)
        if path and os.path.exists(path):
            _gt_cache[table_type] = pd.read_excel(path)
        else:
            _gt_cache[table_type] = pd.DataFrame()
    return _gt_cache[table_type]


def get_gt_row_count(dtcd: int, table_type: str) -> int:
    """DTCD에 해당하는 GT 행 수 (MAX_AG=999 umbrella 제외, S00026만)"""
    df = load_gt(table_type)
    if df.empty or "ISRN_KIND_DTCD" not in df.columns:
        return 0
    gf = df[df["ISRN_KIND_DTCD"] == dtcd]
    if table_type == "S00026" and "MAX_AG" in df.columns:
        gf = gf[gf["MAX_AG"] != 999]
    return len(gf)


# ─── S00026 고유키 비교 ───────────────────────────────────────────────────────

def _gt_keys_s26(dtcd: int) -> set:
    df = load_gt("S00026")
    if df.empty:
        return set()
    gf = df[(df["ISRN_KIND_DTCD"] == dtcd) & (df["MAX_AG"] != 999)]
    keys = set()
    for _, row in gf.iterrows():
        ip = (str(row["ISRN_TERM_DVSN_CODE"]) + str(int(row["MIN_ISRN_TERM"]))
              if pd.notna(row.get("ISRN_TERM_DVSN_CODE")) and pd.notna(row.get("MIN_ISRN_TERM")) else "")
        pp = (str(row["PAYM_TERM_DVSN_CODE"]) + str(int(row["MIN_PAYM_TERM"]))
              if pd.notna(row.get("PAYM_TERM_DVSN_CODE")) and pd.notna(row.get("MIN_PAYM_TERM")) else "")
        g = str(int(float(row["MINU_GNDR_CODE"]))) if pd.notna(row.get("MINU_GNDR_CODE")) else ""
        keys.add((ip, pp, g, int(row["MIN_AG"]), int(row["MAX_AG"])))
    return keys


def _ex_keys_s26(coded_files: list) -> set:
    keys = set()
    for fname in coded_files:
        with open(fname, encoding="utf-8") as f:
            coded = json.load(f)
        for r in coded.get("coded_rows", []):
            ip = r.get("ISRN_TERM_INQY_CODE") or ""
            pp = r.get("PAYM_TERM_INQY_CODE") or ""
            g_val = r.get("MINU_GNDR_CODE")
            g = "" if g_val is None else str(g_val)
            min_a = r.get("MIN_AG")
            max_a = r.get("MAX_AG")
            keys.add((ip, pp, g,
                      int(min_a) if min_a is not None else 0,
                      int(max_a) if max_a is not None else 0))
    return keys


# ─── 추출 파일 검색 ───────────────────────────────────────────────────────────

def find_coded_files(dtcd: int, first_itcd: str, run_id: str, table_type: str) -> list:
    """dtcd + itcd 조합으로 coded json 파일 검색 (run_id 기반)"""
    product_code = f"{dtcd}{first_itcd}"
    pattern = f"{EXTRACT_DIR}/{product_code}_{table_type}_{run_id}_coded.json"
    files = glob.glob(pattern)
    if not files:
        # fallback: run_id 없이 dtcd 기반 검색
        pattern2 = f"{EXTRACT_DIR}/{dtcd}*_{table_type}_*_coded.json"
        files = glob.glob(pattern2)
    return files


def get_ex_row_count(coded_files: list) -> int:
    total = 0
    for fname in coded_files:
        with open(fname, encoding="utf-8") as f:
            coded = json.load(f)
        total += len(coded.get("coded_rows", []))
    return total


# ─── 메인 리포트 생성 ─────────────────────────────────────────────────────────

def build_report() -> pd.DataFrame:
    mapping_df = pd.read_excel(MAPPING_PATH)

    # PDF별 첫번째 ITCD (run_id 구성용)
    pdf_first_itcd: dict = {}
    for _, row in mapping_df.iterrows():
        pdf = str(row.get("사업방법서 파일명", "") or "").strip()
        if pdf not in pdf_first_itcd:
            pdf_first_itcd[pdf] = str(row.get("ISRN_KIND_ITCD", "") or "").strip()

    # run_id = PDF 파일명 기반 (batch_run.py와 동일 로직)
    import re

    def get_run_id(pdf: str) -> str:
        name = re.sub(r"한화생명\s*", "", pdf)
        name = re.sub(r"_사업방법서.*", "", name)
        name = re.sub(r"_상품요약서.*", "", name)
        name = name.strip()
        safe = re.sub(r"[^\w가-힣]", "_", name)
        safe = re.sub(r"_+", "_", safe).strip("_")
        return safe[:50]

    # DTCD별 집계 (unique, 하나의 DTCD가 여러 PDF에 걸쳐있을 수 있음)
    dtcd_pdf_map: dict = {}  # dtcd → {pdf: [entries]}
    for _, row in mapping_df.iterrows():
        pdf = str(row.get("사업방법서 파일명", "") or "").strip()
        dtcd = int(row["ISRN_KIND_DTCD"]) if pd.notna(row.get("ISRN_KIND_DTCD")) else None
        if not dtcd or not pdf:
            continue
        itcd = str(row.get("ISRN_KIND_ITCD", "") or "").strip()
        sale_nm = str(row.get("ISRN_KIND_SALE_NM", "") or "").strip()
        dtcd_pdf_map.setdefault(dtcd, {}).setdefault(pdf, []).append({
            "itcd": itcd, "sale_nm": sale_nm
        })

    rows = []
    for dtcd in sorted(dtcd_pdf_map.keys()):
        pdf_map = dtcd_pdf_map[dtcd]
        pdfs = sorted(pdf_map.keys())

        for pdf in pdfs:
            entries = pdf_map[pdf]
            first_itcd = entries[0]["itcd"]
            sale_nm = entries[0]["sale_nm"]
            run_id = get_run_id(pdf)
            itcd_list = ", ".join(e["itcd"] for e in entries)

            row_data = {
                "사업방법서 파일명": pdf,
                "ISRN_KIND_DTCD": dtcd,
                "ISRN_KIND_ITCD_목록": itcd_list,
                "보험종목명": sale_nm,
            }

            for table_type in ["S00026", "S00027", "S00028", "S00022"]:
                coded_files = find_coded_files(dtcd, first_itcd, run_id, table_type)

                gt_cnt = get_gt_row_count(dtcd, table_type)
                ex_cnt = get_ex_row_count(coded_files) if coded_files else 0

                if table_type == "S00026":
                    gt_keys = _gt_keys_s26(dtcd)
                    ex_keys = _ex_keys_s26(coded_files) if coded_files else set()
                    match_cnt = len(gt_keys & ex_keys)
                    miss_cnt = len(gt_keys - ex_keys)
                    extra_cnt = len(ex_keys - gt_keys)
                    if gt_keys:
                        pass_fail = "PASS" if miss_cnt == 0 else "FAIL"
                    else:
                        pass_fail = "-" if ex_cnt == 0 else "신규"
                else:
                    # S00027/S00028/S00022: 행 수 비교
                    match_cnt = min(gt_cnt, ex_cnt)
                    miss_cnt = max(0, gt_cnt - ex_cnt)
                    extra_cnt = max(0, ex_cnt - gt_cnt)
                    if gt_cnt == 0 and ex_cnt == 0:
                        pass_fail = "-"
                    elif gt_cnt == 0:
                        pass_fail = "신규"
                    elif ex_cnt == 0:
                        pass_fail = "미추출"
                    elif miss_cnt == 0:
                        pass_fail = "일치"
                    else:
                        pass_fail = "불일치"

                lbl = TABLE_LABELS[table_type]
                row_data[f"{lbl}_추출건수"] = ex_cnt
                row_data[f"{lbl}_GT건수"] = gt_cnt
                row_data[f"{lbl}_일치건수"] = match_cnt
                row_data[f"{lbl}_미일치건수"] = miss_cnt
                row_data[f"{lbl}_추가건수"] = extra_cnt
                row_data[f"{lbl}_결과"] = pass_fail

            rows.append(row_data)

    return pd.DataFrame(rows)


def save_report(df: pd.DataFrame, output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="작업현황")

        ws = writer.sheets["작업현황"]

        # 컬럼 너비 자동 조정
        from openpyxl.utils import get_column_letter
        from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

        col_widths = {
            "사업방법서 파일명": 45,
            "ISRN_KIND_DTCD": 14,
            "ISRN_KIND_ITCD_목록": 20,
            "보험종목명": 50,
        }
        default_w = 12

        for col_idx, col_name in enumerate(df.columns, 1):
            col_letter = get_column_letter(col_idx)
            width = col_widths.get(col_name, default_w)
            ws.column_dimensions[col_letter].width = width

        # 헤더 스타일
        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True, size=10)
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[1].height = 36

        # 결과 컬럼 색상 매핑
        color_map = {
            "PASS": "C6EFCE",   # 연두
            "FAIL": "FFC7CE",   # 연빨강
            "일치": "C6EFCE",
            "불일치": "FFC7CE",
            "미추출": "FFEB9C",  # 노랑
            "신규": "BDD7EE",   # 연파랑
            "-": "F2F2F2",      # 회색
        }
        result_cols = [i + 1 for i, c in enumerate(df.columns) if c.endswith("_결과")]

        thin = Side(style="thin", color="CCCCCC")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        for row_idx in range(2, len(df) + 2):
            for col_idx in range(1, len(df.columns) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.border = border

                if col_idx in result_cols:
                    val = str(cell.value or "")
                    color = color_map.get(val, "FFFFFF")
                    cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
                    cell.font = Font(bold=True, size=10)

        # 행 번갈아 배경
        alt_fill = PatternFill(start_color="F5F5F5", end_color="F5F5F5", fill_type="solid")
        for row_idx in range(2, len(df) + 2):
            if row_idx % 2 == 0:
                for col_idx in range(1, len(df.columns) + 1):
                    if col_idx not in result_cols:
                        cell = ws.cell(row=row_idx, column=col_idx)
                        if cell.fill.patternType is None or cell.fill.fgColor.rgb == "00000000":
                            cell.fill = alt_fill

        # 틀 고정 (헤더)
        ws.freeze_panes = "A2"

    print(f"리포트 저장 완료: {output_path} ({len(df)}행)")


def main():
    parser = argparse.ArgumentParser(description="추출 결과 vs GT 비교 리포트 생성")
    parser.add_argument(
        "--output",
        default=f"output/reports/작업현황_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        help="출력 파일 경로"
    )
    args = parser.parse_args()

    print("리포트 생성 중...")
    df = build_report()
    save_report(df, args.output)

    # 요약 출력
    for table_type in ["S00026", "S00027", "S00028", "S00022"]:
        lbl = TABLE_LABELS[table_type]
        col = f"{lbl}_결과"
        if col in df.columns:
            counts = df[col].value_counts()
            print(f"  [{table_type}] {dict(counts)}")

    return 0


if __name__ == "__main__":
    exit(main())
