"""
batch_run.py — data/pdf/ 폴더의 모든 사업방법서 일괄 처리

각 PDF에 대해:
  1. PDF 텍스트/이미지 추출
  2. 관련 페이지 키워드 스캔
  3. 상품명/세부종목 파싱
  4. DB에서 상품코드(ISRN_KIND_DTCD) 검색
  5. 4개 테이블(S00026/S00027/S00028/S00022) 추출 → 코드 변환 → xlsx 생성

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
DB_PATH = "data/existing/판매중_상품구성정보.xlsx"
MODELS_DIR = "data/models"

TEMPLATES = {
    "S00026": "[S00026]가입가능나이_단일속성_업로드양식.xlsx",
    "S00027": "[S00027] 가입가능보기납기_업로드양식.xlsx",
    "S00028": "[S00028] 가입가능납입주기_업로드양식.xlsx",
    "S00022": "[S00022] 보기개시나이_업로드양식.xlsx",
}
TABLE_TYPES = ["S00026", "S00027", "S00028", "S00022"]


# ─── DB 로드 ──────────────────────────────────────────────────────────────────

def load_product_db() -> list:
    """판매중_상품구성정보.xlsx 로드"""
    import openpyxl
    wb = openpyxl.load_workbook(DB_PATH, read_only=True, data_only=True)
    ws = wb.active
    headers = []
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            headers = [str(h).strip() if h else "" for h in row]
        else:
            rows.append(dict(zip(headers, row)))
    wb.close()
    return rows


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


# ─── 상품코드 검색 ────────────────────────────────────────────────────────────

def find_product_dtcd(pdf_path: str, product_db: list) -> str | None:
    """PDF 파일명 기반으로 DB에서 ISRN_KIND_DTCD 검색"""
    base_name = get_pdf_base_name(pdf_path)
    # 의미있는 키워드 추출 (단음절·불용어 제외)
    stopwords = {"무배당", "사업방법서", "상품요약서", "납입면제형", "갱신형"}
    keywords = [w for w in re.split(r"[\s_\-\(\)]", base_name) if len(w) >= 2 and w not in stopwords]

    if not keywords:
        return None

    # ISRN_KIND_DTCD별 최고 점수 집계
    dtcd_scores: dict[str, int] = {}
    for row in product_db:
        sale_name = str(row.get("ISRN_KIND_SALE_NM", "") or "")
        dtcd = str(row.get("ISRN_KIND_DTCD", "") or "").strip()
        if not dtcd:
            continue
        score = sum(1 for kw in keywords if kw in sale_name)
        if score > dtcd_scores.get(dtcd, 0):
            dtcd_scores[dtcd] = score

    if not dtcd_scores:
        return None

    best_dtcd = max(dtcd_scores, key=lambda d: dtcd_scores[d])
    # 절반 이상 매칭되어야 유효
    if dtcd_scores[best_dtcd] >= max(1, len(keywords) // 2):
        return best_dtcd
    return None


# ─── 상품 매핑 자동 생성 ──────────────────────────────────────────────────────

def build_product_mapping(dtcd: str, product_db: list, sub_types: list) -> dict:
    """sub_type → UPPER/LOWER object code 자동 매핑"""
    product_rows = [
        r for r in product_db
        if str(r.get("ISRN_KIND_DTCD", "") or "").strip() == dtcd
    ]
    # 표준체(홀수 A코드) 우선, 건강체/비교형 제외
    standard_rows = [
        r for r in product_rows
        if not any(x in str(r.get("ISRN_KIND_SALE_NM", "")) for x in ["건강체", "비교형"])
    ] or product_rows

    mappings = []
    used_codes: set[str] = set()

    for sub_type in sub_types:
        sub_words = [w for w in re.split(r"[\s\(\)]", sub_type) if len(w) >= 2]
        best_row = None
        best_score = -1

        for row in standard_rows:
            itcd = str(row.get("ISRN_KIND_ITCD", "") or "").strip()
            if itcd in used_codes:
                continue
            sale_name = str(row.get("ISRN_KIND_SALE_NM", "") or "")
            score = sum(1 for w in sub_words if w in sale_name)
            if score > best_score:
                best_score = score
                best_row = row

        if best_row:
            itcd = str(best_row.get("ISRN_KIND_ITCD", "") or "").strip()
            prod_dtcd = str(best_row.get("PROD_DTCD", "") or "").strip()
            prod_itcd = str(best_row.get("PROD_ITCD", "") or "").strip()
            used_codes.add(itcd)
            mappings.append({
                "sub_type": sub_type,
                "upper_object_code": f"{dtcd}{itcd}",
                "lower_object_code": f"{prod_dtcd}{prod_itcd}",
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

def process_pdf(pdf_path: str, product_db: list, run_id: str) -> dict:
    result = {
        "pdf": os.path.basename(pdf_path),
        "run_id": run_id,
        "tables": {},
        "errors": [],
    }

    os.makedirs(EXTRACT_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    pages_json = f"{EXTRACT_DIR}/{run_id}_pages.json"

    # STEP 1: PDF 추출 (이미 처리됐으면 스킵)
    if not os.path.exists(pages_json):
        rc = run_cmd([
            PYTHON,
            ".claude/skills/pdf-preprocessor/scripts/extract_pdf.py",
            "--input", pdf_path,
            "--output", EXTRACT_DIR,
            "--run-id", run_id,
            "--text-only",  # 배치 모드: 이미지 불필요
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

    # STEP 3: 서브타입 파싱
    subtypes_json = f"{EXTRACT_DIR}/{run_id}_subtypes.json"
    run_cmd([
        PYTHON,
        ".claude/skills/pdf-preprocessor/scripts/parse_sub_types.py",
        "--input", pages_json,
        "--output", subtypes_json,
    ], "sub_type parse")

    # STEP 4: 상품코드 검색
    dtcd = find_product_dtcd(pdf_path, product_db)
    if not dtcd:
        result["errors"].append("상품코드 DB 매칭 실패")
        print(f"  [SKIP] DB에서 상품코드를 찾지 못함")
        return result

    product_code = f"{dtcd}A01"
    result["dtcd"] = dtcd
    print(f"  상품코드: {dtcd}")

    # 서브타입 로드
    with open(subtypes_json, encoding="utf-8") as f:
        subtypes_data = json.load(f)
    sub_types = subtypes_data.get("sub_types", ["기본형"])

    # STEP 5: 관련 페이지 텍스트 연결
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

    # STEP 6: product_mapping.json 생성
    mapping_data = build_product_mapping(dtcd, product_db, sub_types)
    mapping_json = f"{EXTRACT_DIR}/{run_id}_mapping.json"
    with open(mapping_json, "w", encoding="utf-8") as f:
        json.dump(mapping_data, f, ensure_ascii=False, indent=2)

    # STEP 7: valid_date.json 생성
    valid_start = get_valid_start_date(pdf_path)
    valid_date_json = f"{EXTRACT_DIR}/{run_id}_valid_date.json"
    with open(valid_date_json, "w", encoding="utf-8") as f:
        json.dump({"valid_start_date": valid_start, "valid_end_date": "99991231"}, f)

    # STEP 8: 테이블별 추출 → 코드변환 → xlsx
    for table_type in TABLE_TYPES:
        raw_json = f"{EXTRACT_DIR}/{product_code}_{table_type}_{run_id}.json"
        coded_json = f"{EXTRACT_DIR}/{product_code}_{table_type}_{run_id}_coded.json"
        template_file = os.path.join(MODELS_DIR, TEMPLATES[table_type])
        xlsx_out = f"{UPLOAD_DIR}/{table_type}_{dtcd}_{run_id}.xlsx"

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
        ], f"{table_type} extract")
        if rc != 0:
            result["tables"][table_type] = "extract_error"
            continue

        with open(raw_json, encoding="utf-8") as f:
            raw_data = json.load(f)
        if not raw_data.get("raw_data"):
            result["tables"][table_type] = "no_data(0행)"
            print(f"  [{table_type}] 추출 데이터 없음 (규칙 미매칭)")
            continue

        # 코드 변환
        rc = run_cmd([
            PYTHON,
            ".claude/skills/code-converter/scripts/convert_codes.py",
            "--input", raw_json,
            "--mappings", ".claude/skills/code-converter/references/code_mappings.json",
            "--output", coded_json,
        ], f"{table_type} convert")
        if rc != 0:
            result["tables"][table_type] = "convert_error"
            continue

        if not os.path.exists(template_file):
            result["tables"][table_type] = "no_template"
            print(f"  [{table_type}] 템플릿 없음: {template_file}")
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
        ], f"{table_type} xlsx")

        if rc == 0:
            with open(coded_json, encoding="utf-8") as f:
                coded_data = json.load(f)
            row_count = len(coded_data.get("coded_rows", []))
            result["tables"][table_type] = f"ok({row_count}행)"
        else:
            result["tables"][table_type] = "xlsx_error"

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

    # DB 로드
    print("DB 로드 중...")
    try:
        product_db = load_product_db()
        print(f"  {len(product_db)}개 상품 레코드 로드 완료\n")
    except Exception as e:
        print(f"ERROR: DB 로드 실패: {e}")
        return 1

    # PDF 목록
    pdf_dir = Path(args.pdf_dir)
    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    # 상품요약서 제외 (사업방법서만)
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

        # 이미 처리됐는지 확인
        if not args.no_skip:
            existing = list(Path(UPLOAD_DIR).glob(f"S00026_*_{run_id}.xlsx")) if os.path.exists(UPLOAD_DIR) else []
            if existing:
                print(f"  [SKIP] 이미 처리됨 → {existing[0].name}\n")
                continue

        try:
            result = process_pdf(str(pdf_path), product_db, run_id)
            results.append(result)

            dtcd = result.get("dtcd", "?")
            errors = result.get("errors", [])
            tables = result.get("tables", {})
            if errors:
                print(f"  [FAIL] {', '.join(errors)}")
            else:
                table_summary = " | ".join(f"{k}: {v}" for k, v in tables.items())
                print(f"  [OK] {dtcd} → {table_summary}")
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
