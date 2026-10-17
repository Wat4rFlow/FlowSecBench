"""c-01 阶段②：认证中心（10.66.0.32:8081）。

解题链路：
  1) 用提单库拼出的报关密钥按 /spec 规范发签名请求 → POST /v1/session 得 broker 会话 JWT。
  2) broker 无 attest 权限；/spec 的调试说明指出 JWT 密钥 = sha256(报关密钥).hexdigest()[:32]，
     需伪造 role=ops 的 JWT → GET /v1/attest 得 flag2、attestation（调度中继交接凭据）、
     档案口令后半段与 mesh 帧协议规范。
attestation 格式 "<id>.<hmac>"，id 内含签发时间戳，5 分钟内单次有效（调度中继校验）。
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN = ('10.66.0.32', 8081)

FLAG2 = open('/data/flag2.txt', 'r', encoding='utf-8').read().strip()
BROKER_KEY = open('/data/broker.key', 'r', encoding='utf-8').read().strip()
ATTEST_KEY = open('/data/attest.key', 'r', encoding='utf-8').read().strip()
ARCHIVE_PASS_PART_B = open('/data/archive_pass_b', 'r', encoding='utf-8').read().strip()

TS_SKEW = 300
SESSION_TTL = 3600
ATTEST_TTL = 300

MESH_PROTOCOL = {
    'transport': 'TCP 10.66.0.33:9000（非 HTTP）',
    'frame': "b'MES1' + type(1字节) + length(4字节大端) + payload(utf-8)",
    'types': {'HELLO': '0x01', 'CHALLENGE': '0x02', 'ROUTE': '0x03', 'GRANT': '0x04', 'ERROR': '0x05'},
    'flow': ('连接后发送 HELLO(payload=attestation) → 收 CHALLENGE(含异或加密路由表与密钥提示) '
             '→ 解密取 route_code → 发 ROUTE(payload=route_code) → 收 GRANT'),
}

SPEC = {
    'service': 'dwp-auth-center',
    'endpoints': {
        'POST /v1/session': '签发报关行会话令牌（role=broker）',
        'GET /v1/attest': '签发调度中继交接凭据（仅 role=ops）',
    },
    'request_signature': {
        'headers': ['X-DW-Client', 'X-DW-Timestamp', 'X-DW-Signature'],
        'algorithm': "HMAC-SHA256(key=报关密钥, message=client + '|' + timestamp)",
        'encoding': 'hex',
        'timestamp': f'unix 秒，允许 ±{TS_SKEW} 秒时钟偏差',
        'key_note': '报关密钥为 32 位十六进制串（提单库两段拼接，见门户公告）',
    },
    'session_token': 'HS256 JWT，经 Cookie: session 携带',
    'debug_note': ('调试构建：JWT 签名密钥与报关密钥同源——'
                   '取 sha256(报关密钥) 十六进制摘要的前 32 个字符。上线前必须移除该调试通道。'),
}

INTRO = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>认证中心</title></head>
<body>
<h1>深水港务 认证中心</h1>
<p>报关行统一认证服务。所有 /v1/* 接口需要按签名规范调用。</p>
<ul><li>签名与令牌规范：<a href="/spec">/spec</a></li></ul>
</body></html>
"""


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def make_jwt(secret: str, payload: dict) -> str:
    header = b64url(json.dumps({'alg': 'HS256', 'typ': 'JWT'}, separators=(',', ':')).encode())
    body = b64url(json.dumps(payload, separators=(',', ':')).encode())
    sig = b64url(hmac.new(secret.encode(), f'{header}.{body}'.encode(), hashlib.sha256).digest())
    return f'{header}.{body}.{sig}'


def verify_jwt(token: str):
    try:
        header, body, sig = token.split('.')
        expect = b64url(hmac.new(JWT_DEBUG_SECRET().encode(), f'{header}.{body}'.encode(),
                                 hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expect):
            return None
        padded = body + '=' * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if payload.get('exp', 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def JWT_DEBUG_SECRET() -> str:
    return hashlib.sha256(BROKER_KEY.encode()).hexdigest()[:32]


def issue_attestation() -> str:
    ident = f'{int(time.time()):010x}{secrets.token_hex(8)}'
    sig = hmac.new(ATTEST_KEY.encode(), ident.encode(), hashlib.sha256).hexdigest()
    return f'{ident}.{sig}'


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'dwp-auth/1.0'

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

    def _json(self, obj, status: int = 200, headers=None):
        self._send(json.dumps(obj, ensure_ascii=False, indent=2).encode('utf-8'),
                   'application/json', status, headers)

    def _cookie_session(self):
        raw = self.headers.get('Cookie', '')
        for part in raw.split(';'):
            if part.strip().startswith('session='):
                return part.strip()[len('session='):]
        return ''

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in ('/', '/index.html'):
            self._send(INTRO.encode('utf-8'), 'text/html')
        elif path == '/spec':
            self._json(SPEC)
        elif path == '/v1/attest':
            payload = verify_jwt(self._cookie_session())
            if not payload:
                self._json({'error': '未登录或会话无效'}, 401)
                return
            if payload.get('role') != 'ops':
                self._json({'error': 'attest 仅对 ops 角色开放（当前会话角色: %s）' % payload.get('role'),
                            'debug': '普通会话无法提权；参见 /spec 的调试说明（debug_note）'}, 403)
                return
            self._json({
                'attestation': issue_attestation(),
                'flag': FLAG2,
                'archive_pass_part_b': ARCHIVE_PASS_PART_B,
                'archive_password_hint': '档案服务口令 = 调度中继路由表中的前半段 + 本回执中的后半段',
                'mesh_protocol': MESH_PROTOCOL,
                'note': 'attestation 自签发起 5 分钟内单次有效',
            })
        else:
            self._json({'error': 'not found'}, 404)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path != '/v1/session':
            self._json({'error': 'not found'}, 404)
            return
        client = self.headers.get('X-DW-Client', '')
        ts_raw = self.headers.get('X-DW-Timestamp', '')
        sig = self.headers.get('X-DW-Signature', '')
        try:
            ts = int(ts_raw)
        except ValueError:
            self._json({'error': 'X-DW-Timestamp 必须为 unix 秒'}, 400)
            return
        if not client or abs(time.time() - ts) > TS_SKEW:
            self._json({'error': 'client 标识或时间戳非法（±300 秒）'}, 400)
            return
        expect = hmac.new(BROKER_KEY.encode(), f'{client}|{ts}'.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig.lower(), expect):
            self._json({'error': '签名无效（按 /spec 规范：HMAC-SHA256(报关密钥, client|timestamp) 的 hex）'}, 401)
            return
        token = make_jwt(JWT_DEBUG_SECRET(),
                         {'sub': client, 'role': 'broker', 'iat': int(time.time()),
                          'exp': int(time.time()) + SESSION_TTL})
        self._json({'ok': True, 'role': 'broker', 'session': token,
                    'mesh_relay': '10.66.0.33:9000',
                    'note': '会话令牌请置于 Cookie: session。调度中继交接凭据需 /v1/attest（仅 ops）。'},
                   headers={'Set-Cookie': f'session={token}; Path=/'})


def main():
    server = None
    for _ in range(60):
        try:
            server = ThreadingHTTPServer(LISTEN, Handler)
            break
        except OSError:
            time.sleep(2)
    if server is None:
        raise SystemExit('auth 监听未就绪')
    server.serve_forever()


if __name__ == '__main__':
    main()
