#!/bin/bash
# 定位实验机上的 ovpn 文件与部署目录结构（只读）
find /root/tsb-lab -name '*.ovpn' -o -name '*.conf' | head -10
echo '---TREE---'
ls /root/tsb-lab/
echo '---PKI---'
ls /root/tsb-lab/pki 2>/dev/null || true
