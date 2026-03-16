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
        # 만N세 줄바꿈 아티팩트 보정: "만N세\n~M세" → "만N세~M세", "만N세~M\n세" → (already fixed above)
        # e정기보험 등: 만19세\n~49세 형태 → 만19세~49세
        text = re.sub(r'(만\d+세)\n~', r'\1~', text)
        # 만N세 접두어 제거: "만19세" → "19세" (가입나이 파싱에서 만 접두어 무시)
        text = re.sub(r'만(\d+세)', r'\1', text)

        results = []

        # 패턴 A-0-4: 연금보험 납입기간별 오프셋 테이블 형식
        # 예: 스마트V연금(1758), 스마트하이브리드연금(2042), Wealth직장인연금(1833)
        # "가입최고나이 : 연금개시나이, 납입기간별로" + 각 납입기간별 (연금개시나이-M)세 오프셋
        annuity_offset_rows = self._extract_annuity_onset_offset_table(text)
        if annuity_offset_rows:
            return annuity_offset_rows

        # 패턴 A-0-5: 연금보험 연금개시나이×납입기간 테이블 (max_age 셀 직접 기재 형식)
        # 예: 연금보험Enterprise — 연금개시나이별 row, 거치형/N년납/전기납 columns, 셀=max_age
        annuity_onset_rows = self._parse_annuity_onset_table(text)
        if annuity_onset_rows:
            return annuity_onset_rows

        # 패턴 A-1: 연금보험 가입최고나이 공식 "(연금개시나이-납입기간)세" 형식
        # 납입기간 × 연금개시나이 조합을 자동 계산하여 생성
        annuity_rows = self._extract_annuity_age_by_formula(text)
        if annuity_rows:
            # 연금전환특약 추가 rows (1745 스마트하이드림 등)
            annuity_rows.extend(self._extract_annuity_conversion_rows(text))
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
        payment_pattern = r"(\d+\s*년납|\d+\s*세납|전기납|일시납)[\s\-]+((?:만?\d+\s*세?\s*[~～\-]\s*\d+\s*세\s*)+)"
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
                elif insurance_periods and 0 < len(ranges) < len(insurance_periods):
                    # 일부 IP 컬럼이 "-"(불가)인 희소 행: e정기보험 순수보장형처럼
                    # 납입기간 레이블 뒤와 첫 범위 사이 텍스트에서 "-" 개수 세어 skip 결정
                    between = part[pm.end(1):pm.start(2)]
                    dash_count = len(re.findall(r'(?<!\d)-(?!\d)', between))
                    n_skip = dash_count if dash_count == len(insurance_periods) - len(ranges) else (len(insurance_periods) - len(ranges))
                    start_idx = n_skip
                    if start_idx + len(ranges) == len(insurance_periods):
                        for i, (min_a, max_a) in enumerate(ranges):
                            ip = insurance_periods[start_idx + i]
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
                elif not true_ips:
                    # IP가 남자/여자 컬럼 헤더 이후에 위치하는 형식
                    # 예: 경영인H정기보험 — 보험기간\n납입기간\n남자\n여자\n90세만기\n전기납\n남자범위\n여자범위
                    first_female_m = re.search(r"여\s*자", section)
                    if first_female_m:
                        post_headers = section[first_female_m.end():first_female_m.end() + 500]
                        col_ips = self._find_insurance_periods_in_header(post_headers)
                        if col_ips:
                            candidate_results = []
                            seen_pay_ranges: set = set()
                            for pm in re.finditer(payment_pattern, section):
                                payment = pm.group(1).replace(" ", "")
                                ranges_text = pm.group(2)
                                ranges = [(int(a), int(b)) for a, b in re.findall(range_pattern, ranges_text)]
                                if len(ranges) == len(col_ips) * 2:
                                    key_pr = (payment, tuple(ranges))
                                    if key_pr in seen_pay_ranges:
                                        continue
                                    seen_pay_ranges.add(key_pr)
                                    for idx, ip in enumerate(col_ips):
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
        # 주의: 이 메서드는 sparse 처리 없이 직접 rows를 만듦 → \s+ 유지 ([\s\-]+ 사용 불가)
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
            elif insurance_periods and len(sub_types) >= 2 and len(insurance_periods) == 1 and len(maxes) == len(sub_types) * 2:
                # 세부보험종목별 × 성별 최고나이 (단일 보험기간)
                # 예: 1종남, 1종여, 2종남, 2종여 (종신보험 기납입플러스형/기본형 등)
                ip = insurance_periods[0]
                for sub_idx, sub_type in enumerate(sub_types):
                    results.append({
                        "sub_type": sub_type,
                        "insurance_period": ip,
                        "payment_period": payment,
                        "gender": "남자",
                        "min_age": min_age,
                        "max_age": maxes[sub_idx * 2]
                    })
                    results.append({
                        "sub_type": sub_type,
                        "insurance_period": ip,
                        "payment_period": payment,
                        "gender": "여자",
                        "min_age": min_age,
                        "max_age": maxes[sub_idx * 2 + 1]
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
        # 페이지 구분자로 테이블이 분할된 경우 처리 (cross-page table continuation)
        if not results:
            section_clean = re.sub(r'--- 페이지 \d+ ---[ \t]*\n', '', section)
            section_clean = re.sub(r'\n\d+ - \d+ - \d+[ \t]*\n', '\n', section_clean)
            section_clean = re.sub(r'\n구분[ \t]*\n최고가입나이[ \t]*\n', '\n', section_clean)
            gender_pattern = r"(\d+\s*년납|전기납|일시납)\s+남자\s+(\d+)\s*세\s+여자\s+(\d+)\s*세"
            for m in re.finditer(gender_pattern, section_clean):
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

        # 확정기간연금형 감지 → X세만기 행 일괄 생성 (우선 처리)
        definite_rows = self._extract_definite_period_annuity_s27_rows(text)
        if definite_rows:
            return definite_rows

        # 증액계약 섹션 제거: 사망/보장보험금 증액계약 전용 납입기간(일시납) 오탐 방지
        text = re.split(r'\n\s*\(\d+\)\s*사망보험금\s*증액계약', text)[0]
        text = re.split(r'\n\s*\(\d+\)\s*보장보험금\s*증액계약', text)[0]

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
        # n_year_info: {n → True} 이면 해당 n의 모든 출현이 종신/고령 경계 컨텍스트
        n_year_info: dict = {}

        # "계약일(부터|이후) N년 경과시점" – 보장형 기준사망보험금 지급 시작 시점
        # 단, "의 장기유지보너스" 뒤에 오는 경우는 제외 (장기유지보너스 경과시점)
        for m in re.finditer(r"계약일\s*(?:부터|이후)\s*(\d+)년\s*경과시점", text):
            context_after = text[m.end():m.end()+40]
            if "장기유지" in context_after or "보너스" in context_after:
                continue
            n = int(m.group(1))
            # 종신/고령 경계 컨텍스트 감지 (예: "계약일부터 10년 경과시점부터 종신")
            is_jongsin = bool(re.search(r'부터\s*(?:종신|\d+세\s*계약해당)', context_after))
            if n not in n_year_info:
                n_year_info[n] = is_jongsin
            else:
                n_year_info[n] = n_year_info[n] and is_jongsin

        # 전환일 패턴 제거 (스마트전환형 계약 전용 → 주계약 오탐 방지)

        # "보험계약일 이후 N년이 경과한" – 스마트연금전환특약 대상계약 조건
        # 앞선 패턴에서 매칭 없을 때만 사용 (false positive 방지)
        if not n_year_info:
            for m in re.finditer(r"보험계약일\s*이후\s*(\d+)년이?\s*경과한", text):
                n = int(m.group(1))
                n_year_info[n] = False

        if n_year_info:
            min_n = min(n_year_info)
            # 종신/고령 경계 컨텍스트에서만 출현한 N은 제외 (단, 최솟값은 항상 포함)
            n_years = {n for n, all_jongsin in n_year_info.items()
                       if not all_jongsin or n == min_n}
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
            # 전환시점 근처의 종신은 전환형 계약 전용 → 보험기간 아님
            if val == "종신":
                ctx_before = text[max(0, m.start() - 200):m.start()]
                if re.search(r"전환시점", ctx_before):
                    continue
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
            # 개인/부부형 연금 상품 세부 종목
            r"개인형",
            r"신부부형",
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
                # 국고채/회사채/증권 등 금융 참조 문구 근처 → 보험기간 아님 (1758 오탐 방지)
                ctx_around = text[max(0, m.start()-30):m.end()+30]
                if re.search(r"국고채|회사채|증권|이율|수익률", ctx_around):
                    continue
                val = self._normalize_period(m.group(0))
                if val not in periods:
                    periods.append(val)

        # 종신: 갱신형 종료나이/종료일 또는 전환시점 컨텍스트에서 나온 건 제외
        for m in re.finditer(r"종신(?!갱신)", text):
            pos = m.start()
            context_before = text[max(0, pos - 200):pos]
            # "재가입 종료 나이" 또는 "종료일은" 근처의 종신은 보험기간이 아님
            if re.search(r"재가입\s*종료\s*나이|종료일은", context_before):
                continue
            # "전환시점" 근처의 종신은 스마트전환형 계약 내용 → 보험기간 아님 (1758 오탐 방지)
            if re.search(r"전환시점", context_before):
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
        """텍스트에서 납입기간 목록 추출.
        'N~M년납' 또는 'N~M년,' 범위 표현도 지원 (예: 5~10년납 또는 5~10년, → 모두 포함)
        """
        periods = []
        # N~M년납 또는 N~M년, 범위 확장 (예: 5~10년납 또는 5~10년, → 5,6,7,8,9,10년납)
        for m in re.finditer(r"(\d+)\s*[~～]\s*(\d+)\s*년[납,]", text):
            n1, n2 = int(m.group(1)), int(m.group(2))
            if 1 <= n1 < n2 <= 50:
                for n in range(n1, n2 + 1):
                    val = f"{n}년납"
                    if val not in periods:
                        periods.append(val)

        # "N년납 이상/미만/초과" 조건문 위치 수집 → false positive 제거용
        condition_pos = {m.start() for m in re.finditer(r"\d+년납\s*(?:이상|이하|미만|초과)", text)}

        patterns = [r"\d+년납", r"\d+세납", r"전기납", r"종신납", r"일시납"]
        for pattern in patterns:
            for m in re.finditer(pattern, text):
                # 조건문("N년납 이상") 에서 나온 match → skip
                if any(m.start() >= cp and m.start() <= cp + 20 for cp in condition_pos):
                    continue
                val = m.group(0)
                # 종신납: 전환시점 근처 컨텍스트 → 스마트전환형 계약 전용 → 오탐 방지
                if val == "종신납":
                    ctx_before = text[max(0, m.start() - 300):m.start()]
                    if re.search(r"전환시점", ctx_before):
                        continue
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
        # GT에서 거치형/일시납은 pp=NaN(''로 저장) → payment_period="" 사용
        geochi_pat = r"거치형[\s\S]{0,30}0\s*[~～]\s*\(연금개시나이\s*[-－]\s*1\)\s*세"
        if re.search(geochi_pat, text):
            for onset_age in range(min_onset, max_onset + 1):
                max_age = onset_age - 1
                if max_age < 0:
                    continue
                key = ("거치형_nan", max_age)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "sub_type": "거치형",
                    "insurance_period": "",
                    "payment_period": "",  # GT: 거치형=일시납은 pp=NaN으로 저장
                    "gender": None,
                    "min_age": min_entry_age,
                    "max_age": max_age,
                })

        # 즉시형 직접 범위 추가: '즉시형 만N세 ~ M세'
        # GT에서 즉시형은 pp=NaN('') 으로 저장되므로 payment_period="" 사용
        soksi_m = re.search(r"즉시형[^\n]{0,10}만?\s*(\d+)\s*세\s*[~～]\s*(\d+)\s*세", text)
        if soksi_m:
            si_min, si_max = int(soksi_m.group(1)), int(soksi_m.group(2))
            key = ("즉시형", si_min, si_max)
            if key not in seen:
                seen.add(key)
                rows.append({
                    "sub_type": "즉시형",
                    "insurance_period": "",
                    "payment_period": "",  # GT: 즉시형은 pp=NaN으로 저장
                    "gender": None,
                    "min_age": si_min,
                    "max_age": si_max,
                })

        # 연금전환특약 확정기간연금형: min=si_min, max=99 (GT 관례)
        # '연금전환특약' + '확정기간' 텍스트가 있을 경우 추가
        if soksi_m and re.search(r"연금전환특약", text) and re.search(r"확정기간", text):
            si_min = int(soksi_m.group(1))
            key_conv = ("연금전환_확정기간", si_min, 99)
            if key_conv not in seen:
                seen.add(key_conv)
                rows.append({
                    "sub_type": "연금전환특약_확정기간",
                    "insurance_period": "",
                    "payment_period": "",
                    "gender": None,
                    "min_age": si_min,
                    "max_age": 99,
                })

        return rows

    def _extract_annuity_onset_range_max(self, text: str):
        """텍스트 내 모든 연금개시나이 범위를 찾아 최대 범위(min, max) 반환.
        각 '연금개시나이' 출현 위치에서 200자 이내의 모든 나이 범위를 탐색.
        """
        all_mins, all_maxes = [], []
        age_range_pat = re.compile(r"만?\s*(\d+)\s*세\s*[~～]\s*(\d+)\s*세")
        age_range_pat2 = re.compile(r"(\d+)\s*[~～]\s*(\d+)\s*세")

        for anchor in re.finditer(r"(?:연금|보기)개시(?:나이|연령)", text):
            window = text[anchor.start():anchor.start() + 300]
            for pat in [age_range_pat, age_range_pat2]:
                for m in pat.finditer(window):
                    v1, v2 = int(m.group(1)), int(m.group(2))
                    if 40 <= v1 <= 80 and v1 < v2 <= 130:
                        all_mins.append(v1)
                        all_maxes.append(v2)
        if all_mins:
            return (min(all_mins), max(all_maxes))
        return None

    def _extract_definite_period_annuity_s27_rows(self, text: str) -> List[Dict]:
        """
        확정기간연금형 S00027 행 생성.

        트리거: "확정기간연금" + "N년형" 패턴이 존재.

        GT 구조 (1571 연금보험Enterprise 예시):
          - 적립형 종신연금 (A999): A999 × (N년납들 + X{onset_min}~X{onset_max}납 + N0)
          - 거치형 종신연금 (A999): A999 × N0
          - 적립형 확정기간 N년형: X{onset+N}세만기 × (N년납들 + X{onset}납 + N0)
          - 거치형 확정기간 N년형: X{onset+N}세만기 × N0

        규칙:
          - 전기납 = 연금개시나이세납 = X{onset}납
          - 일시납(거치형) = N0
          - 보험기간 X{m}세만기의 전기납 = X{m-N}납 (N=확정기간 년수)
        """
        # 트리거: "확정기간연금" + "N년형" 목록
        if not re.search(r"확정기간연금", text):
            return []

        # 확정기간 년수 목록 (예: 5년형, 10년형, 15년형, 20년형 → [5,10,15,20])
        fixed_terms = []
        for m in re.finditer(r"(\d+)년형", text):
            n = int(m.group(1))
            if 1 <= n <= 50 and n not in fixed_terms:
                fixed_terms.append(n)
        if not fixed_terms:
            return []
        fixed_terms = sorted(fixed_terms)

        # 연금개시나이 범위
        onset_range = self._extract_annuity_onset_range(text)
        if not onset_range:
            return []
        min_onset, max_onset = onset_range

        # 적립형 N년납 목록 (전기납/일시납 제외)
        all_pps = self._extract_all_payment_periods(text)
        n_year_pays = [pp for pp in all_pps if re.match(r"^\d+년납$", pp)]

        # 거치형(일시납=N0) 여부
        has_ilshinap = "일시납" in all_pps

        # 전기납(=연금개시나이세납) 여부 — 없으면 X세납 행 생성 안 함
        has_jeonginap = "전기납" in all_pps

        rows = []
        seen: set = set()

        def add_row(ip: str, pp: str) -> None:
            key = (ip, pp)
            if key not in seen:
                seen.add(key)
                rows.append({
                    "sub_type": "기본형",
                    "insurance_period": ip,
                    "payment_period": pp,
                })

        # 1) 종신연금 (A999): 적립형 N년납 + X{onset_min..max}세납(전기납이 있을 때만)
        for pp in n_year_pays:
            add_row("종신", pp)
        if has_jeonginap:
            for onset in range(min_onset, max_onset + 1):
                add_row("종신", f"{onset}세납")
        # 거치형 일시납
        if has_ilshinap:
            add_row("종신", "일시납")

        # 2) 확정기간연금: 각 N년형 × 연금개시나이별
        for n_fixed in fixed_terms:
            for onset in range(min_onset, max_onset + 1):
                ip_age = onset + n_fixed
                ip = f"{ip_age}세만기"
                # 적립형: N년납 + X{onset}세납(전기납 있을 때만)
                for pp in n_year_pays:
                    add_row(ip, pp)
                if has_jeonginap:
                    add_row(ip, f"{onset}세납")
                # 거치형: 일시납
                if has_ilshinap:
                    add_row(ip, "일시납")

        return rows

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

    def _extract_annuity_onset_offset_table(self, text: str) -> List[Dict]:
        """
        연금보험 납입기간별 오프셋 테이블 형식 파싱.
        트리거: "가입최고나이 : 연금개시나이, 납입기간별로 아래와 같음"
        형식: 각 납입기간(N년납/전기납)별 "(연금개시나이 - M)세" 오프셋 기재.
        [남자]/[여자] 블록 없이 오프셋만 기재된 형식.
        예: 스마트V연금보험(1758), 스마트하이브리드연금보험(2042), Wealth직장인연금보험(1833)
        """
        trigger_pat = r"가입최고나이[^\n]{0,30}연금개시나이[^\n]{0,30}납입기간별로\s*아래와\s*같음"
        if not re.search(trigger_pat, text):
            return []

        # [남자]/[여자] 블록이 있으면 Enterprise 형식 → 기존 함수에 위임
        if re.search(r"\[\s*남\s*자\s*\]|\[\s*여\s*자\s*\]", text):
            return []

        # 가입최저나이 추출
        min_age = 0
        m_min = re.search(r"가입최저나이\s*[:：]\s*(?:만\s*)?(\d+)세", text)
        if m_min:
            min_age = int(m_min.group(1))

        # 가입최저나이 예외 파싱 (예: "단, 3종(연금강화형)의 경우 가입최저나이는 40세로 한다")
        exception_min_age = None
        exception_sub_type_hint = None  # 예외가 적용될 특정 종/형 힌트
        m_exc = re.search(r"단[,，]\s*([^\n]*?)가입최저나이는\s*(?:만\s*)?(\d+)세", text)
        if m_exc:
            exception_sub_type_hint = m_exc.group(1).strip()
            exception_min_age = int(m_exc.group(2))

        # 연금개시나이 범위 추출 — 모든 "연금개시나이" 앵커 근처에서 "N세~M세" 탐색 후 min/max
        onset_ranges = []
        for anchor in re.finditer(r"연금개시나이", text):
            snippet = text[anchor.start():anchor.start() + 300]
            for m in re.finditer(r"(\d+)\s*세\s*[~～]\s*(\d+)\s*세", snippet):
                a, b = int(m.group(1)), int(m.group(2))
                if 20 <= a <= 90 and 40 <= b <= 120:
                    onset_ranges.append((a, b))
        if not onset_ranges:
            return []
        onset_min = min(r[0] for r in onset_ranges)
        onset_max = max(r[1] for r in onset_ranges)

        # 오프셋 맵 파싱: "N 년납 ... (연금개시나이 – offset1)세 [... (연금개시나이 – offset2)세]"
        # offset1 = 적립형, offset2 = 거치형 (같은 행 두 번째 컬럼인 경우)
        offset_map: Dict[str, int] = {}   # "N년납" → offset (적립형)
        geochi_offset: Optional[int] = None

        for m in re.finditer(
            r"(\d+)\s*년납[\s\n]{0,30}\(연금개시나이\s*[-–—]\s*(\d+)\)\s*세(?:[\s\n]{0,30}\(연금개시나이\s*[-–—]\s*(\d+)\)\s*세)?",
            text
        ):
            n_yrs = int(m.group(1))
            offset1 = int(m.group(2))
            offset_map[f"{n_yrs}년납"] = offset1
            if m.group(3) is not None and geochi_offset is None:
                geochi_offset = int(m.group(3))

        # 전기납
        m_jeongi = re.search(r"전기납[\s\n]{0,30}\(연금개시나이\s*[-–—]\s*(\d+)\)\s*세", text)
        jeongi_offset: Optional[int] = int(m_jeongi.group(1)) if m_jeongi else None

        if not offset_map and jeongi_offset is None and geochi_offset is None:
            return []

        sub_types = self._find_sub_types_in_section(text) or ["기본형"]

        # 납입기간 섹션에서 종별 납입 방식 파싱
        # 패턴: "(N) 종이름1[, 종이름2] \n - 적립형 : Xn납, ... \n - 거치형 : ..."
        # 결과: sub_type → {"adori_payms": [...], "has_geochi": bool}
        sub_paym_info: Dict[str, Dict] = {}
        for blk in re.finditer(
            r"\(\d+\)\s*([^\n]+)\n((?:\s*[-·‐]\s*[^\n]+\n){1,6})",
            text
        ):
            sub_names_str = blk.group(1)
            body = blk.group(2)
            # 이 블록에 언급된 "N종(이름)" 목록
            block_subs = re.findall(r"\d+종\([^)]+\)", sub_names_str)
            if not block_subs:
                continue
            adori_m = re.search(r"적립형\s*:\s*([^-\n]+)", body)
            has_geochi_blk = bool(re.search(r"거치형", body))
            adori_payms: List[str] = re.findall(r"\d+년납", adori_m.group(1)) if adori_m else []
            has_adori_blk = bool(adori_m)
            for bs in block_subs:
                for actual in sub_types:
                    if bs in actual or actual in bs:
                        sub_paym_info[actual] = {
                            "adori_payms": adori_payms,
                            "has_adori": has_adori_blk,
                            "has_geochi": has_geochi_blk,
                        }

        rows: List[Dict] = []
        seen: set = set()

        def add_row(sub_type, pp, mn, mx):
            key = (sub_type, pp, mn, mx)
            if key not in seen:
                seen.add(key)
                rows.append({
                    "sub_type": sub_type,
                    "insurance_period": "",
                    "payment_period": pp,
                    "gender": None,
                    "min_age": mn,
                    "max_age": mx,
                })

        for sub_type in sub_types:
            # 이 sub_type에 exception_min_age가 적용되는지 판단
            if exception_min_age is not None and exception_sub_type_hint:
                hint_tokens = re.findall(r'\d+종|\w+형', exception_sub_type_hint)
                exc_applies = any(token in sub_type for token in hint_tokens) if hint_tokens else True
            else:
                exc_applies = False  # 힌트 없고 예외 없으면 기본 최저나이 사용

            # 실제 사용할 최저나이: 예외 적용 종이면 exception_min_age, 아니면 min_age
            effective_min = exception_min_age if (exc_applies and exception_min_age is not None) else min_age

            # 납입기간 섹션 정보에서 이 종의 납입 방식 결정
            paym_info = sub_paym_info.get(sub_type, {})
            adori_payms: List[str] = paym_info.get("adori_payms", [])  # 비어있으면 전체 offset_map 사용
            has_adori = paym_info.get("has_adori", True)  # 기본값: 적립형 행 생성
            # 거치형 행 생성 여부: 납입기간 섹션에 거치형이 있거나, 미파싱 시 "거치형" sub_type이면 생성
            if paym_info:
                is_geochi_sub = paym_info.get("has_geochi", False)
            else:
                is_geochi_sub = "거치형" in sub_type

            # 사용할 적립형 오프셋 맵 결정
            if adori_payms:
                effective_offset_map = {k: v for k, v in offset_map.items() if k in adori_payms}
            else:
                effective_offset_map = offset_map

            for onset_age in range(onset_min, onset_max + 1):
                # 적립형 납입기간별 (적립형이 있는 종에만)
                if has_adori:
                    for pp_str, offset in effective_offset_map.items():
                        max_age = onset_age - offset
                        add_row(sub_type, pp_str, effective_min, max_age)

                    # 전기납 → "{onset_age}세납"
                    if jeongi_offset is not None:
                        pp_j = f"{onset_age}세납"
                        max_age_j = onset_age - jeongi_offset
                        add_row(sub_type, pp_j, effective_min, max_age_j)

                # 거치형 (payment_period="") — 거치형 납입 방식이 있는 종에만 생성
                if geochi_offset is not None and is_geochi_sub:
                    max_age_g = onset_age - geochi_offset
                    add_row(sub_type, "", effective_min, max_age_g)

        return rows

    def _parse_annuity_onset_table(self, text: str) -> List[Dict]:
        """
        연금보험 연금개시나이×납입기간 테이블 파싱.
        "가입최고나이 : 연금개시나이, 납입기간별로" 트리거 조건.
        예: 연금보험Enterprise — 연금개시나이별 row, 거치형/N년납/전기납 columns, 셀=max_age 정수.

        구조:
          연금개시나이  거치형  7년납  10년납  15년납  20년납  전기납
          45세         41     34     32     29     24     31
          ...
        [ 남 자 ] / [ 여 자 ] 성별 구분 두 테이블

        반환: [{"sub_type":"기본형","insurance_period":"","payment_period":pp,
                "gender":gender,"min_age":min_age,"max_age":max_age}, ...]
        """
        # 트리거: "가입최고나이 : 연금개시나이, 납입기간별로"
        if not re.search(r"가입최고나이[^\n]{0,50}연금개시나이[^\n]{0,50}납입기간별", text):
            return []

        # 가입최저나이 추출
        min_age = 0
        m_min = re.search(r"가입최저나이[:\s]+(?:만\s*)?(\d+)세", text)
        if m_min:
            min_age = int(m_min.group(1))

        rows = []
        seen: set = set()

        # 성별 블록 분리: [ 남 자 ] ... [ 여 자 ] ...
        gender_block_pat = re.compile(r"\[\s*남\s*자\s*\]|\[\s*여\s*자\s*\]")
        gender_blocks = list(gender_block_pat.finditer(text))

        if not gender_blocks:
            return []

        block_data = []
        for i, gm in enumerate(gender_blocks):
            gender_str = re.sub(r"[\[\]\s]", "", gm.group(0))  # 남자 or 여자
            block_end = gender_blocks[i + 1].start() if i + 1 < len(gender_blocks) else len(text)
            block_text = text[gm.end():block_end]
            block_data.append((gender_str, block_text))

        for gender_str, block_text in block_data:
            # 헤더 행 탐지: "거치형", "N년납", "전기납" 등이 있는 줄 (멀티라인 헤더 지원)
            # 실제 PDF: 거치형 / 적립형(sub) / 7년납 / 10년납 / 15년납 / 20년납 / 전기납 이 각각 별도 줄
            header_columns: Optional[List[str]] = None
            lines = block_text.splitlines()
            i = 0
            while i < len(lines):
                line = lines[i].strip()

                # 헤더 탐지: 거치형 또는 전기납 또는 N년납이 있는 줄에서 시작
                if re.search(r"거치형|\d+년납|전기납", line):
                    # 연속된 헤더 줄들을 수집 (거치형, N년납, 전기납만 포함)
                    header_tokens = []
                    j = i
                    # 데이터 행(N세) 이전까지 헤더 줄들을 수집
                    # 비식별 sub-header(적립형 등)는 스킵하고 계속 진행
                    consecutive_non_header = 0
                    while j < len(lines):
                        hline = lines[j].strip()
                        # 스킵: 페이지 구분자, 빈 줄
                        if re.match(r"^---", hline) or hline == "":
                            j += 1
                            consecutive_non_header = 0
                            continue
                        # 거치형 추가
                        if re.match(r"^거치형$", hline):
                            header_tokens.append("거치형")
                            j += 1
                            consecutive_non_header = 0
                            continue
                        # N년납 추가
                        ny_m = re.match(r"^(\d+년납)$", hline)
                        if ny_m:
                            header_tokens.append(ny_m.group(1))
                            j += 1
                            consecutive_non_header = 0
                            continue
                        # 전기납 추가
                        if re.match(r"^전기납$", hline):
                            header_tokens.append("전기납")
                            j += 1
                            consecutive_non_header = 0
                            continue
                        # 동일 줄에 여러 납입기간이 있는 경우
                        if re.search(r"\d+년납|전기납|거치형", hline):
                            for m in re.finditer(r"(거치형|\d+년납|전기납)", hline):
                                header_tokens.append(m.group(1))
                            j += 1
                            consecutive_non_header = 0
                            continue
                        # 데이터 행(N세) → 헤더 수집 종료
                        if re.match(r"(\d+)세\s*$", hline):
                            break
                        # 비식별 sub-header: 페이지 번호, 한글 서브섹션명(적립형 등) → 스킵하되 카운트
                        consecutive_non_header += 1
                        if consecutive_non_header > 3:
                            # 너무 많은 비식별 줄 → 헤더가 끝났다고 판단
                            break
                        j += 1
                    if header_tokens:
                        header_columns = header_tokens
                    i = j
                    continue

                # 데이터 행 탐지: "N세" 로 시작하는 줄 → 연금개시나이 행
                onset_m = re.match(r"(\d+)세\s*$", line)
                if onset_m and header_columns:
                    onset_age = int(onset_m.group(1))
                    # 다음 len(header_columns)개 숫자 줄 수집
                    vals = []
                    j = i + 1
                    while j < len(lines) and len(vals) < len(header_columns):
                        v_line = lines[j].strip()
                        # 페이지 구분자/빈 줄/헤더 재시작은 스킵
                        if re.match(r"^---", v_line) or v_line == "":
                            j += 1
                            continue
                        # 페이지 번호 행 스킵 (예: "１- 3")
                        if re.match(r"^[１-９\d\s*-]+\d+\s*$", v_line) and not re.match(r"^\d+$", v_line):
                            j += 1
                            continue
                        # 헤더 반복 (멀티페이지) → 헤더 재파싱으로 이동 (break로 현재 데이터 행 종료)
                        if re.search(r"거치형|전기납|\d+년납|연금개시나이", v_line):
                            break
                        # 순수 정수 셀 값
                        v_m = re.match(r"^(\d+)$", v_line)
                        if v_m:
                            vals.append(int(v_m.group(1)))
                            j += 1
                            continue
                        # 다음 연금개시나이 행 또는 비정수 행 → 데이터 수집 종료
                        break

                    if len(vals) == len(header_columns):
                        for col_idx, col_name in enumerate(header_columns):
                            max_age_val = vals[col_idx]
                            if max_age_val < 0:
                                continue
                            # 납입기간 코드 결정
                            if col_name == "거치형":
                                pp = ""  # GT에서 거치형=일시납은 pp=NaN으로 저장
                            elif col_name == "전기납":
                                pp = f"{onset_age}세납"
                            else:
                                pp = col_name  # N년납
                            key = (pp, gender_str, max_age_val)
                            if key not in seen:
                                seen.add(key)
                                rows.append({
                                    "sub_type": "기본형",
                                    "insurance_period": "",
                                    "payment_period": pp,
                                    "gender": gender_str,
                                    "min_age": min_age,
                                    "max_age": max_age_val,
                                })
                    i = j
                    continue
                i += 1

        return rows

    def _extract_annuity_conversion_rows(self, text: str) -> List[Dict]:
        """
        연금전환특약 가입나이 추출 (1745 스마트하이드림연금보험 등).
        "[...연금전환특약]" 섹션을 탐지하여 가입나이 행을 별도로 반환.
        주계약 formula 행과 합산된다.

        GT 구조 (1745):
          ITCD 287: (ip='', pp='', gender=None, min=55, max=80) ← 종신연금형 (주계약 연금개시나이 상한)
          ITCD 288-299: (ip='', pp='', gender=None, min=55, max=99) ← 확정기간연금형
        """
        # 트리거: "[...연금전환특약]" 섹션이 존재
        bracket_m = re.search(r"\[[^\]]*연금전환특약[^\]]*\]", text)
        if not bracket_m:
            return []

        rows = []
        seen: set = set()
        conv_section = text[bracket_m.start():bracket_m.start() + 3000]

        # 가입최소나이: 연금지급 개시시점 표에서 첫 번째 나이 값 (55세 등)
        # 또는 "가입최저나이 : N세" 패턴
        conv_min = None
        min_explicit = re.search(r"가입최저나이[:\s]+(?:만\s*)?(\d+)세", conv_section)
        if min_explicit:
            conv_min = int(min_explicit.group(1))
        else:
            # 연금지급 개시시점 테이블에서 최소 나이 추출
            # 테이블 형식: "N세" 들이 나열됨 (55세, 56세, ...) → 가장 작은 값
            onset_ages = [int(m.group(1)) for m in re.finditer(r"\b(\d+)세\s*\n", conv_section)
                          if 50 <= int(m.group(1)) <= 70]
            if onset_ages:
                conv_min = min(onset_ages)

        if conv_min is None:
            return []

        # 주계약 연금개시나이 최대값 추출 (종신연금형 max_age 기준)
        # 주계약 섹션에서 "만 N세~M세" 또는 "N세~M세" 형식
        onset_max_from_main = None
        main_onset_m = re.search(
            r"연금개시나이[\s\S]{0,200}?만?\s*(\d+)\s*세\s*[~～]\s*(\d+)\s*세", text[:bracket_m.start()]
        )
        if main_onset_m:
            onset_max_from_main = int(main_onset_m.group(2))

        # 확정기간연금형 여부 판단: 섹션에 "확정기간" 키워드 포함
        has_jeonggi = bool(re.search(r"확정기간", conv_section))

        # 종신연금형 여부: 주계약에 포함되어 있거나 섹션에 직접 언급
        # → max_age = 주계약 연금개시나이 max (예: 80세)
        if onset_max_from_main:
            key_jong = ("", "", None, conv_min, onset_max_from_main)
            if key_jong not in seen:
                seen.add(key_jong)
                rows.append({
                    "sub_type": "기본형",
                    "insurance_period": "",
                    "payment_period": "",
                    "gender": None,
                    "min_age": conv_min,
                    "max_age": onset_max_from_main,
                })

        # 확정기간연금형: max_age = 99 (연금가입 나이 상한, 사업방법서 관행)
        if has_jeonggi:
            key_hwa = ("", "", None, conv_min, 99)
            if key_hwa not in seen:
                seen.add(key_hwa)
                rows.append({
                    "sub_type": "기본형",
                    "insurance_period": "",
                    "payment_period": "",
                    "gender": None,
                    "min_age": conv_min,
                    "max_age": 99,
                })

        return rows

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
