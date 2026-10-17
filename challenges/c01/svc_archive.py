"""c-01 阶段④：档案服务（10.66.0.34:8082）。

解题链路：
  1) Basic 认证：archivist + （调度中继路由表前半段 + 认证中心 attest 回执后半段）拼接口令。
  2) /docs 文档说明保险库操作规范（nonce 绑定 HMAC 签名命令）与冷归档作业交接。
  3) 二次注入：/search 只把检索词原样入库；/report 触发批量索引时用遗留子命令
     grep -i -- '<检索词>' <索引文件> 重新执行历史检索词（特殊字符未转义）。
     批量索引以 nobody 身份运行（最小权限），仅能读取 /data 下 world-readable 的
     归档索引与作业票据；服务源码（600 root）与 archive.pass（600 root）不可读。
     借此读到 /data/job.ticket，进入调度作业服务（无 flag，纯跳板）。
仅 Python 标准库。命令执行面只接受一次性短命令，超时 10 秒。
"""
import base64
import os
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN = ('10.66.0.34', 8082)

ARCHIVE_USER = 'archivist'
ARCHIVE_PASS = open('/data/archive.pass', 'r', encoding='utf-8').read().strip()
DOCS_DIR = '/app-c01/docs'
INDEX_FILE = '/data/archive-index.txt'

_history_lock = threading.Lock()
_history = []

DOC_LIST = {
    'indexing.txt': '联合索引流水线（含已知问题 DWP-1173）',
    'transfer.txt': '冷归档作业交接说明（作业票据/调度/审计）',
    'vault-ops.txt': '保险库操作规范（签名命令协议）',
    'portops-notes.txt': '值班备注杂项',
}


def read_doc(name: str):
    if name not in DOC_LIST:
        return None
    path = os.path.join(DOCS_DIR, name)
    if not os.path.isfile(path):
        return None
    return open(path, 'r', encoding='utf-8').read()


def run_batch_index() -> str:
    """遗留批量索引：对每个历史检索词执行归档匹配子命令（未转义 → 二次注入面）。

    以 nobody 身份执行（服务本体以 root 运行）：注入可读 /data 下的 world-readable
    文件（归档索引、作业票据），但读不到 600 权限的服务源码与 archive.pass。
    """
    with _history_lock:
        terms = list(_history)
    outputs = []
    for i, term in enumerate(terms, 1):
        cmd = f"grep -i -- '{term}' {INDEX_FILE}"
        try:
            proc = subprocess.run(['sh', '-c', cmd], capture_output=True, timeout=10,
                                  user='nobody', group='nogroup', extra_groups=[],
                                  cwd='/tmp', env={'PATH': '/usr/local/bin:/usr/bin:/bin',
                                                   'HOME': '/tmp'})
            out = proc.stdout.decode('utf-8', 'replace') + proc.stderr.decode('utf-8', 'replace')
        except Exception as exc:
            out = f'index error: {type(exc).__name__}'
        outputs.append(f'[{i}] $ grep -i -- \'{term}\' {INDEX_FILE}\n{out}')
    return '\n'.join(outputs)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'dwp-archive/1.0'

    def log_message(self, fmt, *args):
        pass

    def _send(self, body: bytes, ctype: str, status: int = 200, headers=None):
        self.send_response(status)
        self.send_header('Content-Type', ctype + '; charset=utf-8')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text: str, status: int = 200, headers=None):
        self._send(text.encode('utf-8'), 'text/html', status, headers)

    def _auth_ok(self) -> bool:
        header = self.headers.get('Authorization', '')
        if not header.startswith('Basic '):
            return False
        try:
            decoded = base64.b64decode(header[6:]).decode('utf-8')
            user, _, password = decoded.partition(':')
        except Exception:
            return False
        return user == ARCHIVE_USER and password == ARCHIVE_PASS

    def _deny(self):
        self._html('<h1>401</h1><p>档案服务需要归档员 Basic 认证。</p>', 401,
                   headers={'WWW-Authenticate': 'Basic realm="dwp-archive"'})

    def _form(self) -> dict:
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length else b''
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode('utf-8', 'replace')).items()}

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if path in ('/', '/index.html'):
            self._html('<h1>深水港务 档案服务</h1><p>归档检索与批量索引。文档目录见 /docs。</p>')
            return
        if not self._auth_ok():
            self._deny()
            return
        if path == '/docs':
            items = ''.join(f'<li><a href="/docs/view?name={n}">{n}</a> — {d}</li>'
                            for n, d in DOC_LIST.items())
            self._html(f'<h1>档案文档</h1><ul>{items}</ul>')
        elif path == '/docs/view':
            name = query.get('name', [''])[0]
            content = read_doc(name)
            if content is None:
                self._html('<h1>404</h1><p>文档不存在（仅限 docs 目录内白名单文件）。</p>', 404)
            else:
                self._html(f'<h1>{name}</h1><pre>{content}</pre>')
        elif path == '/report':
            body = run_batch_index()
            self._html('<h1>批量索引报告</h1><p>以下为后台归档进程原始输出：</p>'
                       f'<pre>{body}</pre>')
        else:
            self._html('<h1>404</h1>', 404)

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != '/search':
            self._html('<h1>404</h1>', 404)
            return
        if not self._auth_ok():
            self._deny()
            return
        q = self._form().get('q', '')
        if not q:
            self._html('<h1>400</h1><p>检索词不能为空。</p>', 400)
            return
        with _history_lock:
            _history.append(q)
            count = len(_history)
        self._html(f'<h1>检索已入库</h1><p>已记录第 {count} 条检索词（原样入库，不做归档匹配）。'
                   '访问 GET /report 触发本轮批量索引。</p>')


def main():
    server = None
    for _ in range(60):
        try:
            server = ThreadingHTTPServer(LISTEN, Handler)
            break
        except OSError:
            time.sleep(2)
    if server is None:
        raise SystemExit('archive 监听未就绪')
    server.serve_forever()


if __name__ == '__main__':
    main()
