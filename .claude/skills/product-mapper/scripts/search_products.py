"""
search_products.py — 보험종목명으로 상품구성정보 검색, 후보군 추출

Usage:
    python search_products.py \
        --subtypes output/extracted/{run_id}_subtypes.json \
        --db data/existing/판매중_상품구성정보.xlsx \
        --output output/extracted/{run_id}_candidates.json
"""

import argparse
import json
import os
import re

try:
    import openpyxl
except ImportError:
    print("ERROR: openpyxl이 필요합니다. pip install openpyxl")
    exit(1)


def normalize(text: str) -> str:
    """비교를 위한 텍스트 정규화"""
    if not text:
        return ""
    text = str(text)
    text = re.sub(r"[\s\(\)\-_]", "", text)
    return text.lower()


def load_product_db(db_path: str) -> list:
    """상품구성정보 xlsx 로드"""
    wb = openpyxl.load_workbook(db_path, read_only=True, data_only=True)
    ws = wb.active

    headers = []
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(row)]
        else:
            row_dict = {headers[j]: row[j] for j in range(min(len(headers), len(row)))}
            rows.append(row_dict)

    wb.close()
    return rows


def score_similarity(product_name: str, sale_name: str) -> float:
    """단순 문자열 유사도 점수 계산"""
    if not product_name or not sale_name:
        return 0.0

    norm_product = normalize(product_name)
    norm_sale = normalize(str(sale_name))

    # 공통 부분 문자열 길이
    min_len = min(len(norm_product), len(norm_sale))
    if min_len == 0:
        return 0.0

    common = sum(1 for c in norm_product if c in norm_sale)
    return common / max(len(norm_product), len(norm_sale))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subtypes", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--top-k", type=int, default=20, help="후보군 최대 수")
    args = parser.parse_args()

    with open(args.subtypes, "r", encoding="utf-8") as f:
        subtypes_data = json.load(f)

    product_name = subtypes_data.get("product_name", "")
    sub_types = subtypes_data.get("sub_types", [])

    print(f"Searching for: {product_name}")
    print(f"Sub types: {sub_types}")

    rows = load_product_db(args.db)

    # 유사도 계산 (실제 DB 컬럼명 사용)
    candidates = []
    for row in rows:
        isrn_kind_dtcd = str(row.get("ISRN_KIND_DTCD", "") or "").strip()
        isrn_kind_itcd = str(row.get("ISRN_KIND_ITCD", "") or "").strip()
        prod_dtcd = str(row.get("PROD_DTCD", "") or "").strip()
        prod_itcd = str(row.get("PROD_ITCD", "") or "").strip()
        sale_name = row.get("ISRN_KIND_SALE_NM", "") or ""
        score = score_similarity(product_name, sale_name)

        if score > 0.3:  # 최소 유사도 임계값
            candidates.append({
                "score": round(score, 3),
                "upper_object_code": f"{isrn_kind_dtcd}{isrn_kind_itcd}",
                "lower_object_code": f"{prod_dtcd}{prod_itcd}",
                "isrn_kind_dtcd": isrn_kind_dtcd,
                "isrn_kind_itcd": isrn_kind_itcd,
                "prod_dtcd": prod_dtcd,
                "prod_itcd": prod_itcd,
                "prod_type": "",
                "sale_name": str(sale_name)
            })

    # 점수 기준 정렬, 상위 K개 추출
    candidates.sort(key=lambda x: x["score"], reverse=True)
    candidates = candidates[:args.top_k]

    result = {
        "product_name": product_name,
        "sub_types": sub_types,
        "candidates": candidates,
        "total_candidates": len(candidates)
    }

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Found {len(candidates)} candidates → {args.output}")
    return 0


if __name__ == "__main__":
    exit(main())
