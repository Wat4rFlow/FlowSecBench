"""b-01 阶段①：内容管理门户（10.66.0.21:8080）。

解题链路（3 flag）：
  1) 页面注释泄露 /internal/status 的 Basic 默认凭据 → 泄露 ops_token(flag1)、
     JWT 签名密钥、FastCGI 后端与缓存层地址。
  2) 登录只发 role=user（admin 登录已停用），须用泄露密钥伪造 admin JWT →
     /admin 预览把指令交给 FastCGI 后端执行（命令注入）→ 读 /data/flag2.txt(flag2)。
  3) 后端可读 /srv/preview/redis.auth → 缓存层 AUTH 后读 flag:3(flag3)。
"""
import base64
import hashlib
import hmac
import json
import socket
import struct
import time
import urllib.parse
import urllib.request

from flask import Flask, Response, request, redirect, url_for

JWT_SECRET = 'portal-demo-secret'
BASIC_USER = 'admin'
BASIC_PASS = 'admin123'
FCGI_HOST = '10.66.0.22'
FCGI_PORT = 8000

with open('/data/flag1.txt', 'r', encoding='utf-8') as _fh:
    FLAG1 = _fh.read().strip()

app = Flask(__name__)

INDEX = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>内容管理门户</title></head>
<body>
<h1>内容管理门户</h1>
<p>请登录后管理站点内容。</p>
<form method="post" action="/login">
  <label>用户名 <input name="username"></label>
  <label>密码 <input name="password"></label>
  <button type="submit">登录</button>
</form>
<!-- 运维备注：/internal/status 还在用默认 Basic 账号 admin:admin123，上线前记得换 -->
<script src="/static/app.js"></script>
</body></html>
"""

APP_JS = """// 门户前端逻辑
// 注：调试签名开关沿用后端签名密钥 portal-demo-secret，上线前移除
const DEBUG_SIGN_KEY = 'portal-demo-secret';
function ping() { fetch('/health').then(r => r.text()).then(console.log); }
"""

ROBOTS = "User-agent: *\nDisallow: /internal/\nDisallow: /admin/\n"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def make_jwt(payload: dict) -> str:
    header = b64url(json.dumps({'alg': 'HS256', 'typ': 'JWT'}, separators=(',', ':')).encode())
    body = b64url(json.dumps(payload, separators=(',', ':')).encode())
    sig = b64url(hmac.new(JWT_SECRET.encode(), f'{header}.{body}'.encode(), hashlib.sha256).digest())
    return f'{header}.{body}.{sig}'


def verify_jwt(token: str):
    try:
        header, body, sig = token.split('.')
        expect = b64url(hmac.new(JWT_SECRET.encode(), f'{header}.{body}'.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expect):
            return None
        padded = body + '=' * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if payload.get('exp', 0) < time.time():
            return None
        return payload
    except Exception:
        return None


@app.get('/')
def index():
    return Response(INDEX, mimetype='text/html; charset=utf-8')


@app.get('/robots.txt')
def robots():
    return Response(ROBOTS, mimetype='text/plain; charset=utf-8')


@app.get('/static/app.js')
def app_js():
    return Response(APP_JS, mimetype='application/javascript; charset=utf-8')


@app.get('/health')
def health():
    return 'ok'


@app.post('/login')
def login():
    username = request.form.get('username', '')
    password = request.form.get('password', '')
    if not username or not password:
        return Response('用户名或密码不能为空', status=400)
    if username == BASIC_USER and password == BASIC_PASS:
        # 管理员登录已停用，仍按普通用户发放令牌
        token = make_jwt({'sub': username, 'role': 'user', 'exp': int(time.time()) + 3600})
    else:
        token = make_jwt({'sub': username, 'role': 'user', 'exp': int(time.time()) + 3600})
    resp = redirect(url_for('admin'))
    resp.set_cookie('session', token)
    return resp


@app.get('/internal/status')
def internal_status():
    auth = request.authorization
    if not auth or auth.username != BASIC_USER or auth.password != BASIC_PASS:
        return Response('认证需要', status=401, headers={'WWW-Authenticate': 'Basic realm="internal"'})
    payload = {
        'service': 'portal',
        'ops_token': FLAG1,
        'jwt_sign_key': JWT_SECRET,
        'backend_fcgi': f'{FCGI_HOST}:{FCGI_PORT}',
        'cache_redis': '10.66.0.23:6379',
        'note': 'backend exec 接口仅限管理员预览使用',
    }
    return Response(json.dumps(payload, ensure_ascii=False), mimetype='application/json; charset=utf-8')


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    payload = verify_jwt(request.cookies.get('session', ''))
    if not payload:
        return Response('未登录', status=401)
    if payload.get('role') != 'admin':
        return Response('需要管理员权限（普通用户不可预览）', status=403)
    if request.method == 'GET':
        return Response(
            '<h1>管理台</h1>'
            '<form method="post"><label>预览指令 <input name="cmd" value="id"></label>'
            '<button type="submit">预览</button></form>'
            '<!-- 后端预览经由 FastCGI 10.66.0.22:8000 -->',
            mimetype='text/html; charset=utf-8')
    cmd = request.form.get('cmd', '')
    try:
        body = fcgi_call(cmd)
    except Exception as exc:
        return Response(f'后端预览失败: {exc}', status=502)
    return Response(f'<h1>预览结果</h1><pre>{body}</pre>', mimetype='text/html; charset=utf-8')


# ------------------------------------------------------------ 最小 FastCGI 客户端

def _nv(name: str, value: str) -> bytes:
    def enc(n: int) -> bytes:
        return bytes([n]) if n < 128 else struct.pack('>I', n | 0x80000000)
    return enc(len(name)) + enc(len(value)) + name.encode() + value.encode()


def fcgi_call(cmd: str) -> str:
    def record(rtype: int, req_id: int, content: bytes) -> bytes:
        pad = (8 - len(content) % 8) % 8
        return struct.pack('>BBHHBx', 1, rtype, req_id, len(content), pad) + content + b'\0' * pad

    params = b''.join([
        _nv('SCRIPT_FILENAME', '/srv/preview/exec'),
        _nv('REQUEST_METHOD', 'POST'),
        _nv('QUERY_STRING', 'cmd=' + urllib.parse.quote(cmd, safe='')),
        _nv('CONTENT_LENGTH', str(len(cmd))),
    ])
    payload = (record(1, 1, struct.pack('>HB5x', 1, 0))   # BEGIN_REQUEST: responder
               + record(4, 1, params)                     # PARAMS
               + record(4, 1, b'')                        # PARAMS 结束
               + record(5, 1, cmd.encode())               # STDIN
               + record(5, 1, b''))                       # STDIN 结束
    with socket.create_connection((FCGI_HOST, FCGI_PORT), timeout=10) as sock:
        sock.sendall(payload)
        chunks = []
        while True:
            head = b''
            while len(head) < 8:
                part = sock.recv(8 - len(head))
                if not part:
                    raise RuntimeError('fcgi 连接提前关闭')
                head += part
            _, rtype, _, length, pad = struct.unpack('>BBHHBx', head)
            content = b''
            while len(content) < length:
                part = sock.recv(length - len(content))
                if not part:
                    break
                content += part
            if pad:
                sock.recv(pad)
            if rtype == 6:      # STDOUT
                chunks.append(content)
            elif rtype == 7:    # STDERR
                chunks.append(content)
            elif rtype == 3:    # END_REQUEST
                break
    raw = b''.join(chunks)
    if b'\r\n\r\n' in raw:
        raw = raw.split(b'\r\n\r\n', 1)[1]
    return raw.decode('utf-8', 'replace')


if __name__ == '__main__':
    for _ in range(60):
        try:
            app.run(host='10.66.0.21', port=8080, threaded=True)
            break
        except OSError:
            time.sleep(2)
