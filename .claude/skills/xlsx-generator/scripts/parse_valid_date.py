"""
parse_valid_date.py — PDF 파일명에서 유효시작일 파싱

Usage:
    python parse_valid_date.py \
        --pdf-name 한화생명_e암보험비갱신형_무배당_사업방법서_20260101.zip \
        --output output/extracted/{run_id}_valid_date.json

Output:
    {"valid_start_date": "2026-01-01", "valid_end_date": "9999-12-31"}
"""

import argparse
import json
import os
import re


def parse_date_from_filename(filename: str) -> str | None:
    """파일명에서 YYYYMMDD 패턴 추출"""
    # _YYYYMMDD.zip 또는 _YYYYMMDD_ 패턴
    patterns = [
        r"_(\d{8})\.zip$",
        r"_(\d{8})_",
        r"(\d{8})",
    ]
    for pattern in patterns:
        m = re.search(pattern, filename)
        if m:
            date_str = m.group(1)
            try:
                year = int(date_str[:4])
                month = int(date_str[4:6])
                day = int(date_str[6:8])
                if 2000 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31:
                    return f"{year:04d}-{month:02d}-{day:02d}"
            except ValueError:
                continue
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf-name", required=True, help="PDF 파일명 (zip 포함)")
    parser.add_argument("--output", required=True)
    parser.add_argument("--manual-date", help="수동 입력 날짜 (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.manual_date:
        valid_start = args.manual_date
        print(f"수동 입력 날짜 사용: {valid_start}")
    else:
        valid_start = parse_date_from_filename(args.pdf_name)
        if not valid_start:
            print(f"ERROR: 파일명에서 날짜 파싱 실패: {args.pdf_name}")
            print("ESCALATION: 사용자에게 유효시작일(YYYY-MM-DD) 입력 요청 필요")
            return 1
        print(f"파싱된 유효시작일: {valid_start}")

    result = {
        "pdf_name": args.pdf_name,
        "valid_start_date": valid_start,
        "valid_end_date": "9999-12-31"
    }

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return 0


if __name__ == "__main__":
    exit(main())
