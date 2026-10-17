#!/usr/bin/env python3
"""d-02 阶段⑥：保险库（10.66.0.46:6380），行协议。

  +HELLO VAULT1 / +NEED AUTH
  AUTH <vault_seed>              → +OK
  SIG <ctr> <sig> <cmd>          → +KEYS ... / +VAL ... / -ERR ...

sig = HMAC-SHA256(gateway.key, "<ctr>|<cmd>|<vault_seed>") 前 32 位；
ctr 为十进制且必须严格递增（重放与乱序都会被拒）。仅标准库。
"""
import hashlib
import hmac
import os
import socketserver

LISTEN = (os.environ.get('D02_VAULT_HOST', '10.66.0.46'),
          int(os.environ.get('D02_VAULT_PORT', '6380')))
DATA = os.environ.get('D02_VAULT_DATA', '/data')

GATEWAY_KEY = open(os.path.join(DATA, 'gateway.key'), encoding='utf-8').read().strip()
VAULT_SEED = open(os.path.join(DATA, 'vault_seed'), encoding='utf-8').read().strip()
FLAG3 = open(os.path.join(DATA, 'flag3.txt'), encoding='utf-8').read().strip()

BANNER = b'+HELLO VAULT1\r\n+NEED AUTH\r\n'


class Session(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(BANNER)
        self.wfile.flush()
        authed = False
        last_ctr = 0

        for raw in self.rfile:
            line = raw.decode('utf-8', 'replace').strip()
            if not line:
                continue
            parts = line.split(' ', 1)
            verb = parts[0].upper()

            if verb == 'AUTH':
                seed = parts[1].strip() if len(parts) > 1 else ''
                if hmac.compare_digest(seed, VAULT_SEED):
                    authed = True
                    self._send('+OK')
                else:
                    self._err('auth failed')
                continue

            if verb == 'SIG':
                if not authed:
                    self._err('not authenticated')
                    continue
                fields = parts[1].split(' ', 2) if len(parts) > 1 else []
                if len(fields) < 3:
                    self._err('usage: SIG <ctr> <sig> <cmd>')
                    continue
                ctr_text, sig, cmd = fields[0], fields[1].strip().lower(), fields[2]
                try:
                    ctr = int(ctr_text)
                except ValueError:
                    self._err('bad counter')
                    continue
                if ctr <= last_ctr:
                    self._err('stale counter')
                    continue
                expect = hmac.new(GATEWAY_KEY.encode(),
                                  f'{ctr}|{cmd}|{VAULT_SEED}'.encode(),
                                  hashlib.sha256).hexdigest()[:32]
                if not hmac.compare_digest(sig, expect):
                    self._err('bad signature')
                    continue
                last_ctr = ctr
                if cmd == 'KEYS':
                    self._send('+KEYS flag:3')
                elif cmd == 'GET flag:3':
                    self._send('+VAL ' + FLAG3)
                else:
                    self._err('unknown command')
                continue

            self._err('unknown command')

    def _send(self, text):
        self.wfile.write((text + '\r\n').encode())
        self.wfile.flush()

    def _err(self, text):
        self._send('-ERR ' + text)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == '__main__':
    Server(LISTEN, Session).serve_forever()
