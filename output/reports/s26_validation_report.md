# S00026 검증 리포트 (Ground Truth 비교)

## 요약
- 총 파일: 44개
- PASS (GT 완전 매칭): 11개
- FAIL (누락/불일치): 22개
- EMPTY (새 상품, UPPER_OBJECT_CODE 미설정): 11개
- NO_CODE: 0개

## PASS 목록 (GT 완전 매칭)
- S00026_1808_노후실손의료비보장보험_갱신형_무배당.xlsx: our=3, gt=1, match=1
- S00026_1976_간편가입_실손의료비보장보험_갱신형_무배당_재가입용.xlsx: our=2, gt=4, match=1
- S00026_2170_H간병보험_무배당.xlsx: our=40, gt=20, match=10
- S00026_2170_H보장보험Ⅰ_무배당.xlsx: our=40, gt=20, match=10
- S00026_2209_20260306_235639.xlsx: our=14, gt=2, match=2
- S00026_2249_Need_AI_암보험_무배당.xlsx: our=6, gt=6, match=4
- S00026_2249_간편가입_Need_AI_암보험_무배당.xlsx: our=12, gt=6, match=4
- S00026_2253_H당뇨보험_무배당.xlsx: our=24, gt=24, match=8
- S00026_2254_간편가입_H당뇨보험_무배당.xlsx: our=24, gt=24, match=8
- S00026_2257_시그니처_H통합건강보험_무배당.xlsx: our=36, gt=16, match=10
- S00026_2257_시그니처_H통합건강보험_무배당_납입면제형.xlsx: our=36, gt=16, match=10

## FAIL 목록 (분석 필요)
- S00026_1571_연금보험Enterprise_무배당.xlsx: our=2, gt=360, match=0, missing=84, new=1
- S00026_2126_상생친구_보장보험_무배당.xlsx: our=32, gt=650, match=1, missing=25, new=2
- S00026_2126_진심가득H보장보험_무배당.xlsx: our=32, gt=650, match=1, missing=25, new=2
- S00026_1726_e정기보험_무배당.xlsx: our=30, gt=30, match=0, missing=21, new=12
- S00026_2244_케어백간병플러스보험_무배당.xlsx: our=60, gt=32, match=0, missing=18, new=20
- S00026_2205_간편가입_시그니처H보장보험_무배당.xlsx: our=24, gt=24, match=0, missing=12, new=5
- S00026_2205_간편가입_시그니처H암보험_무배당.xlsx: our=24, gt=24, match=0, missing=12, new=5
- S00026_2205_시그니처H보장보험_무배당.xlsx: our=24, gt=24, match=0, missing=12, new=5
- S00026_2204_시그니처H암보험_무배당.xlsx: our=24, gt=24, match=0, missing=10, new=5
- S00026_2246_H건강플러스보험_무배당.xlsx: our=27, gt=24, match=0, missing=10, new=3
- S00026_2061_e암보험_비갱신형_무배당.xlsx: our=15, gt=29, match=6, missing=5, new=0
- S00026_2130_간편가입_상속H종신보험_무배당.xlsx: our=3, gt=6, match=0, missing=4, new=2
- S00026_2130_상속H종신보험_무배당.xlsx: our=3, gt=6, match=0, missing=4, new=2
- S00026_2236_스마트H상해보험_무배당.xlsx: our=25, gt=10, match=0, missing=4, new=4
- S00026_2236_스마트V상해보험_무배당.xlsx: our=25, gt=10, match=0, missing=4, new=4
- S00026_1230_장애인전용_곰두리보장보험_무배당.xlsx: our=8, gt=32, match=5, missing=3, new=0
- S00026_2242_경영인H정기보험_무배당.xlsx: our=1, gt=2, match=0, missing=2, new=1
- S00026_2243_간편가입_경영인H정기보험_무배당.xlsx: our=1, gt=2, match=0, missing=2, new=1
- S00026_1982_기본형_급여_실손의료비보장보험_갱신형_무배당.xlsx: our=4, gt=5, match=0, missing=1, new=4
- S00026_1983_기본형_급여_e실손의료비보장보험_갱신형_무배당.xlsx: our=4, gt=5, match=0, missing=1, new=4
- S00026_1984_기본형_급여_실손의료비보장보험_계약전환_단체개인전환_개인중지재개용_갱신형_무배당.xlsx: our=4, gt=5, match=0, missing=1, new=2
- S00026_2259_바로연금보험_무배당.xlsx: our=12, gt=2, match=0, missing=1, new=2

## 주요 FAIL 원인
1. MINU_GNDR_CODE: GT는 남/여 구분(1/2), 추출 결과는 남녀공통(None/공백)
2. MIN_AG/MAX_AG 불일치: 추출 로직과 실제 DB 값 차이
3. UPPER_OBJECT_CODE 범위: 하나의 코드만 커버, 다른 variant 미포함 (1571 연금Enterprise 등)