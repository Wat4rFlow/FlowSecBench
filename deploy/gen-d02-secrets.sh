#!/bin/bash
# 生成 tsb-lab-d02 题目 secrets（flag 单一来源 challenges.json；其余为部署期随机值）
# 用法: 在 /root/tsb-lab 下执行 bash deploy/gen-d02-secrets.sh
set -eu
ROOT="${ROOT:-/root/tsb-lab}"
IMG="${IMG:-flow/dsh-env:0.6.0}"
cd "$ROOT"

mkdir -p secrets/d02
docker run --rm -i -v "$ROOT":/w "$IMG" \
  python3 /w/deploy/gen-d02-secrets.py \
  --challenges /w/challenges/challenges.json --out /w/secrets/d02
chmod 600 secrets/d02/*
