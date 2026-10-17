#!/bin/bash
# 探测9：dsh-api-remotes SDK 导出 + 会话方法名 + curl 认证形态
set -u
D=/opt/dsh020/lib/node_modules/@deepseek-ai/dsh
R="$D/node_modules/@deepseek-ai/dsh-api-remotes"
echo "=== api-remotes files ==="
find "$R" -maxdepth 3 -type f | head -20
echo "=== api-remotes package.json ==="
cat "$R/package.json"
echo "=== exports tail of client.js ==="
tail -60 "$R/lib/client.js"
echo "=== method-like strings in client.js ==="
grep -aoE '[a-z]+\.[a-zA-Z]+\(' "$R/lib/client.js" | sort | uniq -c | sort -rn | head -30
echo "=== 'session' string contexts ==="
grep -aoE '.{30}session.{30}' "$R/lib/client.js" | head -20
echo "=== curl auth smoke on live instance ==="
TOKEN=$(docker logs flow-dsh-live 2>&1 | grep -oE 'token=[A-Za-z0-9._~-]+' | tail -1 | cut -d= -f2)
echo "token length: ${#TOKEN}"
curl -s -m 5 -c /tmp/dsh-cookie.txt -o /dev/null -w 'GET / %{http_code}\n' "http://127.0.0.1:3082/?token=$TOKEN"
curl -s -m 5 -b /tmp/dsh-cookie.txt -o /dev/null -w 'GET status %{http_code}\n' -H 'X-Flow-Client: 1' "http://127.0.0.1:3082/api/flow/tsecbench/status"
curl -s -m 5 -b /tmp/dsh-cookie.txt -H 'X-Flow-Client: 1' "http://127.0.0.1:3082/api/flow/tsecbench/status" | head -c 400
echo
