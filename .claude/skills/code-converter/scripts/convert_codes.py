"""
convert_codes.py — 자연어 표현 → 시스템코드 변환

Usage:
    python convert_codes.py \
        --input output/extracted/{upper_obj}_{table_type}_{run_id}.json \
        --mappings .claude/skills/code-converter/references/code_mappings.json \
        --output output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json
"""

import argparse
import json
import os
import re


# ─── 보험기간 변환 ────────────────────────────────────────────────────────────

def convert_insurance_period(raw: str) -> dict:
    """자연어 보험기간 → 시스템코드"""
    raw = str(raw).strip()

    # 빈 문자열 / NaN → None (연금보험 등 보험기간 미지정 상품)
    if not raw or raw in ('nan', 'None', '-'):
        return {"ISRN_TERM": None, "ISRN_TERM_DVSN_CODE": None, "ISRN_TERM_INQY_CODE": None}

    # 종신
    if re.search(r"종신", raw):
        return {"ISRN_TERM": 999, "ISRN_TERM_DVSN_CODE": "A", "ISRN_TERM_INQY_CODE": "A999"}

    # N세만기 (주피보험자)
    m = re.match(r"(\d+)세만기$", raw)
    if m:
        n = int(m.group(1))
        return {"ISRN_TERM": n, "ISRN_TERM_DVSN_CODE": "X", "ISRN_TERM_INQY_CODE": f"X{n}"}

    # N세만기 (자녀)
    m = re.match(r"(\d+)세만기\(자녀\)", raw)
    if m:
        n = int(m.group(1))
        return {"ISRN_TERM": n, "ISRN_TERM_DVSN_CODE": "Z", "ISRN_TERM_INQY_CODE": f"Z{n}"}

    # N세만기 (피부양자)
    m = re.match(r"(\d+)세만기\(피부양자\)", raw)
    if m:
        n = int(m.group(1))
        return {"ISRN_TERM": n, "ISRN_TERM_DVSN_CODE": "V", "ISRN_TERM_INQY_CODE": f"V{n}"}

    # N세만기 (계약자)
    m = re.match(r"(\d+)세만기\(계약자\)", raw)
    if m:
        n = int(m.group(1))
        return {"ISRN_TERM": n, "ISRN_TERM_DVSN_CODE": "W", "ISRN_TERM_INQY_CODE": f"W{n}"}

    # N년만기
    m = re.match(r"(\d+)년만기$", raw)
    if m:
        n = int(m.group(1))
        return {"ISRN_TERM": n, "ISRN_TERM_DVSN_CODE": "N", "ISRN_TERM_INQY_CODE": f"N{n}"}

    # N일만기
    m = re.match(r"(\d+)일만기$", raw)
    if m:
        n = int(m.group(1))
        return {"ISRN_TERM": n, "ISRN_TERM_DVSN_CODE": "D", "ISRN_TERM_INQY_CODE": f"D{n}"}

    # N월만기
    m = re.match(r"(\d+)월만기$", raw)
    if m:
        n = int(m.group(1))
        return {"ISRN_TERM": n, "ISRN_TERM_DVSN_CODE": "M", "ISRN_TERM_INQY_CODE": f"M{n}"}

    return {"ISRN_TERM": None, "ISRN_TERM_DVSN_CODE": None, "ISRN_TERM_INQY_CODE": None,
            "_convert_error": f"알 수 없는 보험기간 표현: {raw}"}


# ─── 납입기간 변환 ────────────────────────────────────────────────────────────

def convert_payment_period(raw: str, insurance_period_code: dict = None) -> dict:
    """자연어 납입기간 → 시스템코드"""
    raw = str(raw).strip()

    # 전기납: 보험기간과 동일
    if re.search(r"전기납", raw):
        if insurance_period_code:
            return {
                "PAYM_TERM": insurance_period_code.get("ISRN_TERM"),
                "PAYM_TERM_DVSN_CODE": insurance_period_code.get("ISRN_TERM_DVSN_CODE"),
                "PAYM_TERM_INQY_CODE": insurance_period_code.get("ISRN_TERM_INQY_CODE")
            }
        return {"PAYM_TERM": None, "PAYM_TERM_DVSN_CODE": None, "PAYM_TERM_INQY_CODE": None,
                "_convert_error": "전기납이지만 보험기간 코드 없음"}

    # 일시납
    if re.search(r"일시납", raw):
        return {"PAYM_TERM": 0, "PAYM_TERM_DVSN_CODE": "N", "PAYM_TERM_INQY_CODE": "N0"}

    # 종신납 (= 종신 전기납)
    if re.search(r"종신납", raw):
        return {"PAYM_TERM": 999, "PAYM_TERM_DVSN_CODE": "A", "PAYM_TERM_INQY_CODE": "A999"}

    # N년납
    m = re.match(r"(\d+)년납$", raw)
    if m:
        n = int(m.group(1))
        return {"PAYM_TERM": n, "PAYM_TERM_DVSN_CODE": "N", "PAYM_TERM_INQY_CODE": f"N{n}"}

    # N세납 (예: 60세납 → X60)
    m = re.match(r"(\d+)세납$", raw)
    if m:
        n = int(m.group(1))
        return {"PAYM_TERM": n, "PAYM_TERM_DVSN_CODE": "X", "PAYM_TERM_INQY_CODE": f"X{n}"}

    return {"PAYM_TERM": None, "PAYM_TERM_DVSN_CODE": None, "PAYM_TERM_INQY_CODE": None,
            "_convert_error": f"알 수 없는 납입기간 표현: {raw}"}


# ─── 납입주기 변환 ────────────────────────────────────────────────────────────

PAYMENT_CYCLE_MAP = {
    "월납": {"PAYM_CYCL_VAL": 1, "PAYM_CYCL_DVSN_CODE": "M", "PAYM_CYCL_INQY_CODE": "M1"},
    "3월납": {"PAYM_CYCL_VAL": 3, "PAYM_CYCL_DVSN_CODE": "M", "PAYM_CYCL_INQY_CODE": "M3"},
    "3개월납": {"PAYM_CYCL_VAL": 3, "PAYM_CYCL_DVSN_CODE": "M", "PAYM_CYCL_INQY_CODE": "M3"},
    "6월납": {"PAYM_CYCL_VAL": 6, "PAYM_CYCL_DVSN_CODE": "M", "PAYM_CYCL_INQY_CODE": "M6"},
    "6개월납": {"PAYM_CYCL_VAL": 6, "PAYM_CYCL_DVSN_CODE": "M", "PAYM_CYCL_INQY_CODE": "M6"},
    "년납": {"PAYM_CYCL_VAL": 12, "PAYM_CYCL_DVSN_CODE": "M", "PAYM_CYCL_INQY_CODE": "M12"},
    "연납": {"PAYM_CYCL_VAL": 12, "PAYM_CYCL_DVSN_CODE": "M", "PAYM_CYCL_INQY_CODE": "M12"},
    "일시납": {"PAYM_CYCL_VAL": 0, "PAYM_CYCL_DVSN_CODE": "M", "PAYM_CYCL_INQY_CODE": "M0"},
}


def convert_payment_cycle(raw: str) -> dict:
    raw = str(raw).strip()
    if raw in PAYMENT_CYCLE_MAP:
        return PAYMENT_CYCLE_MAP[raw]
    # 부분 매칭 시도
    for key, val in PAYMENT_CYCLE_MAP.items():
        if key in raw:
            return val
    return {"PAYM_CYCL_VAL": None, "PAYM_CYCL_DVSN_CODE": None, "PAYM_CYCL_INQY_CODE": None,
            "_convert_error": f"알 수 없는 납입주기: {raw}"}


# ─── 성별 변환 ────────────────────────────────────────────────────────────────

GENDER_MAP = {"남자": "1", "남": "1", "여자": "2", "여": "2", "남녀": None, "남녀공통": None}


def convert_gender(raw: str) -> str | None:
    return GENDER_MAP.get(str(raw).strip())


# ─── 테이블별 변환 ────────────────────────────────────────────────────────────

def convert_s00026(raw_rows: list) -> list:
    """S00026 (가입가능나이) 코드 변환"""
    coded = []
    for row in raw_rows:
        ip = convert_insurance_period(row.get("insurance_period", ""))
        pp = convert_payment_period(row.get("payment_period", ""), ip)
        gender_code = convert_gender(row.get("gender", ""))

        coded_row = {
            **ip, **pp,
            "MINU_GNDR_CODE": gender_code,
            "MIN_AG": row.get("min_age"),
            "MAX_AG": row.get("max_age"),
            "sub_type": row.get("sub_type"),
            "_raw": row
        }
        errors = [v for k, v in coded_row.items() if k == "_convert_error"]
        if any(coded_row.get(k) is None for k in ["ISRN_TERM", "PAYM_TERM"]):
            coded_row["_warnings"] = [f"{k}=None" for k in ["ISRN_TERM", "PAYM_TERM"] if coded_row.get(k) is None]
        coded.append(coded_row)

    # 포스트-프로세싱: gender-neutral 행 자동 생성
    # GT DB 관례: 동일 ip/pp에서 남자(g=1)와 여자(g=2) 둘 다 min=0인 동일 max_age 행이 있으면
    # gender-neutral(g=None) 행도 함께 등록
    _add_gender_neutral_rows(coded)

    return coded


def _add_gender_neutral_rows(coded: list) -> None:
    """gender-neutral 행 생성 (in-place).
    조건: 동일 (ip_code, pp_code)에서 g=1/g=2 모두 min=0이고 max_age가 동일한 쌍 존재.
    기존에 이미 g=None 행이 있으면 중복 추가 안 함.
    """
    from collections import defaultdict
    # (ip_code, pp_code, max_ag) → {g값} 집합 (min=0 한정)
    group = defaultdict(set)
    for r in coded:
        if r.get('MINU_GNDR_CODE') in ('1', '2', 1, 2) and r.get('MIN_AG') == 0 and r.get('MAX_AG') is not None:
            key = (r.get('ISRN_TERM_INQY_CODE'), r.get('PAYM_TERM_INQY_CODE'), r.get('MAX_AG'))
            group[key].add(str(r['MINU_GNDR_CODE']))

    # 이미 존재하는 g=None 키
    existing_gn = {
        (r.get('ISRN_TERM_INQY_CODE'), r.get('PAYM_TERM_INQY_CODE'), r.get('MAX_AG'))
        for r in coded
        if r.get('MINU_GNDR_CODE') is None and r.get('MIN_AG') == 0 and r.get('MAX_AG') is not None
    }

    new_rows = []
    seen_keys = set(existing_gn)
    for (ip_code, pp_code, max_ag), gset in group.items():
        if {'1', '2'}.issubset(gset):
            key = (ip_code, pp_code, max_ag)
            if key not in seen_keys:
                # 원본 행에서 ip/pp 상세 필드 복사
                ref = next((r for r in coded
                            if r.get('ISRN_TERM_INQY_CODE') == ip_code
                            and r.get('PAYM_TERM_INQY_CODE') == pp_code
                            and r.get('MINU_GNDR_CODE') in ('1', 1)), None)
                if ref:
                    new_row = {
                        'ISRN_TERM': ref.get('ISRN_TERM'),
                        'ISRN_TERM_DVSN_CODE': ref.get('ISRN_TERM_DVSN_CODE'),
                        'ISRN_TERM_INQY_CODE': ip_code,
                        'PAYM_TERM': ref.get('PAYM_TERM'),
                        'PAYM_TERM_DVSN_CODE': ref.get('PAYM_TERM_DVSN_CODE'),
                        'PAYM_TERM_INQY_CODE': pp_code,
                        'MINU_GNDR_CODE': None,
                        'MIN_AG': 0,
                        'MAX_AG': max_ag,
                        'sub_type': ref.get('sub_type'),
                        '_generated': 'gender_neutral',
                    }
                    new_rows.append(new_row)
                    seen_keys.add(key)

    coded.extend(new_rows)


def convert_s00027(raw_rows: list) -> list:
    """S00027 (가입가능보기납기) 코드 변환"""
    coded = []
    for row in raw_rows:
        ip = convert_insurance_period(row.get("insurance_period", ""))
        pp = convert_payment_period(row.get("payment_period", ""), ip)

        coded_row = {
            **ip, **pp,
            "sub_type": row.get("sub_type"),
            "_raw": row
        }
        coded.append(coded_row)
    return coded


def convert_s00028(raw_rows: list) -> list:
    """S00028 (가입가능납입주기) 코드 변환"""
    coded = []
    for row in raw_rows:
        pc = convert_payment_cycle(row.get("payment_cycle", ""))
        coded_row = {
            **pc,
            "sub_type": row.get("sub_type"),
            "_raw": row
        }
        coded.append(coded_row)
    return coded


def convert_s00022(raw_rows: list) -> list:
    """S00022 (보기개시나이) 코드 변환
    X-type: min_age~max_age 범위를 연도별 개별 행으로 확장 (SPIN_STRT_DVSN_CODE='X')
    N-type: n_years 필드 존재 시 단일 행 생성 (SPIN_STRT_DVSN_CODE='N')
    """
    coded = []
    seen_spin = set()
    for row in raw_rows:
        sub_type = row.get("sub_type")
        n_years = row.get("n_years")

        if n_years is not None:
            # N-type: 년 기반 보기개시 (스마트연금전환특약 등)
            try:
                n_years = int(n_years)
            except (ValueError, TypeError):
                continue
            spin_code = f"N{n_years}"
            if spin_code in seen_spin:
                continue
            seen_spin.add(spin_code)
            coded.append({
                "FPIN_STRT_AG_INQY_CODE": "0",
                "FPIN_STRT_DVSN_CODE": "0",
                "FPIN_STRT_DVSN_VAL": 0,
                "SPIN_STRT_AG_INQY_CODE": spin_code,
                "SPIN_STRT_DVSN_CODE": "N",
                "SPIN_STRT_DVSN_VAL": n_years,
                "sub_type": sub_type,
                "_raw": row
            })
        else:
            # X-type: 나이 범위 확장
            min_age = row.get("min_age")
            max_age = row.get("max_age")
            if min_age is None or max_age is None:
                continue
            try:
                min_age = int(min_age)
                max_age = int(max_age)
            except (ValueError, TypeError):
                continue
            for age in range(min_age, max_age + 1):
                spin_code = f"X{age}"
                if spin_code in seen_spin:
                    continue
                seen_spin.add(spin_code)
                coded.append({
                    "FPIN_STRT_AG_INQY_CODE": "0",
                    "FPIN_STRT_DVSN_CODE": "0",
                    "FPIN_STRT_DVSN_VAL": 0,
                    "SPIN_STRT_AG_INQY_CODE": spin_code,
                    "SPIN_STRT_DVSN_CODE": "X",
                    "SPIN_STRT_DVSN_VAL": age,
                    "sub_type": sub_type,
                    "_raw": row
                })
    return coded


TABLE_CONVERTERS = {
    "S00022": convert_s00022,
    "S00026": convert_s00026,
    "S00027": convert_s00027,
    "S00028": convert_s00028,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--mappings", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        extracted = json.load(f)

    table_type = extracted.get("table_type", "")
    raw_data = extracted.get("raw_data", [])

    converter = TABLE_CONVERTERS.get(table_type)
    if not converter:
        print(f"ERROR: 알 수 없는 테이블 타입: {table_type}")
        return 1

    coded_rows = converter(raw_data)

    # 변환 오류 집계
    errors = []
    for row in coded_rows:
        if "_convert_error" in row:
            errors.append(row["_convert_error"])

    result = {
        **extracted,
        "coded_rows": coded_rows,
        "convert_errors": errors,
        "convert_error_count": len(errors)
    }

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if errors:
        print(f"WARNING: {len(errors)} 변환 오류 발생:")
        for e in errors:
            print(f"  - {e}")
    else:
        print(f"코드 변환 완료: {len(coded_rows)}행 → {args.output}")

    return 1 if errors else 0


if __name__ == "__main__":
    exit(main())
