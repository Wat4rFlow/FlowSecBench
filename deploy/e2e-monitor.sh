#!/bin/bash
# E2E 监控：轮询平台 debug/state，直到两题全部完成（a01>=1 flag, b01>=3 flags）或超时 40 分钟
LOG=/root/tsb-lab/e2e-monitor.log
: > "$LOG"
for i in $(seq 1 160); do
  state=$(curl -s http://127.0.0.1:3090/debug/state)
  if [ -z "$state" ]; then
    echo "[$(date +%T)] probe empty" >> "$LOG"
    sleep 15
    continue
  fi
  echo "$state" > /tmp/tsb-state.json
  summary=$(python3 - <<'PYEOF'
import json
d = json.load(open('/tmp/tsb-state.json'))
ch = d['challenges']
a = ch['tsb-lab-a01']; b = ch['tsb-lab-b01']
print("a01 flags=%d score=%s status=%s | b01 flags=%d score=%s status=%s | events=%d" % (
    len(a['awarded_flags']), a['score'], a['container_status'],
    len(b['awarded_flags']), b['score'], b['container_status'], len(d['events'])))
PYEOF
)
  echo "[$(date +%T)] $summary" >> "$LOG"
  done_flag=$(python3 - <<'PYEOF'
import json
d = json.load(open('/tmp/tsb-state.json'))
ch = d['challenges']
a = ch['tsb-lab-a01']; b = ch['tsb-lab-b01']
print('YES' if len(a['awarded_flags']) >= 1 and len(b['awarded_flags']) >= 3 else 'NO')
PYEOF
)
  if [ "$done_flag" = "YES" ]; then
    echo "[$(date +%T)] E2E COMPLETE" >> "$LOG"
    cp /tmp/tsb-state.json /root/tsb-lab/e2e-final-state.json
    echo DONE
    exit 0
  fi
  sleep 15
done
echo "[$(date +%T)] TIMEOUT after 40min" >> "$LOG"
echo TIMEOUT
exit 1
