"""
batch_run.py — data/pdf/ 폴더의 모든 사업방법서 일괄 처리

각 PDF에 대해:
  1. PDF 텍스트/이미지 추출
  2. 관련 페이지 키워드 스캔
  3. 매핑 파일에서 DTCD+ITCD 직접 조회
  4. 4개 테이블(S00026/S00027/S00028/S00022) 추출 → 코드 변환 → xlsx 생성

Usage:
    python scripts/batch_run.py
    python scripts/batch_run.py --limit 5     # 최대 5개만
    python scripts/batch_run.py --no-skip     # 기존 파일 무시하고 재처리
"""

import argparse
import json
import os
import re
import subprocess
import sys
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

# Windows 콘솔 인코딩 문제 해결
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 서브프로세스 UTF-8 환경 변수
_SUBPROC_ENV = dict(os.environ, PYTHONIOENCODING="utf-8")

PYTHON = sys.executable
PDF_DIR = "data/pdf"
EXTRACT_DIR = "output/extracted"
UPLOAD_DIR = "output/upload"
LOG_DIR = "output/logs"
MAPPING_PATH = "data/existing/판매중_상품구성_사업방법서_매핑.xlsx"
MODELS_DIR = "data/models"

TEMPLATES = {
    "S00026": "[S00026]가입가능나이_단일속성_업로드양식.xlsx",
    "S00027": "[S00027] 가입가능보기납기_업로드양식.xlsx",
    "S00028": "[S00028] 가입가능납입주기_업로드양식.xlsx",
    "S00022": "[S00022] 보기개시나이_업로드양식.xlsx",
}
TABLE_TYPES = ["S00026", "S00027", "S00028", "S00022"]


# ─── 매핑 파일 로드 ───────────────────────────────────────────────────────────

def load_mapping_db() -> dict:
    """판매중_상품구성_사업방법서_매핑.xlsx 로드
    반환: {pdf파일명: [{"dtcd": str, "itcd": str, "prod_dtcd": str, "prod_itcd": str, ...}, ...]}
    """
    import pandas as pd
    df = pd.read_excel(MAPPING_PATH)
    result = {}
    for _, row in df.iterrows():
        pdf = str(row.get("사업방법서 파일명", "") or "").strip()
        if not pdf:
            continue
        entry = {
            "dtcd": str(int(row["ISRN_KIND_DTCD"])) if not _is_na(row.get("ISRN_KIND_DTCD")) else "",
            "itcd": str(row.get("ISRN_KIND_ITCD", "") or "").strip(),
            "sale_nm": str(row.get("ISRN_KIND_SALE_NM", "") or "").strip(),
            "prod_dtcd": str(int(row["PROD_DTCD"])) if not _is_na(row.get("PROD_DTCD")) else "",
            "prod_itcd": str(int(row["PROD_ITCD"])) if not _is_na(row.get("PROD_ITCD")) else "",
            "prod_sale_nm": str(row.get("PROD_SALE_NM", "") or "").strip(),
        }
        result.setdefault(pdf, []).append(entry)
    return result


def _is_na(val) -> bool:
    try:
        import math
        return val is None or (isinstance(val, float) and math.isnan(val))
    except Exception:
        return False


# ─── PDF → 매핑 조회 ──────────────────────────────────────────────────────────

def get_pdf_entries(pdf_path: str, mapping_db: dict) -> list:
    """PDF 파일명으로 매핑 항목 조회. 반환: 해당 PDF의 entry 리스트"""
    filename = os.path.basename(pdf_path)
    return mapping_db.get(filename, [])


def get_dtcd_groups(entries: list) -> dict:
    """entries를 DTCD별로 그룹화. 반환: {dtcd: [entry, ...]}"""
    groups = {}
    for e in entries:
        dtcd = e["dtcd"]
        groups.setdefault(dtcd, []).append(e)
    return groups


# ─── PDF 파일명 파싱 ──────────────────────────────────────────────────────────

def get_pdf_base_name(pdf_path: str) -> str:
    """PDF 파일명에서 상품명 추출 (회사명·사업방법서 접미 제거)"""
    name = os.path.basename(pdf_path)
    name = re.sub(r"한화생명\s*", "", name)
    name = re.sub(r"_사업방법서.*", "", name)
    name = re.sub(r"_상품요약서.*", "", name)
    return name.strip()


def get_safe_run_id(pdf_path: str) -> str:
    """파일 시스템 안전한 run_id 생성 (PDF base name 기반)"""
    base = get_pdf_base_name(pdf_path)
    safe = re.sub(r"[^\w가-힣]", "_", base)
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe[:50]


def get_valid_start_date(pdf_path: str) -> str:
    """PDF 파일명에서 시행일 추출 (예: _20260101~.pdf → 20260101)"""
    m = re.search(r"_(\d{8})~", os.path.basename(pdf_path))
    return m.group(1) if m else datetime.now().strftime("%Y%m%d")


# ─── 상품 매핑 JSON 생성 ──────────────────────────────────────────────────────

def build_product_mapping(dtcd: str, entries: list) -> dict:
    """매핑 파일 항목으로 product_mapping.json 생성"""
    mappings = []
    for e in entries:
        mappings.append({
            "sub_type": e["sale_nm"],
            "upper_object_code": f"{e['dtcd']}{e['itcd']}",
            "lower_object_code": f"{e['prod_dtcd']}{e['prod_itcd']}",
        })
    return {"product_mappings": mappings}


# ─── 서브프로세스 실행 ────────────────────────────────────────────────────────

def run_cmd(args_list: list, label: str = "") -> int:
    """서브프로세스 실행, 마지막 stdout 줄 출력"""
    result = subprocess.run(
        args_list, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
        env=_SUBPROC_ENV,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        print(f"  [ERR] {label}: {stderr[:200]}")
    elif result.stdout.strip():
        last_line = result.stdout.strip().splitlines()[-1]
        print(f"  {last_line}")
    return result.returncode


# ─── 단일 PDF 처리 ────────────────────────────────────────────────────────────

def process_pdf(pdf_path: str, mapping_db: dict, run_id: str) -> dict:
    result = {
        "pdf": os.path.basename(pdf_path),
        "run_id": run_id,
        "tables": {},
        "errors": [],
    }

    os.makedirs(EXTRACT_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    pages_json = f"{EXTRACT_DIR}/{run_id}_pages.json"

    # STEP 1: PDF 추출
    if not os.path.exists(pages_json):
        rc = run_cmd([
            PYTHON,
            ".claude/skills/pdf-preprocessor/scripts/extract_pdf.py",
            "--input", pdf_path,
            "--output", EXTRACT_DIR,
            "--run-id", run_id,
            "--text-only",
        ], "PDF extract")
        if rc != 0 or not os.path.exists(pages_json):
            result["errors"].append("PDF extract failed")
            return result
    else:
        print(f"  [CACHED] PDF 페이지 이미 존재")

    # STEP 2: 키워드 스캔
    keywords_json = f"{EXTRACT_DIR}/{run_id}_keywords.json"
    run_cmd([
        PYTHON,
        ".claude/skills/pdf-preprocessor/scripts/scan_keywords.py",
        "--input", pages_json,
        "--output", keywords_json,
    ], "keyword scan")

    # STEP 3: 매핑 파일에서 DTCD+ITCD 직접 조회
    entries = get_pdf_entries(pdf_path, mapping_db)
    if not entries:
        result["errors"].append("매핑 파일에서 PDF를 찾지 못함")
        print(f"  [SKIP] 매핑 파일에 해당 PDF 없음: {os.path.basename(pdf_path)}")
        return result

    dtcd_groups = get_dtcd_groups(entries)
    dtcd_list = sorted(dtcd_groups.keys())
    print(f"  상품코드: {dtcd_list} (ITCD {len(entries)}개)")
    result["dtcd"] = dtcd_list

    # 관련 페이지 텍스트 연결 (모든 DTCD 공통)
    with open(keywords_json, encoding="utf-8") as f:
        keywords_data = json.load(f)
    with open(pages_json, encoding="utf-8") as f:
        pages_data = json.load(f)

    all_relevant = keywords_data.get("all_relevant_pages", [])
    if not all_relevant:
        all_relevant = sorted(int(p) for p in pages_data.get("pages", {}).keys())

    combined_text_path = f"{EXTRACT_DIR}/{run_id}_combined.txt"
    with open(combined_text_path, "w", encoding="utf-8") as outf:
        for page_id in sorted(all_relevant):
            page_info = pages_data.get("pages", {}).get(str(page_id), {})
            txt_path = page_info.get("text_path", "")
            if txt_path and os.path.exists(txt_path):
                with open(txt_path, encoding="utf-8", errors="ignore") as f:
                    outf.write(f"\n--- 페이지 {page_id} ---\n")
                    outf.write(f.read())

    # valid_date.json 생성 (공통)
    valid_start = get_valid_start_date(pdf_path)
    valid_date_json = f"{EXTRACT_DIR}/{run_id}_valid_date.json"
    with open(valid_date_json, "w", encoding="utf-8") as f:
        json.dump({"valid_start_date": valid_start, "valid_end_date": "99991231"}, f)

    # STEP 4: DTCD별 테이블 추출
    for dtcd, grp_entries in dtcd_groups.items():
        # 첫 번째 ITCD를 product_code 접미로 사용 (파일명 식별용)
        first_itcd = grp_entries[0]["itcd"]
        product_code = f"{dtcd}{first_itcd}"

        # product_mapping.json 생성
        mapping_data = build_product_mapping(dtcd, grp_entries)
        mapping_json = f"{EXTRACT_DIR}/{run_id}_{dtcd}_mapping.json"
        with open(mapping_json, "w", encoding="utf-8") as f:
            json.dump(mapping_data, f, ensure_ascii=False, indent=2)

        for table_type in TABLE_TYPES:
            raw_json = f"{EXTRACT_DIR}/{product_code}_{table_type}_{run_id}.json"
            coded_json = f"{EXTRACT_DIR}/{product_code}_{table_type}_{run_id}_coded.json"
            template_file = os.path.join(MODELS_DIR, TEMPLATES[table_type])
            xlsx_out = f"{UPLOAD_DIR}/{table_type}_{dtcd}_{run_id}.xlsx"

            table_key = f"{dtcd}/{table_type}"

            # 추출 (규칙 기반)
            rc = run_cmd([
                PYTHON,
                ".claude/agents/table-extractor/scripts/run_extraction_rules.py",
                "--table-type", table_type,
                "--product-code", product_code,
                "--input", combined_text_path,
                "--rules", "rules/extraction_rules.py",
                "--output", raw_json,
                "--run-id", run_id,
            ], f"{table_key} extract")
            if rc != 0:
                result["tables"][table_key] = "extract_error"
                continue

            with open(raw_json, encoding="utf-8") as f:
                raw_data = json.load(f)
            if not raw_data.get("raw_data"):
                result["tables"][table_key] = "no_data(0행)"
                print(f"  [{table_key}] 추출 데이터 없음 (규칙 미매칭)")
                continue

            # 코드 변환
            rc = run_cmd([
                PYTHON,
                ".claude/skills/code-converter/scripts/convert_codes.py",
                "--input", raw_json,
                "--mappings", ".claude/skills/code-converter/references/code_mappings.json",
                "--output", coded_json,
            ], f"{table_key} convert")
            if rc != 0:
                result["tables"][table_key] = "convert_error"
                continue

            if not os.path.exists(template_file):
                result["tables"][table_key] = "no_template"
                print(f"  [{table_key}] 템플릿 없음: {template_file}")
                continue

            # xlsx 생성
            rc = run_cmd([
                PYTHON,
                ".claude/skills/xlsx-generator/scripts/generate_upload.py",
                "--input", coded_json,
                "--template", template_file,
                "--valid-date", valid_date_json,
                "--product-mapping", mapping_json,
                "--output", xlsx_out,
            ], f"{table_key} xlsx")

            if rc == 0:
                with open(coded_json, encoding="utf-8") as f:
                    coded_data = json.load(f)
                row_count = len(coded_data.get("coded_rows", []))
                result["tables"][table_key] = f"ok({row_count}행)"
            else:
                result["tables"][table_key] = "xlsx_error"

    return result


# ─── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="전체 상품 일괄 처리")
    parser.add_argument("--limit", type=int, default=0, help="처리할 최대 PDF 수 (0=전체)")
    parser.add_argument("--no-skip", action="store_true", help="이미 처리된 파일도 재처리")
    parser.add_argument("--pdf-dir", default=PDF_DIR, help="PDF 폴더 경로")
    args = parser.parse_args()

    print("=" * 60)
    print("전체 상품 일괄 처리 시작")
    print("=" * 60)
    batch_start = datetime.now()

    # 매핑 DB 로드
    print("매핑 파일 로드 중...")
    try:
        mapping_db = load_mapping_db()
        pdf_count = len(mapping_db)
        entry_count = sum(len(v) for v in mapping_db.values())
        print(f"  {pdf_count}개 사업방법서, {entry_count}개 상품 항목 로드 완료\n")
    except Exception as e:
        print(f"ERROR: 매핑 파일 로드 실패: {e}")
        return 1

    # PDF 목록
    pdf_dir = Path(args.pdf_dir)
    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    pdf_files = [p for p in pdf_files if "사업방법서" in p.name]

    if not pdf_files:
        print(f"ERROR: PDF 없음 ({args.pdf_dir})")
        return 1

    if args.limit:
        pdf_files = pdf_files[: args.limit]

    print(f"처리 대상: {len(pdf_files)}개 사업방법서 PDF\n")

    os.makedirs(LOG_DIR, exist_ok=True)
    results = []

    for i, pdf_path in enumerate(pdf_files, 1):
        run_id = get_safe_run_id(str(pdf_path))
        print(f"[{i}/{len(pdf_files)}] {pdf_path.name}")
        print(f"  run_id: {run_id}")

        # 매핑 없으면 스킵
        entries = get_pdf_entries(str(pdf_path), mapping_db)
        if not entries:
            print(f"  [SKIP] 매핑 파일에 없는 PDF\n")
            continue

        # 이미 처리됐는지 확인
        if not args.no_skip:
            existing = list(Path(UPLOAD_DIR).glob(f"S00026_*_{run_id}.xlsx")) if os.path.exists(UPLOAD_DIR) else []
            if existing:
                print(f"  [SKIP] 이미 처리됨 → {existing[0].name}\n")
                continue

        try:
            result = process_pdf(str(pdf_path), mapping_db, run_id)
            results.append(result)

            dtcd = result.get("dtcd", "?")
            errors = result.get("errors", [])
            tables = result.get("tables", {})
            if errors:
                print(f"  [FAIL] {', '.join(errors)}")
            else:
                # DTCD별로 S00026 결과만 요약 출력
                s26 = {k: v for k, v in tables.items() if "S00026" in k}
                summary = " | ".join(f"{k}: {v}" for k, v in s26.items()) if s26 else str(tables)
                print(f"  [OK] {dtcd} → {summary}")
        except Exception as e:
            print(f"  [ERROR] {e}")
            results.append({"pdf": pdf_path.name, "errors": [str(e)]})

        print()

    # 요약
    elapsed = (datetime.now() - batch_start).total_seconds()
    ok = sum(1 for r in results if not r.get("errors") and any("ok" in v for v in r.get("tables", {}).values()))
    skipped = len(pdf_files) - len(results)

    print("=" * 60)
    print(f"처리 완료: {len(results)}개 처리 (성공 {ok}, 실패 {len(results)-ok}, 스킵 {skipped})")
    print(f"소요 시간: {elapsed:.0f}초 ({elapsed/60:.1f}분)")

    # 로그 저장
    batch_ts = batch_start.strftime("%Y%m%d_%H%M%S")
    log_path = f"{LOG_DIR}/batch_{batch_ts}.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "batch_run": batch_ts,
                "total": len(results),
                "success": ok,
                "skipped": skipped,
                "elapsed_sec": round(elapsed),
                "results": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"로그: {log_path}")
    return 0


if __name__ == "__main__":
    exit(main())
