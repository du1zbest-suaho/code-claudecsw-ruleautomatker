"""
model_key_loader.py — 모델상세 xlsx에서 비교키 컬럼 목록 동적 로드

ROW_NO ~ CREATE_DATE 사이 컬럼(속성물리명)을 반환.
모든 테이블(S00026/S00027/S00028/S00022)에서 공통으로 사용.
"""

import glob
import os
import warnings

try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas가 필요합니다. pip install pandas openpyxl")
    raise

MODELS_DIR = "data/models"

_MODEL_FILE_PATTERNS = {
    "S00026": "*S00026*모델상세*.xlsx",
    "S00027": "*S00027*모델상세*.xlsx",
    "S00028": "*S00028*모델상세*.xlsx",
    "S00022": "*S00022*모델상세*.xlsx",
}

_cache: dict = {}


def load_model_key_cols(table_type: str, models_dir: str = MODELS_DIR) -> list:
    """ROW_NO 다음 ~ CREATE_DATE 이전 컬럼명 목록 반환 (캐시됨).

    모델상세 xlsx 구조:
      - 열0: 속성논리명(한글)
      - 열1: 속성물리명(영문 컬럼명)  ← 이 열을 기준으로 ROW_NO/CREATE_DATE 위치 탐색
      - 열2: 데이터유형
      - 열3: NULLABLE
      - 열4: COLUMN_ID
    """
    cache_key = (table_type, models_dir)
    if cache_key in _cache:
        return _cache[cache_key]

    pattern = _MODEL_FILE_PATTERNS.get(table_type)
    if not pattern:
        return []

    files = glob.glob(os.path.join(models_dir, pattern))
    if not files:
        return []

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_excel(files[0], header=None)

    # 열1 (속성물리명) 리스트
    phys = df[1].tolist()

    try:
        row_no_idx = phys.index("ROW_NO")
        create_idx = phys.index("CREATE_DATE")
    except ValueError:
        _cache[cache_key] = []
        return []

    cols = [str(phys[i]) for i in range(row_no_idx + 1, create_idx)]
    _cache[cache_key] = cols
    return cols


def normalize_val(v):
    """GT/EX 값 정규화: NaN→None, 모든 유효값→문자열.

    GT는 Excel에서 코드값을 숫자(0, 45...)로 저장하고,
    EX(coded_rows)는 동일 값을 문자열("0", "X45")로 저장하므로
    타입을 문자열로 통일해야 일치 비교가 가능.
    """
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, float):
        # 0.0 → "0", 15.0 → "15", 3.14 → "3.14"
        if v == int(v):
            return str(int(v))
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        stripped = v.strip()
        return stripped if stripped else None
    return str(v)


def make_row_key(row_dict: dict, key_cols: list) -> tuple:
    """컬럼 목록으로 정규화된 키 tuple 생성 (None 포함)."""
    return tuple(normalize_val(row_dict.get(col)) for col in key_cols)


def get_active_key_cols(gt_rows: list, ex_rows: list, key_cols: list) -> list:
    """DTCD별 실제 비교키 컬럼 산출.

    GT와 EX 양쪽에 non-None 값이 있는 컬럼만 반환한다.
    - GT에만 값이 있고 EX=None인 컬럼: 추출 로직이 해당 컬럼을 생성하지 않음 →
      현재 추출 수준에서 비교 불가이므로 제외 (별도 추출 개선 과제로 분리).
    - EX에만 값이 있는 컬럼: 신규 추출값으로 extra로 처리되므로 여기선 무관.
    - 상품세목에 따라 GT에서 실제 입력 컬럼이 다르므로 DTCD별 동적 결정.
    """
    gt_active = {col for col in key_cols
                 if any(normalize_val(r.get(col)) is not None for r in gt_rows)}
    ex_active = {col for col in key_cols
                 if any(normalize_val(r.get(col)) is not None for r in ex_rows)}
    return [col for col in key_cols if col in gt_active and col in ex_active]
