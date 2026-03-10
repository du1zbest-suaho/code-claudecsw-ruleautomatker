import sys, re, glob
sys.path.insert(0, '.')
from rules.extraction_rules import ExtractionRules
sys.stdout.reconfigure(encoding='utf-8')
rules = ExtractionRules()

tests = [
    '기본형_급여_실손의료비보장보험_계약전환_단체개인전환_개인중지재개용_갱신형_무배당_combined.txt',
    '스마트H상해보험_무배당_combined.txt',
    'H종신보험_무배당_combined.txt',
    'e암보험_비갱신형_무배당_combined.txt',
    '튼튼이_치아보험_갱신형_무배당_combined.txt',
]
for fname in tests:
    with open(f'output/extracted/{fname}', encoding='utf-8') as f:
        text = f.read()
    ip = rules._extract_all_insurance_periods(text)
    pp = rules._extract_all_payment_periods(text)
    print(f'{fname[:40]}: ip={ip[:3]}, pp={pp[:3]}')
