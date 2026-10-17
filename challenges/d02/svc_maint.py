#!/usr/bin/env python3
"""d-02 死路 B：维护台（10.66.0.53:9600），HTTP。

所有请求返回 401 + Basic 挑战，正文说明维护凭据已于 2024-11 轮换。
1 次请求即可证伪，不需要继续投入。仅 Python 标准库。
"""
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN = (os.environ.get('D02_MAINT_HOST', '10.66.0.53'),
          int(os.environ.get('D02_MAINT_PORT', '9600')))

BODY = """冷链路维护台（maintenance console）
================================
本控制台仅在内网维护窗口开放。
维护凭据已于 2024-11 统一轮换，旧凭据与工单口令全部失效；
如需操作请联系值班组走变更流程（变更单号 MNT-2024-11）。
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'coldchain-maint/1.4'

    def log_message(self, *args):
        pass

    def _deny(self):
        raw = BODY.encode('utf-8')
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="coldchain-maint"')
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = _deny
    do_POST = _deny
    do_HEAD = _deny


if __name__ == '__main__':
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
