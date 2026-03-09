"""
manage_registry.py — 성공 run 등록/조회, 회귀 테스트 기준 run_id 관리

Usage:
    # 성공 run 등록
    python manage_registry.py --action register --run-id 20260306_143022 \
        --product-code 2258A01 --tables S00022,S00026,S00027,S00028

    # 특정 상품의 기준 run_id 조회
    python manage_registry.py --action get-baseline --product-code 2258A01

    # 전체 목록 조회
    python manage_registry.py --action list
"""

import argparse
import json
import os
from datetime import datetime

REGISTRY_PATH = os.path.join("output", "logs", "run_registry.json")


def load_registry():
    if os.path.exists(REGISTRY_PATH):
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"runs": [], "baselines": {}}


def save_registry(registry):
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def register(run_id: str, product_code: str, tables: list):
    registry = load_registry()

    entry = {
        "run_id": run_id,
        "product_code": product_code,
        "tables": tables,
        "registered_at": datetime.now().isoformat(),
        "status": "success"
    }
    registry["runs"].append(entry)

    # 상품별 최신 성공 run_id를 기준으로 등록
    if product_code not in registry["baselines"]:
        registry["baselines"][product_code] = {}
    for table in tables:
        registry["baselines"][product_code][table] = run_id

    save_registry(registry)
    print(f"Registered: run_id={run_id}, product={product_code}, tables={tables}")


def get_baseline(product_code: str):
    registry = load_registry()
    baselines = registry.get("baselines", {}).get(product_code, {})
    if not baselines:
        print(f"No baseline found for product: {product_code}")
        return None
    print(json.dumps(baselines, ensure_ascii=False, indent=2))
    return baselines


def list_runs():
    registry = load_registry()
    runs = registry.get("runs", [])
    print(json.dumps(runs, ensure_ascii=False, indent=2))
    return runs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=["register", "get-baseline", "list"])
    parser.add_argument("--run-id")
    parser.add_argument("--product-code")
    parser.add_argument("--tables")
    args = parser.parse_args()

    if args.action == "register":
        if not args.run_id or not args.product_code or not args.tables:
            print("ERROR: register requires --run-id, --product-code, --tables")
            return 1
        tables = args.tables.split(",")
        register(args.run_id, args.product_code, tables)

    elif args.action == "get-baseline":
        if not args.product_code:
            print("ERROR: get-baseline requires --product-code")
            return 1
        get_baseline(args.product_code)

    elif args.action == "list":
        list_runs()

    return 0


if __name__ == "__main__":
    exit(main())
