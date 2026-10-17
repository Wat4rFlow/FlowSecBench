#!/bin/bash
# 部署前预检：镜像能力、端口、设备、DSH 实例状态（只读，不改动任何东西）
set -u
echo "=== 1. 端口占用（1194/3090） ==="
ss -tulnp | grep -E ':(1194|3090)\b' || echo "free"
echo "=== 2. dsh-env 内 openvpn / python flask / iptables / nc ==="
docker run --rm --network none flow/dsh-env:0.6.0 sh -c '
openvpn --version 2>&1 | head -1
python3 --version
python3 -c "import flask; print(\"flask\", flask.__version__)" 2>&1
which iptables || echo "no iptables"
which nc || echo "no nc"
which curl openssl || true
' 2>&1
echo "=== 3. 宿主机 /dev/net/tun ==="
ls -l /dev/net/tun 2>&1 || echo "missing"
echo "=== 4. flow-dsh-live 能力（NET_ADMIN / device / cap） ==="
docker inspect flow-dsh-live --format 'CapAdd={{json .HostConfig.CapAdd}} Devices={{json .HostConfig.Devices}} Privileged={{.HostConfig.Privileged}}'
docker exec flow-dsh-live sh -c 'ls -l /dev/net/tun 2>&1; ip link show tun-flow 2>&1 | head -1; which openvpn ip' 2>&1
echo "=== 5. DSH token（用于 UI/API 访问） ==="
TOKEN=$(docker logs flow-dsh-live 2>&1 | grep -oE 'token=[A-Za-z0-9._~-]+' | tail -1 | cut -d= -f2)
if [ -n "$TOKEN" ]; then echo "token_len=${#TOKEN}"; echo "TOKEN=$TOKEN" > /root/tsb-lab-dsh-token.tmp; else echo "no token found"; fi
echo "=== 6. 现有 docker 网络（避免网段冲突） ==="
docker network ls --format '{{.Name}} {{.Driver}}'
docker network inspect $(docker network ls -q) --format '{{.Name}} {{(index .IPAM.Config 0).Subnet}}' 2>/dev/null | head -20
echo "=== 7. 内存余量 ==="
free -h | head -2
