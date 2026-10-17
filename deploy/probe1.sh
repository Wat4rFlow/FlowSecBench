#!/bin/bash
# 实验机探测：DSH 实例配置、路由面、镜像能力（只打印密钥名，不打印值）
set -u
echo "=== docker version ==="
docker version --format '{{.Server.Version}}' 2>/dev/null || docker --version
echo "=== flow-dsh-live env keys ==="
docker inspect flow-dsh-live --format '{{range .Config.Env}}{{println .}}{{end}}' | sed 's/=.*//' | sort
echo "=== flow-dsh-live cmd ==="
docker inspect flow-dsh-live --format '{{json .Config.Cmd}} {{json .Config.Entrypoint}} {{.HostConfig.NetworkMode}}'
echo "=== dsh package layout ==="
ls /opt/dsh020/lib/node_modules/@deepseek-ai/dsh/lib 2>/dev/null | head -30
echo "=== dsh route paths (sample) ==="
grep -rhoE "['\"]/api/[a-zA-Z0-9/_.-]{1,60}['\"]" /opt/dsh020/lib/node_modules/@deepseek-ai/dsh/lib 2>/dev/null | sort -u | head -60
echo "=== dsh bin ==="
ls /opt/dsh020/bin
echo "=== node on host ==="
node --version
echo "=== images with openvpn in range candidate ==="
echo "=== port 1194/3090 free? ==="
ss -tlnp | grep -E ':(1194|3090)\b' || echo "free"
ss -ulnp | grep -E ':(1194|3090)\b' || echo "udp free"
echo "=== ip route 10.66 ==="
ip route show | grep 10.66 || echo "no 10.66 routes"
echo "=== local nets ==="
ip -4 -o addr show | awk '{print $2, $4}'
