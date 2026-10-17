"""c-01 阶段⑤：调度作业服务（10.66.0.36:8083），异步作业队列。

解题链路：
  1) 档案服务 RCE 读到 /data/job.ticket（"<ticket_id>.<hmac(sched_key, ticket_id)>"）。
  2) POST /v1/jobs?ticket=... 建作业；服务为本次投递生成新的 job_id（不复用历史作业），
     返回 eta_seconds 与轮询地址。
  3) 作业在 ETA 秒内不可用（GET 返回 202 + remaining），到点后返回加密 blob：
     base64( xor( zlib(json), sha256(job_id + "|" + sig)[:16] ) )。
  4) blob 含保险库密钥后半段、审计网关地址与审计种子。
仅 Python 标准库。
"""
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
import urllib.parse
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN = ('10.66.0.36', 8083)
ETA_SECONDS = 420

SCHED_KEY = open('/data/sched.key', 'r', encoding='utf-8').read().strip()
PART_B = open('/data/vault_part_b', 'r', encoding='utf-8').read().strip()
AUDIT_SEED = open('/data/audit_seed', 'r', encoding='utf-8').read().strip()

JOBS = {}
LOCK = threading.Lock()

INDEX = """深水港务 冷归档作业调度（scheduler）
================================================
接口：
  POST /v1/jobs?ticket=<ticket_id>.<sig>   投递作业（ticket 由档案主机签发）
  GET  /v1/jobs/<job_id>?sig=<sig>         轮询作业（job_id 与 sig 由建单响应给出）

说明：
- 每次投递都会生成新的 job_id，不复用历史作业；ETA 从建单时刻起算。
- 作业为异步批处理，建单后 eta_seconds 秒内返回 202（state=running、remaining 秒数）。
- 到点后返回 200，body 含 blob 与 encoding 说明：
    blob = base64( xor( zlib(json), sha256(job_id + "|" + sig) 十六进制摘要前 16 字节 ) )
  其中 json 含保险库密钥后半段、审计网关地址与审计种子。
"""


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def make_blob(job_id: str, sig: str) -> str:
    payload = {
        'vault_key_part_b': PART_B,
        'audit_gateway': '10.66.0.37:9100',
        'audit_seed': AUDIT_SEED,
        'note': '保险库密钥 = 审计网关 GRANT 的前半段 + 本作业的后半段（各 16 位十六进制，按此顺序拼接）',
    }
    key = hashlib.sha256(f'{job_id}|{sig}'.encode()).digest()[:16]
    raw = zlib.compress(json.dumps(payload).encode('utf-8'))
    return b64(bytes(b ^ key[i % len(key)] for i, b in enumerate(raw)))


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'dwp-scheduler/1.0'

    def log_message(self, fmt, *args):
        pass

    def _send(self, body: bytes, ctype: str, status: int = 200):
        self.send_response(status)
        self.send_header('Content-Type', ctype + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200):
        self._send(json.dumps(obj, ensure_ascii=False, indent=2).encode('utf-8'),
                   'application/json', status)

    def _query(self):
        return {k: v[0] for k, v in urllib.parse.parse_qs(
            urllib.parse.urlsplit(self.path).query).items()}

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path in ('/', '/index.html'):
            self._send(INDEX.encode('utf-8'), 'text/plain')
            return
        if not path.startswith('/v1/jobs/'):
            self._json({'error': 'not found'}, 404)
            return
        job_id = path[len('/v1/jobs/'):]
        sig = self._query().get('sig', '')
        with LOCK:
            job = JOBS.get(job_id)
        if not job or not hmac.compare_digest(job['sig'], sig):
            self._json({'error': 'job 不存在或签名不匹配'}, 404)
            return
        elapsed = time.time() - job['created']
        if elapsed < ETA_SECONDS:
            self._json({'job_id': job_id, 'state': 'running',
                        'remaining': int(ETA_SECONDS - elapsed) + 1,
                        'eta_seconds': ETA_SECONDS}, 202)
            return
        self._json({'job_id': job_id, 'state': 'done',
                    'blob': make_blob(job_id, sig),
                    'encoding': 'base64( xor( zlib(json), sha256(job_id + "|" + sig)[:16] ) )'})

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != '/v1/jobs':
            self._json({'error': 'not found'}, 404)
            return
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length else b''
        form = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode('utf-8', 'replace')).items()}
        ticket = form.get('ticket') or urllib.parse.parse_qs(parsed.query).get('ticket', [''])[0]
        try:
            ticket_id, sig = ticket.split('.', 1)
        except ValueError:
            self._json({'error': 'ticket 格式应为 <ticket_id>.<sig>'}, 400)
            return
        expect = hmac.new(SCHED_KEY.encode(), ticket_id.encode(), hashlib.sha256).hexdigest()
        if not sig or not hmac.compare_digest(sig.lower(), expect):
            self._json({'error': 'ticket 签名无效'}, 401)
            return
        # 每次投递都生成新作业，不复用历史作业（避免 ETA 被历史状态预热）
        job_id = secrets.token_hex(6)
        with LOCK:
            JOBS[job_id] = {'created': time.time(), 'sig': sig}
        self._json({'job_id': job_id, 'state': 'queued', 'eta_seconds': ETA_SECONDS,
                    'poll': f'/v1/jobs/{job_id}?sig={sig}'}, 202)


def main():
    server = None
    for _ in range(60):
        try:
            server = ThreadingHTTPServer(LISTEN, Handler)
            break
        except OSError:
            time.sleep(2)
    if server is None:
        raise SystemExit('sched 监听未就绪')
    server.serve_forever()


if __name__ == '__main__':
    main()
