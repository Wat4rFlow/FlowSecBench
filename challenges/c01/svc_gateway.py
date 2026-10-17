"""c-01 阶段①：深水港务集团货代门户（10.66.0.31:80）。

解题链路（5 跳 4 flag）：
  1) 门户提单库 /public/（robots.txt 泄露）内 seal 为 base64：
     FRAG-1/2 + FRAG-2/2 拼接 = flag1；DWKEY-1/2 + DWKEY-2/2 拼接 = 报关密钥（32 位十六进制串）。
  2) 报关密钥用于认证中心（10.66.0.32:8081）的 HMAC 签名请求。
/staff/ 员工通道是冻结死路（引导回认证中心）。
仅 Python 标准库，内存占用 < 100MB。
"""
import base64
import json
import string
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN = ('10.66.0.31', 80)

FLAG1 = open('/data/flag1.txt', 'r', encoding='utf-8').read().strip()
BROKER_KEY = open('/data/broker.key', 'r', encoding='utf-8').read().strip()
KEY_PART1, KEY_PART2 = BROKER_KEY[:16], BROKER_KEY[16:]

MID = len(FLAG1) // 2
FLAG_HALF1, FLAG_HALF2 = FLAG1[:MID], FLAG1[MID:]


def b64(text: str) -> str:
    return base64.b64encode(text.encode('utf-8')).decode('ascii')


MANIFESTS = [
    {'id': 'MN-7701', 'carrier': 'COSCO', 'status': 'cleared', 'ref': 'DWKEY-1/2',
     'seal': b64(f'broker-key-part-1: {KEY_PART1}')},
    {'id': 'MN-7702', 'carrier': 'MSK', 'status': 'cleared', 'ref': 'DWKEY-2/2',
     'seal': b64(f'broker-key-part-2: {KEY_PART2}')},
    {'id': 'MN-8814', 'carrier': 'OOCL', 'status': 'cleared', 'ref': 'FRAG-1/2',
     'seal': b64(FLAG_HALF1)},
    {'id': 'MN-8815', 'carrier': 'HMM', 'status': 'cleared', 'ref': 'FRAG-2/2',
     'seal': b64(FLAG_HALF2)},
    {'id': 'MN-9003', 'carrier': 'APL', 'status': 'hazard', 'ref': None,
     'seal': b64('危险品占位提单：真正的线索请看 ref 字段的成对关系（DWKEY/FRAG 各成一对）。')},
]

INDEX = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>深水港务集团 - 货代门户</title></head>
<body>
<h1>深水港务集团（DeepWater PortOps）货代门户</h1>
<p>为报关行与承运人提供提单、通关与调度服务。</p>
<ul>
  <li><a href="/news/">港务公告</a></li>
  <li><a href="/contact/">联系方式</a></li>
  <li><a href="/staff/">员工通道</a></li>
</ul>
<hr>
<p>内部系统（员工专用）：认证中心 / 调度中继 / 档案服务 / 保险库。</p>
</body></html>
"""

NEWS = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>港务公告</title></head>
<body>
<h1>港务公告</h1>
<dl>
<dt>2026-Q3 系统迁移</dt>
<dd>报关行统一认证已迁移至认证中心 auth.dwp.internal:8081；旧员工通道（/staff/）整体冻结停用。</dd>
<dt>通关密钥分存通知</dt>
<dd>自本季度起，通关密钥（报关密钥）不再整串下发，改为<strong>分两段封存</strong>在提单封条（seal）中；
提单库位于 /public/（目录收录见 robots.txt）。</dd>
<dt>封条编码规范</dt>
<dd>提单封条内容统一为 base64 编码；<strong>ref 字段标记了片段的配对与顺序</strong>（形如 x/2）。</dd>
</dl>
<p><a href="/">返回门户首页</a></p>
</body></html>
"""

CONTACT = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>联系方式</title></head>
<body>
<h1>联系方式</h1>
<p>通关业务：clearance@dwp.internal　调度值班：dispatch@dwp.internal</p>
<p>注：调度中继、档案服务与保险库为内部系统，不对报关行开放直连入口。</p>
<p><a href="/">返回门户首页</a></p>
</body></html>
"""

STAFF = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>员工通道</title></head>
<body>
<h1>员工通道（已冻结）</h1>
<form method="post" action="/staff/login">
  <label>工号 <input name="uid"></label>
  <label>口令 <input name="pass" type="password"></label>
  <button type="submit">登录</button>
</form>
</body></html>
"""

STAFF_DENY = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>登录失败</title></head>
<body>
<h1>账号已冻结</h1>
<p>员工通道自 Q3 起停用，账号不再核验。请统一使用认证中心（auth.dwp.internal:8081）。</p>
<p><a href="/staff/">返回</a></p>
</body></html>
"""

ROBOTS = "User-agent: *\nDisallow: /public/\n"


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'dwp-gateway/1.0'

    def log_message(self, fmt, *args):
        pass

    def _send(self, body: bytes, ctype: str, status: int = 200):
        self.send_response(status)
        self.send_header('Content-Type', ctype + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text: str, status: int = 200):
        self._send(text.encode('utf-8'), 'text/html', status)

    def _form(self) -> dict:
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length else b''
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode('utf-8', 'replace')).items()}

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in ('/', '/index.html'):
            self._html(INDEX)
        elif path == '/robots.txt':
            self._send(ROBOTS.encode('utf-8'), 'text/plain')
        elif path == '/news/':
            self._html(NEWS)
        elif path == '/contact/':
            self._html(CONTACT)
        elif path in ('/staff/', '/staff'):
            self._html(STAFF)
        elif path in ('/public/', '/public'):
            body = json.dumps({'service': 'dwp-gateway', 'note': '提单库（清关记录与封条）',
                               'manifests': MANIFESTS}, ensure_ascii=False, indent=2)
            self._send(body.encode('utf-8'), 'application/json')
        else:
            self._html('<h1>404</h1><p>页面不存在。</p>', 404)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in ('/staff/login',):
            self._form()  # 无论提交什么一律冻结
            self._html(STAFF_DENY, 403)
        else:
            self._html('<h1>404</h1>', 404)


def main():
    server = None
    for _ in range(60):
        try:
            server = ThreadingHTTPServer(LISTEN, Handler)
            break
        except OSError:
            time.sleep(2)
    if server is None:
        raise SystemExit('gateway 监听未就绪')
    server.serve_forever()


if __name__ == '__main__':
    main()
