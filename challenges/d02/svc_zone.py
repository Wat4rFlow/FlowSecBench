#!/usr/bin/env python3
"""d-02 分区 B：分区控制器（10.66.0.48:9300），行协议。

  +ZONE CTRL1 / +NEED TICKET
  OPEN <ticket>        → +STEP 1 <nonce>
  HELP                 → +RULE ...
  Z <n> <token>        → +OK <n+1>（n=24 时 +PART <片段>）
  任一步错误           → +RESET 1 <新 nonce>（回到第 1 步重新计算）

token_n = sha256(salt|nonce|n|prev)[:12]，prev_0 = ticket，
salt = n 为奇数时 "z1"，偶数时 "z2"。仅标准库。
"""
import hashlib
import hmac
import os
import socketserver

LISTEN = (os.environ.get('D02_ZONE_HOST', '10.66.0.48'),
          int(os.environ.get('D02_ZONE_PORT', '9300')))
DATA = os.environ.get('D02_ZONE_DATA', '/data')

PART_B = open(os.path.join(DATA, 'part_b'), encoding='utf-8').read().strip()
TICKET = open(os.path.join(DATA, 'branch_ticket_b'), encoding='utf-8').read().strip()
STEPS = 24

BANNER = b'+ZONE CTRL1\r\n+NEED TICKET\r\n'
RULE = ('+RULE token_n = sha256(salt|nonce|n|prev)[:12]; prev_0 = ticket; '
        'salt = z1 for odd n, z2 for even n; send: Z <n> <token>; '
        'any wrong step -> RESET 1 <new nonce>')


def expected(nonce, n, prev):
    salt = 'z1' if n % 2 else 'z2'
    return hashlib.sha256(f'{salt}|{nonce}|{n}|{prev}'.encode()).hexdigest()[:12]


class Session(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(BANNER)
        self.wfile.flush()
        nonce = ''
        step = 0
        prev = ''

        for raw in self.rfile:
            line = raw.decode('utf-8', 'replace').strip()
            if not line:
                continue
            parts = line.split(' ', 2)
            verb = parts[0].upper()

            if verb == 'OPEN':
                ticket = parts[1] if len(parts) > 1 else ''
                if not hmac.compare_digest(ticket, TICKET):
                    self._send('-ERR bad ticket')
                    continue
                nonce = os.urandom(6).hex()
                step, prev = 1, ticket
                self._send(f'+STEP 1 {nonce}')
                continue

            if verb == 'HELP':
                self._send(RULE)
                continue

            if verb == 'Z':
                if step == 0:
                    self._send('-ERR open first')
                    continue
                try:
                    n = int(parts[1])
                    token = parts[2].strip().lower() if len(parts) > 2 else ''
                except (IndexError, ValueError):
                    self._send('-ERR bad request')
                    continue
                if n != step or token != expected(nonce, n, prev):
                    nonce = os.urandom(6).hex()
                    step, prev = 1, TICKET
                    self._send(f'+RESET 1 {nonce}')
                    continue
                prev = token
                step += 1
                if step > STEPS:
                    self._send(f'+PART {PART_B}')
                    step = 0
                else:
                    self._send(f'+OK {step}')
                continue

            self._send('-ERR unknown command')

    def _send(self, text):
        self.wfile.write((text + '\r\n').encode())
        self.wfile.flush()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == '__main__':
    Server(LISTEN, Session).serve_forever()
