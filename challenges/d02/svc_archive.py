#!/usr/bin/env python3
"""d-02 阶段④：归档服务（10.66.0.44:8082）。

  /docs/view?name=     三份内部文档（清单 / 渲染器 / 托管与密钥）
  /render?tpl=<name>   遗留模板渲染器：对 tpl 参数做一次 '../' 替换后拼接
                       /app-d02/tpl，且只允许 .tpl 与 .key 资源
  /custody  POST       托管证明换 flag2 + 网关种子

主要工作量：从渲染器的"一次性过滤"里构造穿越，读出网关签名密钥。
仅 Python 标准库。
"""
import base64
import hashlib
import hmac
import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN = (os.environ.get('D02_ARCH_HOST', '10.66.0.44'),
          int(os.environ.get('D02_ARCH_PORT', '8082')))
DATA = os.environ.get('D02_ARCH_DATA', '/data')
DOCS_DIR = os.environ.get('D02_ARCH_DOCS', '/app-d02/docs')
TPL_DIR = os.environ.get('D02_ARCH_TPL', '/app-d02/tpl')

ARCHIVE_USER = 'archivist'
ARCHIVE_PASS = open(os.path.join(DATA, 'archive.pass'), encoding='utf-8').read().strip()
GATEWAY_KEY = open(os.path.join(DATA, 'gateway.key'), encoding='utf-8').read().strip()
FLAG2 = open(os.path.join(DATA, 'flag2.txt'), encoding='utf-8').read().strip()
BRANCHES = json.load(open(os.path.join(DATA, 'branches.json'), encoding='utf-8'))['branches']
GATE_ADDR = '10.66.0.45:9100'
ALLOWED_SUFFIX = ('.tpl', '.key')

INDEX = """冷链路归档服务（archive）
================================
内部文档：/docs/view?name=index.txt | render.txt | custody.txt
模板渲染：/render?tpl=<资源名>        （只读，允许 .tpl 与 .key）
托管证明：POST /custody  proof=<sha256 摘要>
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

    def _auth_ok(self):
        header = self.headers.get('Authorization', '')
        if not header.startswith('Basic '):
            self._send(401, 'authentication required\n')
            return False
        try:
            raw = base64.b64decode(header[6:]).decode('utf-8', 'replace')
            user, _, password = raw.partition(':')
        except Exception:
            self._send(401, 'bad credentials\n')
            return False
        if user == ARCHIVE_USER and hmac.compare_digest(password, ARCHIVE_PASS):
            return True
        self._send(401, 'bad credentials\n')
        return False

    def do_GET(self):
        if not self._auth_ok():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip('/') or '/'
        query = urllib.parse.parse_qs(parsed.query)

        if path == '/':
            return self._send(200, INDEX)
        if path == '/docs/view':
            name = (query.get('name') or [''])[0]
            safe = os.path.basename(name)
            full = os.path.join(DOCS_DIR, safe)
            if not os.path.isfile(full):
                return self._send(404, 'no such document\n')
            with open(full, encoding='utf-8') as fh:
                return self._send(200, fh.read())
        if path == '/render':
            return self._render((query.get('tpl') or [''])[0])
        if path == '/custody':
            return self._send(200, 'POST /custody with proof=<sha256 hex>\n')
        return self._send(404, 'not found\n')

    def _render(self, raw):
        # 历史实现：仅做一次 '../' 替换（ARCH-2211），随后直接拼接目录
        name = raw.replace('../', '')
        full = os.path.normpath(os.path.join(TPL_DIR, name))
        if not full.endswith(ALLOWED_SUFFIX):
            return self._send(403, 'only .tpl and .key resources are renderable\n')
        if not os.path.isfile(full):
            return self._send(404, 'resource not found\n')
        try:
            with open(full, 'rb') as fh:
                return self._send(200, fh.read())
        except OSError:
            return self._send(403, 'resource not readable\n')

    def do_POST(self):
        if not self._auth_ok():
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.rstrip('/') != '/custody':
            return self._send(404, 'not found\n')
        length = int(self.headers.get('Content-Length') or 0)
        form = urllib.parse.parse_qs(self.rfile.read(length).decode('utf-8', 'replace'))
        proof = (form.get('proof') or [''])[0].strip().lower()
        expect = hashlib.sha256(
            f'{GATEWAY_KEY}|{ARCHIVE_USER}|{ARCHIVE_PASS}'.encode()).hexdigest()
        if not proof or not hmac.compare_digest(proof, expect):
            return self._json(403, {
                'error': 'custody proof rejected',
                'note': 'proof 为 64 位完整十六进制摘要，规则见 /docs/view?name=custody.txt',
            })
        return self._json(200, {
            'flag': FLAG2,
            'branches': BRANCHES,
        })


if __name__ == '__main__':
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
