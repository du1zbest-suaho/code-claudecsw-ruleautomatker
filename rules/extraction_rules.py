"""
extraction_rules.py — 사업방법서에서 구조화된 데이터를 추출하는 룰 모음

메서드 이름과 시그니처는 변경 금지.
내부 로직은 rule-optimizer 서브에이전트 또는 사용자가 수정 가능.
"""

import json
import os
import re
from typing import Dict, List, Optional


class ExtractionRules:
    """
    사업방법서에서 구조화된 데이터를 추출하는 룰 모음.
    메서드 이름과 시그니처는 변경 금지. 내부 로직만 수정 가능.
    """

    def __init__(self, exceptions_path: str = "rules/product_exceptions.json"):
        """product_exceptions.json 로드"""
        self.exceptions = {}
        if os.path.exists(exceptions_path):
            try:
                with open(exceptions_path, "r", encoding="utf-8") as f:
                    self.exceptions = json.load(f)
            except Exception:
                pass

    # ─── S00026: 가입가능나이 ─────────────────────────────────────────────────

    def extract_age_table(self, text: str, product_code: str) -> List[Dict]:
        """
        S00026 (가입가능나이) 추출.
        반환: [{"sub_type": str, "insurance_period": str, "payment_period": str,
                "gender": str, "min_age": int, "max_age": int}, ...]
        """
        if product_code in self.exceptions:
            exc = self.exceptions[product_code]
            if "extract_age_table" in exc:
                return self._apply_exception(exc["extract_age_table"], text)

        # PDF 줄바꿈 아티팩트 보정: "digit\n세" → "digit세"
        # 예: "0세~35\n세" → "0세~35세" (페이지 폭 제한으로 줄바꿈 발생)
        text = re.sub(r'(\d+)\n세', r'\1세', text)
        # 보험기간 헤더 정규화: "60세\n만기" → "60세만기", "10년\n만기" → "10년만기"
        text = re.sub(r'(\d+)\s*세\s*\n\s*만기', r'\1세만기', text)
        text = re.sub(r'(\d+)\s*년\s*\n\s*만기', r'\1년만기', text)

        results = []

        # 패턴 A-1: 연금보험 가입최고나이 공식 "(연금개시나이-납입기간)세" 형식
        # 납입기간 × 연금개시나이 조합을 자동 계산하여 생성
        annuity_rows = self._extract_annuity_age_by_formula(text)
        if annuity_rows:
            return annuity_rows

        # 패턴 A0: 성별 구분 섹션 형식 (남자/여자가 행 헤더로 분리된 테이블)
        # 예: e정기보험, 시그니처H보장보험 등 — 남자/여자 섹션 아래 납입기간별 나이범위
        results.extend(self._parse_age_table_gender_sections(text, product_code))

        # 패턴 A: "만N세~N세" 형식이 납입기간 행에 있는 테이블
        if not results:
            results.extend(self._parse_age_table_inline_range(text, product_code))

        # 패턴 B: 가입최저나이/가입최고나이 분리 형식 (성별 구분 포함)
        if not results:
            results.extend(self._parse_age_table_separate_minmax(text, product_code))

        # 패턴 C: 수직 테이블 / 기간-나이 리스트 형식 (포켓골절, 기업복지 등)
        if not results:
            results.extend(self._parse_age_table_period_age_list(text, product_code))

        # 패턴 D: 단순 가입나이 범위 서술형
        if not results:
            results.extend(self._parse_age_table_narrative(text, product_code))

        return results

    def _parse_one_gender_section(self, section: str, sub: str) -> List[Dict]:
        """
        단일 성별 구분 섹션 파싱 헬퍼.
        section: 가입나이 섹션 텍스트 (3000자 내외)
        sub: 세부상품종목명
        """
        section_results = []
        payment_pattern = r"(\d+\s*년납|\d+\s*세납|전기납|일시납)\s+((?:만?\d+\s*세?\s*[~～\-]\s*\d+\s*세\s*)+)"
        range_pattern = r"만?\s*(\d+)\s*세?\s*[~～\-]\s*(\d+)\s*세"

        insurance_periods = self._find_insurance_periods_in_header(section)

        # 성별 마커로 섹션 분리
        parts = re.split(r"(남\s*자|여\s*자)", section)
        current_gender = None
        for part in parts:
            stripped = re.sub(r"\s+", "", part)
            if stripped == "남자":
                current_gender = "남자"
                continue
            if stripped == "여자":
                current_gender = "여자"
                continue
            if current_gender is None:
                continue
            for pm in re.finditer(payment_pattern, part):
                payment = pm.group(1).replace(" ", "")
                ranges_text = pm.group(2)
                ranges = [(int(a), int(b)) for a, b in re.findall(range_pattern, ranges_text)]
                if not ranges:
                    continue
                if insurance_periods and len(ranges) == len(insurance_periods):
                    for idx, ip in enumerate(insurance_periods):
                        min_a, max_a = ranges[idx]
                        section_results.append({
                            "sub_type": sub,
                            "insurance_period": ip,
                            "payment_period": payment,
                            "gender": current_gender,
                            "min_age": min_a,
                            "max_age": max_a
                        })
                elif not insurance_periods and ranges:
                    min_a, max_a = ranges[0]
                    section_results.append({
                        "sub_type": sub,
                        "insurance_period": "",
                        "payment_period": payment,
                        "gender": current_gender,
                        "min_age": min_a,
                        "max_age": max_a
                    })

        # 남자 결과가 없으면 → 성별이 서브컬럼 헤더인 경우 (예: 2126 상생친구보장보험)
        # section_results가 비어있어도 실행 (4컬럼 테이블에서 payment 데이터가 마지막 gender마커 뒤에 있는 경우)
        male_results = [r for r in section_results if r["gender"] == "남자"]
        if not male_results:
            first_gender_m = re.search(r"남\s*자|여\s*자", section)
            if first_gender_m:
                pre_gender = section[max(0, first_gender_m.start() - 500): first_gender_m.start()]
                true_ips = self._find_insurance_periods_in_header(pre_gender)
                if true_ips:
                    gender_markers_all = list(re.finditer(r"남\s*자|여\s*자", section))
                    start_gm_idx = next(
                        (gi for gi, gm in enumerate(gender_markers_all)
                         if gm.start() == first_gender_m.start()), None
                    )

                    # n_ip 후보: IP헤더 기반 + 첫 payment행 이전 gender마커 기반
                    first_pay_m = re.search(payment_pattern, section)
                    n_ip_candidates = [len(true_ips)]
                    if first_pay_m:
                        pre_pay_markers = list(re.finditer(r"남\s*자|여\s*자", section[:first_pay_m.start()]))
                        n_from_markers = len(pre_pay_markers) // 2
                        if n_from_markers >= 1 and n_from_markers not in n_ip_candidates:
                            n_ip_candidates.append(n_from_markers)

                    for n_ip in n_ip_candidates:
                        post_gender_start = None
                        if start_gm_idx is not None:
                            target_idx = start_gm_idx + n_ip * 2 - 1
                            if target_idx < len(gender_markers_all):
                                post_gender_start = gender_markers_all[target_idx].end()
                        if post_gender_start is None:
                            continue
                        post_last_female = section[post_gender_start:]
                        # n_ip가 너무 작으면 post 구간에 gender 마커가 payment 행 앞에 남아있음
                        # → 그 n_ip는 스킵하고 더 큰 n_ip 후보 시도
                        first_pay_in_post = re.search(payment_pattern, post_last_female)
                        if first_pay_in_post:
                            pre_pay_gm = re.findall(r"남\s*자|여\s*자", post_last_female[:first_pay_in_post.start()])
                            if pre_pay_gm:
                                continue
                        candidate_results = []
                        for pm in re.finditer(payment_pattern, post_last_female):
                            payment = pm.group(1).replace(" ", "")
                            ranges_text = pm.group(2)
                            ranges = [(int(a), int(b)) for a, b in re.findall(range_pattern, ranges_text)]
                            # n_ip 매치: 모든 n_ip 쌍 추출 (true_ips를 순환하여 8컬럼 표준형 포함)
                            n_use = len(true_ips)
                            if len(ranges) == n_ip * 2 and n_use <= n_ip:
                                for idx in range(n_ip):
                                    ip = true_ips[idx % n_use]
                                    candidate_results.append({
                                        "sub_type": sub,
                                        "insurance_period": ip,
                                        "payment_period": payment,
                                        "gender": "남자",
                                        "min_age": ranges[idx * 2][0],
                                        "max_age": ranges[idx * 2][1],
                                    })
                                    candidate_results.append({
                                        "sub_type": sub,
                                        "insurance_period": ip,
                                        "payment_period": payment,
                                        "gender": "여자",
                                        "min_age": ranges[idx * 2 + 1][0],
                                        "max_age": ranges[idx * 2 + 1][1],
                                    })
                        if candidate_results:
                            section_results = candidate_results
                            break
        return section_results

    def _parse_age_table_gender_sections(self, text: str, product_code: str) -> List[Dict]:
        """
        성별 구분 섹션 형식 파싱.
        PDF 텍스트에 "남자" / "여자"가 독립 행 헤더로 나타나고,
        각 헤더 아래 납입기간별 나이범위가 있는 테이블.
        예: e정기보험 만기환급형, 시그니처H보장보험 등
        여러 종속특약 테이블을 모두 스캔하여 결과 합산 (dedup).
        """
        sub_types = self._find_sub_types_in_section(text)
        sub = sub_types[0] if sub_types else "기본형"

        seen_keys: set = set()
        results = []

        # 모든 "가입나이" 위치에서 섹션 추출 후 파싱 (멀티섹션 지원)
        age_positions = [m.start() for m in re.finditer(r"(?:피보험자\s*)?가입나이", text)]
        if not age_positions:
            age_positions = [0]

        for pos in age_positions:
            # 최저가입나이/최고가입나이의 suffix인 경우 스킵
            if re.search(r"최[저고]\s*$", text[max(0, pos - 3):pos]):
                continue

            # 태아보장기간 미니테이블의 "가입나이" 위치는 스킵 (200자 이내에 태아보장기간 존재)
            lookahead = text[pos:pos + 200]
            if re.search(r"태아보장기간|태아\s*\n", lookahead):
                continue

            # 상생협력형 열 헤더 / 주의사항 내 가입나이 스킵 (100자 이내에 20년만기/전기납이 보험기간으로 등장)
            if re.search(r"20년만기|전기납", text[pos:pos + 100]):
                continue

            # 납입기간 바로 다음 열로 나오는 가입나이 스킵 (상생협력형 표 열 헤더)
            lookbehind = text[max(0, pos - 50):pos]
            if re.search(r"납입기간\s*\n\s*$", lookbehind):
                continue

            section = text[pos:pos + 3000]

            # 성별 구분 섹션 마커 탐지: "남자" 또는 "남\n자" 뒤에 줄바꿈 (행 헤더로 사용됨)
            has_male = bool(re.search(r"남\s*자\s*\n", section))
            has_female = bool(re.search(r"여\s*자\s*\n", section))
            if not (has_male and has_female):
                continue

            for r in self._parse_one_gender_section(section, sub):
                key = (r["insurance_period"], r["payment_period"], r["gender"], r["min_age"], r["max_age"])
                if key not in seen_keys:
                    seen_keys.add(key)
                    results.append(r)

        return results

    def _parse_age_table_inline_range(self, text: str, product_code: str) -> List[Dict]:
        """
        인라인 범위 형식 파싱.
        예: "5년납  만15세~80세 만15세~80세 만15세~80세 만15세~80세"
        """
        results = []

        # 섹션 찾기: "피보험자 가입나이" 또는 "가입나이" 섹션
        section = self._extract_age_section(text)
        if not section:
            section = text

        # 보험기간 컬럼 헤더 추출 (구 분 행 앞뒤에서)
        insurance_periods = self._find_insurance_periods_in_header(section)
        # 세부보험종목 탐지
        sub_types = self._find_sub_types_in_section(section)

        # 납입기간 행 + 나이범위 파싱
        # 패턴: "N년납\s+(만?\d+세~\d+세\s*)+" 또는 "전기납\s+(만?\d+세~\d+세\s*)+"
        # 확장: 만N~N세 (세 생략), N 세~N 세 (공백 포함), N세납(60세납 등) 지원
        payment_pattern = r"(\d+\s*년납|\d+\s*세납|전기납|일시납)\s+((?:만?\d+\s*세?\s*[~～\-]\s*\d+\s*세\s*)+)"
        for m in re.finditer(payment_pattern, section):
            payment = m.group(1).replace(" ", "")
            ranges_text = m.group(2)

            # 나이범위들 추출 (세? → 첫 숫자 뒤 세 생략 허용)
            range_pattern = r"만?\s*(\d+)\s*세?\s*[~～\-]\s*(\d+)\s*세"
            ranges = [(int(a), int(b)) for a, b in re.findall(range_pattern, ranges_text)]

            if not ranges:
                continue

            # 보험기간 × 성별 조합으로 매핑
            # ranges 수가 (보험기간 수 × 2) 이면 각 보험기간에 남/여 쌍
            if insurance_periods and len(ranges) == len(insurance_periods) * 2:
                for idx, ip in enumerate(insurance_periods):
                    male_min, male_max = ranges[idx * 2]
                    female_min, female_max = ranges[idx * 2 + 1]
                    sub = sub_types[0] if sub_types else "기본형"
                    results.append({
                        "sub_type": sub,
                        "insurance_period": ip,
                        "payment_period": payment,
                        "gender": "남자",
                        "min_age": male_min,
                        "max_age": male_max
                    })
                    results.append({
                        "sub_type": sub,
                        "insurance_period": ip,
                        "payment_period": payment,
                        "gender": "여자",
                        "min_age": female_min,
                        "max_age": female_max
                    })
            elif insurance_periods and len(ranges) == len(insurance_periods):
                # 남녀 공통
                for idx, ip in enumerate(insurance_periods):
                    min_a, max_a = ranges[idx]
                    sub = sub_types[0] if sub_types else "기본형"
                    results.append({
                        "sub_type": sub,
                        "insurance_period": ip,
                        "payment_period": payment,
                        "gender": "남녀공통",
                        "min_age": min_a,
                        "max_age": max_a
                    })
            else:
                # 보험기간 모를 때 - 첫 번째 범위만 사용
                min_a, max_a = ranges[0]
                results.append({
                    "sub_type": sub_types[0] if sub_types else "기본형",
                    "insurance_period": insurance_periods[0] if insurance_periods else "",
                    "payment_period": payment,
                    "gender": "남녀공통",
                    "min_age": min_a,
                    "max_age": max_a
                })

        # 세부보험종목별로 같은 패턴이 반복되는 경우 (간편가입형 등)
        if not results:
            # 세부보험종목 없이 전체 파싱 재시도
            for m in re.finditer(payment_pattern, text):
                payment = m.group(1).replace(" ", "")
                ranges_text = m.group(2)
                range_pattern = r"만?\s*(\d+)\s*세?\s*[~～\-]\s*(\d+)\s*세"
                ranges = [(int(a), int(b)) for a, b in re.findall(range_pattern, ranges_text)]
                if not ranges:
                    continue
                min_a, max_a = ranges[0]
                results.append({
                    "sub_type": "기본형",
                    "insurance_period": insurance_periods[0] if insurance_periods else "",
                    "payment_period": payment,
                    "gender": "남녀공통",
                    "min_age": min_a,
                    "max_age": max_a
                })

        # 희소 테이블 보완: 일부 셀이 '-'인 행(e암보험 등) 처리
        # 이미 추출된 납입기간 외 누락된 납입기간 행을 line-by-line으로 추출
        # 주의: 메인 스캔 결과가 없을 때는 sparse를 실행하지 않음 (오탐 방지)
        if insurance_periods and results:
            captured_payments = {r["payment_period"] for r in results}
            sparse = self._parse_age_table_sparse_multiline(section, insurance_periods, sub_types)
            for row in sparse:
                if row["payment_period"] not in captured_payments:
                    results.append(row)

        return results

    def _parse_age_table_sparse_multiline(
        self, section: str, insurance_periods: List[str], sub_types: List[str]
    ) -> List[Dict]:
        """
        희소 테이블 파싱: 각 셀이 개별 줄에 있고 일부 셀이 '-'(해당없음)인 형식.
        예: e암보험(비갱신형) — 20년납, 30년납, 60세납, 전기납 행에서
            일부 보험기간 조합이 '-'로 표시됨.
        """
        results = []
        n_ip = len(insurance_periods)
        if n_ip == 0:
            return results

        lines = [ln.strip() for ln in section.splitlines() if ln.strip()]
        payment_pat = re.compile(r'^(\d+\s*(?:년납|세납)|전기납|일시납)$')
        age_range_pat = re.compile(r'만?\s*(\d+)\s*세?\s*[~～]\s*(\d+)\s*세')
        sub = sub_types[0] if sub_types else "기본형"

        i = 0
        while i < len(lines):
            mp = payment_pat.match(lines[i])
            if mp:
                payment = mp.group(1).replace(' ', '')
                # 다음 n_ip개 셀 수집 (다음 납입기간 레이블이 나오면 중단)
                cells = []
                j = i + 1
                while j < len(lines) and len(cells) < n_ip:
                    if payment_pat.match(lines[j]):
                        break
                    cells.append(lines[j])
                    j += 1

                if len(cells) == n_ip:
                    for idx, cell in enumerate(cells):
                        if cell == '-':
                            continue
                        rm = age_range_pat.search(cell)
                        if rm:
                            results.append({
                                "sub_type": sub,
                                "insurance_period": insurance_periods[idx],
                                "payment_period": payment,
                                "gender": "남녀공통",
                                "min_age": int(rm.group(1)),
                                "max_age": int(rm.group(2)),
                            })
                i = j
                continue
            i += 1

        return results

    def _parse_age_table_separate_minmax(self, text: str, product_code: str) -> List[Dict]:
        """
        가입최저나이 / 가입최고나이 분리 형식 파싱.
        예:
          - 가입최저나이 : 만 15세
          - 가입최고나이 : 성별, 납입기간별로 아래와 같음
          구 분  90세만기  100세만기
                 남자 여자  남자 여자
          5년납  64세 64세  70세 70세
        """
        results = []

        # 최저나이 추출
        min_age = self._extract_min_age(text)
        if min_age is None:
            min_age = 0

        section = self._extract_age_section(text)
        if not section:
            section = text

        # 보험기간 표기 내 공백 정규화 (예: "110세 만기" → "110세만기")
        section = re.sub(r"(\d+)\s*세\s*만기", r"\1세만기", section)
        section = re.sub(r"(\d+)\s*년\s*만기", r"\1년만기", section)

        insurance_periods = self._find_insurance_periods_in_header(section)
        # N세만기/N년만기 기간이 있을 때 '종신' 처리:
        # 테이블 헤더에서 N세/년만기와 '종신'이 인접(200자 이내)하면 공존 가능 → 유지
        # 멀리 떨어져 있으면 다른 섹션의 오탐 → 제거 (예: 적립형 계약 문구)
        if any("세만기" in p or "년만기" in p for p in insurance_periods):
            period_positions = [m.start() for p in insurance_periods
                                if "세만기" in p or "년만기" in p
                                for m in [re.search(re.escape(p), section)] if m]
            jongshin_positions = [m.start() for m in re.finditer(r"종신", section)]
            nearby = period_positions and jongshin_positions and any(
                abs(jp - pp) <= 200
                for pp in period_positions for jp in jongshin_positions
            )
            if not nearby:
                insurance_periods = [p for p in insurance_periods if p != "종신"]
        sub_types = self._find_sub_types_in_section(section)
        sub = sub_types[0] if sub_types else "기본형"

        # "N년납\s+N세\s+N세\s+..." 패턴 (각 셀이 숫자만)
        payment_max_pattern = r"(\d+\s*년납|전기납|일시납)\s+((?:\d+\s*세\s*)+)"
        for m in re.finditer(payment_max_pattern, section):
            payment = m.group(1).replace(" ", "")
            maxes_text = m.group(2)
            maxes = [int(x) for x in re.findall(r"(\d+)\s*세", maxes_text)]
            if not maxes:
                continue

            if insurance_periods and len(maxes) == len(insurance_periods) * 2:
                for idx, ip in enumerate(insurance_periods):
                    results.append({
                        "sub_type": sub,
                        "insurance_period": ip,
                        "payment_period": payment,
                        "gender": "남자",
                        "min_age": min_age,
                        "max_age": maxes[idx * 2]
                    })
                    results.append({
                        "sub_type": sub,
                        "insurance_period": ip,
                        "payment_period": payment,
                        "gender": "여자",
                        "min_age": min_age,
                        "max_age": maxes[idx * 2 + 1]
                    })
            elif insurance_periods and len(maxes) == len(insurance_periods):
                # 값 2개인 경우: 성별(남/여) 구분 테이블일 수 있음 (각 블록이 1개 보험기간만 가짐)
                if len(maxes) == 2:
                    local_before = section[max(0, m.start() - 500): m.start()]
                    local_periods = self._find_insurance_periods_in_header(local_before)
                    has_gender = bool(re.search(r"남\s*자.*여\s*자|여\s*자.*남\s*자", local_before, re.DOTALL))
                    if has_gender and local_periods:
                        ip = local_periods[-1]
                        results.append({
                            "sub_type": sub,
                            "insurance_period": ip,
                            "payment_period": payment,
                            "gender": "남자",
                            "min_age": min_age,
                            "max_age": maxes[0]
                        })
                        results.append({
                            "sub_type": sub,
                            "insurance_period": ip,
                            "payment_period": payment,
                            "gender": "여자",
                            "min_age": min_age,
                            "max_age": maxes[1]
                        })
                        continue
                for idx, ip in enumerate(insurance_periods):
                    results.append({
                        "sub_type": sub,
                        "insurance_period": ip,
                        "payment_period": payment,
                        "gender": "남녀공통",
                        "min_age": min_age,
                        "max_age": maxes[idx]
                    })
            elif maxes:
                results.append({
                    "sub_type": sub,
                    "insurance_period": insurance_periods[0] if insurance_periods else "",
                    "payment_period": payment,
                    "gender": "남녀공통",
                    "min_age": min_age,
                    "max_age": maxes[0]
                })

        # 희소 테이블 보완: 일부 셀이 '-'인 행 (예: 1230 장애인전용 곰두리보장보험)
        # payment 라인별로 다음 n_ip개 토큰을 수집, '-'는 해당없음으로 스킵
        if insurance_periods:
            captured_payments = {r["payment_period"] for r in results}
            n_ip = len(insurance_periods)
            lines = [ln.strip() for ln in section.splitlines() if ln.strip()]
            sparse_pay_pat = re.compile(r'^(\d+\s*(?:년납|세납)|전기납|일시납)$')
            max_age_cell = re.compile(r'^(\d+)\s*세$')
            dash_cell = re.compile(r'^-$')
            i = 0
            while i < len(lines):
                mp = sparse_pay_pat.match(lines[i])
                if mp:
                    payment = mp.group(1).replace(' ', '')
                    if payment not in captured_payments:
                        cells = []
                        j = i + 1
                        while j < len(lines) and len(cells) < n_ip:
                            if sparse_pay_pat.match(lines[j]):
                                break
                            cells.append(lines[j])
                            j += 1
                        if len(cells) == n_ip:
                            added = False
                            for idx, cell in enumerate(cells):
                                if dash_cell.match(cell):
                                    continue
                                mm = max_age_cell.match(cell)
                                if mm:
                                    results.append({
                                        "sub_type": sub,
                                        "insurance_period": insurance_periods[idx],
                                        "payment_period": payment,
                                        "gender": "남녀공통",
                                        "min_age": min_age,
                                        "max_age": int(mm.group(1)),
                                    })
                                    added = True
                            if added:
                                captured_payments.add(payment)
                        i = j
                        continue
                i += 1

        # 패턴 2: "N년납\n남자\nN세\n여자\nN세" (종신보험 성별 구분 형식)
        # 예: 간편가입_H종신보험, 제로백H종신보험 등
        if not results:
            gender_pattern = r"(\d+\s*년납|전기납|일시납)\s+남자\s+(\d+)\s*세\s+여자\s+(\d+)\s*세"
            for m in re.finditer(gender_pattern, section):
                payment = m.group(1).replace(" ", "")
                male_max = int(m.group(2))
                female_max = int(m.group(3))
                ip = insurance_periods[0] if insurance_periods else "종신"
                results.append({
                    "sub_type": sub,
                    "insurance_period": ip,
                    "payment_period": payment,
                    "gender": "남자",
                    "min_age": min_age,
                    "max_age": male_max
                })
                results.append({
                    "sub_type": sub,
                    "insurance_period": ip,
                    "payment_period": payment,
                    "gender": "여자",
                    "min_age": min_age,
                    "max_age": female_max
                })

        return results

    def _parse_age_table_period_age_list(self, text: str, product_code: str) -> List[Dict]:
        """
        수직 테이블 / 기간-나이 리스트 형식 파싱.
        예1 (포켓골절): 가입나이\\n보험기간\\n납입기간\\n납입주기\\n만19세~65세\\n1년만기\\n일시납
        예2 (기업복지): 1년만기\\n만15세 ~ 80세\\n전기납
        예3 (치아보험): 5년만기 갱신\\n6 세~70 세\\n전기납
        예4 (Wealth단체): 3년만기\\n만 15세 ~ 75세 ... 60세만기\\n5년납\\n만 15세 ~ 53세
        """
        results = []

        # 가장 마지막(가장 구체적인) '피보험자 가입나이' 섹션 사용
        # → 가. 보험기간, 나. 납입기간 섹션을 포함하지 않도록
        section_matches = list(re.finditer(r"피보험자\s*가입나이", text))
        if section_matches:
            start = section_matches[-1].start()
            section = text[start: start + 3000]
        else:
            section = self._extract_age_section(text) or text

        # "나. 보험료 납입기간 - IP: pp1, pp2,..." 형식에서 IP→첫번째 납입기간 매핑 추출
        # Wealth단체 등 납입기간별 가입나이가 동일한 경우 활용
        ip_pp_map: Dict[str, str] = {}
        pp_sec_m = re.search(r"보험료\s*납입기간[^\n]*\n((?:[ \t]*-[^\n]+\n?)+)", text)
        if pp_sec_m:
            for line in pp_sec_m.group(1).splitlines():
                lm = re.match(r"\s*-\s*(\d+년만기|\d+세만기):\s*(.+)", line)
                if lm:
                    ip_key = self._normalize_period(lm.group(1))
                    pps = [p.strip() for p in lm.group(2).split(",")]
                    ip_pp_map[ip_key] = pps[0] if pps else "전기납"

        # 나이범위 패턴 (첫 숫자 뒤 세 생략 허용, 공백 허용)
        age_range_pat = r"만?\s*(\d+)\s*세?\s*[~～]\s*(\d+)\s*세"

        seen = set()
        for m in re.finditer(age_range_pat, section):
            min_age_v = int(m.group(1))
            max_age_v = int(m.group(2))

            # 직전 80자: 바로 앞 행 우선, 납입주기용
            tight_before = section[max(0, m.start() - 80): m.start()]
            tight_after = section[m.end(): min(len(section), m.end() + 80)]
            # 보험기간 탐색: 뒤 300자 (갱신형 주석이 늦게 등장), 앞 600자 (대형 테이블 헤더가 멀리 있을 수 있음)
            wide_before = section[max(0, m.start() - 600): m.start()]
            wide_after = section[m.end(): min(len(section), m.end() + 300)]

            period_pat = r"\d+년만기(?:\s*갱신)?|\d+세만기|종신"
            payment_pat = r"\d+년납|전기납|일시납"

            # 보험기간: wide_before LAST → wide_after FIRST 순서로 탐색
            before_periods = list(re.finditer(period_pat, wide_before))
            after_periods = list(re.finditer(period_pat, wide_after))
            period_m = before_periods[-1] if before_periods else (after_periods[0] if after_periods else None)

            period = self._normalize_period(period_m.group(0)) if period_m else ""

            # 납입기간: tight_before LAST → tight_after FIRST 순서로 탐색
            before_payments = list(re.finditer(payment_pat, tight_before))
            if not before_payments:
                after_payments = list(re.finditer(payment_pat, tight_after))
                # tight_after에서 현재 IP와 다른 IP가 납입기간보다 먼저 나오면
                # 그 납입기간은 다른 IP 행의 것 → ip_pp_map 로 대체
                if after_payments:
                    first_pay_pos = after_payments[0].start()
                    after_ips = list(re.finditer(period_pat, tight_after[:first_pay_pos]))
                    if after_ips:
                        first_after_ip = self._normalize_period(after_ips[0].group(0))
                        if first_after_ip != period:
                            after_payments = []  # 다른 IP 행의 납입기간 → 무시
                payment_m = after_payments[0] if after_payments else None
            else:
                payment_m = before_payments[-1]

            # 납입기간 최종 결정: tight_before/after → ip_pp_map → 전기납
            if payment_m:
                payment = payment_m.group(0)
            elif period and period in ip_pp_map:
                payment = ip_pp_map[period]
            else:
                payment = "전기납"

            # 기간 정보 없는 단순 나이범위는 스킵 (다른 메서드에서 처리)
            if not period:
                continue

            key = (period, payment, min_age_v, max_age_v)
            if key in seen:
                continue
            seen.add(key)

            results.append({
                "sub_type": "기본형",
                "insurance_period": period,
                "payment_period": payment,
                "gender": "남녀공통",
                "min_age": min_age_v,
                "max_age": max_age_v
            })

        return results

    def _parse_age_table_narrative(self, text: str, product_code: str) -> List[Dict]:
        """서술형 가입나이 파싱"""
        results = []

        # 패턴 A: "피보험자 가입나이: N세~N세" 형식
        pattern = r"(?:피보험자\s*)?가입(?:가능)?(?:나이|연령)[:\s]*(?:만\s*)?(\d+)세[~～\-]\s*(?:만\s*)?(\d+)세"
        for m in re.finditer(pattern, text):
            min_age = int(m.group(1))
            max_age = int(m.group(2))
            insurance_periods = self._find_insurance_periods_in_header(
                text[max(0, m.start()-500):m.start()+500]
            )
            payment_periods = self._find_payment_periods_in_section(
                text[max(0, m.start()-200):m.start()+200]
            )
            results.append({
                "sub_type": "기본형",
                "insurance_period": insurance_periods[0] if insurance_periods else "",
                "payment_period": payment_periods[0] if payment_periods else "",
                "gender": "남녀공통",
                "min_age": min_age,
                "max_age": max_age
            })

        # 패턴 B: 표 형식 "1년\nN세 ~ N세\n전기납" (갱신형 실손 등)
        # 보험기간, 가입나이(N세~N세), 납입기간이 각 행에 있는 형식
        if not results:
            table_pattern = r"(\d+년)\s*\n\s*(\d+)\s*세\s*[~～]\s*(\d+)\s*세\s*\n\s*(\w+납)"
            for m in re.finditer(table_pattern, text):
                ins_period = m.group(1) + "만기"
                min_age = int(m.group(2))
                max_age = int(m.group(3))
                payment = m.group(4)
                results.append({
                    "sub_type": "기본형",
                    "insurance_period": ins_period,
                    "payment_period": payment,
                    "gender": "남녀공통",
                    "min_age": min_age,
                    "max_age": max_age
                })

        # 패턴 C: 단순 "N세 ~ N세" 범위 (세부보험종목 행 아래에 있는 경우)
        # 예: "종신연금형(개인형)\n45 ~ 85세"
        if not results:
            sub_age_pattern = r"([가-힣\w]+형(?:\([가-힣\w]+\))?)\s*\n\s*(\d+)\s*[~～]\s*(\d+)\s*세"
            for m in re.finditer(sub_age_pattern, text):
                sub = m.group(1)
                min_age = int(m.group(2))
                max_age = int(m.group(3))
                insurance_periods = self._find_insurance_periods_in_header(text)
                payment_periods = self._find_payment_periods_in_section(text)
                results.append({
                    "sub_type": sub,
                    "insurance_period": insurance_periods[0] if insurance_periods else "종신",
                    "payment_period": payment_periods[0] if payment_periods else "일시납",
                    "gender": "남녀공통",
                    "min_age": min_age,
                    "max_age": max_age
                })

        # 패턴 D: 최저/최고 단순 서술
        if not results:
            min_age = self._extract_min_age(text)
            max_age_m = re.search(
                r"가입최고나이[:\s]*(?:만\s*)?(\d+)세(?!\s*만기|\s*이상|\s*이하)",
                text
            )
            if min_age is not None and max_age_m:
                insurance_periods = self._find_insurance_periods_in_header(text)
                payment_periods = self._find_payment_periods_in_section(text)
                results.append({
                    "sub_type": "기본형",
                    "insurance_period": insurance_periods[0] if insurance_periods else "",
                    "payment_period": payment_periods[0] if payment_periods else "",
                    "gender": "남녀공통",
                    "min_age": min_age,
                    "max_age": int(max_age_m.group(1))
                })

        return results

    # ─── S00027: 가입가능보기납기 ─────────────────────────────────────────────

    def extract_period_table(self, text: str, product_code: str) -> List[Dict]:
        """
        S00027 (가입가능보기납기) 추출.
        반환: [{"sub_type": str, "insurance_period": str, "payment_period": str}, ...]
        """
        if product_code in self.exceptions:
            exc = self.exceptions[product_code]
            if "extract_period_table" in exc:
                return self._apply_exception(exc["extract_period_table"], text)

        results = []
        sub_types = self._find_sub_types_in_section(text) or ["기본형"]

        # 보험기간 및 납입기간 추출
        insurance_periods = self._extract_all_insurance_periods(text)
        payment_periods = self._extract_all_payment_periods(text)

        # 전기납 → 연금개시나이별 X{age} 확장
        if "전기납" in payment_periods:
            onset_range = self._extract_annuity_onset_range(text)
            if onset_range:
                min_a, max_a = onset_range
                payment_periods = [
                    pp for pp in payment_periods if pp != "전기납"
                ] + [f"{a}세납" for a in range(min_a, max_a + 1)]

        if insurance_periods and payment_periods:
            # 세부보험종목별 × 보험기간 × 납입기간 조합
            seen = set()
            for sub in sub_types:
                for ip in insurance_periods:
                    for pp in payment_periods:
                        key = (sub, ip, pp)
                        if key not in seen:
                            seen.add(key)
                            results.append({
                                "sub_type": sub,
                                "insurance_period": ip,
                                "payment_period": pp
                            })
        else:
            # 서술형: 직접 파싱
            pattern = r"(\d+(?:세|년)만기|종신)\s*(?:[+\s]+)\s*(\d+년납|전기납|일시납)"
            for m in re.finditer(pattern, text):
                ip = self._normalize_period(m.group(1))
                pp = m.group(2)
                for sub in sub_types:
                    results.append({
                        "sub_type": sub,
                        "insurance_period": ip,
                        "payment_period": pp
                    })

        return results

    # ─── S00028: 가입가능납입주기 ─────────────────────────────────────────────

    def extract_payment_cycle(self, text: str, product_code: str) -> List[Dict]:
        """
        S00028 (가입가능납입주기) 추출.
        반환: [{"sub_type": str, "payment_cycle": str}, ...]
        """
        if product_code in self.exceptions:
            exc = self.exceptions[product_code]
            if "extract_payment_cycle" in exc:
                return self._apply_exception(exc["extract_payment_cycle"], text)

        results = []
        cycles_ordered = ["월납", "3개월납", "6개월납", "3월납", "6월납", "년납", "연납", "일시납"]
        sub_types = self._find_sub_types_in_section(text) or ["기본형"]

        # PDF 줄바꿈 아티팩트 수정: "3\n개월납" → "3개월납"
        text = re.sub(r'(\d)\n(개월납)', r'\1\2', text)

        # "납입주기: 월납, 3개월납" 패턴
        pattern = r"납입(?:주기|방법)[:\s]+((?:월납|3개월납|6개월납|3월납|6월납|년납|연납|일시납)(?:[,、\s]+(?:월납|3개월납|6개월납|3월납|6월납|년납|연납|일시납))*)"
        m = re.search(pattern, text)
        found_cycles = []
        if m:
            cycle_text = m.group(1)
            for cycle in cycles_ordered:
                if cycle in cycle_text:
                    found_cycles.append(cycle)
        else:
            # 단순 키워드 탐색
            for cycle in cycles_ordered:
                if cycle in text:
                    found_cycles.append(cycle)

        # 중복 제거 및 결과 생성
        seen_cycles = set()
        for sub in sub_types:
            for cycle in found_cycles:
                if cycle not in seen_cycles:
                    seen_cycles.add(cycle)
                    results.append({"sub_type": sub, "payment_cycle": cycle})

        return results

    # ─── S00022: 보기개시나이 ─────────────────────────────────────────────────

    def extract_benefit_start_age(self, text: str, product_code: str) -> List[Dict]:
        """
        S00022 (보기개시나이) 추출. 해당사항 없으면 빈 리스트 반환.
        반환: [{"sub_type": str, "min_age": int, "max_age": int}, ...]
              또는 N-type: [{"sub_type": str, "n_years": int}, ...]
        """
        if product_code in self.exceptions:
            exc = self.exceptions[product_code]
            if "extract_benefit_start_age" in exc:
                return self._apply_exception(exc["extract_benefit_start_age"], text)

        results = []

        # ── N-type: 年 기반 보기개시 (종신보험 스마트연금전환특약 등) ──────────
        n_years: set = set()

        # "계약일(부터|이후) N년 경과시점" – 보장형 기준사망보험금 지급 시작 시점
        # 단, "의 장기유지보너스" 뒤에 오는 경우는 제외 (장기유지보너스 경과시점)
        for m in re.finditer(r"계약일\s*(?:부터|이후)\s*(\d+)년\s*경과시점", text):
            context_after = text[m.end():m.end()+30]
            if "장기유지" in context_after or "보너스" in context_after:
                continue
            n_years.add(int(m.group(1)))

        # "전환일(부터|이후) N년 경과시점" – 스마트전환형 계약 기준사망보험금 시작
        for m in re.finditer(r"전환일\s*(?:부터|이후)\s*(\d+)년\s*경과시점", text):
            n_years.add(int(m.group(1)))

        # "보험계약일 이후 N년이 경과한" – 스마트연금전환특약 대상계약 조건
        # 앞선 패턴에서 매칭 없을 때만 사용 (false positive 방지)
        if not n_years:
            for m in re.finditer(r"보험계약일\s*이후\s*(\d+)년이?\s*경과한", text):
                n_years.add(int(m.group(1)))

        if n_years:
            for yr in sorted(n_years):
                results.append({"sub_type": "기본형", "n_years": yr})
            return results

        # ── X-type: 나이(세) 기반 보기개시 ────────────────────────────────────

        # 패턴 0: "N종(...)\n만 N세~M세" 형식 다중 종별 테이블 (1종/2종 구분 상품)
        # 예: 하이드림연금보험(1745), 미래로기업복지연금보험(1809) 등
        # 모든 "연금개시나이" 출현 위치를 순회하며 검색
        for onset_m in re.finditer(r"(?:연금|보기)개시(?:나이|연령)", text):
            section = text[onset_m.start():onset_m.start()+600]
            per_type_pairs = re.findall(
                r"(\d+종[^\n]*)\n\s*만?\s*(\d+)\s*세\s*[~～]\s*(\d+)\s*세",
                section
            )
            if per_type_pairs:
                for sub_type, min_a, max_a in per_type_pairs:
                    results.append({"sub_type": sub_type.strip(), "min_age": int(min_a), "max_age": int(max_a)})
                return results

        # 패턴 1: "연금개시나이\n- N세 ~ N세" (개행 포함, 실제 형식)
        onset_section_pattern = r"(?:연금|보기)개시(?:나이|연령)[\s\S]{0,80}?(\d+)\s*세\s*[~～]\s*(\d+)\s*세"
        m = re.search(onset_section_pattern, text)
        if m:
            min_age = int(m.group(1))
            max_age = int(m.group(2))
            sub_types = self._find_sub_types_in_section(
                text[max(0, m.start()-300):m.start()+300]
            ) or ["기본형"]
            for sub in sub_types:
                results.append({
                    "sub_type": sub,
                    "min_age": min_age,
                    "max_age": max_age
                })
            return results

        # 패턴 1b: "연금개시나이" 이후 "N ~ M세" (첫 숫자에 세 없음) – 바로연금보험 등
        onset_no_first_se = r"(?:연금|보기)개시(?:나이|연령)[\s\S]{0,200}?(\d+)\s*[~～]\s*(\d+)\s*세"
        m = re.search(onset_no_first_se, text)
        if m:
            min_age = int(m.group(1))
            max_age = int(m.group(2))
            results.append({"sub_type": "기본형", "min_age": min_age, "max_age": max_age})
            return results

        # 패턴 2: "연금개시나이: N세~N세" (같은 줄)
        same_line_pattern = r"(?:연금|보기)개시(?:나이|연령)[:\s]+(\d+)세[~～\-]\s*(\d+)세"
        for m in re.finditer(same_line_pattern, text):
            results.append({
                "sub_type": "기본형",
                "min_age": int(m.group(1)),
                "max_age": int(m.group(2))
            })

        # 패턴 3: 단일 나이 "연금개시나이: N세"
        if not results:
            single_pattern = r"(?:연금|보기)개시(?:나이|연령)[:\s]+(\d+)세"
            for m in re.finditer(single_pattern, text):
                age = int(m.group(1))
                results.append({
                    "sub_type": "기본형",
                    "min_age": age,
                    "max_age": age
                })

        return results

    # ─── 헬퍼 메서드 ──────────────────────────────────────────────────────────

    def _extract_age_section(self, text: str) -> Optional[str]:
        """가입나이 섹션 텍스트 추출"""
        # "피보험자 가입나이" 또는 "가입나이" 항목 이후 텍스트
        m = re.search(r"(?:피보험자\s*)?가입나이", text)
        if m:
            return text[m.start():m.start() + 3000]
        return None

    def _extract_min_age(self, text: str) -> Optional[int]:
        """가입최저나이 추출"""
        m = re.search(r"가입최저나이[:\s]+(?:만\s*)?(\d+)세", text)
        if m:
            return int(m.group(1))
        m = re.search(r"최저\s*가입\s*나이[:\s]+(?:만\s*)?(\d+)세", text)
        if m:
            return int(m.group(1))
        return None

    def _find_insurance_periods_in_header(self, text: str) -> List[str]:
        """섹션 내 보험기간 컬럼 헤더 추출 (출현 순서 유지)"""
        combined = re.compile(r"\d+세만기|\d+년만기|종신")
        periods = []
        seen: set = set()
        for m in combined.finditer(text):
            val = self._normalize_period(m.group(0))
            if val not in seen:
                seen.add(val)
                periods.append(val)
        return periods

    def _find_payment_periods_in_section(self, text: str) -> List[str]:
        """섹션 내 납입기간 추출"""
        periods = []
        patterns = [r"\d+년납", r"전기납", r"일시납"]
        for pattern in patterns:
            for m in re.finditer(pattern, text):
                val = m.group(0)
                if val not in periods:
                    periods.append(val)
        return periods

    def _find_sub_types_in_section(self, text: str) -> List[str]:
        """섹션 내 세부보험종목 목록 추출"""
        sub_types = []
        patterns = [
            r"간편가입형(?:\(\d+년\))?",
            r"일반가입형(?:Ⅰ|Ⅱ|[IⅡ])?",
            r"건강가입형(?:Ⅰ|Ⅱ)?",
            r"표준체형",
            r"비흡연체형",
            r"\d+종\([^)]+\)",
            r"[가나다]종(?:\([^)]+\))?",
        ]
        for pattern in patterns:
            for m in re.finditer(pattern, text):
                val = m.group(0)
                if val not in sub_types:
                    sub_types.append(val)
        return sub_types

    def _normalize_period(self, raw: str) -> str:
        """보험기간 자연어 정규화"""
        raw = raw.strip()
        if "종신" in raw:
            return "종신"
        # 공백 제거 후 패턴 매칭 (예: "110세 만기" → "110세만기")
        compact = re.sub(r"\s+", "", raw)
        m = re.match(r"(\d+)세만기", compact)
        if m:
            return f"{m.group(1)}세만기"
        m = re.match(r"(\d+)년만기", compact)
        if m:
            return f"{m.group(1)}년만기"
        return raw

    def _extract_all_insurance_periods(self, text: str) -> List[str]:
        """텍스트에서 보험기간 목록 추출"""
        periods = []
        # 순서: 구체적 패턴 우선
        for pattern in [r"\d+세\s*만기", r"\d+년\s*만기"]:
            for m in re.finditer(pattern, text):
                val = self._normalize_period(m.group(0))
                if val not in periods:
                    periods.append(val)

        # 종신: 갱신형 종료나이/종료일 컨텍스트에서 나온 건 제외
        for m in re.finditer(r"종신(?!갱신)", text):
            pos = m.start()
            context_before = text[max(0, pos - 200):pos]
            # "재가입 종료 나이" 또는 "종료일은" 근처의 종신은 보험기간이 아님
            if re.search(r"재가입\s*종료\s*나이|종료일은", context_before):
                continue
            if "종신" not in periods:
                periods.append("종신")

        # 보험기간 테이블 내 'N년' 단순 기재 형식 (갱신형 실손)
        # "N년\n숫자세~" 패턴: 갱신형 테이블에서 보험기간 셀이 단독 N년으로 기재
        if not periods:
            for m in re.finditer(r"(\d+)년\s*\n\d+세\s*~", text):
                n = int(m.group(1))
                val = f"{n}년만기"
                if val not in periods:
                    periods.append(val)

        return periods

    def _extract_all_payment_periods(self, text: str) -> List[str]:
        """텍스트에서 납입기간 목록 추출"""
        periods = []
        patterns = [r"\d+년납", r"\d+세납", r"전기납", r"종신납", r"일시납"]
        for pattern in patterns:
            for m in re.finditer(pattern, text):
                val = m.group(0)
                if val not in periods:
                    periods.append(val)
        return periods

    def _extract_annuity_age_by_formula(self, text: str) -> List[Dict]:
        """
        연금보험 가입나이 공식 형식 감지 및 자동 계산.
        패턴1: '가입최고나이 : (연금개시나이-납입기간)세'
        패턴2: '0 ~ (연금개시나이-납입기간)세'  (미래로기업복지연금, 하이드림연금 등)
        연금개시나이 범위 × 납입기간 조합으로 가입나이 행 생성.
        GT ip=NaN, gender=NaN 이므로 ip='', gender=None 으로 생성.
        """
        formula_pat1 = r"가입최고나이[^\n]{0,30}\(연금개시나이\s*[-－]\s*납입기간\)세"
        formula_pat2 = r"0\s*[~～]\s*\(연금개시나이\s*[-－]\s*납입기간\)\s*세"
        if not (re.search(formula_pat1, text) or re.search(formula_pat2, text)):
            return []

        # 모든 연금개시나이 범위 중 최대 범위 사용 (1종 55~80, 2종 55~110 → 55~110)
        onset = self._extract_annuity_onset_range_max(text)
        if not onset:
            onset = self._extract_annuity_onset_range(text)
        if not onset:
            return []
        min_onset, max_onset = onset

        payment_periods = self._extract_all_payment_periods(text)
        if not payment_periods:
            return []

        # 가입최저나이 추출 (예: "가입최저나이 : 만 19세" → 19, 없으면 0)
        min_entry_age = 0
        m_min = re.search(r"가입최저나이\s*[:：]\s*만?\s*(\d+)\s*세", text)
        if m_min:
            min_entry_age = int(m_min.group(1))

        # 전기납 최소 납입연수 파악 (예: "전기납(10년이상)" → 10)
        min_elective_yrs = 10
        m = re.search(r"전기납\s*\((\d+)년\s*이상\)", text)
        if m:
            min_elective_yrs = int(m.group(1))

        rows = []
        seen: set = set()

        # 납입기간 공식 행 생성 (max = onset - payment_years)
        for onset_age in range(min_onset, max_onset + 1):
            for pp in payment_periods:
                if pp == "전기납":
                    n = min_elective_yrs
                    pp_key = f"{onset_age}세납"
                else:
                    n_m = re.match(r"(\d+)년납", pp)
                    if not n_m:
                        continue
                    n = int(n_m.group(1))
                    pp_key = pp

                max_age = onset_age - n
                if max_age < 0:
                    continue
                key = (pp_key, max_age)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "sub_type": "기본형",
                    "insurance_period": "",
                    "payment_period": pp_key,
                    "gender": None,
                    "min_age": min_entry_age,
                    "max_age": max_age,
                })

        # 거치형 공식 행 생성: 0 ~ (연금개시나이- 1)세 → max = onset - 1
        geochi_pat = r"거치형[^\n]{0,20}0\s*[~～]\s*\(연금개시나이\s*[-－]\s*1\)\s*세"
        if re.search(geochi_pat, text):
            for onset_age in range(min_onset, max_onset + 1):
                max_age = onset_age - 1
                if max_age < 0:
                    continue
                key = ("일시납_거치형", max_age)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "sub_type": "거치형",
                    "insurance_period": "",
                    "payment_period": "일시납",
                    "gender": None,
                    "min_age": min_entry_age,
                    "max_age": max_age,
                })

        # 즉시형 직접 범위 추가: '즉시형 만N세 ~ M세'
        soksi_m = re.search(r"즉시형[^\n]{0,10}만?\s*(\d+)\s*세\s*[~～]\s*(\d+)\s*세", text)
        if soksi_m:
            si_min, si_max = int(soksi_m.group(1)), int(soksi_m.group(2))
            key = ("즉시형", si_min, si_max)
            if key not in seen:
                seen.add(key)
                rows.append({
                    "sub_type": "즉시형",
                    "insurance_period": "",
                    "payment_period": "일시납",
                    "gender": None,
                    "min_age": si_min,
                    "max_age": si_max,
                })

        return rows

    def _extract_annuity_onset_range_max(self, text: str):
        """텍스트 내 모든 연금개시나이 범위를 찾아 최대 범위(min, max) 반환"""
        all_mins, all_maxes = [], []
        for pat in [
            r"(?:연금|보기)개시(?:나이|연령)[\s\S]{0,200}?만?\s*(\d+)\s*세\s*[~～]\s*(\d+)\s*세",
            r"(?:연금|보기)개시(?:나이|연령)[\s\S]{0,200}?(\d+)\s*[~～]\s*(\d+)\s*세",
        ]:
            for m in re.finditer(pat, text):
                v1, v2 = int(m.group(1)), int(m.group(2))
                if 40 <= v1 <= 80 and v1 < v2 <= 130:
                    all_mins.append(v1)
                    all_maxes.append(v2)
        if all_mins:
            return (min(all_mins), max(all_maxes))
        return None

    def _extract_annuity_onset_range(self, text: str):
        """연금개시나이 범위 추출 → (min_age, max_age) 또는 None
        전기납의 PP를 X{age}로 확장할 때 사용"""
        # "N세 ~ M세" 또는 "N ~ M세" 형식
        for pat in [
            r"(?:연금|보기)개시(?:나이|연령)[\s\S]{0,200}?(\d+)\s*세\s*[~～]\s*(\d+)\s*세",
            r"(?:연금|보기)개시(?:나이|연령)[\s\S]{0,200}?만?\s*(\d+)\s*세\s*[~～]\s*(\d+)\s*세",
            r"(?:연금|보기)개시(?:나이|연령)[\s\S]{0,200}?(\d+)\s*[~～]\s*(\d+)\s*세",
        ]:
            m = re.search(pat, text)
            if m:
                return (int(m.group(1)), int(m.group(2)))
        return None

    def _apply_exception(self, exception_config: dict, text: str) -> List[Dict]:
        """예외 룰 적용 (product_exceptions.json에 정의된 고정 데이터 반환)"""
        if "fixed_data" in exception_config:
            return exception_config["fixed_data"]
        if "pattern_override" in exception_config:
            pattern = exception_config["pattern_override"]
            results = []
            for m in re.finditer(pattern["regex"], text):
                row = {}
                for key, group_idx in pattern.get("groups", {}).items():
                    row[key] = m.group(group_idx)
                results.append(row)
            return results
        return []
