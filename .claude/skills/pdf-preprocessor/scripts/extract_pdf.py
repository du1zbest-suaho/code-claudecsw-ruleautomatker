"""
extract_pdf.py — 사업방법서 PDF(또는 ZIP) 해체 + 페이지별 텍스트/이미지 추출

지원 형식:
  - .pdf  : PyMuPDF로 텍스트/이미지 직접 추출
  - .zip  : manifest.json + {n}.txt + {n}.jpeg 구조 (원래 설계 형식)

Usage:
    python extract_pdf.py --input data/pdf/파일명.pdf --output output/extracted/ --run-id 20260306_143022

Output:
    output/extracted/{run_id}_pages.json  — 페이지 인덱스
    output/extracted/{run_id}_page_{n}.txt  — 페이지별 텍스트
    output/extracted/{run_id}_page_{n}.jpeg — 페이지별 이미지 (150 DPI)
"""

import argparse
import json
import os
import shutil
import zipfile


def extract_from_pdf(pdf_path: str, output_dir: str, run_id: str, text_only: bool = False) -> dict:
    """PyMuPDF로 PDF에서 페이지별 텍스트(/이미지) 추출"""
    import fitz  # PyMuPDF

    pages_info = {}
    doc = fitz.open(pdf_path)
    total = len(doc)

    for page_num in range(total):
        page_str = str(page_num + 1)
        page = doc[page_num]

        # 텍스트 추출
        text = page.get_text("text")
        txt_path = os.path.join(output_dir, f"{run_id}_page_{page_str}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)

        img_path = None
        if not text_only:
            # 이미지 추출 (150 DPI)
            mat = fitz.Matrix(150 / 72, 150 / 72)
            pix = page.get_pixmap(matrix=mat)
            img_path = os.path.join(output_dir, f"{run_id}_page_{page_str}.jpeg")
            pix.save(img_path, output="jpeg")

        pages_info[page_str] = {
            "text_path": txt_path,
            "image_path": img_path
        }

    print(f"  {total}페이지 추출 완료 ({'텍스트만' if text_only else '텍스트+이미지'})")
    doc.close()
    return pages_info


def extract_from_zip(zip_path: str, output_dir: str, run_id: str) -> dict:
    """ZIP(manifest.json + txt + jpeg) 형식 처리"""
    pages_info = {}

    with zipfile.ZipFile(zip_path, "r") as zf:
        if "manifest.json" not in zf.namelist():
            raise ValueError(f"manifest.json not found in {zip_path}")

        with zf.open("manifest.json") as mf:
            manifest = json.load(mf)

        page_list = manifest.get("pages", [])
        if not page_list:
            files = zf.namelist()
            txt_files = [f for f in files if f.endswith(".txt") and f != "manifest.json"]
            page_list = sorted([f.replace(".txt", "") for f in txt_files], key=lambda x: int(x))

        for page_id in page_list:
            page_str = str(page_id)
            text_path = None
            image_path = None

            txt_name = f"{page_str}.txt"
            if txt_name in zf.namelist():
                dest_txt = os.path.join(output_dir, f"{run_id}_page_{page_str}.txt")
                with zf.open(txt_name) as src, open(dest_txt, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                text_path = dest_txt

            for img_name in [f"{page_str}.jpeg", f"{page_str}.jpg"]:
                if img_name in zf.namelist():
                    dest_img = os.path.join(output_dir, f"{run_id}_page_{page_str}.jpeg")
                    with zf.open(img_name) as src, open(dest_img, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    image_path = dest_img
                    break

            pages_info[page_str] = {
                "text_path": text_path,
                "image_path": image_path
            }

    return pages_info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="사업방법서 PDF 또는 ZIP 파일 경로")
    parser.add_argument("--output", required=True, help="출력 디렉토리")
    parser.add_argument("--run-id", required=True, help="실행 ID")
    parser.add_argument("--text-only", action="store_true", help="텍스트만 추출 (이미지 저장 생략)")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    pdf_name = os.path.basename(args.input)
    ext = os.path.splitext(args.input)[1].lower()

    print(f"처리 중: {pdf_name}")

    if ext == ".pdf":
        pages_info = extract_from_pdf(args.input, args.output, args.run_id, args.text_only)
    elif ext == ".zip":
        pages_info = extract_from_zip(args.input, args.output, args.run_id)
    else:
        print(f"ERROR: 지원하지 않는 파일 형식: {ext} (.pdf 또는 .zip 필요)")
        return 1

    result = {
        "run_id": args.run_id,
        "pdf_name": pdf_name,
        "total_pages": len(pages_info),
        "pages": pages_info
    }

    out_path = os.path.join(args.output, f"{args.run_id}_pages.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"완료: {len(pages_info)}페이지 추출 → {out_path}")
    return 0


if __name__ == "__main__":
    exit(main())
