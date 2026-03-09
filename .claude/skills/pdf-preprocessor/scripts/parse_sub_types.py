"""
parse_sub_types.py — 보험종목명 + 세부보험종목 목록 파싱 (1~3페이지)

Usage:
    python parse_sub_types.py --input output/extracted/{run_id}_pages.json \
                              --output output/extracted/{run_id}_subtypes.json

Output:
    {run_id}_subtypes.json — 보험종목명 + 세부보험종목 목록
"""

import argparse
import json
import os
import re


# 세부보험종목 패턴 (간편가입형, 일반가입형, 건강가입형, 표준체형, 비흡연체형 등)
SUB_TYPE_PATTERNS = [
    r"간편가입형(?:\(\d+년\))?",
    r"일반가입형(?:\(\d+년\))?",
    r"건강가입형(?:\(\d+년\))?",
    r"표준체형",
    r"비흡연체형",
    r"흡연체형",
    r"무심사형",
    r"심사형",
    r"납입면제형",
    r"비납입면제형",
    r"(\w+가입형(?:\(\d+년\))?)",
    r"(\w+체형)",
]

# 보험종목명 추출 패턴
PRODUCT_NAME_PATTERNS = [
    r"보험종목의\s*명칭[:\s]*([^\n]+)",
    r"상품명[:\s]*([^\n]+)",
    r"보험종목명[:\s]*([^\n]+)",
]


def extract_product_name(text: str) -> str | None:
    for pattern in PRODUCT_NAME_PATTERNS:
        m = re.search(pattern, text)
        if m:
            name = m.group(1).strip()
            # 불필요한 문자 제거
            name = re.sub(r"\s+", " ", name)
            return name
    return None


def extract_sub_types(text: str) -> list:
    found = set()
    for pattern in SUB_TYPE_PATTERNS:
        for m in re.finditer(pattern, text):
            sub_type = m.group(0).strip()
            if len(sub_type) >= 3:  # 너무 짧은 매칭 제외
                found.add(sub_type)
    return sorted(found)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-pages", type=int, default=3, help="검색할 최대 페이지 수")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        pages_data = json.load(f)

    combined_text = ""
    source_pages = []
    pages = pages_data.get("pages", {})

    # 1~max_pages 페이지 텍스트 결합
    for page_id in sorted(pages.keys(), key=lambda x: int(x)):
        if int(page_id) > args.max_pages:
            break
        text_path = pages[page_id].get("text_path")
        if text_path and os.path.exists(text_path):
            with open(text_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            combined_text += f"\n--- 페이지 {page_id} ---\n{text}"
            source_pages.append(int(page_id))

    product_name = extract_product_name(combined_text)
    sub_types = extract_sub_types(combined_text)

    # 세부보험종목이 없으면 단일 종목으로 처리
    if not sub_types:
        sub_types = ["기본형"]

    result = {
        "product_name": product_name or pages_data.get("pdf_name", "").replace(".zip", ""),
        "sub_types": sub_types,
        "source_pages": source_pages
    }

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Product: {result['product_name']}")
    print(f"Sub types: {sub_types}")
    return 0


if __name__ == "__main__":
    exit(main())
