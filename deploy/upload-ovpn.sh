#!/bin/bash
# 手动执行 ovpn 上传（显示每步错误）
set -x
DSH=http://10.100.12.56:3081
API=$DSH/api/flow/tsecbench
JAR=/tmp/tsb-dsh-cookie.txt

docker run --rm -v /root/tsb-lab:/lab flow/dsh-env:0.6.0 \
  python3 -c "import json;print(json.dumps({'content':open('/lab/client.ovpn').read()}))" > /tmp/ovpn-req.json
echo "json bytes: $(wc -c < /tmp/ovpn-req.json)"
head -c 120 /tmp/ovpn-req.json; echo

curl -s -b "$JAR" -X POST "$API/ovpn" \
  -H 'Content-Type: application/json' -H 'X-Flow-Client: 1' \
  -d @/tmp/ovpn-req.json
echo
set +x
echo "=== 连接 VPN ==="
curl -s -b "$JAR" -X POST "$API/connect" \
  -H 'Content-Type: application/json' -H 'X-Flow-Client: 1' \
  -d '{}'
echo
echo "=== 最终状态 ==="
curl -s -b "$JAR" "$API/status"; echo
echo "=== 平台探测 ==="
curl -s -b "$JAR" -X POST "$API/probe" \
  -H 'Content-Type: application/json' -H 'X-Flow-Client: 1' \
  -d '{}'; echo
