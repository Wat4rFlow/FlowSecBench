#!/bin/bash
# 探测8：web 应用路由清单 + headless 应用是否存在 + 会话事件协议
set -u
D=/opt/dsh020/lib/node_modules/@deepseek-ai/dsh
WEB="$D/node_modules/@deepseek-ai/dsh-web-app"
echo "=== web-app lib files ==="
ls "$WEB/lib" | head -30
echo "=== route path strings in web-app ==="
grep -rhoE '["'"'"']/?api/[a-zA-Z0-9/_.:{}-]{2,50}["'"'"']' "$WEB" 2>/dev/null | sort -u | head -60
echo "=== app ids (headless?) ==="
grep -rhoE 'id:\s*"[a-z-]+"' "$D/lib/profile-boot-BZ2ZjNWi.js" 2>/dev/null | sort -u | head -20
grep -rlao 'headless' "$D/lib" 2>/dev/null | head -5
echo "=== shipped profiles ==="
ls "$D/node_modules/@deepseek-ai/dsh-web-app/presets" 2>/dev/null
docker run --rm --user 0:0 --network none -v /opt/dsh020:/opt/dsh020:ro \
  -e DSH_HOME=/tmp/p8 -e HOME=/tmp/p8 -e LD_LIBRARY_PATH=/opt/dsh020/lib -e DSH_TELEMETRY_DISABLED=1 \
  flow/dsh-env:0.6.0 sh -c 'mkdir -p /tmp/p8; node /opt/dsh020/bin/dsh --profile headless headless --help 2>&1 | head -30'
