#!/bin/bash
# 增量部署：新增 tsb-lab-d02（六段式冷链路，3 flag / 420 分）的 6 个容器。
# 不动平台/VPN/既有题目，不重新生成 benchmark token 与 ovpn。
# 前置：challenges/d02/ 与更新后的 challenges.json 已同步到 /root/tsb-lab
#       （challenges.json 必须 in-place 覆盖，保持平台 bind 挂载的 inode）。
# 运行：在实验机 /root/tsb-lab 下 bash deploy/add-d02.sh
set -euo pipefail
ROOT=/root/tsb-lab
IMG=flow/dsh-env:0.6.0
cd "$ROOT"

echo "=== 0. 幂等清理 d02 容器 ==="
for c in tsb-d02-edge tsb-d02-auth tsb-d02-mesh tsb-d02-archive tsb-d02-gate tsb-d02-vault \
         tsb-d02-ticket tsb-d02-zone tsb-d02-pack \
         tsb-d02-legacy tsb-d02-maint; do
  docker rm -f "$c" >/dev/null 2>&1 || true
done

echo "=== 1. 题库校验（应含 4 题） ==="
docker run --rm -i -v "$ROOT":/w "$IMG" python3 - <<'PYEOF'
import json
rows = json.load(open('/w/challenges/challenges.json'))
codes = [r['unique_code'] for r in rows]
assert codes == ['tsb-lab-a01', 'tsb-lab-b01', 'tsb-lab-c01', 'tsb-lab-d02'], codes
row = rows[3]
assert row['flag_count'] == 3 and row['total_score'] == 420 and len(row['container_addr']) == 11
print('challenges.json ok:', codes)
PYEOF
curl -sf -m 5 http://127.0.0.1:3090/healthz >/dev/null || { echo "platform unhealthy"; exit 1; }

echo "=== 2. 生成 d02 secrets ==="
bash deploy/gen-d02-secrets.sh

echo "=== 3. 启动 d02 容器（回程路由照抄 setup.sh） ==="
SEC="$ROOT/secrets/d02"
IMG_RUN() {  # $1=name $2=ip $3=svc；其余为 -v 挂载
  local name=$1 ip=$2 svc=$3; shift 3
  docker run -d --name "$name" --network tsb-lab --ip "$ip" \
    --cap-add NET_ADMIN --memory 128m --memory-swap 128m \
    -v "$ROOT/challenges/d02":/app-d02:ro \
    "$@" \
    "$IMG" sh -c "ip route add 10.66.1.0/24 via 10.66.0.10; exec python3 -u $svc" >/dev/null
}
IMG_RUN tsb-d02-edge 10.66.0.41 /app-d02/svc_edge.py \
  -v "$SEC/flag1.txt":/data/flag1.txt:ro -v "$SEC/nodes.json":/data/nodes.json:ro \
  -v "$SEC/seal.expected":/data/seal.expected:ro -v "$SEC/aud_seed":/data/aud_seed:ro
IMG_RUN tsb-d02-auth 10.66.0.42 /app-d02/svc_auth.py \
  -v "$SEC/aud_seed":/data/aud_seed:ro -v "$SEC/mesh_seed":/data/mesh_seed:ro \
  -v "$SEC/archive_pass_a":/data/archive_pass_a:ro
IMG_RUN tsb-d02-mesh 10.66.0.43 /app-d02/svc_mesh.py \
  -v "$SEC/mesh_seed":/data/mesh_seed:ro -v "$SEC/archive_pass_b":/data/archive_pass_b:ro
IMG_RUN tsb-d02-archive 10.66.0.44 /app-d02/svc_archive.py \
  -v "$SEC/archive.pass":/data/archive.pass:ro -v "$SEC/gateway.key":/data/gateway.key:ro \
  -v "$SEC/flag2.txt":/data/flag2.txt:ro -v "$SEC/branches.json":/data/branches.json:ro
IMG_RUN tsb-d02-gate 10.66.0.45 /app-d02/svc_gate.py \
  -v "$SEC/gateway.key":/data/gateway.key:ro -v "$SEC/gate_seed":/data/gate_seed:ro \
  -v "$SEC/vault_seed":/data/vault_seed:ro
IMG_RUN tsb-d02-vault 10.66.0.46 /app-d02/svc_vault.py \
  -v "$SEC/gateway.key":/data/gateway.key:ro -v "$SEC/vault_seed":/data/vault_seed:ro \
  -v "$SEC/flag3.txt":/data/flag3.txt:ro
IMG_RUN tsb-d02-ticket 10.66.0.47 /app-d02/svc_ticket.py \
  -v "$SEC/part_a":/data/part_a:ro -v "$SEC/branch_ticket_a":/data/branch_ticket_a:ro
IMG_RUN tsb-d02-zone 10.66.0.48 /app-d02/svc_zone.py \
  -v "$SEC/part_b":/data/part_b:ro -v "$SEC/branch_ticket_b":/data/branch_ticket_b:ro
IMG_RUN tsb-d02-pack 10.66.0.49 /app-d02/svc_pack.py \
  -v "$SEC/part_c":/data/part_c:ro -v "$SEC/branch_ticket_c":/data/branch_ticket_c:ro
# 死路：旧版中继与维护台（不挂任何 secret，1 次请求即可证伪）
IMG_RUN tsb-d02-legacy 10.66.0.52 /app-d02/svc_legacy.py
IMG_RUN tsb-d02-maint 10.66.0.53 /app-d02/svc_maint.py

echo "=== 4. 健康检查（应用层直连，不用 nmap） ==="
docker run --rm -i --network tsb-lab "$IMG" python3 - <<'PYEOF'
import socket
import time
import urllib.error
import urllib.request


def wait_http(url, ok=(200,)):
    for _ in range(60):
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status in ok:
                    return True
        except urllib.error.HTTPError as err:
            if err.code in ok:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def wait_tcp(addr):
    for _ in range(60):
        try:
            sock = socket.create_connection(addr, timeout=2)
            sock.close()
            return True
        except Exception:
            time.sleep(1)
    return False


checks = {
    'edge': wait_http('http://10.66.0.41/'),
    'auth': wait_http('http://10.66.0.42:8081/spec'),
    'mesh': wait_tcp(('10.66.0.43', 9000)),
    'archive': wait_http('http://10.66.0.44:8082/', ok=(401,)),
    'gate': wait_tcp(('10.66.0.45', 9100)),
    'vault': wait_tcp(('10.66.0.46', 6380)),
    'ticket': wait_http('http://10.66.0.47:9200/'),
    'zone': wait_tcp(('10.66.0.48', 9300)),
    'pack': wait_tcp(('10.66.0.49', 9400)),
    'legacy': wait_tcp(('10.66.0.52', 9500)),
    'maint': wait_http('http://10.66.0.53:9600/', ok=(401,)),
}
bad = [k for k, v in checks.items() if not v]
assert not bad, f'unreachable: {bad}'
print('d02 all services reachable:', sorted(checks))
PYEOF

echo "=== 5. 挂载最小化校验 ==="
for spec in "tsb-d02-edge:flag2.txt flag3.txt gateway.key vault_seed" \
            "tsb-d02-auth:flag1.txt flag2.txt flag3.txt gateway.key vault_seed" \
            "tsb-d02-mesh:flag1.txt flag2.txt flag3.txt gateway.key vault_seed" \
            "tsb-d02-archive:flag1.txt flag3.txt vault_seed aud_seed" \
            "tsb-d02-gate:flag1.txt flag2.txt flag3.txt part_a part_b part_c" \
            "tsb-d02-vault:flag1.txt flag2.txt part_a part_b part_c" \
            "tsb-d02-ticket:flag1.txt flag2.txt flag3.txt gateway.key part_b part_c" \
            "tsb-d02-zone:flag1.txt flag2.txt flag3.txt gateway.key part_a part_c" \
            "tsb-d02-pack:flag1.txt flag2.txt flag3.txt gateway.key part_a part_b" \
            "tsb-d02-legacy:flag1.txt flag2.txt flag3.txt gateway.key vault_seed part_a" \
            "tsb-d02-maint:flag1.txt flag2.txt flag3.txt gateway.key vault_seed part_a"; do
  name=${spec%%:*}; leaks=${spec#*:}
  for f in $leaks; do
    if docker exec "$name" sh -c "test -e /data/$f"; then
      echo "$name 不应看到 /data/$f，拒绝继续"; exit 1
    fi
  done
done
echo "各容器仅见本跳所需 secret"

echo "=== 6. 平台题库热更生效检查 ==="
TOKEN=$(cat secrets/benchmark.token)
COUNT=$(curl -sf -m 5 -H "BENCHMARK_TOKEN: $TOKEN" http://127.0.0.1:3090/openapi/v1/challenges | grep -o '"unique_code"' | wc -l)
[ "$COUNT" -eq 4 ] || { echo "平台仍只看到 $COUNT 题（bind inode 是否被替换？）"; exit 1; }
echo "平台已识别 4 题"

echo "=== 7. 容器状态 ==="
docker ps --filter name=tsb-d02- --format '{{.Names}}\t{{.Status}}'
echo "add-d02 完成"
