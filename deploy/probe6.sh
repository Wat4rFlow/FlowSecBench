#!/bin/bash
# 探测6：headless 会话能力（决定解题闭环的驱动方式）
set -u
export DSH_HOME=/tmp/flow-probe-home6 HOME=/tmp/flow-probe-home6 LD_LIBRARY_PATH=/opt/dsh020/lib DSH_TELEMETRY_DISABLED=1
mkdir -p /tmp/flow-probe-home6
echo "=== dsh headless --help ==="
node /opt/dsh020/lib/node_modules/@deepseek-ai/dsh/lib/bin.js --profile web headless --help 2>&1 | head -60
echo "=== web app help (profile web) ==="
node /opt/dsh020/lib/node_modules/@deepseek-ai/dsh/lib/bin.js --profile web web --help 2>&1 | head -40
echo "=== preset list in flow-live config ==="
grep -n "id: flow" /root/dsh-workspace/Flow/.runtime/runs/update-20261015070617345-5d1d69cd/dsh-home/profiles/flow-live/package.json 2>/dev/null | head
ls /root/dsh-workspace/Flow/.runtime/runs/update-20261015070617345-5d1d69cd/dsh-home/profiles/flow-live/ 2>/dev/null
