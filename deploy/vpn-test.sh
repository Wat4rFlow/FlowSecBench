#!/bin/bash
# VPN 数据面验证：独立客户端容器模拟插件的连接方式（--dev tun-*、--route-nopull），
# 验证证书、握手、路由注入与回程（题目容器静态路由）全链路。
set -u
docker run --rm --cap-add NET_ADMIN --device /dev/net/tun \
  -v /root/tsb-lab/client.ovpn:/client.ovpn:ro \
  flow/dsh-env:0.6.0 sh -c '
    openvpn --config /client.ovpn --dev tun-test --dev-type tun --route-nopull \
      --daemon ovpn --log /tmp/ovpn.log --verb 3
    for i in $(seq 1 30); do
      grep -q "Initialization Sequence Completed" /tmp/ovpn.log && break
      sleep 1
    done
    if ! grep -q "Initialization Sequence Completed" /tmp/ovpn.log; then
      echo "VPN_FAIL"; tail -30 /tmp/ovpn.log; exit 1
    fi
    echo "VPN_OK"
    ip -4 addr show tun-test | grep inet
    ip route add 10.66.0.11/32 dev tun-test
    ip route add 10.66.0.21/32 dev tun-test
    ip route add 10.66.0.22/32 dev tun-test
    ip route add 10.66.0.23/32 dev tun-test
    echo "--- a01 via VPN ---"
    curl -s -m 8 http://10.66.0.11/robots.txt && echo
    echo "--- b01 portal via VPN ---"
    curl -s -m 8 -o /dev/null -w "%{http_code}\n" http://10.66.0.21:8080/
    echo "VPN_DATA_PATH_OK"
  '
echo "exit=$?"
