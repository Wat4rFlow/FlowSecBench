#!/usr/bin/env python3
"""d-02 死路 A：旧版中继（10.66.0.52:9500），CHN1 协议。

连接后先下发 CHN1 提示；收到第一帧后统一返回“已下线、迁移到 CHN2”，
使这条路径在 1 次请求内即可被证伪。仅 Python 标准库。
"""
import os
import socketserver

LISTEN = (os.environ.get('D02_LEGACY_HOST', '10.66.0.52'),
          int(os.environ.get('D02_LEGACY_PORT', '9500')))

BANNER = (b'CHN1 legacy relay 2024.11 | frame=magic(CHN1)+type:u8+len:u16be+payload | '
          b'HELLO=1 DATA=2 PING=3\r\n')


class Session(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(BANNER)
        self.wfile.flush()
        head = self.rfile.read(7)
        if len(head) < 7:
            return
        if head[:4] != b'CHN1':
            self._reply('ERROR bad magic; this relay only serves CHN1')
            return
        length = int.from_bytes(head[5:7], 'big')
        if length:
            self.rfile.read(length)
        self._reply('ERROR CHN1 decommissioned 2024-11; migrate to CHN2 relay 10.66.0.43:9000')

    def _reply(self, text):
        try:
            self.wfile.write((text + '\r\n').encode())
            self.wfile.flush()
        except Exception:
            pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == '__main__':
    Server(LISTEN, Session).serve_forever()
