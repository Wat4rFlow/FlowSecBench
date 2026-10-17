#!/bin/bash
# 获取平台 benchmark token 与容器拓扑（只读诊断）
docker ps --format '{{.Names}}' | sort
echo '---ENV---'
for c in $(docker ps --format '{{.Names}}'); do
  envs=$(docker inspect "$c" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -iE 'TSB|TOKEN' || true)
  if [ -n "$envs" ]; then
    echo "[$c]"
    echo "$envs"
  fi
done
echo '---SECRETS---'
ls /root/tsb-lab/secrets 2>/dev/null || true
