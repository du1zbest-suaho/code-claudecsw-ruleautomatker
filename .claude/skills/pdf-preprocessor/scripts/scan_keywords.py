"""
scan_keywords.py — 키워드 기반 관련 페이지 식별

Usage:
    python scan_keywords.py --input output/extracted/{run_id}_pages.json \
                            --output output/extracted/{run_id}_keywords.json

Output:
    {run_id}_keywords.json — 키워드별 관련 페이지 목록 + fallback_needed 플래그
"""

import argparse
import json
import os
import re

KEYWORD_GROUPS = {
    "가입나이_보기납기": [
        "가입나이", "가입가능나이", "피보험자 가입나이", "보험기간", "납입기간",
        "가입가능연령", "가입연령"
    ],
    "납입주기": [
        "납입주기", "납입방법", "보험료 납입주기", "납입 주기"
    ],
    "보기개시나이": [
        "보기개시", "연금개시", "보험금 지급개시", "개시나이", "연금지급개시"
    ]
}


def scan_page(text: str, keywords: list) -> bool:
    text_lower = text.lower()
    for kw in keywords:
        if kw in text:
            return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        pages_data = json.load(f)

    relevant_pages = {group: [] for group in KEYWORD_GROUPS}

    for page_id, page_info in pages_data.get("pages", {}).items():
        text_path = page_info.get("text_path")
        if not text_path or not os.path.exists(text_path):
            continue

        with open(text_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()

        for group, keywords in KEYWORD_GROUPS.items():
            if scan_page(text, keywords):
                relevant_pages[group].append(int(page_id))

    # 전체 관련 페이지 합집합
    all_relevant = set()
    for pages in relevant_pages.values():
        all_relevant.update(pages)

    fallback_needed = len(all_relevant) == 0

    result = {
        "fallback_needed": fallback_needed,
        "relevant_pages": relevant_pages,
        "all_relevant_pages": sorted(all_relevant)
    }

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if fallback_needed:
        print("WARNING: No relevant pages found. fallback_needed=true")
    else:
        print(f"Found relevant pages: {relevant_pages}")

    return 0


if __name__ == "__main__":
    exit(main())
