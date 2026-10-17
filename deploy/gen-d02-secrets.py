#!/usr/bin/env python3
"""生成 tsb-lab-d02 的部署期 secrets（flag 单一来源 challenges.json）。

产物（写入 --out 目录）：
  flag1..3.txt          题目 flag
  nodes.json            封条链（30 节点，10 个保留分片）
  seal.expected         sha256(按规则拼接的保留分片)[:32]
  aud_seed              认证中心令牌派生种子
  mesh_seed             调度中继会话种子
  archive_pass_a/b      归档口令两段（认证中心 / 调度中继）
  archive.pass          归档校验用完整口令
  gateway.key           网关签名密钥（归档 / 网关 / 保险库）
  gate_seed             网关阶梯初始值（归档托管后下发）
  vault_seed            保险库会话种子（仅网关与保险库）
"""
import argparse
import base64
import hashlib
import json
import os
import secrets

NODE_COUNT = 30
KEEP = {0, 3, 6, 9, 12, 15, 18, 21, 24, 27}   # 保留分片所在节点号
FINAL_NODE = NODE_COUNT - 1                      # 末节点必须为干扰节点（无后继）


def build_chain():
    tags = ['K' if i in KEEP else 'D' for i in range(NODE_COUNT)]
    tags[FINAL_NODE] = 'D'

    used = set()

    def new_ref():
        while True:
            ref = secrets.token_hex(3)
            if ref not in used:
                used.add(ref)
                return ref

    refs = [None] * NODE_COUNT
    parts = [None] * NODE_COUNT
    refs[0] = new_ref()

    for i in range(NODE_COUNT - 1):
        if tags[i] == 'K':
            # 保留节点的 next 由 sha256(part)[:6] 决定，必须与下一节点 ref 对齐
            while True:
                part = base64.b64encode(secrets.token_bytes(12)).decode()
                nxt = hashlib.sha256(part.encode()).hexdigest()[:6]
                if nxt not in used:
                    break
            used.add(nxt)
            refs[i + 1] = nxt
            parts[i] = part
        else:
            refs[i + 1] = new_ref()
            parts[i] = base64.b64encode(secrets.token_bytes(12)).decode()

    parts[FINAL_NODE] = base64.b64encode(secrets.token_bytes(12)).decode()

    nodes = []
    for i in range(NODE_COUNT):
        node = {
            'ref': refs[i],
            'node': i,
            'part': parts[i],
            'tag': tags[i],
            'next': None,
            'next_hint': None,
        }
        if tags[i] == 'K':
            node['next_hint'] = 'sha256(part) 前 6 位十六进制'
        elif i < FINAL_NODE:
            node['next'] = refs[i + 1]
        nodes.append(node)

    assert len({n['ref'] for n in nodes}) == NODE_COUNT
    return {'head': refs[0], 'nodes': nodes}


def assemble(chain):
    kept = sorted((n for n in chain['nodes'] if n['tag'] == 'K'), key=lambda n: n['node'])
    out = b''
    for node in kept:
        raw = base64.b64decode(node['part'])
        if node['node'] % 9 == 0:
            raw = bytes(b ^ (node['node'] & 0xFF) for b in raw)
        out += raw
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--challenges', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    rows = {r['unique_code']: r for r in json.load(open(args.challenges, encoding='utf-8'))}
    row = rows['tsb-lab-d02']
    os.makedirs(args.out, exist_ok=True)

    def put(name, text):
        with open(os.path.join(args.out, name), 'w', encoding='utf-8') as fh:
            fh.write(text if text.endswith('\n') else text + '\n')

    for idx, flag in enumerate(row['flags'], 1):
        put(f'flag{idx}.txt', flag)

    chain = build_chain()
    put('nodes.json', json.dumps(chain, ensure_ascii=False))
    put('seal.expected', hashlib.sha256(assemble(chain)).hexdigest()[:32])

    archive_a, archive_b = secrets.token_hex(10), secrets.token_hex(10)
    part_a, part_b, part_c = (secrets.token_hex(10) for _ in range(3))
    ticket_a, ticket_b, ticket_c = (secrets.token_hex(8) for _ in range(3))
    put('aud_seed', secrets.token_hex(16))
    put('mesh_seed', secrets.token_hex(12))
    put('archive_pass_a', archive_a)
    put('archive_pass_b', archive_b)
    put('archive.pass', archive_a + archive_b)
    put('gateway.key', secrets.token_hex(16))
    put('vault_seed', secrets.token_hex(12))

    # 冷库三分区：各自持有一段种子，网关种子 = 三段按 A/B/C 拼接
    put('part_a', part_a)
    put('part_b', part_b)
    put('part_c', part_c)
    put('branch_ticket_a', ticket_a)
    put('branch_ticket_b', ticket_b)
    put('branch_ticket_c', ticket_c)
    put('gate_seed', part_a + part_b + part_c)
    put('branches.json', json.dumps({'branches': [
        {'name': 'ticket', 'url': 'http://10.66.0.47:9200', 'ticket': ticket_a},
        {'name': 'zone', 'url': 'http://10.66.0.48:9300', 'ticket': ticket_b},
        {'name': 'pack', 'url': 'http://10.66.0.49:9400', 'ticket': ticket_c},
    ]}, ensure_ascii=False))

    print('d02 secrets written:', sorted(os.listdir(args.out)))


if __name__ == '__main__':
    main()
