# code-converter 스킬

## 역할
LLM이 추출한 자연어 표현(90세만기, 10년납, 월납 등)을 시스템 코드값으로 결정론적으로 변환한다.

## 코드 변환 규칙

### 보험기간 (ISRN_TERM_*)
| 자연어 | ISRN_TERM | ISRN_TERM_DVSN_CODE | ISRN_TERM_INQY_CODE |
|--------|-----------|---------------------|---------------------|
| 90세만기 | 90 | X | X90 |
| 100세만기 | 100 | X | X100 |
| 110세만기 | 110 | X | X110 |
| 종신 | 999 | A | A999 |
| 20년만기 | 20 | N | N20 |
| 30년만기 | 30 | N | N30 |
| N세만기(자녀) | N | Z | Z{N} |
| N세만기(피부양자) | N | V | V{N} |
| N세만기(계약자) | N | W | W{N} |
| N일만기 | N | D | D{N} |
| N월만기 | N | M | M{N} |

### 납입기간 (PAYM_TERM_*)
| 자연어 | PAYM_TERM | PAYM_TERM_DVSN_CODE | PAYM_TERM_INQY_CODE |
|--------|-----------|---------------------|---------------------|
| 5년납 | 5 | N | N5 |
| 7년납 | 7 | N | N7 |
| 10년납 | 10 | N | N10 |
| 15년납 | 15 | N | N15 |
| 20년납 | 20 | N | N20 |
| 전기납 | 보험기간과 동일 | 보험기간과 동일 | 보험기간과 동일 |
| 일시납 | 0 | N | N0 |

**전기납 처리**:
- 보험기간 N(년만기): PAYM_TERM=보험기간값, DVSN=N
- 보험기간 X(세만기): PAYM_TERM=보험기간값, DVSN=X
- 보험기간 A(종신): PAYM_TERM=999, DVSN=A

### 납입주기 (PAYM_CYCL_*)
| 자연어 | PAYM_CYCL_VAL | PAYM_CYCL_DVSN_CODE | PAYM_CYCL_INQY_CODE |
|--------|---------------|---------------------|---------------------|
| 월납 | 1 | M | M1 |
| 3월납 | 3 | M | M3 |
| 6월납 | 6 | M | M6 |
| 년납 | 12 | M | M12 |
| 일시납 | 0 | M | M0 |

### 성별
| 자연어 | MINU_GNDR_CODE |
|--------|----------------|
| 남자 | 1 |
| 여자 | 2 |
| 남녀공통 | — (별도 행 생성) |

### 판매채널 기본값
`SALE_CHNL_CODE`: `1,2,3,4,7` (기존 데이터 패턴 반영)

## 스크립트

### init_code_mappings.py
- **용도**: 업로드 양식 4종의 6행에서 허용 코드값 추출 → `code_mappings.json` 생성
- **프로젝트 초기화 시 1회 실행**

```bash
python .claude/skills/code-converter/scripts/init_code_mappings.py \
  --templates data/templates/ \
  --output .claude/skills/code-converter/references/code_mappings.json
```

### convert_codes.py
- **용도**: 추출된 자연어 데이터를 시스템 코드로 변환
- **STEP 4 시작 시 호출**

```bash
python .claude/skills/code-converter/scripts/convert_codes.py \
  --input output/extracted/{upper_obj}_{table_type}_{run_id}.json \
  --mappings .claude/skills/code-converter/references/code_mappings.json \
  --output output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json
```

### apply_special_contract_codes.py
- **용도**: 주계약 코드 변환 결과를 특약에 복사 + 코드 교체
- **convert_codes.py 후 호출**

```bash
python .claude/skills/code-converter/scripts/apply_special_contract_codes.py \
  --coded output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json \
  --special-contracts output/extracted/{run_id}_special_contracts.json \
  --output output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json
```

### validate_codes.py
- **용도**: 변환된 코드값이 code_mappings.json의 허용값에 포함되는지 검증

```bash
python .claude/skills/code-converter/scripts/validate_codes.py \
  --input output/extracted/{upper_obj}_{table_type}_{run_id}_coded.json \
  --mappings .claude/skills/code-converter/references/code_mappings.json
```

## 실패 처리
변환 불가 항목 → 로그 + 에스컬레이션. 자동 재시도 없음 (결정론적 실패이므로 룰 수정 필요).
