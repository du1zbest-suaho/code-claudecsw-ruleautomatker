"""
regression_test.py — 룰 변경 후 전체 성공 상품 재검증

Usage:
    python regression_test.py \
        --rules rules/extraction_rules.py \
        --registry output/logs/run_registry.json \
        --output output/reports/regression_{run_id}.json
"""

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime


def load_extraction_rules(rules_path: str):
    """extraction_rules.py 동적 로드"""
    spec = importlib.util.spec_from_file_location("extraction_rules", rules_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ExtractionRules()


def load_registry(registry_path: str) -> dict:
    if not os.path.exists(registry_path):
        return {"runs": [], "baselines": {}}
    with open(registry_path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules", required=True, help="extraction_rules.py 경로")
    parser.add_argument("--registry", required=True, help="run_registry.json 경로")
    parser.add_argument("--output", required=True, help="회귀 테스트 결과 출력 경로")
    args = parser.parse_args()

    if not os.path.exists(args.rules):
        print(f"ERROR: 룰 파일 없음: {args.rules}")
        return 1

    # extraction_rules 로드
    try:
        rules = load_extraction_rules(args.rules)
    except Exception as e:
        print(f"ERROR: 룰 파일 로드 실패: {e}")
        return 1

    registry = load_registry(args.registry)
    successful_runs = registry.get("runs", [])

    if not successful_runs:
        print("INFO: 등록된 성공 run 없음. 회귀 테스트 스킵.")
        result = {"status": "skipped", "reason": "no registered runs", "timestamp": datetime.now().isoformat()}
        os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return 0

    regression_results = []
    total_pass = 0
    total_fail = 0

    for run in successful_runs:
        run_id = run["run_id"]
        product_code = run["product_code"]
        tables = run["tables"]

        for table_type in tables:
            # 이전 추출 결과 파일 탐색
            extracted_dir = "output/extracted"
            pattern = f"{product_code}_{table_type}_{run_id}.json"
            prev_result_path = os.path.join(extracted_dir, pattern)

            if not os.path.exists(prev_result_path):
                regression_results.append({
                    "run_id": run_id,
                    "product_code": product_code,
                    "table_type": table_type,
                    "status": "skipped",
                    "reason": f"이전 결과 파일 없음: {prev_result_path}"
                })
                continue

            with open(prev_result_path, "r", encoding="utf-8") as f:
                prev_data = json.load(f)

            # 원본 텍스트로 재추출 시도
            page_texts = prev_data.get("page_texts", {})
            if not page_texts:
                regression_results.append({
                    "run_id": run_id,
                    "product_code": product_code,
                    "table_type": table_type,
                    "status": "skipped",
                    "reason": "page_texts 없음 (재추출 불가)"
                })
                continue

            combined_text = "\n".join(page_texts.values())

            try:
                method_map = {
                    "S00026": rules.extract_age_table,
                    "S00027": rules.extract_period_table,
                    "S00028": rules.extract_payment_cycle,
                    "S00022": rules.extract_benefit_start_age,
                }
                method = method_map.get(table_type)
                if not method:
                    regression_results.append({
                        "run_id": run_id,
                        "product_code": product_code,
                        "table_type": table_type,
                        "status": "skipped",
                        "reason": f"알 수 없는 테이블 타입: {table_type}"
                    })
                    continue

                new_raw = method(combined_text, product_code)
                prev_raw = prev_data.get("raw_data", [])

                # 단순 개수 비교 (내용 비교는 추후 확장)
                count_match = len(new_raw) == len(prev_raw)
                status = "pass" if count_match else "fail"

                if status == "pass":
                    total_pass += 1
                else:
                    total_fail += 1

                regression_results.append({
                    "run_id": run_id,
                    "product_code": product_code,
                    "table_type": table_type,
                    "status": status,
                    "prev_row_count": len(prev_raw),
                    "new_row_count": len(new_raw),
                    "count_match": count_match
                })

            except Exception as e:
                total_fail += 1
                regression_results.append({
                    "run_id": run_id,
                    "product_code": product_code,
                    "table_type": table_type,
                    "status": "error",
                    "error": str(e)
                })

    overall_pass = total_fail == 0
    result = {
        "timestamp": datetime.now().isoformat(),
        "overall_pass": overall_pass,
        "total_tested": total_pass + total_fail,
        "total_pass": total_pass,
        "total_fail": total_fail,
        "results": regression_results
    }

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    status_str = "PASS" if overall_pass else "FAIL"
    print(f"회귀 테스트 {status_str}: {total_pass}/{total_pass+total_fail} 통과")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    exit(main())
