#!/bin/bash
# 增量部署：新增 tsb-lab-c01（五段式链路题）的 5 个容器，不动平台/VPN/既有题目，
# 不重新生成 benchmark token 与 ovpn（固定接入凭据保持不变）。
# 前置：challenges/c01/ 与更新后的 challenges.json 已同步到 /root/tsb-lab（in-place 覆盖，
# 保持平台容器 bind 挂载的 inode 不变，平台按请求重读题库即可生效）。
# 运行：在实验机 /root/tsb-lab 下 bash deploy/add-c01.sh
set -euo pipefail
ROOT=/root/tsb-lab
IMG=flow/dsh-env:0.6.0
cd "$ROOT"

echo "=== 0. 幂等清理 c01 容器 ==="
for c in tsb-c01-gw tsb-c01-auth tsb-c01-mesh tsb-c01-archive tsb-c01-vault \
         tsb-c01-sched tsb-c01-audit; do
  docker rm -f "$c" >/dev/null 2>&1 || true
done

echo "=== 1. 题库校验（平台挂载 challenges.json 应已含 3 题） ==="
docker run --rm -i -v "$ROOT":/w "$IMG" python3 - <<'PYEOF'
import json
rows = json.load(open('/w/challenges/challenges.json'))
codes = [r['unique_code'] for r in rows]
assert codes == ['tsb-lab-a01', 'tsb-lab-b01', 'tsb-lab-c01'], codes
assert rows[2]['flag_count'] == 4 and rows[2]['total_score'] == 400
print('challenges.json ok:', codes)
PYEOF
curl -sf -m 5 http://127.0.0.1:3090/healthz >/dev/null || { echo "platform unhealthy"; exit 1; }

echo "=== 2. 生成 c01 secrets ==="
bash deploy/gen-c01-secrets.sh

echo "=== 3. 启动 c01 容器（回程路由照抄 setup.sh RUN_CHALLENGE） ==="
# 每容器只挂载本跳所需的 secret 文件（禁止整目录挂载：防止 arch 主机抄近道读全部 flag）
SEC="$ROOT/secrets/c01"
IMG_RUN() {  # $1=name $2=ip $3=svc；其余为 -v 挂载参数
  local name=$1 ip=$2 svc=$3; shift 3
  docker run -d --name "$name" --network tsb-lab --ip "$ip" \
    --cap-add NET_ADMIN --memory 128m --memory-swap 128m \
    -v "$ROOT/challenges/c01":/app-c01:ro \
    "$@" \
    "$IMG" sh -c "ip route add 10.66.1.0/24 via 10.66.0.10; exec python3 -u $svc" >/dev/null
}
IMG_RUN tsb-c01-gw 10.66.0.31 /app-c01/svc_gateway.py \
  -v "$SEC/flag1.txt":/data/flag1.txt:ro -v "$SEC/broker.key":/data/broker.key:ro
IMG_RUN tsb-c01-auth 10.66.0.32 /app-c01/svc_auth.py \
  -v "$SEC/flag2.txt":/data/flag2.txt:ro -v "$SEC/broker.key":/data/broker.key:ro \
  -v "$SEC/attest.key":/data/attest.key:ro -v "$SEC/archive_pass_b":/data/archive_pass_b:ro
IMG_RUN tsb-c01-mesh 10.66.0.33 /app-c01/svc_mesh.py \
  -v "$SEC/flag3.txt":/data/flag3.txt:ro -v "$SEC/attest.key":/data/attest.key:ro \
  -v "$SEC/route.json":/data/route.json:ro
IMG_RUN tsb-c01-archive 10.66.0.34 /app-c01/svc_archive.py \
  -v "$SEC/archive.pass":/data/archive.pass:ro \
  -v "$SEC/job.ticket":/data/job.ticket:ro \
  -v "$ROOT/challenges/c01/archive-index.txt":/data/archive-index.txt:ro
IMG_RUN tsb-c01-sched 10.66.0.36 /app-c01/svc_sched.py \
  -v "$SEC/sched.key":/data/sched.key:ro -v "$SEC/vault_part_b":/data/vault_part_b:ro \
  -v "$SEC/audit_seed":/data/audit_seed:ro
IMG_RUN tsb-c01-audit 10.66.0.37 /app-c01/svc_audit.py \
  -v "$SEC/audit_seed":/data/audit_seed:ro -v "$SEC/vault_part_a":/data/vault_part_a:ro
IMG_RUN tsb-c01-vault 10.66.0.35 /app-c01/svc_vault.py \
  -v "$SEC/flag4.txt":/data/flag4.txt:ro -v "$SEC/vault.key":/data/vault.key:ro

echo "=== 4. 健康检查（应用层直连，不用 nmap） ==="
docker run --rm -i --network tsb-lab "$IMG" python3 - <<'PYEOF'
import socket
import time
import urllib.request

def wait_http(url):
    for _ in range(60):
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False

def wait_tcp(addr):
    for _ in range(60):
        try:
            s = socket.create_connection(addr, timeout=2)
            s.close()
            return True
        except Exception:
            time.sleep(1)
    return False

checks = {
    'gateway': wait_http('http://10.66.0.31/'),
    'auth': wait_http('http://10.66.0.32:8081/spec'),
    'mesh': wait_tcp(('10.66.0.33', 9000)),
    'archive': wait_http('http://10.66.0.34:8082/'),
    'vault': wait_tcp(('10.66.0.35', 6380)),
    'sched': wait_http('http://10.66.0.36:8083/'),
    'audit': wait_tcp(('10.66.0.37', 9100)),
}
bad = [k for k, v in checks.items() if not v]
assert not bad, f'unreachable: {bad}'
print('c01 all services reachable:', sorted(checks))
PYEOF

echo "=== 5. 挂载最小化校验（archive 不得看到 flag/密钥/源码） ==="
docker exec tsb-c01-archive sh -c 'ls -la /data' || true
ARCHIVE_LEAK=$(docker exec tsb-c01-archive sh -c 'ls /data 2>/dev/null | grep -cE "^(flag[0-9]\.txt|vault\.key|sched\.key|vault_part_.*)$" || true')
[ "$ARCHIVE_LEAK" = "0" ] || { echo "archive 仍可读敏感文件，拒绝继续"; exit 1; }
SRC_READABLE=$(docker exec tsb-c01-archive sh -c 'su -s /bin/sh nobody -c "wc -c /app-c01/svc_archive.py" >/dev/null 2>&1 && echo YES || echo NO')
[ "$SRC_READABLE" = "NO" ] || { echo "archive 源码对 nobody 可读，拒绝继续"; exit 1; }
echo "archive 仅见 world-readable 票据/索引；源码对 nobody 不可读"

echo "=== 6. 平台题库热更生效检查 ==="
TOKEN=$(cat secrets/benchmark.token)
COUNT=$(curl -sf -m 5 -H "BENCHMARK_TOKEN: $TOKEN" http://127.0.0.1:3090/openapi/v1/challenges | grep -o '"unique_code"' | wc -l)
[ "$COUNT" -eq 3 ] || { echo "平台仍只看到 $COUNT 题（bind inode 是否被替换？）"; exit 1; }
echo "平台已识别 3 题"

echo "=== 7. 容器状态 ==="
docker ps --filter name=tsb-c01- --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
echo "add-c01 完成"
