#!/bin/bash
# 探测4：bin/dsh 形态 + 容器内 CLI help + 会话端点定位
set -u
echo "=== bin/dsh file type ==="
ls -la /opt/dsh020/bin/ /opt/dsh020/bin/dsh 2>&1 | head -10
file /opt/dsh020/bin/dsh 2>/dev/null || true
echo "=== grep session.export anywhere ==="
grep -rl "session.export" /opt/dsh020/lib/node_modules/@deepseek-ai/ 2>/dev/null | head -5
echo "=== grep api route list ==="
grep -rl "api/session" /opt/dsh020/lib/node_modules/@deepseek-ai/ 2>/dev/null | head -5
echo "=== dsh CLI help in container ==="
docker run --rm --user 0:0 --network none \
  -v /opt/dsh020:/opt/dsh020:ro \
  -e DSH_HOME=/tmp/probe-home -e HOME=/tmp/probe-home -e LD_LIBRARY_PATH=/opt/dsh020/lib -e DSH_TELEMETRY_DISABLED=1 \
  flow/dsh-env:0.6.0 sh -c 'mkdir -p /tmp/probe-home; node /opt/dsh020/bin/dsh --help 2>&1 | head -40'
echo "=== ports 1194/3090 ==="
ss -tlnp | grep -E ':(1194|3090)\b' || echo "tcp free"
ss -ulnp | grep -E ':(1194|3090)\b' || echo "udp free"
echo "=== route 10.66 ==="
ip route show | grep '10\.66' || echo "no 10.66 routes"
echo "=== local nets ==="
ip -4 -o addr show | awk '{print $2, $4}'
echo "=== host openvpn ==="
which openvpn 2>/dev/null && openvpn --version 2>/dev/null | head -1 || echo "no openvpn on host"
