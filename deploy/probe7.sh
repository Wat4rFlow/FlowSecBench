#!/bin/bash
# 探测7：headless 能力 + 会话 RPC 协议（决定端到端驱动方式）
set -u
D=/opt/dsh020/lib/node_modules/@deepseek-ai/dsh
echo "=== headless help (container, temp home) ==="
docker run --rm --user 0:0 --network none \
  -v /opt/dsh020:/opt/dsh020:ro \
  -e DSH_HOME=/tmp/probe7-home -e HOME=/tmp/probe7-home -e LD_LIBRARY_PATH=/opt/dsh020/lib -e DSH_TELEMETRY_DISABLED=1 \
  flow/dsh-env:0.6.0 sh -c 'mkdir -p /tmp/probe7-home; node /opt/dsh020/bin/dsh --profile web headless --help 2>&1 | head -50'
echo "=== remote.mux protocol hints ==="
grep -aoE "remote\.mux[^\"']{0,40}" "$D/node_modules/@deepseek-ai/dsh-api-remotes/lib/client.js" | sort -u | head -10
grep -aoE "['\"]/(api/)?remote\.mux[^\"']{0,20}['\"]" "$D/node_modules/@deepseek-ai/dsh-api-remotes/lib/client.js" | sort -u | head
echo "=== rpc method names in api-remotes ==="
grep -aoE "['\"][a-z]+\.[a-zA-Z]+['\"]" "$D/node_modules/@deepseek-ai/dsh-api-remotes/lib/client.js" | sort -u | head -40
echo "=== web-app route strings ==="
WEB=$(ls -d "$D"/node_modules/@deepseek-ai/dsh-web-app 2>/dev/null || ls -d "$D"/node_modules/.pnpm/*dsh-web-app*/node_modules/@deepseek-ai/dsh-web-app 2>/dev/null | head -1)
echo "WEB=$WEB"
grep -rhoE "['\"](/api)?/[a-zA-Z0-9/_.:-]{2,50}['\"]" "$WEB/lib" 2>/dev/null | sort -u | head -60
