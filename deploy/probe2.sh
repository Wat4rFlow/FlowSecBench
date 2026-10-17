#!/bin/bash
# 探测2：DSH 会话 API 端点、CLI 能力、端口与网段
set -u
D=/opt/dsh020/lib/node_modules/@deepseek-ai/dsh
echo "=== api path strings ==="
grep -rhoE '["'"'"']/api/[a-zA-Z0-9/_.:{}-]{1,60}["'"'"']' "$D" 2>/dev/null | sort -u | head -80
echo "=== session-ish strings ==="
grep -rhoE '["'"'"']/(session|sessions|chat|message|messages|agent|agents|preset|presets|tool|tools)[a-zA-Z0-9/_.:{}-]{0,40}["'"'"']' "$D/lib" "$D/bin.js" 2>/dev/null | sort -u | head -40
echo "=== dsh cli help (isolated home) ==="
export DSH_HOME=/tmp/flow-probe-home HOME=/tmp/flow-probe-home LD_LIBRARY_PATH=/opt/dsh020/lib
mkdir -p /tmp/flow-probe-home
node /opt/dsh020/bin/dsh --help 2>&1 | head -60
echo "=== ports ==="
ss -tlnp | grep -E ':(1194|3090)\b' || echo "tcp free"
ss -ulnp | grep -E ':(1194|3090)\b' || echo "udp free"
echo "=== ip route 10.66 ==="
ip route show | grep '10\.66' || echo "no 10.66 routes"
echo "=== local nets ==="
ip -4 -o addr show | awk '{print $2, $4}'
