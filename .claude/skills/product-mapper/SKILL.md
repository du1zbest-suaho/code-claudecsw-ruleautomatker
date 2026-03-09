# product-mapper 스킬

## 역할
사업방법서의 보험종목명과 세부보험종목을 판매중_상품구성정보.xlsx의 코드와 매핑한다.

## 데이터 구조
판매중_상품구성정보.xlsx 주요 컬럼:
- `UPPER_OBJECT_CODE`: 상위객체코드 (보험종류세코드+목코드, 예: 2258A01)
- `LOWER_OBJECT_CODE`: 하위객체코드 (상품세코드+목코드, 예: 2258001)
- `ISRN_KIND_DTCD`: 보험종류세코드
- `ISRN_KIND_ITCD`: 보험종류목코드
- `PROD_DTCD`: 상품세코드
- `PROD_ITCD`: 상품목코드
- `PROD_ADTO_DVSN_CODE`: 주/특약 구분 ('01'=주계약, '02'=특약)
- `SALE_NM`: 판매명

## 스크립트

### search_products.py
- **용도**: 보험종목명으로 상품구성정보 검색, 후보군 추출
- **STEP 2 시작 시 호출**

```bash
python .claude/skills/product-mapper/scripts/search_products.py \
  --subtypes output/extracted/{run_id}_subtypes.json \
  --db data/existing/판매중_상품구성정보.xlsx \
  --output output/extracted/{run_id}_candidates.json
```

### map_codes.py
- **용도**: LLM 매핑 결과를 받아 주계약(type=01) 코드 추출
- **LLM 판단 후 호출**

```bash
python .claude/skills/product-mapper/scripts/map_codes.py \
  --candidates output/extracted/{run_id}_candidates.json \
  --mapping '{"간편가입형(0년)": "2258A01_2258001"}' \
  --output output/extracted/{run_id}_mapping.json
```

### collect_special_contracts.py
- **용도**: 동일 UPPER_OBJECT_CODE의 특약(type=02) 전체 수집
- **map_codes.py 후 호출**

```bash
python .claude/skills/product-mapper/scripts/collect_special_contracts.py \
  --mapping output/extracted/{run_id}_mapping.json \
  --db data/existing/판매중_상품구성정보.xlsx \
  --output output/extracted/{run_id}_special_contracts.json
```

## LLM 판단 지침 (STEP 2)

search_products.py 결과로 후보군을 받은 후, LLM이 다음 기준으로 매핑:
1. 보험종목명 유사도 (퍼지 매칭)
2. 세부보험종목명 → SALE_NM의 특정 패턴 매칭
3. 판매일자 범위 확인

**매핑 불가 시**: 유사 후보 상위 3개를 제시하고 사용자에게 확인 요청

## 출력 형식

`{run_id}_mapping.json`:
```json
{
  "product_mappings": [
    {
      "sub_type": "간편가입형(0년)",
      "upper_object_code": "2258A01",
      "lower_object_code": "2258001",
      "isrn_kind_dtcd": "2258",
      "isrn_kind_itcd": "A01",
      "prod_dtcd": "2258",
      "prod_itcd": "001",
      "prod_type": "01",
      "sale_name": "한화생명 시그니처 H통합건강보험 무배당(납입면제형) 간편가입형(0년)"
    }
  ]
}
```

`{run_id}_special_contracts.json`:
```json
{
  "related_special_contracts": [
    {
      "upper_object_code": "2258A01",
      "lower_object_code": "2258901",
      "prod_type": "02",
      "sale_name": "..."
    }
  ]
}
```
