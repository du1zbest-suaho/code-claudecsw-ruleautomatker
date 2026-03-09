# 보험 사업방법서 속성 추출 자동화 에이전트 — 통합 설계서

> **버전**: 1.2
> **목적**: Claude Code 기반 구현 시 참조하는 계획서
> **작성일**: 2026-03-06
> **개정이력**:
> - v1.1 (2026-03-06): 설계 재검토 — PDF 형식, 룰 인터페이스, MISSING 루프, 특약 흐름, 병렬처리, 코드맵 등 13개 이슈 보완
> - v1.2 (2026-03-06): 스킬 완전성 검토 — 신규 스킬 run-manager, 신규 스크립트 7개(parse_sub_types/collect_special_contracts/apply_special_contract_codes/check_combination_completeness/parse_valid_date/run_extraction_rules/init_run+manage_registry) 추가. 기존 4개 스크립트 역할 명세 보완

---

## 1. 작업 컨텍스트

### 1.1 배경 및 목적

한화생명 보험 상품의 사업방법서(PDF)에서 **가입 가능 연령**, **보험기간/납입기간**, **납입주기**, **보기개시나이** 정보를 자동 추출하여 시스템 업로드 양식(xlsx)에 맞게 변환하는 에이전트 시스템이다.

현재 이 작업은 사람이 사업방법서를 읽고 수작업으로 엑셀에 입력하고 있다. 이를 LLM 기반 추출 + 점진적 룰 고도화 방식으로 자동화한다.

### 1.2 범위

**포함**:
- 사업방법서 PDF에서 4종 테이블 데이터 추출 (S00022, S00026, S00027, S00028)
- 추출 룰의 자동 생성 및 점진적 고도화
- 기존 판매중 데이터와의 비교 검증
- 최종 업로드 양식(xlsx) 생성

**제외**:
- 사업방법서 자체의 생성/수정
- 업로드 이후의 시스템 연동
- S00006(보험종류_상품구조) 추출 (이미 존재하는 마스터 데이터)

### 1.3 입출력 정의

**입력**:

| 입력물 | 형식 | 설명 |
|--------|------|------|
| 사업방법서 | **.zip** (내부 구성: `manifest.json` + `{n}.jpeg` + `{n}.txt` per page) | 보험 상품별 사업방법서. 파일 확장자는 `.zip`이며 extract_pdf.py가 직접 zip으로 읽음. 각 페이지는 이미지(jpeg)와 OCR 텍스트(txt)로 구성. `manifest.json`에 페이지 목록 기재. |
| 판매중_상품구성정보 | xlsx | 상위/하위 객체코드, 보험종류코드, 상품코드, 주계약/특약 구분 등 |
| 판매중_가입나이정보 | xlsx | 기존 추출 완료된 가입나이 데이터 (Ground Truth) |
| 판매중_보기납기정보 | xlsx | 기존 추출 완료된 보기납기 데이터 (Ground Truth) |
| 판매중_납입주기정보 | xlsx | 기존 추출 완료된 납입주기 데이터 (Ground Truth) |
| 판매중_보기개시나이정보 | xlsx | 기존 추출 완료된 보기개시나이 데이터 (Ground Truth) |
| 업로드 양식 4종 | xlsx | S00022, S00026, S00027, S00028 업로드 템플릿 (헤더 6행 고정, 7행부터 데이터) |
| 모델상세 4종 | xlsx | 각 테이블의 컬럼 정의 (물리명, 논리명, 데이터유형) |

**출력**:

| 출력물 | 형식 | 설명 |
|--------|------|------|
| 추출 결과 엑셀 | xlsx (업로드 양식) | 4종 업로드 양식 그대로 출력. 1~6행 헤더 유지, 7행부터 데이터. 코드값 형식 준수 |
| 추출 룰 파일 | Python (.py) | 사용자가 수정 가능한 추출 로직 코드 |
| 검증 리포트 | JSON + 콘솔 로그 | 기존 데이터와의 비교 결과 (일치/불일치/누락) |
| 고도화 이력 로그 | JSON | 룰 변경 이력, 사유, 영향 범위 |

### 1.4 제약조건

- **Ground Truth**: 기존 DB(판매중_* 파일)가 정답. 사업방법서 해석이 불일치하면 DB 기준으로 룰을 수정
- **무영향 원칙**: 특정 상품을 위한 룰 변경이 다른 상품의 추출 정확도에 영향을 주면 안 됨
- **주계약 + 특약**: 둘 다 추출 대상. 단, 제공된 사업방법서에는 주계약 정보만 있으므로, 특약은 판매중_상품구성정보의 코드 매핑을 통해 주계약과 동일 조건 적용 여부를 판단
- **교차검증 필수**: PDF 내 txt(텍스트)와 jpeg(이미지)를 모두 활용하여 교차검증
- **실행환경**: Claude Code에서 개발 및 실행, 향후 독립 Python 스크립트로 전환 가능하도록 설계
- **사람 개입**: 룰 고도화 과정에서 사용자에게 의견 질의 가능. 불일치 건에 대해 에스컬레이션

### 1.5 용어 정의

| 용어 | 정의 |
|------|------|
| **보험종류** | 보험 상품의 대분류 (보험종류세코드 + 목코드로 식별, 예: 2258/A01) |
| **주계약** | PROD_ADTO_DVSN_CODE = '01'. 상품의 기본 계약 |
| **특약** | PROD_ADTO_DVSN_CODE = '02'. 주계약에 부가하는 선택 계약 |
| **상위객체코드** | UPPER_OBJECT_CODE. 보험종류세코드+목코드 조합 (예: 2258A01) |
| **하위객체코드** | LOWER_OBJECT_CODE. 상품세코드+목코드 조합 (예: 2258001) |
| **세트코드** | 추출 대상 테이블 식별자 (S00022, S00026, S00027, S00028) |
| **보기개시나이 (S00022)** | 보험기간 개시 나이. 주로 연금보험에서 연금 개시 나이를 의미 |
| **가입가능나이 (S00026)** | 가입 시 피보험자의 최소/최대 나이. 성별, 보험기간, 납입기간별로 상이 |
| **가입가능보기납기 (S00027)** | 보험기간 + 납입기간의 조합. 보험기간조회코드(예: X90, A999)와 납입기간조회코드(예: N10, N20) 쌍 |
| **가입가능납입주기 (S00028)** | 보험료 납입 주기 (월납=M1, 3월납=M3, 6월납=M6, 년납=M12, 일시납=M0) |
| **만기 코드 체계** | N=년만기, X=세만기(주피), A=종신, Z=세만기(자녀), V=세만기(피부양자), W=세만기(계약자), D=일만기, M=월만기 |
| **추출 룰** | PDF 텍스트에서 구조화된 데이터를 추출하는 파싱 로직 + 코드 변환 매핑 |
| **룰 고도화** | 검증 실패 건을 분석하여 룰을 수정하되, 기존 성공 건에 영향 없도록 점진적으로 개선하는 과정 |

---

## 2. 워크플로우 정의

### 2.1 전체 흐름 개요

```
┌─────────────────────────────────────────────────────────────────┐
│                    메인 워크플로우                                │
│                                                                 │
│  [사용자] ──▶ PDF 선택 + 테이블 선택                             │
│                    │                                            │
│                    ▼                                            │
│  ┌─────────────────────────────┐                                │
│  │ STEP 1. 문서 전처리         │ ◀── 스크립트                    │
│  │  PDF 해체, 텍스트/이미지 추출 │                                │
│  └──────────┬──────────────────┘                                │
│             │                                                   │
│             ▼                                                   │
│  ┌─────────────────────────────┐                                │
│  │ STEP 2. 상품 매핑           │ ◀── 스크립트 + LLM 판단         │
│  │  사업방법서 ↔ 상품구성정보    │                                │
│  └──────────┬──────────────────┘                                │
│             │                                                   │
│             ▼                                                   │
│  ┌─────────────────────────────┐                                │
│  │ STEP 3. 테이블 추출         │ ◀── LLM 핵심 (교차검증)         │
│  │  txt 파싱 + jpeg 해석       │                                │
│  └──────────┬──────────────────┘                                │
│             │                                                   │
│             ▼                                                   │
│  ┌─────────────────────────────┐                                │
│  │ STEP 4. 코드 변환           │ ◀── 스크립트 (결정론적)          │
│  │  자연어 → 시스템 코드        │                                │
│  └──────────┬──────────────────┘                                │
│             │                                                   │
│             ▼                                                   │
│  ┌─────────────────────────────┐                                │
│  │ STEP 5. 검증               │ ◀── 스크립트 + LLM 판단         │
│  │  기존 DB 대조 + 교차검증     │                                │
│  └──────────┬──────────────────┘                                │
│             │                                                   │
│        ┌────┴────┐                                              │
│        ▼         ▼                                              │
│   [PASS]    [FAIL]──▶ STEP 6. 룰 고도화                        │
│     │                   │   (LLM 분석 + 사람 확인)               │
│     ▼                   └──▶ STEP 3로 재실행                    │
│  STEP 7. 양식 생성                                              │
│  (업로드 xlsx 출력)                                              │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 단계별 상세 정의

---

#### STEP 1: 문서 전처리

**처리 주체**: 스크립트

**입력**: 사업방법서 PDF 파일 (1개 이상)

**처리 내용**:
0. **(사전)** run-manager 스킬의 `init_run.py`로 run_id 발급 — **모든 STEP보다 먼저 실행**
1. `extract_pdf.py`: PDF(zip) 해체 → manifest.json 파싱, 페이지별 txt/jpeg 파일 추출, 페이지 인덱스 JSON 출력
2. `scan_keywords.py`: 키워드 스캔으로 관련 페이지 식별: `가입나이`, `보험기간`, `납입기간`, `납입주기`, `보기개시`, `피보험자 가입나이`. 0건 시 `fallback_needed=true` 반환
3. `parse_sub_types.py`: [신규] 보험종목명 추출 (1~3페이지 "보험종목의 명칭" 섹션) + 세부보험종목 목록 추출 (간편가입형, 일반가입형 등)

**출력**:
```json
{
  "pdf_name": "한화생명_e암보험비갱신형_무배당_사업방법서_20260101.pdf",
  "product_name": "한화생명 e암보험(비갱신형) 무배당",
  "sub_types": ["표준체형", "비흡연체형"],
  "total_pages": 8,
  "relevant_pages": {
    "가입나이_보기납기": [3],
    "납입주기": [3],
    "보기개시나이": []
  },
  "page_texts": { "3": "...(전문)..." },
  "page_images": { "3": "/tmp/extracted/3.jpeg" }
}
```

**성공 기준**: 관련 페이지가 1개 이상 식별됨. 보험종목명이 추출됨.
**검증 방법**: 규칙 기반 — 키워드 매칭 결과 확인
**실패 시 처리**: 키워드 매칭 실패 → LLM에게 전체 텍스트를 주고 관련 페이지 판단 요청 (자동 재시도 1회). 그래도 실패 → 에스컬레이션 (사용자에게 관련 페이지 번호 질문)

---

#### STEP 2: 상품 매핑

**처리 주체**: 스크립트 + LLM 판단

**입력**: STEP 1 출력 + 판매중_상품구성정보.xlsx

**처리 내용**:
1. `search_products.py`: 사업방법서의 보험종목명으로 상품구성정보 검색, 후보군 추출
2. **LLM 판단**: 보험종목명과 세부보험종목이 상품구성정보의 어떤 행들과 매칭되는지 판단
   - 예: "시그니처 H통합건강보험 무배당(납입면제형)" → 보험종류 2258/*에 해당
   - 세부보험종목 "간편가입형(0년)" → 2258/A01 매핑
3. `map_codes.py`: 매핑된 주계약(type=01) 행에서 UPPER_OBJECT_CODE, LOWER_OBJECT_CODE, ISRN_KIND_DTCD, ISRN_KIND_ITCD, PROD_DTCD, PROD_ITCD 추출
4. `collect_special_contracts.py` [신규]: 동일 UPPER_OBJECT_CODE의 특약(type=02) 목록 수집 → `related_special_contracts` 생성

**출력**:
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
      "sale_name": "한화생명 시그니처 H통합건강보험 무배당(납입면제형) 간편가입형(0년) ..."
    }
  ],
  "related_special_contracts": []
}
```

**성공 기준**: 사업방법서의 모든 세부보험종목이 상품구성정보의 코드와 1:1 매핑됨
**검증 방법**: 규칙 기반 — 매핑 누락 건수 = 0
**실패 시 처리**: 매핑 불가 건 → 에스컬레이션 (사용자에게 코드 확인 질문). 유사 이름 후보가 있으면 LLM이 선택지를 제시하고 사용자에게 확인

---

#### STEP 3: 테이블 추출 (LLM 핵심 단계)

**처리 주체**: LLM (교차검증)

**입력**: STEP 1의 관련 페이지 텍스트 + 이미지, 추출 룰 파일 (있으면), 추출 대상 테이블 종류

**처리 내용**:

이 단계가 전체 시스템의 핵심이다. 두 가지 채널로 병행 추출하여 교차검증한다.

**(A) 텍스트 기반 추출 (1차)**:
1. 관련 페이지 텍스트를 LLM에게 제공
2. 추출 룰이 있으면 룰을 참조하여 구조화된 데이터 추출
3. 추출 룰이 없으면 (초기) LLM이 자체 판단으로 추출

**(B) 이미지 기반 추출 (2차)**:
1. 관련 페이지 이미지를 LLM에게 제공
2. 동일한 추출 지시로 구조화된 데이터 추출

**(C) 교차검증**:
1. (A)와 (B) 결과 비교
2. 일치 → 확정
3. 불일치 → 이미지 기반 결과를 우선 채택 (이미지가 원본에 가까움), 불일치 사유 로그 기록
4. 양쪽 모두 스키마 실패 시 → 에스컬레이션 (사용자에게 해당 페이지 번호 확인 요청)

**병렬 처리**: S00022, S00026, S00027, S00028 — 4개 테이블은 **독립적**이므로 메인 에이전트가 4개 table-extractor 서브에이전트를 동시 호출하여 병렬 처리한다. 단, S00026(가입나이)과 S00027(보기납기)은 동일 페이지를 참조하므로 페이지 로드는 공유 가능.

**Two-Phase 이미지 전략 (비용 최적화)**:
- 텍스트 추출 결과의 confidence가 "high"이고 스키마 검증 통과 시 → 이미지 추출 스킵 (비용 절감)
- confidence가 "medium" 이하이거나 스키마 검증 실패 시 → 이미지 추출 실행
- 이미지 추출 여부는 `image_used: true/false`로 결과 JSON에 기록

**추출 대상별 LLM 프롬프트 핵심**:

**S00026 (가입가능나이)**: "이 사업방법서에서 보험기간별, 납입기간별, 성별 가입 가능 나이 범위를 추출하세요. 세부보험종목(간편가입형/일반가입형/건강가입형 등)별로 다르면 각각 분리하세요."

**S00027 (가입가능보기납기)**: "보험기간과 납입기간의 가능한 조합을 모두 추출하세요. 예: 90세만기+10년납, 90세만기+15년납, 종신+10년납 등"

**S00028 (가입가능납입주기)**: "보험료 납입주기를 추출하세요. 보통 '보험료 납입주기: 월납'과 같이 한 줄로 표현됨"

**S00022 (보기개시나이)**: "연금개시나이 등 보기개시나이 관련 정보를 추출하세요. 해당사항 없으면 '없음'으로 표시"

**출력** (중간 구조):
```json
{
  "table_type": "S00026",
  "source": "cross_verified",
  "confidence": "high",
  "raw_data": [
    {
      "sub_type": "간편가입형(0년)",
      "insurance_period": "90세만기",
      "payment_period": "10년납",
      "gender": "남자",
      "min_age": 15,
      "max_age": 79,
      "text_source": { "min_age": 15, "max_age": 79 },
      "image_source": { "min_age": 15, "max_age": 79 },
      "match": true
    }
  ],
  "discrepancies": []
}
```

**성공 기준**: (A)와 (B)의 일치율 95% 이상. 핵심 수치(나이, 기간)에 불일치 없음.
**검증 방법**: 스키마 검증 (필수 필드 존재, 숫자 범위 합리성) + LLM 자기검증 (추출 결과의 일관성 확인)
**실패 시 처리**: 교차검증 불일치 → 이미지 우선 채택 + 불일치 로그. 스키마 검증 실패 → 자동 재시도 (프롬프트에 실패 사유 포함, 최대 2회). 재시도 실패 → 에스컬레이션

---

#### STEP 4: 코드 변환

**처리 주체**: 스크립트 (결정론적)

**입력**: STEP 3의 raw_data + 업로드 양식의 6행 코드 정의

**처리 내용**:

자연어 표현을 시스템 코드값으로 변환하는 결정론적 매핑이다.

**주요 변환 규칙**:

| 자연어 | 코드 | 분류 |
|--------|------|------|
| 90세만기 | ISRN_TERM=90, ISRN_TERM_DVSN_CODE=X, ISRN_TERM_INQY_CODE=X90 | 보험기간 |
| 100세만기 | ISRN_TERM=100, ISRN_TERM_DVSN_CODE=X, ISRN_TERM_INQY_CODE=X100 | 보험기간 |
| 종신 | ISRN_TERM=999, ISRN_TERM_DVSN_CODE=A, ISRN_TERM_INQY_CODE=A999 | 보험기간 |
| 20년만기 | ISRN_TERM=20, ISRN_TERM_DVSN_CODE=N, ISRN_TERM_INQY_CODE=N20 | 보험기간 |
| N세만기(자녀) | ISRN_TERM=N, ISRN_TERM_DVSN_CODE=Z, ISRN_TERM_INQY_CODE=Z{N} | 보험기간 |
| N세만기(피부양자) | ISRN_TERM=N, ISRN_TERM_DVSN_CODE=V, ISRN_TERM_INQY_CODE=V{N} | 보험기간 |
| N세만기(계약자) | ISRN_TERM=N, ISRN_TERM_DVSN_CODE=W, ISRN_TERM_INQY_CODE=W{N} | 보험기간 |
| N일만기 | ISRN_TERM=N, ISRN_TERM_DVSN_CODE=D, ISRN_TERM_INQY_CODE=D{N} | 보험기간 |
| N월만기 | ISRN_TERM=N, ISRN_TERM_DVSN_CODE=M, ISRN_TERM_INQY_CODE=M{N} | 보험기간 |
| 10년납 | PAYM_TERM=10, PAYM_TERM_DVSN_CODE=N, PAYM_TERM_INQY_CODE=N10 | 납입기간 |
| 전기납 | PAYM_TERM=보험기간과 동일, PAYM_TERM_DVSN_CODE=보험기간과 동일 | 납입기간 |
| 월납 | PAYM_CYCL_VAL=1, PAYM_CYCL_DVSN_CODE=M, PAYM_CYCL_INQY_CODE=M1 | 납입주기 |
| 3월납 | PAYM_CYCL_VAL=3, PAYM_CYCL_DVSN_CODE=M, PAYM_CYCL_INQY_CODE=M3 | 납입주기 |
| 6월납 | PAYM_CYCL_VAL=6, PAYM_CYCL_DVSN_CODE=M, PAYM_CYCL_INQY_CODE=M6 | 납입주기 |
| 년납 | PAYM_CYCL_VAL=12, PAYM_CYCL_DVSN_CODE=M, PAYM_CYCL_INQY_CODE=M12 | 납입주기 |
| 일시납 | PAYM_CYCL_VAL=0, PAYM_CYCL_DVSN_CODE=M, PAYM_CYCL_INQY_CODE=M0 | 납입주기 |
| 남자 | MINU_GNDR_CODE=1 | 성별 |
| 여자 | MINU_GNDR_CODE=2 | 성별 |
| 만15세~79세 | MIN_AG=15, MAX_AG=79 | 나이 |
| 판매채널 전체 | SALE_CHNL_CODE=1,2,3,4,7 (기본) | 채널 |

**"전기납" 특수 처리 로직**:
- 보험기간이 N(년만기)이면: 납입기간 = 보험기간값, 구분코드 = N
- 보험기간이 X(세만기)이면: 납입기간 = 보험기간값, 구분코드 = X
- 보험기간이 A(종신)이면: 납입기간 = 999, 구분코드 = A

**출력**: 업로드 양식 스키마에 맞는 코드 변환된 행 데이터 (리스트)

**코드맵 동기화**: `code_mappings.json`은 업로드 양식 6행의 허용 코드 목록과 항상 동기화되어야 한다. 프로젝트 초기화 시 `init_code_mappings.py`를 실행하여 업로드 양식 4종의 6행에서 자동 생성한다. 양식이 변경될 때마다 재실행 필요.

**특약 처리 — `apply_special_contract_codes.py` [신규]** (`convert_codes.py` 완료 후 실행):
1. STEP 2에서 수집한 `related_special_contracts` 목록 참조
2. 각 특약(PROD_ADTO_DVSN_CODE='02')에 대해 동일 보험종류(UPPER_OBJECT_CODE)의 주계약 코드 변환 결과를 복사
3. 특약의 UPPER_OBJECT_CODE, LOWER_OBJECT_CODE로 교체하여 행 생성
4. 예외: 사업방법서에 특약 전용 가입조건이 별도 기재된 경우 해당 내용 우선 적용 (LLM이 STEP 3에서 특약 섹션을 식별했을 경우)
5. 특약 처리 결과는 주계약 결과와 합산하여 STEP 5 검증 진행

**성공 기준**: 모든 자연어 표현이 코드로 변환됨. 변환 불가 항목 0건.
**검증 방법**: 규칙 기반 — 코드값이 업로드 양식 6행의 허용 코드에 포함되는지 체크
**실패 시 처리**: 변환 불가 항목 → 로그 + 에스컬레이션 (사용자에게 코드 매핑 확인). 자동 재시도 없음 (결정론적 실패이므로 룰 수정 필요)

---

#### STEP 5: 검증

**처리 주체**: 스크립트 + LLM 판단

**입력**: STEP 4 출력 + 기존 판매중_* 데이터

**처리 내용**:

**(A) 기존 데이터 대조 — `compare_with_db.py`**:
1. 동일 상품코드(UPPER_OBJECT_CODE + LOWER_OBJECT_CODE)로 기존 데이터 검색
2. 행 단위 비교: 핵심 필드(나이범위, 기간코드, 주기코드)의 일치 여부
3. 결과 분류:
   - **MATCH**: 기존 데이터와 완전 일치
   - **MISMATCH**: 기존 데이터와 값이 다름
   - **NEW**: 기존 데이터에 없는 행 (신규 상품이면 정상)
   - **MISSING**: 기존 데이터에 있으나 추출에서 누락된 행

**(B) 정합성 검증 — `check_integrity.py`**:
1. 나이 범위 합리성: min_age < max_age, 0 ≤ age ≤ 120
2. 기간 합리성: 납입기간 ≤ 보험기간
3. 코드 존재 여부: 생성된 코드가 업로드 양식 6행의 허용값에 포함

**(C) 불일치 분석 — LLM**:
- MISMATCH 건에 대해 LLM이 원인 분석
- "기존 DB가 정답"이므로 추출 룰의 어디서 오류가 발생했는지 판단

**출력**:
```json
{
  "summary": {
    "total_rows": 48,
    "match": 45,
    "mismatch": 2,
    "new": 1,
    "missing": 0
  },
  "mismatches": [
    {
      "product": "2258A01",
      "field": "MAX_AG",
      "extracted": 80,
      "existing": 79,
      "analysis": "텍스트에서 '79세 80세' 구간 파싱 오류. 90세만기의 남자 30년납에서 발생."
    }
  ],
  "pass": false,
  "fail_reason": "2건 불일치"
}
```

**(D) 조합 완전성 검증 — `check_combination_completeness.py` [신규, S00026 전용]**:
- 신규 상품은 기존 DB 비교 불가이므로, 추출된 보험기간 목록 × 납입기간 목록 × 성별(남/여)의 카테시안 곱 행 수와 실제 추출 행 수를 비교
- 부족 조합(누락 예상 건) 탐지 시 해당 조합을 힌트로 STEP 3 재실행

**성공 기준**: MISMATCH = 0, MISSING = 0
**검증 방법**: 규칙 기반 (위 기준 자동 판정)
**실패 시 처리**: MISMATCH > 0 → STEP 6(룰 고도화)로 진행. MISSING > 0 → STEP 3 재실행 (누락 항목 힌트 포함, **최대 2회**). 2회 재실행 후에도 MISSING > 0 → 에스컬레이션 (사용자에게 누락 건 확인). NEW > 0 → 정상 (신규 상품), 로그만 기록

---

#### STEP 6: 룰 고도화

**처리 주체**: LLM + 사용자 확인

**입력**: STEP 5의 불일치 분석 결과 + 현재 추출 룰 + 원본 텍스트/이미지

**처리 내용**:

1. **LLM 분석**: 불일치 원인 파악
   - 텍스트 파싱 오류 (공백 누락 등)
   - 테이블 구조 미인식 (새로운 포맷)
   - 코드 변환 규칙 누락
   - 특수 조건 미처리 (예: "전기납"의 의미가 상품마다 다름)

2. **룰 수정안 생성**: LLM이 수정안을 제안
   - 수정 범위: 해당 상품에만 적용되는 예외 룰 vs 범용 룰 수정
   - **무영향 검증**: 수정된 룰로 이전에 성공했던 모든 상품을 재검증
   - 영향이 있으면 → 예외 룰로 분리

3. **사용자 확인 (AskUserQuestionTool)**:
   - 불일치 원인이 모호하면 사용자에게 질문
   - "이 상품의 30년납 남자 가입최고나이가 기존 DB에서 79세인데, 사업방법서에는 '59세 59세79세 80세'로 되어 있습니다. 이 텍스트에서 남자=59세, 여자=79세로 읽는 것이 맞는지 확인해주세요."

4. **룰 파일 업데이트**: Python 코드로 추출 룰 수정

**출력**: 업데이트된 추출 룰 파일 + 고도화 이력 로그

**분기 조건**:
- 룰 수정 후 STEP 3~5 재실행
- 재실행 후에도 실패 → 사용자에게 수동 입력 요청 (해당 행만)
- 최대 고도화 반복: 3회 (3회 초과 시 에스컬레이션)

**성공 기준**: 수정된 룰로 해당 상품 + 기존 모든 성공 상품의 MISMATCH = 0
**검증 방법**: 전체 회귀 테스트 (기존 성공 상품 전부 재검증)
**실패 시 처리**: 3회 반복 후에도 실패 → 사용자에게 해당 건 수동 처리 요청 + 로그 기록

---

#### STEP 7: 양식 생성

**처리 주체**: 스크립트

**입력**: 검증 통과된 코드 변환 데이터 + 업로드 양식 템플릿

**처리 내용**:
1. `parse_valid_date.py` [신규]: PDF 파일명(`_YYYYMMDD.zip`) 파싱 → VALID_START_DATE 결정. 파싱 불가 시 에스컬레이션 (사용자에게 날짜 입력 요청). VALID_END_DATE = 기본 `9999-12-31`
2. `generate_upload.py`: 업로드 양식 xlsx 복사 (1~6행 헤더 유지)
3. 7행부터 데이터 삽입
4. SET_ATTR_VAL_ID는 빈 값 (시스템 자동 채번)
5. VALID_START_DATE, VALID_END_DATE: `parse_valid_date.py` 결과 사용
6. SALE_CHNL_CODE에 기존 데이터의 패턴 반영 (기본: "1,2,3,4,7")

**출력**: 4종 업로드 양식 xlsx 파일

**성공 기준**: xlsx가 정상 열림. 6행까지 헤더 보존. 코드값이 6행 허용값에 포함.
**검증 방법**: 스키마 검증 — openpyxl로 열어서 헤더 무결성 + 코드값 유효성 확인
**실패 시 처리**: 자동 재시도 1회 (파일 I/O 오류 가능성). 재시도 실패 → 에스컬레이션

---

### 2.3 LLM 판단 영역 vs 코드 처리 영역 요약

| 단계 | LLM 판단 | 스크립트 처리 |
|------|---------|-------------|
| **시작 전** | 없음 | `init_run.py` — run_id 발급 |
| STEP 1. 전처리 | 관련 페이지 판단 (폴백, scan_keywords 실패 시) | `extract_pdf.py`, `scan_keywords.py`, `parse_sub_types.py` [신규] |
| STEP 2. 상품매핑 | 보험종목명 ↔ 코드 매칭 판단 | `search_products.py`, `map_codes.py`, `collect_special_contracts.py` [신규] |
| STEP 3. 테이블추출 | **핵심**: 텍스트/이미지에서 데이터 추출 (룰 없을 때). 병렬 4건 동시 처리 | **룰 있을 때**: `run_extraction_rules.py` [신규] 실행 |
| STEP 4. 코드변환 | 없음 (결정론적) | `convert_codes.py`, `apply_special_contract_codes.py` [신규], `validate_codes.py` |
| STEP 5. 검증 | 불일치 원인 분석 | `compare_with_db.py`, `check_integrity.py`, `check_combination_completeness.py` [신규] |
| STEP 6. 룰고도화 | 원인 분석 + 수정안 생성 + 사용자 질의 | `regression_test.py`, `manage_registry.py` |
| STEP 7. 양식생성 | 없음 | `parse_valid_date.py` [신규], `generate_upload.py` |
| **완료 후** | 없음 | `manage_registry.py` — 성공 run 등록 |

---

## 3. 구현 스펙

### 3.1 폴더 구조

```
/project-root
├── CLAUDE.md                              # 메인 오케스트레이터 지침
├── /.claude
│   ├── /skills
│   │   ├── /run-manager                   # [신규] 실행 컨텍스트 관리 스킬
│   │   │   ├── SKILL.md
│   │   │   └── /scripts
│   │   │       ├── init_run.py            # run_id 발급 + 세션 디렉토리 생성
│   │   │       └── manage_registry.py     # 성공 run 등록/조회, 회귀셋 기준 run_id 관리
│   │   │
│   │   ├── /pdf-preprocessor
│   │   │   ├── SKILL.md                   # PDF 전처리 스킬 지침
│   │   │   └── /scripts
│   │   │       ├── extract_pdf.py         # zip 해체 + 페이지별 텍스트/이미지 파일 추출 + 인덱스 JSON 출력
│   │   │       ├── scan_keywords.py       # 키워드 기반 관련 페이지 식별. 미발견 시 fallback_needed=true 반환
│   │   │       └── parse_sub_types.py     # [신규] 보험종목명 + 세부보험종목 목록 파싱 (1~3페이지)
│   │   │
│   │   ├── /product-mapper
│   │   │   ├── SKILL.md                   # 상품 매핑 스킬 지침
│   │   │   └── /scripts
│   │   │       ├── search_products.py     # 보험종목명으로 상품구성정보 검색, 후보군 추출
│   │   │       ├── map_codes.py           # 주계약(type=01) 코드(UPPER/LOWER_OBJECT_CODE 등) 추출
│   │   │       └── collect_special_contracts.py  # [신규] 동일 UPPER_OBJECT_CODE의 특약(type=02) 전체 수집
│   │   │
│   │   ├── /code-converter
│   │   │   ├── SKILL.md                   # 코드 변환 스킬 지침
│   │   │   ├── /scripts
│   │   │   │   ├── convert_codes.py               # 자연어→시스템코드 변환 (보험기간, 납입기간, 주기, 성별, 나이)
│   │   │   │   ├── apply_special_contract_codes.py # [신규] 주계약 결과 복사 + 특약 OBJECT_CODE로 교체
│   │   │   │   ├── validate_codes.py              # 변환된 코드의 허용값 체크
│   │   │   │   └── init_code_mappings.py          # 업로드 양식 6행→code_mappings.json 자동 생성 (초기화 전용)
│   │   │   └── /references
│   │   │       └── code_mappings.json     # 코드 변환 매핑 사전 (init_code_mappings.py로 생성)
│   │   │
│   │   ├── /validator
│   │   │   ├── SKILL.md                   # 검증 스킬 지침
│   │   │   └── /scripts
│   │   │       ├── compare_with_db.py               # 기존 판매중 데이터와 행 단위 비교
│   │   │       ├── check_integrity.py               # 나이범위, 기간 관계 정합성 체크
│   │   │       ├── check_combination_completeness.py # [신규] S00026 전용: 보험기간×납입기간×성별 카테시안 곱 vs 추출 행 수
│   │   │       └── regression_test.py               # 룰 변경 후 전체 상품 재검증 (run_registry.json 참조)
│   │   │
│   │   └── /xlsx-generator
│   │       ├── SKILL.md                   # 양식 생성 스킬 지침
│   │       └── /scripts
│   │           ├── parse_valid_date.py    # [신규] PDF 파일명에서 유효시작일 파싱. 불가 시 에스컬레이션
│   │           └── generate_upload.py     # 업로드 양식 xlsx 생성 (parse_valid_date.py 완료 후 실행)
│   │
│   └── /agents
│       ├── /table-extractor
│       │   ├── AGENT.md                   # 테이블 추출 서브에이전트 지침
│       │   └── /scripts
│       │       └── run_extraction_rules.py # [신규] ExtractionRules 인스턴스화 + 테이블별 메서드 실행
│       │                                  # 룰 파일 존재 시 사용. 없으면 LLM 자체 판단
│       │
│       └── /rule-optimizer
│           └── AGENT.md                   # 룰 고도화 서브에이전트 지침
│                                          # (ExtractionRules 메서드 내부 로직만 수정 가능, 시그니처 불변)
│
├── /data
│   ├── /pdf                               # 사업방법서 zip 원본
│   ├── /existing                          # 판매중_* 기존 데이터
│   ├── /templates                         # 업로드 양식 템플릿 (S00022~S00028)
│   └── /models                            # 모델상세 파일
│
├── /output
│   ├── /extracted                         # 추출 중간 결과 (JSON, 회귀 테스트 셋으로 보관)
│   ├── /upload                            # 최종 업로드 양식 (xlsx)
│   ├── /reports                           # 검증 리포트
│   └── /logs
│       └── run_registry.json              # [신규] 성공 run 목록 + 회귀셋 기준 run_id
│
├── /rules
│   ├── extraction_rules.py                # 추출 룰 (사용자 수정 가능, ExtractionRules 클래스)
│   ├── rule_history.json                  # 룰 변경 이력
│   └── product_exceptions.json            # 상품별 예외 룰
│
└── /docs
    └── code_reference.md                  # 코드 체계 참조 문서
```

### 3.2 CLAUDE.md 핵심 섹션 목록

1. **프로젝트 개요**: 시스템 목적, 핵심 원칙 (Ground Truth = 기존 DB, 무영향 원칙)
2. **워크플로우 요약**: 7단계 흐름 간략 설명 + 분기 조건
3. **실행 컨텍스트 관리**: 워크플로우 시작 시 run-manager 스킬의 `init_run.py`로 run_id 발급. run_id는 모든 스크립트 호출 시 `--run-id` 인자로 전달. 성공 완료 시 `manage_registry.py`로 run 등록.
4. **서브에이전트 호출 규칙**: table-extractor, rule-optimizer 호출 시점과 입출력
5. **스킬 호출 규칙**: 각 스킬의 트리거 조건
6. **사용자 인터랙션 규칙**: AskUserQuestionTool 사용 시점 (에스컬레이션, 룰 고도화 확인)
7. **파일 경로 규약**: 입출력 디렉토리 규칙 + run_id 포함 파일명 패턴
8. **코드 체계 참조**: 핵심 코드 변환 규칙 요약 (상세는 code_reference.md)

### 3.3 에이전트 구조

**메인 에이전트 (CLAUDE.md)** = 오케스트레이터
- 사용자로부터 PDF 선택 + 테이블 선택을 받음
- STEP 1, 2, 4, 5, 7은 스킬의 스크립트를 직접 호출
- STEP 3은 table-extractor 서브에이전트에 위임
- STEP 6은 rule-optimizer 서브에이전트에 위임

**서브에이전트 분리 근거**:
- **table-extractor**: STEP 3의 프롬프트가 테이블 종류(S00022~S00028)별로 매우 다르고, 교차검증 로직이 복잡하여 별도 컨텍스트로 분리
- **rule-optimizer**: STEP 6은 불일치 분석 + 룰 수정 + 회귀 테스트라는 독립적 작업 블록이며, 추출 룰 파일 전체와 고도화 이력을 컨텍스트로 필요로 함

### 3.4 스킬/스크립트 파일 목록

> **[신규]** 표시는 v1.2에서 추가된 항목. 신규 스킬 1개(run-manager) + 신규 스크립트 7개.

| 스킬 | 스크립트 | 역할 | 트리거 |
|------|---------|------|--------|
| **run-manager** [신규] | init_run.py | run_id(`YYYYMMDD_HHMMSS`) 발급, 세션 출력 디렉토리 생성 | **워크플로우 시작 직전** |
| **run-manager** [신규] | manage_registry.py | `run_registry.json` 성공 run 등록/조회, 회귀 테스트 기준 run_id 제공 | STEP 5 PASS 시 / STEP 6 회귀 테스트 전 |
| pdf-preprocessor | extract_pdf.py | zip 해체, 페이지별 텍스트/이미지 파일 추출, 페이지 인덱스 JSON 출력 (종목명 파싱 제외) | STEP 1 시작 시 |
| pdf-preprocessor | scan_keywords.py | 키워드 기반 관련 페이지 식별. 0건 시 `fallback_needed=true` 반환, LLM 폴백은 메인 에이전트 처리 | STEP 1 내부 |
| pdf-preprocessor [신규] | parse_sub_types.py | 보험종목명 + 세부보험종목 목록 파싱 (1~3페이지, 정규식) | STEP 1 내부, scan_keywords.py 후 |
| product-mapper | search_products.py | 보험종목명으로 상품구성정보 검색, 후보군 추출 | STEP 2 시작 시 |
| product-mapper | map_codes.py | 주계약(type=01) UPPER/LOWER_OBJECT_CODE 등 코드 추출 (특약 수집 제외) | STEP 2에서 LLM 매칭 후 |
| product-mapper [신규] | collect_special_contracts.py | 동일 UPPER_OBJECT_CODE의 특약(type=02) 전체 수집 → `related_special_contracts` | STEP 2 내부, map_codes.py 후 |
| code-converter | convert_codes.py | 자연어 표현→시스템코드 변환 (보험기간, 납입기간, 주기, 성별, 나이) | STEP 4 시작 시 |
| code-converter [신규] | apply_special_contract_codes.py | 주계약 코드 변환 결과 복사 + 특약 OBJECT_CODE로 교체 | STEP 4 내부, convert_codes.py 후 |
| code-converter | validate_codes.py | 변환된 코드의 code_mappings.json 허용값 체크 | STEP 4 완료 후 |
| code-converter | init_code_mappings.py | 업로드 양식 4종 6행→code_mappings.json 자동 생성 (초기화 전용) | 프로젝트 초기화 시 (1회) |
| validator | compare_with_db.py | 기존 판매중 데이터와 행 단위 비교 (MATCH/MISMATCH/NEW/MISSING 분류) | STEP 5 시작 시 |
| validator | check_integrity.py | 나이범위(min<max, 0~120), 납입기간≤보험기간 정합성 체크 | STEP 5 내부 |
| validator [신규] | check_combination_completeness.py | S00026 전용: 보험기간×납입기간×성별 카테시안 곱 vs 추출 행 수, 누락 조합 반환 | STEP 5 내부, compare_with_db.py 후 (S00026만) |
| validator | regression_test.py | 룰 변경 후 전체 상품 재검증. `manage_registry.py`로 기준 run_id 조회 후 비교 | STEP 6 룰 수정 후 |
| xlsx-generator [신규] | parse_valid_date.py | PDF 파일명(`_YYYYMMDD.zip`)에서 유효시작일 파싱. 불가 시 에스컬레이션 | STEP 7 시작 시 (generate_upload.py 전) |
| xlsx-generator | generate_upload.py | 업로드 양식 xlsx 생성 | STEP 7 내부, parse_valid_date.py 후 |

### 3.5 서브에이전트 상세

#### table-extractor

| 항목 | 내용 |
|------|------|
| **이름** | table-extractor |
| **역할** | 사업방법서 페이지에서 구조화된 테이블 데이터 추출 |
| **트리거** | 메인 에이전트가 STEP 3 진입 시 병렬 호출 (4종 테이블 동시) |
| **입력** | 관련 페이지 텍스트, 관련 페이지 이미지 경로, 추출 대상 테이블 종류(S00022/S00026/S00027/S00028), run_id, 세부보험종목 목록 |
| **출력** | `/output/extracted/{upper_obj}_{table_type}_{run_id}.json` — 교차검증된 추출 결과 |
| **룰 실행 방식** | `extraction_rules.py` 존재 시 → `run_extraction_rules.py --table-type {type} --product-code {code} --input {text_file} --output {json}`로 스크립트 실행. 미존재 시 → LLM 자체 판단으로 추출 |
| **참조 스크립트** | `run_extraction_rules.py` (룰 있을 때). LLM 폴백 시 스크립트 없음 |
| **데이터 전달** | 파일 기반 (JSON) |

#### rule-optimizer

| 항목 | 내용 |
|------|------|
| **이름** | rule-optimizer |
| **역할** | 추출 불일치 원인 분석, 룰 수정, 회귀 테스트, 사용자 질의 |
| **트리거** | 메인 에이전트가 STEP 5에서 MISMATCH > 0일 때 호출 |
| **입력** | 불일치 리포트 JSON, 현재 추출 룰 파일, 원본 텍스트/이미지, 기존 DB의 정답 데이터 |
| **출력** | 수정된 `/rules/extraction_rules.py`, `/rules/rule_history.json` 업데이트, 회귀 테스트 결과 |
| **수정 가능 범위** | `ExtractionRules` 클래스의 메서드 **내부 로직만** 수정 가능. 메서드 시그니처·클래스 구조 변경 금지 (3.8절 인터페이스 준수) |
| **수정 후 검증** | `run_extraction_rules.py`로 수정된 룰을 현재 상품에 적용 후 결과 확인 → 이후 regression_test.py로 전체 회귀 테스트 |
| **참조 스킬** | validator (regression_test.py), run-manager (manage_registry.py) |
| **데이터 전달** | 파일 기반 (Python 파일 + JSON) |
| **사용자 질의** | 불일치 원인이 모호할 때 AskUserQuestionTool 사용 |

### 3.6 주요 산출물 파일 형식 및 명명 규칙

**파일명 규칙**: 동일 상품 재실행 시 덮어쓰기 방지를 위해 실행 ID(`{YYYYMMDD_HHMMSS}`)를 포함한다.

| 산출물 | 형식 | 파일명 패턴 | 위치 |
|--------|------|------------|------|
| 추출 중간 결과 (STEP 3) | JSON | `{upper_obj}_{table_type}_{run_id}.json` | `/output/extracted/` |
| 코드 변환 결과 (STEP 4) | JSON | `{upper_obj}_{table_type}_{run_id}_coded.json` | `/output/extracted/` |
| 검증 리포트 (STEP 5) | JSON | `{upper_obj}_{table_type}_{run_id}_report.json` | `/output/reports/` |
| 최종 업로드 양식 (STEP 7) | xlsx (업로드 템플릿 기반) | `{table_type}_{upper_obj}_{run_id}.xlsx` | `/output/upload/` |
| 고도화 이력 | JSON | `rule_history.json` (누적 append) | `/output/logs/` |
| **실행 레지스트리** [신규] | **JSON** | **`run_registry.json` (누적 append)** | **`/output/logs/`** |
| 추출 룰 | Python | `extraction_rules.py` (버전 관리) | `/rules/` |
| 상품별 예외 룰 | JSON | `product_exceptions.json` | `/rules/` |
| 코드 매핑 사전 | JSON | `code_mappings.json` | `/.claude/skills/code-converter/references/` |

> **주의**: `/output/extracted/`의 성공 건 JSON 파일은 회귀 테스트 셋으로 사용되므로 삭제 금지. 가장 최근 성공 실행 결과가 기준이 된다.

### 3.7 데이터 전달 패턴

- **STEP 간 전달**: 모두 파일 기반 (`/output/extracted/`에 JSON 저장, 파일 경로만 전달)
- **서브에이전트 호출**: 입력 파일 경로를 프롬프트에 명시
- **스크립트 호출**: CLI 인자로 파일 경로 전달 (예: `python scripts/convert_codes.py --input /output/extracted/step3.json --output /output/extracted/step4.json`)

---

### 3.8 ExtractionRules 인터페이스 명세

`/rules/extraction_rules.py`는 사용자가 직접 수정 가능한 Python 모듈이다. 메인 에이전트와 스크립트가 공통으로 사용하는 인터페이스를 아래와 같이 정의한다.

```python
from typing import List, Dict, Optional

class ExtractionRules:
    """
    사업방법서에서 구조화된 데이터를 추출하는 룰 모음.
    메서드 이름과 시그니처는 변경 금지. 내부 로직만 수정 가능.
    """

    def __init__(self, exceptions_path: str = "/rules/product_exceptions.json"):
        """product_exceptions.json 로드"""
        ...

    def extract_age_table(self, text: str, product_code: str) -> List[Dict]:
        """
        S00026 (가입가능나이) 추출.
        반환: [{"sub_type": str, "insurance_period": str, "payment_period": str,
                "gender": str, "min_age": int, "max_age": int}, ...]
        """
        ...

    def extract_period_table(self, text: str, product_code: str) -> List[Dict]:
        """
        S00027 (가입가능보기납기) 추출.
        반환: [{"sub_type": str, "insurance_period": str, "payment_period": str}, ...]
        """
        ...

    def extract_payment_cycle(self, text: str, product_code: str) -> List[Dict]:
        """
        S00028 (가입가능납입주기) 추출.
        반환: [{"sub_type": str, "payment_cycle": str}, ...]
        """
        ...

    def extract_benefit_start_age(self, text: str, product_code: str) -> List[Dict]:
        """
        S00022 (보기개시나이) 추출. 해당사항 없으면 빈 리스트 반환.
        반환: [{"sub_type": str, "min_age": int, "max_age": int}, ...]
        """
        ...
```

> **rule-optimizer 서브에이전트**가 위 인터페이스를 준수하며 메서드 내부 로직을 수정한다. 시그니처 변경은 금지.

### run_extraction_rules.py 연결 명세

table-extractor 서브에이전트가 `extraction_rules.py`가 존재할 때 사용하는 실행 스크립트.

```
# 호출 방식 (table-extractor AGENT.md에서 실행)
python /.claude/agents/table-extractor/scripts/run_extraction_rules.py \
  --table-type S00026 \
  --product-code 2258A01 \
  --input /output/extracted/page_text.txt \
  --rules /rules/extraction_rules.py \
  --output /output/extracted/2258A01_S00026_{run_id}.json

# 처리 흐름
# 1. extraction_rules.py의 ExtractionRules 클래스 import
# 2. 테이블 타입에 맞는 메서드 호출
#    S00026 → extract_age_table(text, product_code)
#    S00027 → extract_period_table(text, product_code)
#    S00028 → extract_payment_cycle(text, product_code)
#    S00022 → extract_benefit_start_age(text, product_code)
# 3. 결과를 JSON으로 출력
```

> **판단 기준**: extraction_rules.py가 없으면 이 스크립트를 호출하지 않고 LLM이 직접 추출한다. 있으면 스크립트 실행 결과를 사용하고, 스크립트 오류 시 LLM으로 폴백한다.

---

## 4. 점진적 고도화 프로세스 상세

### 4.1 초기 룰 생성 (콜드 스타트)

첫 실행 시에는 추출 룰이 없다. 다음 순서로 초기 룰을 생성한다:

1. **초기화**: `init_code_mappings.py` 실행 → 업로드 양식 4종 6행에서 `code_mappings.json` 자동 생성
2. **샘플 선정**: 사용자가 2~3개 사업방법서를 선택 (구조가 다른 것으로 추천)
   - 추천: e암보험(단순 매트릭스) + H통합건강보험(복잡 매트릭스) + Wealth단체저축(서술형)
3. **1차 추출**: `extraction_rules.py` 없이 LLM(table-extractor)이 자체 판단으로 추출
4. **기존 데이터 대조**: 판매중_* 데이터와 비교
5. **초기 룰 생성**: rule-optimizer 서브에이전트가 일치 건들의 공통 파싱 패턴을 분석하여 `extraction_rules.py`의 각 메서드 내부 로직을 Python 코드로 자동 생성. 사용자 검토 후 저장.
6. **불일치 건 보정**: rule-optimizer가 불일치 원인 분석 → 룰 수정 또는 예외 룰 추가
7. **룰 파일 저장**: `/rules/extraction_rules.py` + `/rules/rule_history.json` 초기 이력 기록

### 4.2 반복 고도화 사이클

```
새 사업방법서 투입
    │
    ▼
기존 룰로 추출 시도 (STEP 3)
    │
    ▼
검증 (STEP 5)
    │
    ├── PASS → 룰 성능 확인됨, 다음 상품으로
    │
    └── FAIL → 룰 고도화 (STEP 6)
                │
                ├── 범용 룰 수정 가능 → 수정 + 회귀 테스트
                │     │
                │     ├── 회귀 PASS → 반영
                │     └── 회귀 FAIL → 예외 룰로 분리
                │
                └── 상품 특수 케이스 → 예외 룰 추가
                      (product_exceptions.json)
```

### 4.3 무영향 보장 메커니즘

추출 룰 변경 시 기존 성공 건에 영향이 없도록 하는 핵심 메커니즘:

1. **회귀 테스트 셋**: 성공한 모든 (상품, 테이블) 조합을 `/output/extracted/`에 보관
2. **룰 변경 전/후 비교**: `regression_test.py`가 모든 성공 건을 재추출하여 결과 변화 탐지
3. **변화 감지 시**: 범용 룰 수정을 취소하고, 해당 상품만을 위한 예외 룰로 분리
4. **예외 룰 구조**: `product_exceptions.json`에 상품코드 → 커스텀 파싱 로직 매핑

```python
# extraction_rules.py 구조 예시 (개념)
class ExtractionRules:
    def extract_age_table(self, text, product_code):
        # 예외 룰 우선 확인
        if product_code in self.exceptions:
            return self.exceptions[product_code].extract(text)
        # 범용 룰 적용
        return self.default_extract_age_table(text)
```

---

## 5. 잠재 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| OCR 텍스트 품질 저하 (공백 누락, 문자 오인식) | 텍스트 파싱 정확도 하락 | 이미지 교차검증으로 보완. 이미지 해석 결과를 우선 채택 |
| 사업방법서 포맷 변경 (신규 테이블 레이아웃) | 기존 룰로 추출 불가 | 예외 룰 추가. LLM의 범용 이해력으로 초기 추출은 가능, 이후 룰화 |
| 특약 정보가 사업방법서에 별도 기재되지 않는 경우 | 특약 추출 불가 | 주계약과 동일 조건 적용 가능 여부를 사용자에게 확인 |
| LLM 추출 결과의 비결정성 (동일 입력에 다른 결과) | 재현성 저하 | 추출 룰을 Python 코드로 구체화하여 결정론적으로 전환. LLM은 룰 생성/수정 시에만 사용 |
| 코드 매핑 누락 (새로운 만기 유형 등) | 코드 변환 실패 | 업로드 양식 6행의 코드 목록을 code_mappings.json에 미리 전수 등록 |
| 대량 상품 처리 시 시간/비용 | 처리 지연, API 비용 | 이미지 해석은 불일치 발생 시에만 사용하는 옵션도 고려 가능 |

---

## 6. 향후 Python 자동화 전환 가이드

Claude Code에서의 개발이 완료되면, 독립 Python 스크립트로 전환할 때의 구조:

```
/automation
├── main.py                    # CLI 엔트리포인트
├── config.yaml                # 설정 (API 키, 경로, 모델명 등)
├── /extractors
│   ├── pdf_preprocessor.py    # STEP 1
│   ├── product_mapper.py      # STEP 2
│   ├── table_extractor.py     # STEP 3 (Claude API 호출)
│   ├── code_converter.py      # STEP 4
│   ├── validator.py           # STEP 5
│   ├── rule_optimizer.py      # STEP 6 (Claude API 호출)
│   └── xlsx_generator.py      # STEP 7
├── /rules                     # Claude Code에서 생성된 룰 파일 그대로 사용
└── /data                      # 입출력 디렉토리 구조 동일
```

**전환 시 핵심 변경점**:
- STEP 3, 6의 LLM 호출 → Anthropic API (`claude-sonnet-4-6`) 사용
- 사용자 질의 → CLI 프롬프트 또는 웹 UI
- 워크플로우 오케스트레이션 → main.py의 순차 호출

---

## 7. 검증 체크리스트 (구현 완료 후)

구현이 완료된 후 다음 체크리스트로 시스템 검증:

- [ ] e암보험(비갱신형) — 단순 매트릭스 포맷. 4종 테이블 모두 기존 DB와 100% 일치
- [ ] H통합건강보험(납입면제형) — 복잡 매트릭스 + 성별 분리. 13개 세부보험종목 전체 매핑
- [ ] Wealth단체저축보험 — 서술형 포맷. 보험기간별 분리 추출
- [ ] H보장보험Ⅰ — 간편가입형+일반가입형 구분. 특약 없음 확인
- [ ] 회귀 테스트 — 룰 고도화 후 이전 성공 건 전부 재검증 PASS
- [ ] 업로드 양식 — xlsx 정상 열림, 헤더 6행 보존, 코드값 유효
- [ ] 추출 룰 파일 — 사용자가 Python으로 직접 수정 가능한 구조
