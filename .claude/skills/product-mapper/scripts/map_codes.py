"""
map_codes.py — LLM 매핑 결과를 받아 주계약(type=01) 코드 추출

Usage:
    python map_codes.py \
        --candidates output/extracted/{run_id}_candidates.json \
        --mapping '{"간편가입형(0년)": "UPPER_OBJECT_CODE:LOWER_OBJECT_CODE"}' \
        --output output/extracted/{run_id}_mapping.json

    또는 --mapping-file 로 JSON 파일 경로 지정
"""

import argparse
import json
import os


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--mapping", help="JSON 문자열: {sub_type: 'UPPER:LOWER'}")
    parser.add_argument("--mapping-file", help="JSON 파일 경로")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.candidates, "r", encoding="utf-8") as f:
        candidates_data = json.load(f)

    if args.mapping_file:
        with open(args.mapping_file, "r", encoding="utf-8") as f:
            mapping = json.load(f)
    elif args.mapping:
        mapping = json.loads(args.mapping)
    else:
        raise ValueError("--mapping 또는 --mapping-file 중 하나 필요")

    candidates = {
        f"{c['upper_object_code']}:{c['lower_object_code']}": c
        for c in candidates_data.get("candidates", [])
    }

    product_mappings = []
    for sub_type, code_key in mapping.items():
        if code_key in candidates:
            c = candidates[code_key]
            product_mappings.append({
                "sub_type": sub_type,
                "upper_object_code": c["upper_object_code"],
                "lower_object_code": c["lower_object_code"],
                "isrn_kind_dtcd": c["isrn_kind_dtcd"],
                "isrn_kind_itcd": c["isrn_kind_itcd"],
                "prod_dtcd": c["prod_dtcd"],
                "prod_itcd": c["prod_itcd"],
                "prod_type": c["prod_type"],
                "sale_name": c["sale_name"]
            })
        else:
            print(f"WARNING: {sub_type} → {code_key} 후보에서 찾을 수 없음")

    result = {
        "product_name": candidates_data.get("product_name", ""),
        "product_mappings": product_mappings
    }

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Mapped {len(product_mappings)} sub-types → {args.output}")
    return 0


if __name__ == "__main__":
    exit(main())
