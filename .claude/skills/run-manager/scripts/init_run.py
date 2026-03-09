"""
init_run.py — run_id 발급 + 세션 디렉토리 생성

Usage:
    python init_run.py [--output-dir output/]

Output:
    stdout: run_id (YYYYMMDD_HHMMSS)
    output/logs/run_{run_id}.json: 세션 메타데이터
"""

import argparse
import json
import os
import sys
from datetime import datetime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args()

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 세션 디렉토리 생성
    for subdir in ["extracted", "upload", "reports", "logs"]:
        os.makedirs(os.path.join(args.output_dir, subdir), exist_ok=True)

    # 세션 메타데이터 저장
    session_meta = {
        "run_id": run_id,
        "started_at": datetime.now().isoformat(),
        "status": "running"
    }
    log_path = os.path.join(args.output_dir, "logs", f"run_{run_id}.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(session_meta, f, ensure_ascii=False, indent=2)

    # run_id를 stdout으로 출력 (메인 에이전트가 캡처)
    print(run_id)
    return run_id


if __name__ == "__main__":
    main()
