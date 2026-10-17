#!/bin/bash
# 探测3：DSH 会话 API 上下文、CLI help、端口与网段
set -u
D=/opt/dsh020/lib/node_modules/@deepseek-ai/dsh
echo "=== session.export context ==="
grep -rhoE '.{80}api/session\.[a-zA-Z]+.{40}' "$D/lib" 2>/dev/null | head -8
echo "=== /api/file and /api/ping context ==="
grep -rhoE ".{60}'/api/(file|ping|data)'.{40}" "$D/lib" 2>/dev/null | head -8
echo "=== route registration style ==="
grep -rhoE 'register\(\{[^}]{0,120}' "$D/lib" 2>/dev/null | sort -u | head -20
echo "=== dsh cli help ==="
export DSH_HOME=/tmp/flow-probe-home HOME=/tmp/flow-probe-home LD_LIBRARY_PATH=/opt/dsh020/lib
mkdir -p /tmp/flow-probe-home
/opt/dsh020/bin/dsh --help 2>&1 | head -50
echo "=== exit=$? ==="
echo "=== ports ==="
ss -tlnp | grep -E ':(1194|3090)\b' || echo "tcp free"
ss -ulnp | grep -E ':(1194|3090)\b' || echo "udp free"
echo "=== ip route 10.66 ==="
ip route show | grep '10\.66' || echo "no 10.66 routes"
echo "=== local nets ==="
ip -4 -o addr show | awk '{print $2, $4}'
echo "=== openvpn binary on host ==="
which openvpn && openvpn --version | head -1 || echo "no openvpn on host"
