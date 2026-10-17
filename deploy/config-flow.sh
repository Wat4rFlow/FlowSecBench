#!/bin/bash
# 通过 DSH Web API 配置 TSecBench 插件接入（与官方 progress-browser-check 同款认证方式）
# 在实验机本地执行：cookie 认证 + X-Flow-Client 头
set -eu
DSH=http://10.100.12.56:3081
API=$DSH/api/flow/tsecbench
DSH_TOKEN=$(cut -d= -f2 /root/tsb-lab-dsh-token.tmp)
BENCH_TOKEN=$(cat /root/tsb-lab/secrets/benchmark.token)
JAR=/tmp/tsb-dsh-cookie.txt

echo "=== 0. 会话认证 ==="
curl -s -c "$JAR" -o /dev/null -w "auth page: %{http_code}\n" "$DSH/?token=$DSH_TOKEN"

echo "=== 1. 当前插件状态 ==="
curl -s -b "$JAR" "$API/status"; echo

echo "=== 2. 保存平台配置（baseUrl + token） ==="
curl -s -b "$JAR" -X POST "$API/config" \
  -H 'Content-Type: application/json' -H 'X-Flow-Client: 1' \
  -d "{\"baseUrl\":\"http://10.100.12.56:3090\",\"token\":\"$BENCH_TOKEN\"}"; echo

echo "=== 3. 上传 ovpn ==="
docker run --rm -i -v /root/tsb-lab:/lab flow/dsh-env:0.6.0 \
  python3 -c "import json;print(json.dumps({'content':open('/lab/client.ovpn').read()}))" > /tmp/ovpn-req.json
curl -s -b "$JAR" -X POST "$API/ovpn" \
  -H 'Content-Type: application/json' -H 'X-Flow-Client: 1' \
  -d @/tmp/ovpn-req.json; echo

echo "=== 4. 连接 VPN ==="
curl -s -b "$JAR" -X POST "$API/connect" \
  -H 'Content-Type: application/json' -H 'X-Flow-Client: 1' \
  -d '{}'; echo

echo "=== 5. 最终状态 ==="
curl -s -b "$JAR" "$API/status"; echo

echo "=== 6. 平台探测 ==="
curl -s -b "$JAR" -X POST "$API/probe" \
  -H 'Content-Type: application/json' -H 'X-Flow-Client: 1' \
  -d '{}'; echo
