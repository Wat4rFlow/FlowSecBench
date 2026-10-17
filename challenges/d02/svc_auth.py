#!/usr/bin/env python3
"""d-02 阶段②：认证中心（10.66.0.42:8081）。

  GET  /spec                              令牌与挑战应答规范（含一枚已过期的签名样例）
  POST /v1/session                        Bearer 令牌换会话（严格校验签名与声明）
  POST /v1/session/<sid>/answer           6 轮串行挑战应答
  POST /v1/attest                         取得中继种子与档案口令前半

令牌签名密钥由门户下发的 aud_seed 派生，JSON 必须是紧凑单行、键序固定，
否则签名对不上——这是本跳的主要工作量来源。仅 Python 标准库。
"""
import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN = (os.environ.get('D02_AUTH_HOST', '10.66.0.42'),
          int(os.environ.get('D02_AUTH_PORT', '8081')))
DATA = os.environ.get('D02_AUTH_DATA', '/data')

AUD_SEED = open(os.path.join(DATA, 'aud_seed'), encoding='utf-8').read().strip()
ARCHIVE_PASS_A = open(os.path.join(DATA, 'archive_pass_a'), encoding='utf-8').read().strip()
MESH_SEED = open(os.path.join(DATA, 'mesh_seed'), encoding='utf-8').read().strip()
MESH_ADDR = '10.66.0.43:9000'

KID = 'edge-aud'
ROUNDS = 6
WINDOW = 300
NONCE_RE = re.compile(r'^[0-9a-f]{16}$')

LOCK = threading.RLock()
SESSIONS = {}
USED_NONCES = set()


def signing_key() -> bytes:
    return hashlib.sha256((AUD_SEED + '|' + KID).encode()).hexdigest()[:32].encode()


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def b64url_dec(text: str) -> bytes:
    pad = '=' * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def compact(obj) -> bytes:
    return json.dumps(obj, separators=(',', ':'), ensure_ascii=False).encode()


def sign(header: dict, payload: dict) -> str:
    head = b64url(compact(header))
    body = b64url(compact(payload))
    sig = hmac.new(signing_key(), f'{head}.{body}'.encode(), hashlib.sha256).digest()
    return f'{head}.{body}.{b64url(sig)}'


HEADER = {'alg': 'HS256', 'kid': KID, 'typ': 'JWT'}
SAMPLE_PAYLOAD = {
    'sub': AUD_SEED[:8],
    'role': 'auditor',
    'scope': ['mesh', 'archive'],
    'exp': int(time.time()) - 1000,
    'nonce': '0' * 16,
}
SAMPLE_TOKEN = sign(HEADER, SAMPLE_PAYLOAD)

SPEC = {
    'service': 'coldchain-auth',
    'token': {
        'type': 'JWT HS256',
        'header': HEADER,
        'payload': {
            'sub': 'aud_seed 前 8 位十六进制',
            'role': 'auditor',
            'scope': ['mesh', 'archive'],
            'exp': 'Unix 秒，与本机时间偏差不得超过 300',
            'nonce': '16 位小写十六进制，一次性',
        },
        'payload_key_order': ['sub', 'role', 'scope', 'exp', 'nonce'],
        'signing_key': '由 aud_seed 与 kid 派生（SHA-256，取 32 个 ASCII 字符作为 HMAC 密钥；具体拼接方式需自行确认）',
        'canonical': 'header 与 payload 各自 JSON 紧凑序列化（分隔符 "," 与 ":"，无空格，保留键序），分别 b64url 去 padding 后以 "." 连接签名',
        'exp_window_seconds': WINDOW,
        'sample_token': SAMPLE_TOKEN,
        'sample_note': '该样例签名正确但 exp 已过期，可用于核对你的规范化实现',
    },
    'session': {
        'endpoint': 'POST /v1/session  (Authorization: Bearer <token>)',
        'challenge_rounds': ROUNDS,
        'answer_rule': "answer_n = sha256(challenge + '|' + answer_{n-1} + '|' + str(n)) 的十六进制全串；answer_0 = 令牌中的 nonce",
        'hint_rule': '服务端每次返回 next_hint = 下一轮期望答案的前 8 位十六进制',
        'attest': 'POST /v1/attest  {"session": "<sid>"}',
    },
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        raw = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _body(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
            return json.loads(self.rfile.read(length) or b'{}')
        except Exception:
            return {}

    def do_GET(self):
        if self.path.rstrip('/') in ('', '/'):
            return self._send(200, 'coldchain-auth: see /spec\n')
        if self.path.startswith('/spec'):
            return self._json(200, SPEC)
        return self._json(404, {'error': 'not found'})

    def do_POST(self):
        if self.path.startswith('/v1/session/'):
            return self._answer()
        if self.path.startswith('/v1/session'):
            return self._session()
        if self.path.startswith('/v1/attest'):
            return self._attest()
        return self._json(404, {'error': 'not found'})

    # ---- 会话建立 ----
    def _session(self):
        auth = self.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return self._json(401, {'error': 'bearer token required'})
        token = auth[7:].strip()
        parts = token.split('.')
        if len(parts) != 3:
            return self._json(401, {'error': 'malformed token'})
        head_b64, body_b64, sig_b64 = parts
        try:
            header = json.loads(b64url_dec(head_b64))
            payload = json.loads(b64url_dec(body_b64))
            sig = b64url_dec(sig_b64)
        except Exception:
            return self._json(401, {'error': 'undecodable token'})
        if header.get('alg') != 'HS256' or header.get('kid') != KID:
            return self._json(401, {'error': 'unsupported header'})
        expect = hmac.new(signing_key(), f'{head_b64}.{body_b64}'.encode(),
                          hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expect):
            return self._json(401, {'error': 'bad signature'})
        if payload.get('sub') != AUD_SEED[:8]:
            return self._json(403, {'error': 'bad subject'})
        if payload.get('role') != 'auditor':
            return self._json(403, {'error': 'role not allowed'})
        scope = payload.get('scope') or []
        if not isinstance(scope, list) or 'mesh' not in scope or 'archive' not in scope:
            return self._json(403, {'error': 'insufficient scope'})
        try:
            exp = int(payload.get('exp'))
        except Exception:
            return self._json(401, {'error': 'bad exp'})
        if abs(exp - time.time()) > WINDOW:
            return self._json(401, {'error': 'token expired or not yet valid'})
        nonce = str(payload.get('nonce') or '')
        if not NONCE_RE.match(nonce):
            return self._json(401, {'error': 'bad nonce format'})
        with LOCK:
            if nonce in USED_NONCES:
                return self._json(409, {'error': 'nonce already used'})
            USED_NONCES.add(nonce)
            sid = os.urandom(6).hex()
            challenge = os.urandom(12).hex()
            SESSIONS[sid] = {'challenge': challenge, 'prev': nonce, 'round': 0}
        return self._json(200, {'session': sid, 'challenge': challenge, 'rounds': ROUNDS,
                                'next_round': 1})

    # ---- 挑战应答 ----
    def _answer(self):
        parts = self.path.rstrip('/').split('/')
        sid = parts[-2] if len(parts) >= 2 else ''
        body = self._body()
        with LOCK:
            sess = SESSIONS.get(sid)
            if sess is None:
                return self._json(404, {'error': 'unknown session'})
            try:
                n = int(body.get('round'))
            except Exception:
                return self._json(422, {'error': 'round required'})
            answer = str(body.get('answer') or '').strip().lower()
            if n != sess['round'] + 1:
                return self._json(409, {'error': 'round out of order',
                                        'expected_round': sess['round'] + 1})
            msg = f"{sess['challenge']}|{sess['prev']}|{n}"
            expect = hashlib.sha256(msg.encode()).hexdigest()
            if not hmac.compare_digest(answer, expect):
                return self._json(403, {'error': 'bad answer',
                                        'next_hint': expect[:8]})
            sess['prev'] = answer
            sess['round'] = n
            if n < ROUNDS:
                nxt = hashlib.sha256(
                    f"{sess['challenge']}|{answer}|{n + 1}".encode()).hexdigest()
                return self._json(200, {'ok': True, 'round': n, 'next_hint': nxt[:8]})
        return self._json(200, {'ok': True, 'round': n, 'done': True})

    # ---- 取证 ----
    def _attest(self):
        body = self._body()
        sid = str(body.get('session') or '')
        with LOCK:
            sess = SESSIONS.get(sid)
            if sess is None:
                return self._json(404, {'error': 'unknown session'})
            if sess['round'] < ROUNDS:
                return self._json(409, {'error': 'challenge rounds incomplete',
                                        'round': sess['round'], 'rounds': ROUNDS})
            SESSIONS.pop(sid, None)
        return self._json(200, {
            'attestation': os.urandom(8).hex(),
            'mesh': MESH_ADDR,
            'mesh_seed': MESH_SEED,
            'archive': {'url': 'http://10.66.0.44:8082', 'user': 'archivist'},
            'archive_pass_a': ARCHIVE_PASS_A,
        })


if __name__ == '__main__':
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
