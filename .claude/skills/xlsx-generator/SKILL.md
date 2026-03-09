# xlsx-generator 스킬

## 역할
검증 통과된 코드 변환 데이터를 업로드 양식 xlsx로 생성한다.

## 업로드 양식 구조
- **1~6행**: 헤더 (고정, 수정 금지)
- **7행부터**: 데이터 삽입
- **SET_ATTR_VAL_ID**: 빈 값 (시스템 자동 채번)
- **VALID_START_DATE**: PDF 파일명에서 파싱한 날짜
- **VALID_END_DATE**: `9999-12-31` (기본값)
- **SALE_CHNL_CODE**: 기존 데이터 패턴 반영 (`1,2,3,4,7`)

## 스크립트

### parse_valid_date.py
- **용도**: PDF 파일명 (`_YYYYMMDD.zip`) 에서 유효시작일 파싱
- **STEP 7 시작 시, generate_upload.py 전 실행**

```bash
python .claude/skills/xlsx-generator/scripts/parse_valid_date.py \
  --pdf-name 한화생명_e암보험비갱신형_무배당_사업방법서_20260101.zip \
  --output output/extracted/{run_id}_valid_date.json
```

**출력**:
```json
{"valid_start_date": "2026-01-01", "valid_end_date": "9999-12-31"}
```

파싱 불가 시: 에스컬레이션 (사용자에게 날짜 직접 입력 요청)

### generate_upload.py
- **용도**: 업로드 양식 xlsx 생성 (헤더 1~6행 보존, 7행부터 데이터)
- **parse_valid_date.py 완료 후 실행**

```bash
python .claude/skills/xlsx-generator/scripts/generate_upload.py \
  --input output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json \
  --template data/templates/{table_type}_업로드양식.xlsx \
  --valid-date output/extracted/{run_id}_valid_date.json \
  --product-mapping output/extracted/{run_id}_mapping.json \
  --output output/upload/{table_type}_{upper_obj}_{run_id}.xlsx
```

## 성공 기준
- xlsx가 정상 열림
- 6행까지 헤더 보존
- 코드값이 허용값에 포함
- 7행부터 데이터 존재
