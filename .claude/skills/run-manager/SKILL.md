# run-manager 스킬

## 역할
워크플로우 실행 컨텍스트를 관리한다. run_id 발급, 세션 디렉토리 생성, 성공 run 등록/조회를 담당한다.

## 스크립트

### init_run.py
- **용도**: 워크플로우 시작 시 run_id 발급 + 세션 출력 디렉토리 생성
- **호출**: 모든 STEP보다 먼저 실행
- **출력**: run_id (`YYYYMMDD_HHMMSS` 형식) stdout 출력 + `output/logs/` 하위 세션 정보 기록

```bash
python .claude/skills/run-manager/scripts/init_run.py
# → 20260306_143022
```

### manage_registry.py
- **용도**: `output/logs/run_registry.json`에 성공 run 등록/조회
- **호출**: STEP 5 PASS 시 register, STEP 6 회귀 테스트 전 get-baseline

```bash
# 성공 run 등록
python .claude/skills/run-manager/scripts/manage_registry.py \
  --action register \
  --run-id 20260306_143022 \
  --product-code 2258A01 \
  --tables S00022,S00026,S00027,S00028

# 회귀 테스트 기준 run_id 조회
python .claude/skills/run-manager/scripts/manage_registry.py \
  --action get-baseline \
  --product-code 2258A01

# 전체 성공 run 목록 조회
python .claude/skills/run-manager/scripts/manage_registry.py \
  --action list
```
