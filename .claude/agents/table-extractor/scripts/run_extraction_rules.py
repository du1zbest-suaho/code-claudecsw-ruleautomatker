"""
run_extraction_rules.py — ExtractionRules 인스턴스화 + 테이블별 메서드 실행

Usage:
    python run_extraction_rules.py \
        --table-type S00026 \
        --product-code 2258A01 \
        --input output/extracted/page_text.txt \
        --rules rules/extraction_rules.py \
        --output output/extracted/2258A01_S00026_{run_id}.json

    # run_id를 함께 전달하려면:
    python run_extraction_rules.py ... --run-id 20260306_143022
"""

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime


def load_rules(rules_path: str):
    """extraction_rules.py 동적 로드"""
    spec = importlib.util.spec_from_file_location("extraction_rules", rules_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ExtractionRules()


TABLE_METHOD_MAP = {
    "S00026": "extract_age_table",
    "S00027": "extract_period_table",
    "S00028": "extract_payment_cycle",
    "S00022": "extract_benefit_start_age",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table-type", required=True, choices=["S00022", "S00026", "S00027", "S00028"])
    parser.add_argument("--product-code", required=True)
    parser.add_argument("--input", required=True, help="페이지 텍스트 파일 경로")
    parser.add_argument("--rules", required=True, help="extraction_rules.py 경로")
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    args = parser.parse_args()

    # 룰 파일 로드
    if not os.path.exists(args.rules):
        print(f"ERROR: 룰 파일 없음: {args.rules}")
        return 1

    try:
        rules = load_rules(args.rules)
    except Exception as e:
        print(f"ERROR: 룰 로드 실패: {e}")
        return 1

    # 텍스트 파일 읽기
    if not os.path.exists(args.input):
        print(f"ERROR: 입력 텍스트 없음: {args.input}")
        return 1

    with open(args.input, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    # 메서드 실행
    method_name = TABLE_METHOD_MAP.get(args.table_type)
    if not method_name:
        print(f"ERROR: 알 수 없는 테이블 타입: {args.table_type}")
        return 1

    method = getattr(rules, method_name, None)
    if not method:
        print(f"ERROR: ExtractionRules에 {method_name} 메서드 없음")
        return 1

    try:
        raw_data = method(text, args.product_code)
    except Exception as e:
        print(f"ERROR: 추출 실패: {e}")
        return 1

    result = {
        "table_type": args.table_type,
        "product_code": args.product_code,
        "run_id": args.run_id,
        "source": "extraction_rules",
        "confidence": "high",
        "image_used": False,
        "raw_data": raw_data,
        "discrepancies": [],
        "row_count": len(raw_data)
    }

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"추출 완료: {len(raw_data)}행 → {args.output}")
    return 0


if __name__ == "__main__":
    exit(main())
