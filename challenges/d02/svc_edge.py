#!/usr/bin/env python3
"""d-02 阶段①：冷链路货代门户（10.66.0.41:80）。

对外只提供公开页面与"封条链"（seal chain）：
  /robots.txt          泄露链头 ref
  /seal/<ref>          逐个节点返回分片（tag=K 保留 / D 干扰）
  /readme              组装规则
  /redeem?proof=       校验拼接摘要，返回 flag1 + 认证中心种子

链头之后每个节点的 next 只有两种来源：直接给出（干扰节点），或由
sha256(part)[:6] 计算（保留节点）——必须逐节点推进，且部分分片需按
节点号异或还原。仅 Python 标准库。
"""
import base64
import hashlib
import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN = (os.environ.get('D02_EDGE_HOST', '10.66.0.41'),
          int(os.environ.get('D02_EDGE_PORT', '80')))
DATA = os.environ.get('D02_EDGE_DATA', '/data')

CHAIN = json.load(open(os.path.join(DATA, 'nodes.json'), encoding='utf-8'))
NODES = {n['ref']: n for n in CHAIN['nodes']}
HEAD = CHAIN['head']
EXPECTED = open(os.path.join(DATA, 'seal.expected'), encoding='utf-8').read().strip()
FLAG1 = open(os.path.join(DATA, 'flag1.txt'), encoding='utf-8').read().strip()
AUD_SEED = open(os.path.join(DATA, 'aud_seed'), encoding='utf-8').read().strip()

INDEX = """深冷冷链 · 货代门户（edge）
================================
公开资源：
  /robots.txt            抓取策略（含封条链起点）
  /readme                封条链与提货校验说明
  /seal/<ref>            封条节点（JSON）
  /frozen/creds          2024 老旧分支的只读凭据（已轮换）

本门户不直接持有提货凭证：需要把封条链里的保留分片按规则拼接，
通过 /redeem 校验后才下发。
"""

README = """封条链运维说明（edge）
================================
1) 封条链起点：robots.txt 中 seal-head 的 ref。逐个 GET /seal/<ref> 取节点。
2) 节点字段：
     node       节点序号（0 起）
     part       base64 编码的 12 字节分片
     tag        K = 保留分片，D = 干扰分片
     next       下一节点 ref（仅干扰节点直接给出）
     next_hint  保留节点不直接给出 next，其值 = sha256(part 字符串) 前 6 位十六进制
3) 组装规则：
   - 取所有 tag=K 的节点，按 node 升序；
   - 每个 part 先 base64 解码；
   - 若 node % 9 == 0，解码后的每个字节需与 node 异或（node=0 时不变）；
   - 按顺序拼接全部分片字节。
4) 提货校验：
   proof = sha256(拼接结果) 的十六进制前 32 位
   GET /redeem?proof=<proof>
   校验通过返回 flag1、认证中心种子与地址。

/frozen/ 为 2024 年旧版只读分支，凭据已轮换，仅用于排障对照。
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype='text/plain; charset=utf-8'):
        raw = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), 'application/json; charset=utf-8')

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip('/') or '/'
        query = urllib.parse.parse_qs(parsed.query)

        if path == '/':
            return self._send(200, INDEX)
        if path == '/readme':
            return self._send(200, README)
        if path == '/robots.txt':
            return self._send(200, f'User-agent: *\nDisallow: /frozen/\n# seal-head: {HEAD}\n')
        if path == '/frozen/creds':
            return self._json(200, {
                'note': '2024 legacy branch, rotated',
                'archive': {'url': 'http://10.66.0.44:8082', 'user': 'archivist',
                            'pass': 'legacy-rotated-0000'},
            })
        if path.startswith('/seal/'):
            ref = path[len('/seal/'):].strip().lower()
            node = NODES.get(ref)
            if node is None:
                return self._json(404, {'error': 'unknown ref', 'note': 'ref 为 6 位小写十六进制'})
            return self._json(200, node)
        if path == '/redeem':
            proof = (query.get('proof') or [''])[0].strip().lower()
            if proof and proof == EXPECTED:
                return self._json(200, {
                    'flag': FLAG1,
                    'aud_seed': AUD_SEED,
                    'auth': 'http://10.66.0.42:8081',
                })
            return self._json(403, {
                'error': 'proof mismatch',
                'note': 'proof = sha256(按规则拼接的保留分片字节) 的十六进制前 32 位',
            })
        return self._send(404, 'not found\n')


if __name__ == '__main__':
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
