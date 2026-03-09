# pdf-preprocessor 스킬

## 역할
사업방법서 ZIP 파일을 해체하여 페이지별 텍스트/이미지를 추출하고, 관련 페이지를 식별하며, 보험종목명과 세부보험종목을 파싱한다.

## 입력 형식
사업방법서는 `.zip` 파일로 제공된다. ZIP 내부 구성:
- `manifest.json`: 페이지 목록 및 메타데이터
- `{n}.jpeg`: 각 페이지 이미지
- `{n}.txt`: 각 페이지 OCR 텍스트

## 스크립트

### extract_pdf.py
- **용도**: ZIP 해체, 페이지별 txt/jpeg 추출, 페이지 인덱스 JSON 생성
- **STEP 1 시작 시 호출**

```bash
python .claude/skills/pdf-preprocessor/scripts/extract_pdf.py \
  --input data/pdf/{파일명}.zip \
  --output output/extracted/ \
  --run-id {run_id}
```

**출력** (`output/extracted/{run_id}_pages.json`):
```json
{
  "run_id": "20260306_143022",
  "pdf_name": "한화생명_e암보험비갱신형_무배당_사업방법서_20260101.zip",
  "total_pages": 8,
  "pages": {
    "1": {
      "text_path": "output/extracted/20260306_143022_page_1.txt",
      "image_path": "output/extracted/20260306_143022_page_1.jpeg"
    }
  }
}
```

### scan_keywords.py
- **용도**: 키워드 기반 관련 페이지 식별
- **키워드**: `가입나이`, `보험기간`, `납입기간`, `납입주기`, `보기개시`, `피보험자 가입나이`
- **0건 시** `fallback_needed=true` 반환 → 메인 에이전트가 LLM 폴백 처리

```bash
python .claude/skills/pdf-preprocessor/scripts/scan_keywords.py \
  --input output/extracted/{run_id}_pages.json \
  --output output/extracted/{run_id}_keywords.json
```

**출력** (`{run_id}_keywords.json`):
```json
{
  "fallback_needed": false,
  "relevant_pages": {
    "가입나이_보기납기": [3, 4],
    "납입주기": [3],
    "보기개시나이": []
  }
}
```

### parse_sub_types.py
- **용도**: 1~3페이지에서 보험종목명 + 세부보험종목 목록 파싱
- **scan_keywords.py 후 실행**

```bash
python .claude/skills/pdf-preprocessor/scripts/parse_sub_types.py \
  --input output/extracted/{run_id}_pages.json \
  --output output/extracted/{run_id}_subtypes.json
```

**출력** (`{run_id}_subtypes.json`):
```json
{
  "product_name": "한화생명 e암보험(비갱신형) 무배당",
  "sub_types": ["표준체형", "비흡연체형"],
  "source_pages": [1, 2]
}
```

## 실패 처리
- `extract_pdf.py` 실패: ZIP 파일 형식 오류 → 에스컬레이션
- `scan_keywords.py` 0건: LLM 폴백 (전체 텍스트 제공하여 관련 페이지 판단 요청, 최대 1회). 실패 시 사용자에게 페이지 번호 질문
- `parse_sub_types.py` 실패: 수동 입력 요청
