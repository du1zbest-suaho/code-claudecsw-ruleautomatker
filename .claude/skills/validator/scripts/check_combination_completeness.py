"""
check_combination_completeness.py — S00026 전용: 보험기간×납입기간×성별 조합 완전성 검사

두 가지 모드:
  --mode gt   (기본): GT 파일의 조합을 기준으로 추출 결과 비교 (올바른 검증)
  --mode self : 추출 결과 자체의 카테시안 곱과 비교 (내부 일관성만 확인, GT 무관)

Usage:
    # GT 기준 (권장)
    python check_combination_completeness.py \
        --input output/extracted/{upper_obj}_S00026_{run_id}_coded.json \
        --db data/existing/판매중_가입나이정보_0312.xlsx \
        --product-code 2258A01 \
        --output output/reports/{upper_obj}_S00026_{run_id}_completeness.json

    # 내부 일관성만 확인 (GT 없을 때)
    python check_combination_completeness.py \
        --input output/extracted/{upper_obj}_S00026_{run_id}_coded.json \
        --output output/reports/{upper_obj}_S00026_{run_id}_completeness.json \
        --mode self
"""

import argparse
import json
import os
import sys
import warnings
from itertools import product

warnings.filterwarnings("ignore")

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from model_key_loader import normalize_val  # noqa: E402


def _combo(r: dict) -> tuple:
    return (
        str(r.get("ISRN_TERM_INQY_CODE", "") or ""),
        str(r.get("PAYM_TERM_INQY_CODE", "") or ""),
        str(r.get("MINU_GNDR_CODE", "") or ""),
    )


def load_gt_combos(db_path: str, product_code: str) -> set:
    """GT 파일에서 해당 상품의 (IP, PP, gender) 조합 세트 반환."""
    try:
        import pandas as pd
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = pd.read_excel(db_path)
    except Exception as e:
        print(f"WARNING: GT 파일 로드 실패: {e}")
        return set()

    dtcd_str = product_code[:4] if len(product_code) >= 4 else product_code
    if "ISRN_KIND_DTCD" in df.columns:
        df = df[df["ISRN_KIND_DTCD"].astype(str).str.strip() == dtcd_str]
    rows = df.to_dict("records")
    return {_combo(r) for r in rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--db", default=None, help="GT 파일 경로 (--mode gt 시 필수)")
    parser.add_argument("--product-code", default=None, help="상품코드 (DTCD+ITCD, --mode gt 시 필수)")
    parser.add_argument("--mode", choices=["gt", "self"], default="gt",
                        help="gt=GT 기준 비교(기본), self=자기 데이터 내부 일관성만 확인")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        coded_data = json.load(f)

    table_type = coded_data.get("table_type", "")
    if table_type != "S00026":
        print(f"WARNING: S00026 전용 스크립트. 현재 테이블: {table_type}")
        return 0

    coded_rows = coded_data.get("coded_rows", [])

    # 추출된 조합
    extracted_combos = {_combo(r) for r in coded_rows}

    # 기간/성별 고유값 (출력용)
    insurance_periods = sorted({c[0] for c in extracted_combos if c[0]})
    payment_periods   = sorted({c[1] for c in extracted_combos if c[1]})
    genders           = sorted({c[2] for c in extracted_combos if c[2]})

    if args.mode == "gt":
        if not args.db or not args.product_code:
            print("ERROR: --mode gt 는 --db 와 --product-code 가 필요합니다.")
            return 1
        if not os.path.exists(args.db):
            print(f"WARNING: GT 파일 없음: {args.db}. self 모드로 전환.")
            args.mode = "self"
        else:
            gt_combos = load_gt_combos(args.db, args.product_code)
            if not gt_combos:
                print("WARNING: GT 조합이 비어있음. self 모드로 전환.")
                args.mode = "self"

    if args.mode == "self":
        # [구 방식] 추출 데이터 자체의 카테시안 곱과 비교
        # ※ 이 비교는 GT와 무관하며 내부 일관성만 확인합니다.
        #   추출이 과다해도 COMPLETE가 나올 수 있어 의미가 제한적입니다.
        expected_combos = set(product(insurance_periods, payment_periods, genders))
        mode_label = "self (내부 일관성, GT 비교 아님)"
    else:
        # [GT 방식] GT 조합을 기준으로 비교
        expected_combos = gt_combos
        mode_label = f"gt (GT 기준: {len(gt_combos)}개 조합)"

    missing_combos = expected_combos - extracted_combos
    extra_combos   = extracted_combos - expected_combos
    is_complete    = len(missing_combos) == 0

    result = {
        "table_type": "S00026",
        "mode": args.mode,
        "mode_label": mode_label,
        "insurance_periods": insurance_periods,
        "payment_periods": payment_periods,
        "genders": genders,
        "expected_count": len(expected_combos),
        "extracted_count": len(extracted_combos),
        "missing_count": len(missing_combos),
        "extra_count": len(extra_combos),
        "is_complete": is_complete,
        "missing_combinations": [
            {"ISRN_TERM_INQY_CODE": c[0], "PAYM_TERM_INQY_CODE": c[1], "MINU_GNDR_CODE": c[2]}
            for c in sorted(missing_combos)
        ],
        "extra_combinations": [
            {"ISRN_TERM_INQY_CODE": c[0], "PAYM_TERM_INQY_CODE": c[1], "MINU_GNDR_CODE": c[2]}
            for c in sorted(extra_combos)
        ]
    }

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if is_complete:
        print(f"COMPLETE [{args.mode}]: 추출 {len(extracted_combos)}개 = 기대 {len(expected_combos)}개")
    else:
        print(f"INCOMPLETE [{args.mode}]: 누락 {len(missing_combos)}개 / 초과 {len(extra_combos)}개 (기대 {len(expected_combos)}개)")
        for c in sorted(missing_combos)[:10]:
            print(f"  누락: 보험기간={c[0]}, 납입기간={c[1]}, 성별={c[2]}")

    return 0 if is_complete else 1


if __name__ == "__main__":
    exit(main())
