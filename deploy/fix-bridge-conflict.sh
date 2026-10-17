#!/bin/bash
# 让 TSecBench 插件能为本靶场注入 /32 路由（消除 prepare_network 的 TARGET_ROUTES_CONFLICT）
#
# 背景：flow-dsh-live 以 host 网络运行，靶场网桥 br-<id> 持有 10.66.0.1/24；
# 插件 target-routes.js 的两条冲突规则会拒绝为同网段目标加 /32 dev tun-flow。
# 做法：把网桥地址由 /24 改为 /32（保留 10.66.0.1 作为容器默认网关），
# 并为平台（10.66.0.2）与 VPN 网关（10.66.0.10）保留显式 /32 路由。
# 该变更在宿主机重启或 docker 网络重建后失效，需要重新执行。
#
# 用法（实验机）：bash /root/tsb-lab/deploy/fix-bridge-conflict.sh
# 回滚：见脚本末尾说明。
set -euo pipefail

BR=$(ip -o link show | awk '$2 ~ /^br-/ {print $2}' | cut -d: -f1 | while read -r b; do
       ip -4 addr show "$b" 2>/dev/null | grep -q 'inet 10\.66\.0\.1/' && echo "$b"; done | head -1)
[ -n "$BR" ] || { echo "未找到持有 10.66.0.1 的网桥"; exit 1; }

echo "bridge=$BR"
if ip -4 addr show "$BR" | grep -q 'inet 10\.66\.0\.1/32'; then
  echo "已是 /32，跳过地址变更"
else
  ip addr del 10.66.0.1/24 dev "$BR"
  ip addr add 10.66.0.1/32 dev "$BR"
  echo "已把 10.66.0.1/24 改为 10.66.0.1/32"
fi

for ip in 10.66.0.2 10.66.0.10; do
  if ip route show | grep -q "^$ip dev $BR"; then
    echo "路由已存在: $ip dev $BR"
  else
    ip route add "$ip/32" dev "$BR"
    echo "已添加路由: $ip/32 dev $BR"
  fi
done

echo "=== 当前状态 ==="
ip -4 addr show "$BR" | grep inet || true
ip route show | grep '^10\.66' || true
curl -sf -m 5 http://127.0.0.1:3090/healthz >/dev/null && echo "platform healthz OK"

# 回滚（如需恢复 /24）：
#   ip route del 10.66.0.2/32 dev $BR
#   ip route del 10.66.0.10/32 dev $BR
#   ip addr del 10.66.0.1/32 dev $BR
#   ip addr add 10.66.0.1/24 dev $BR
