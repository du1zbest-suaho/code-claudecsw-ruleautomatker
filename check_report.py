import sys, json, glob, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')

df = pd.read_excel('output/reports/작업현황_20260310_230414.xlsx')

gt26 = pd.read_excel('data/existing/판매중_가입나이정보.xlsx')
gt27 = pd.read_excel('data/existing/판매중_보기납기정보.xlsx')
gt22 = pd.read_excel('data/existing/판매중_보기개시나이정보.xlsx')

def s26_keys_gt(dtcd):
    gf = gt26[(gt26['ISRN_KIND_DTCD'] == dtcd) & (gt26['MAX_AG'] != 999)]
    keys = set()
    for _, row in gf.iterrows():
        ip = str(row['ISRN_TERM_DVSN_CODE']) + str(int(row['MIN_ISRN_TERM'])) if pd.notna(row['ISRN_TERM_DVSN_CODE']) and pd.notna(row['MIN_ISRN_TERM']) else ''
        pp = str(row['PAYM_TERM_DVSN_CODE']) + str(int(row['MIN_PAYM_TERM'])) if pd.notna(row['PAYM_TERM_DVSN_CODE']) and pd.notna(row['MIN_PAYM_TERM']) else ''
        g = str(int(float(row['MINU_GNDR_CODE']))) if pd.notna(row['MINU_GNDR_CODE']) else ''
        keys.add((ip, pp, g, int(row['MIN_AG']), int(row['MAX_AG'])))
    return keys

def s26_keys_ex(dtcd):
    keys = set()
    for f in glob.glob(f'output/extracted/{dtcd}*_S00026_*_coded.json'):
        if 'A0' in f: continue  # 구버전 파일 제외
        with open(f, encoding='utf-8') as fp:
            d = json.load(fp)
        for r in d.get('coded_rows', []):
            ip = r.get('ISRN_TERM_INQY_CODE') or ''
            pp = r.get('PAYM_TERM_INQY_CODE') or ''
            g = '' if r.get('MINU_GNDR_CODE') is None else str(r['MINU_GNDR_CODE'])
            keys.add((ip, pp, g, int(r.get('MIN_AG', 0)), int(r.get('MAX_AG', 0))))
    return keys

def s27_keys_gt(dtcd):
    gf = gt27[gt27['ISRN_KIND_DTCD'] == dtcd]
    return set(zip(gf['ISRN_TERM_INQY_CODE'].fillna(''), gf['PAYM_TERM_INQY_CODE'].fillna('')))

def s27_keys_ex(dtcd):
    keys = set()
    for f in glob.glob(f'output/extracted/{dtcd}*_S00027_*_coded.json'):
        if 'A0' in f: continue
        with open(f, encoding='utf-8') as fp:
            d = json.load(fp)
        for r in d.get('coded_rows', []):
            keys.add((r.get('ISRN_TERM_INQY_CODE') or '', r.get('PAYM_TERM_INQY_CODE') or ''))
    return keys

# S00026 FAIL 중 miss<=10이고 NaN GT 아닌 것
print("=" * 70)
print("S00026 FAIL 중 non-NaN GT (접근 가능 후보)")
print("=" * 70)
fail_dtcds = df[df['가입가능나이_결과'] == 'FAIL']['ISRN_KIND_DTCD'].unique()
for dtcd in sorted(fail_dtcds):
    gk = s26_keys_gt(dtcd)
    ek = s26_keys_ex(dtcd)
    miss = gk - ek
    extra = ek - gk
    # NaN GT 여부 확인
    nan_gt = all(k[0] == '' and k[1] == '' for k in gk)
    if nan_gt or len(miss) == 0:
        continue
    print(f"\n  DTCD {dtcd}: GT={len(gk)}, EX={len(ek)}, miss={len(miss)}, extra={len(extra)}")
    print(f"  MISS: {sorted(miss)[:5]}")
    print(f"  EXTRA: {sorted(extra)[:5]}")

# S00027 FAIL 중 접근 가능 후보
print("\n" + "=" * 70)
print("S00027 불일치 중 접근 가능 후보 (구조적 연금보험 제외)")
print("=" * 70)
ANNUITY_DTCDS = {1228, 1571, 1629, 1745, 1772, 1809}
fail27 = df[df['보기납기_결과'] == '불일치']['ISRN_KIND_DTCD'].unique()
for dtcd in sorted(fail27):
    if dtcd in ANNUITY_DTCDS:
        continue
    gk = s27_keys_gt(dtcd)
    ek = s27_keys_ex(dtcd)
    miss = gk - ek
    extra = ek - gk
    print(f"\n  DTCD {dtcd}: GT={len(gk)}, EX={len(ek)}, miss={len(miss)}, extra={len(extra)}")
    print(f"  MISS: {sorted(miss)[:8]}")
    print(f"  EXTRA: {sorted(extra)[:8]}")
