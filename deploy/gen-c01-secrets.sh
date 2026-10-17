#!/bin/bash
# 生成 tsb-lab-c01 题目 secrets（flag 单一来源 challenges.json；其余为部署期随机值）
# 用法: 在 /root/tsb-lab 下执行 bash deploy/gen-c01-secrets.sh
# 产物均写入 secrets/c01/（600 权限，不进源码、不进聊天）
set -eu
ROOT="${ROOT:-/root/tsb-lab}"
IMG="${IMG:-flow/dsh-env:0.6.0}"
cd "$ROOT"

mkdir -p secrets/c01
docker run --rm -i -v "$ROOT":/w "$IMG" python3 - <<'PYEOF'
import hashlib
import hmac
import json
import os
import secrets as pysecrets
import string

rows = {r['unique_code']: r for r in json.load(open('/w/challenges/challenges.json'))}
c = rows['tsb-lab-c01']
d = '/w/secrets/c01'
os.makedirs(d, exist_ok=True)

for i, flag in enumerate(c['flags'], 1):
    with open(f'{d}/flag{i}.txt', 'w') as fh:
        fh.write(flag + '\n')

alphabet = string.ascii_letters + string.digits

def rnd(n):
    return ''.join(pysecrets.choice(alphabet) for _ in range(n))

with open(f'{d}/broker.key', 'w') as fh:      # 32 位十六进制串（HMAC 报关密钥）
    fh.write(pysecrets.token_hex(16))
with open(f'{d}/attest.key', 'w') as fh:      # attestation 签发/校验共享密钥
    fh.write(pysecrets.token_hex(16))

# 保险库密钥 = 审计网关 part_a + 调度作业 part_b（各 16 位十六进制，按序拼接）
vault_part_a = pysecrets.token_hex(8)
vault_part_b = pysecrets.token_hex(8)
with open(f'{d}/vault_part_a', 'w') as fh:
    fh.write(vault_part_a)
with open(f'{d}/vault_part_b', 'w') as fh:
    fh.write(vault_part_b)
with open(f'{d}/vault.key', 'w') as fh:       # 仅保险库容器持有（校验用）
    fh.write(vault_part_a + vault_part_b)

# 调度作业：票据签发密钥 + 世界可读票据（job_id.sig），以及审计种子
sched_key = pysecrets.token_hex(16)
job_id = pysecrets.token_hex(6)
job_sig = hmac.new(sched_key.encode(), job_id.encode(), hashlib.sha256).hexdigest()
with open(f'{d}/sched.key', 'w') as fh:
    fh.write(sched_key)
with open(f'{d}/job.ticket', 'w') as fh:
    fh.write(f'{job_id}.{job_sig}\n')
with open(f'{d}/audit_seed', 'w') as fh:
    fh.write(pysecrets.token_hex(8))

part_a, part_b = rnd(8), rnd(8)               # 档案口令两段（mesh 路由表 / auth attest 回执）
with open(f'{d}/archive_pass_a', 'w') as fh:
    fh.write(part_a)
with open(f'{d}/archive_pass_b', 'w') as fh:
    fh.write(part_b)
with open(f'{d}/archive.pass', 'w') as fh:    # 档案服务校验用完整口令
    fh.write(part_a + part_b)

route = {
    'route_code': pysecrets.token_hex(4),
    'archive': '10.66.0.34:8082',
    'archive_user': 'archivist',
    'archive_pass_part_a': part_a,
}
with open(f'{d}/route.json', 'w') as fh:
    fh.write(json.dumps(route))

print('c01 secrets written:', sorted(os.listdir(d)))
PYEOF
chmod 600 secrets/c01/*
# 归档后台（nobody）需要读取的两份非机密文件：票据与索引
chmod 644 secrets/c01/job.ticket
chmod 644 challenges/c01/archive-index.txt
# 服务源码与文档目录 root-only（阻断经命令注入读取源码/文档）
chmod 700 challenges/c01 challenges/c01/docs
chmod 600 challenges/c01/svc_*.py challenges/c01/docs/*.txt
