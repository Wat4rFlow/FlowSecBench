#!/bin/bash
# TSB Lab 一键部署：平台 + 三道题靶场（a01/b01/c01）+ VPN 服务
# 拓扑（宿主机 10.100.12.56）：
#   docker 网络 tsb-lab = 10.66.0.0/24
#   tsb-platform 10.66.0.2  (宿主 3090 端口)
#   tsb-a01      10.66.0.11 (员工论坛, HTTP)
#   tsb-b01-web  10.66.0.21 (门户, 8080)
#   tsb-b01-fcgi 10.66.0.22 (FastCGI 后端, 8000)
#   tsb-b01-redis 10.66.0.23 (缓存, 6379)
#   tsb-c01-gw   10.66.0.31 (c01 货代门户, 80)
#   tsb-c01-auth 10.66.0.32 (c01 认证中心, 8081)
#   tsb-c01-mesh 10.66.0.33 (c01 调度中继, 9000, MES1 二进制帧)
#   tsb-c01-archive 10.66.0.34 (c01 档案服务, 8082)
#   tsb-c01-vault 10.66.0.35 (c01 保险库, 6380, 签名 RESP)
#   tsb-c01-sched 10.66.0.36 (c01 调度作业, 8083, 异步 ETA 420s)
#   tsb-c01-audit 10.66.0.37 (c01 审计网关, 9100, 10 轮×15s 窗口)
#   tsb-vpn      10.66.0.10 (OpenVPN UDP 1194, 隧道 10.66.1.0/24)
# 注意：benchmark token 与 client.ovpn 为固定接入凭据，存在即复用（勿再随机化）。
set -euo pipefail
ROOT=/root/tsb-lab
IMG=flow/dsh-env:0.6.0
HOST_IP=10.100.12.56
cd "$ROOT"

echo "=== 0. 幂等清理 ==="
for c in tsb-platform tsb-a01 tsb-b01-web tsb-b01-fcgi tsb-b01-redis tsb-vpn \
         tsb-c01-gw tsb-c01-auth tsb-c01-mesh tsb-c01-archive tsb-c01-vault \
         tsb-c01-sched tsb-c01-audit; do
  docker rm -f "$c" >/dev/null 2>&1 || true
done
docker network rm tsb-lab >/dev/null 2>&1 || true
rm -f pki/server.conf

echo "=== 1. 生成 secrets（题目 flag 单一来源 challenges.json） ==="
mkdir -p secrets/b01
docker run --rm -i -v "$ROOT":/w "$IMG" python3 - <<'PYEOF'
import json, os
rows = {r['unique_code']: r for r in json.load(open('/w/challenges/challenges.json'))}
os.makedirs('/w/secrets/b01', exist_ok=True)
open('/w/secrets/a01.flag', 'w').write(rows['tsb-lab-a01']['flags'][0] + '\n')
for i, flag in enumerate(rows['tsb-lab-b01']['flags'], 1):
    open(f'/w/secrets/b01/flag{i}.txt', 'w').write(flag + '\n')
print('flags written')
PYEOF
REDIS_PASS="redis-lab-$(openssl rand -hex 8)"
printf '%s\n' "$REDIS_PASS" > secrets/b01/redis.auth
# benchmark token 为固定接入凭据：存在即复用，避免重部署后 Flow 实例配置失效
if [ -s secrets/benchmark.token ]; then
  BENCH_TOKEN=$(cat secrets/benchmark.token)
  echo "复用既有 benchmark token"
else
  BENCH_TOKEN="tsb-lab-$(openssl rand -hex 16)"
  printf '%s\n' "$BENCH_TOKEN" > secrets/benchmark.token
fi
# c01 secrets（flag 单一来源 challenges.json + 部署期随机密钥/口令分段）
bash deploy/gen-c01-secrets.sh
chmod 600 secrets/b01/redis.auth secrets/benchmark.token secrets/a01.flag secrets/b01/flag*.txt

echo "=== 2. 生成 PKI（存在即复用，保持 client.ovpn 内容不变） ==="
if [ -f pki/ca.crt ] && [ -f pki/server.crt ] && [ -f pki/server.key ] \
   && [ -f pki/client.crt ] && [ -f pki/client.key ]; then
  echo "复用既有 PKI"
else
  rm -rf pki
  bash deploy/gen-pki.sh pki
fi
cp deploy/server.conf pki/server.conf

echo "=== 3. 生成客户端 ovpn（内联证书，符合插件白名单；存在即复用） ==="
if [ -f client.ovpn ]; then
  echo "复用既有 client.ovpn"
else
  {
    cat <<'EOF'
client
dev tun
proto udp
remote __HOST_IP__ 1194
resolv-retry infinite
nobind
float
persist-key
persist-tun
remote-cert-tls server
cipher AES-256-GCM
auth SHA256
verb 3
EOF
    echo '<ca>';   cat pki/ca.crt;       echo '</ca>'
    echo '<cert>'; cat pki/client.crt;   echo '</cert>'
    echo '<key>';  cat pki/client.key;   echo '</key>'
  } | sed "s/__HOST_IP__/$HOST_IP/" > client.ovpn
  chmod 600 client.ovpn
fi

echo "=== 4. 创建网络与容器 ==="
docker network create --subnet 10.66.0.0/24 tsb-lab

# 平台 API（TSB_TOKENS 认证）
docker run -d --name tsb-platform --network tsb-lab --ip 10.66.0.2 \
  -p 3090:3090 -v "$ROOT/platform":/app -w /app \
  -v "$ROOT/challenges/challenges.json":/app/challenges.json:ro \
  -e TSB_TOKENS="$BENCH_TOKEN" -e TSB_PORT=3090 \
  "$IMG" python3 -u app.py >/dev/null

# 题目容器统一入口：先加隧道回程路由，再起服务
RUN_CHALLENGE() {  # $1=name $2=ip $3=workdir-svc
  docker run -d --name "$1" --network tsb-lab --ip "$2" \
    --cap-add NET_ADMIN \
    -v "$ROOT/challenges/a01":/app-a01:ro \
    -v "$ROOT/challenges/b01":/app-b01:ro \
    -v "$ROOT/secrets/b01":/data:ro \
    -v "$ROOT/secrets/b01/redis.auth":/srv/preview/redis.auth:ro \
    -e FLAG_A01="$(cat secrets/a01.flag)" \
    "$IMG" sh -c "ip route add 10.66.1.0/24 via 10.66.0.10; exec python3 -u $3" >/dev/null
}
RUN_CHALLENGE tsb-a01       10.66.0.11 /app-a01/app.py
RUN_CHALLENGE tsb-b01-web   10.66.0.21 /app-b01/svc_web.py
RUN_CHALLENGE tsb-b01-fcgi  10.66.0.22 /app-b01/svc_fcgi.py
RUN_CHALLENGE tsb-b01-redis 10.66.0.23 /app-b01/svc_redis.py

# c01：五段式链路题（门户/认证/调度中继/档案/保险库），仅标准库、限内存
# 每容器只挂载本跳所需 secret 文件（禁止整目录挂载，防止抄近道读全部 flag）
RUN_C01() {  # $1=name $2=ip $3=svc；其余为 -v 挂载参数
  local name=$1 ip=$2 svc=$3; shift 3
  docker run -d --name "$name" --network tsb-lab --ip "$ip" \
    --cap-add NET_ADMIN --memory 128m --memory-swap 128m \
    -v "$ROOT/challenges/c01":/app-c01:ro \
    "$@" \
    "$IMG" sh -c "ip route add 10.66.1.0/24 via 10.66.0.10; exec python3 -u $svc" >/dev/null
}
SEC="$ROOT/secrets/c01"
RUN_C01 tsb-c01-gw 10.66.0.31 /app-c01/svc_gateway.py \
  -v "$SEC/flag1.txt":/data/flag1.txt:ro -v "$SEC/broker.key":/data/broker.key:ro
RUN_C01 tsb-c01-auth 10.66.0.32 /app-c01/svc_auth.py \
  -v "$SEC/flag2.txt":/data/flag2.txt:ro -v "$SEC/broker.key":/data/broker.key:ro \
  -v "$SEC/attest.key":/data/attest.key:ro -v "$SEC/archive_pass_b":/data/archive_pass_b:ro
RUN_C01 tsb-c01-mesh 10.66.0.33 /app-c01/svc_mesh.py \
  -v "$SEC/flag3.txt":/data/flag3.txt:ro -v "$SEC/attest.key":/data/attest.key:ro \
  -v "$SEC/route.json":/data/route.json:ro
RUN_C01 tsb-c01-archive 10.66.0.34 /app-c01/svc_archive.py \
  -v "$SEC/archive.pass":/data/archive.pass:ro \
  -v "$SEC/job.ticket":/data/job.ticket:ro \
  -v "$ROOT/challenges/c01/archive-index.txt":/data/archive-index.txt:ro
RUN_C01 tsb-c01-sched 10.66.0.36 /app-c01/svc_sched.py \
  -v "$SEC/sched.key":/data/sched.key:ro -v "$SEC/vault_part_b":/data/vault_part_b:ro \
  -v "$SEC/audit_seed":/data/audit_seed:ro
RUN_C01 tsb-c01-audit 10.66.0.37 /app-c01/svc_audit.py \
  -v "$SEC/audit_seed":/data/audit_seed:ro -v "$SEC/vault_part_a":/data/vault_part_a:ro
RUN_C01 tsb-c01-vault 10.66.0.35 /app-c01/svc_vault.py \
  -v "$SEC/flag4.txt":/data/flag4.txt:ro -v "$SEC/vault.key":/data/vault.key:ro

# VPN 服务端
docker run -d --name tsb-vpn --network tsb-lab --ip 10.66.0.10 \
  -p 1194:1194/udp --cap-add NET_ADMIN --device /dev/net/tun \
  -v "$ROOT/pki/server.conf":/etc/openvpn/server.conf:ro \
  -v "$ROOT/pki":/etc/openvpn/pki:ro \
  "$IMG" sh -c 'sysctl -w net.ipv4.ip_forward=1 >/dev/null; exec openvpn --config /etc/openvpn/server.conf' >/dev/null

echo "=== 5. 健康检查 ==="
for i in $(seq 1 30); do
  if curl -sf -m 3 "http://127.0.0.1:3090/healthz" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -sf -m 5 "http://127.0.0.1:3090/healthz" || { echo "platform unhealthy"; docker logs tsb-platform 2>&1 | tail -20; exit 1; }
echo
docker ps --filter name=tsb- --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'

echo "=== 6. 部署产物 ==="
echo "benchmark_token : $BENCH_TOKEN"
echo "client ovpn     : $ROOT/client.ovpn ($(wc -c < client.ovpn) bytes)"
echo "平台 API        : http://$HOST_IP:3090"
