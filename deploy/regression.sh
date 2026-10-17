#!/bin/bash
# c01 日常回归：平台契约测试 + 解题链路自检（含异步作业与审计窗口的真实等待，约 8–10 分钟）
# 用法（实验机）：bash /root/tsb-lab/deploy/regression.sh
# 退出码：0 = 全部通过；非 0 = 有失败（verify 或 solve 任一失败）
set -uo pipefail
ROOT=/root/tsb-lab
IMG=flow/dsh-env:0.6.0
LOG=$ROOT/regression.log
OUT=$(mktemp)

stamp=$(date '+%F %T')
{
  echo "===== $stamp regression start ====="
  docker run --rm --network host -v "$ROOT":/root/tsb-lab "$IMG" \
    python3 /root/tsb-lab/deploy/verify-platform.py
  verify_rc=$?
  docker run --rm --network tsb-lab --ip 10.66.0.50 -v "$ROOT":/lab "$IMG" \
    python3 /lab/deploy/solve-test.py
  solve_rc=$?
  echo "verify_rc=$verify_rc solve_rc=$solve_rc"
  if [ "$verify_rc" -eq 0 ] && [ "$solve_rc" -eq 0 ]; then
    echo "RESULT PASS"
  else
    echo "RESULT FAIL"
  fi
  echo "===== $(date '+%F %T') regression end ====="
} 2>&1 | tee -a "$LOG" | tee "$OUT" >/dev/null

grep -q "RESULT PASS" "$OUT"
rc=$?
rm -f "$OUT"
if [ "$rc" -eq 0 ]; then
  echo "regression PASS (log: $LOG)"
else
  echo "regression FAIL (log: $LOG)"
fi
exit "$rc"
