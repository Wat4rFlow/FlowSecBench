#!/usr/bin/env python3
"""d-02 阶段⑤：冷库网关（10.66.0.45:9100），行协议。

  +HELLO GATE1 / +NEED SEED
  HELLO <gate_seed>                 → +LADDER <token> 12
  R <n> <answer>                    → +OK <n+1>（共 12 轮）
  SIGN <ctr> <cmd>                  → +SIG <sig>（仅 GRANT 后）

answer_n = HMAC-SHA256(gateway.key, "<token>|<n>|<answer_{n-1}>") 前 16 位，
answer_0 = gate_seed。全 12 轮通过才下发保险库地址与种子。仅标准库。
"""
import hashlib
import hmac
import os
import socketserver

LISTEN = (os.environ.get('D02_GATE_HOST', '10.66.0.45'),
          int(os.environ.get('D02_GATE_PORT', '9100')))
DATA = os.environ.get('D02_GATE_DATA', '/data')

GATEWAY_KEY = open(os.path.join(DATA, 'gateway.key'), encoding='utf-8').read().strip()
GATE_SEED = open(os.path.join(DATA, 'gate_seed'), encoding='utf-8').read().strip()
VAULT_SEED = open(os.path.join(DATA, 'vault_seed'), encoding='utf-8').read().strip()
VAULT_ADDR = '10.66.0.46:6380'
ROUNDS = 24

BANNER = b'+HELLO GATE1\r\n+NEED SEED\r\n'


def ladder_answer(token: str, n: int, prev: str) -> str:
    msg = f'{token}|{n}|{prev}'.encode()
    return hmac.new(GATEWAY_KEY.encode(), msg, hashlib.sha256).hexdigest()[:16]


class Session(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(BANNER)
        self.wfile.flush()
        token = os.urandom(4).hex()
        prev = GATE_SEED
        round_no = 0
        granted = False

        for raw in self.rfile:
            line = raw.decode('utf-8', 'replace').strip()
            if not line:
                continue
            parts = line.split(' ', 2)
            verb = parts[0].upper()

            if verb == 'HELLO':
                seed = parts[1] if len(parts) > 1 else ''
                if seed != GATE_SEED:
                    self._err('bad seed')
                    continue
                self._send(f'+LADDER {token} {ROUNDS}')
                continue

            if verb == 'R':
                if granted:
                    self._err('already granted')
                    continue
                try:
                    n = int(parts[1])
                    answer = parts[2].strip().lower() if len(parts) > 2 else ''
                except (IndexError, ValueError):
                    self._err('bad round')
                    continue
                if n != round_no + 1:
                    self._err(f'round out of order (expected {round_no + 1})')
                    continue
                if not hmac.compare_digest(answer, ladder_answer(token, n, prev)):
                    self._err('bad answer')
                    continue
                prev = answer
                round_no = n
                if n < ROUNDS:
                    self._send(f'+OK {n + 1}')
                else:
                    granted = True
                    self._send(f'+GRANT {VAULT_ADDR} {VAULT_SEED}')
                continue

            if verb == 'SIGN':
                if not granted:
                    self._err('ladder incomplete')
                    continue
                try:
                    ctr = int(parts[1])
                    cmd = parts[2]
                except (IndexError, ValueError):
                    self._err('usage: SIGN <ctr> <cmd>')
                    continue
                sig = hmac.new(GATEWAY_KEY.encode(), f'{ctr}|{cmd}|{VAULT_SEED}'.encode(),
                               hashlib.sha256).hexdigest()[:32]
                self._send(f'+SIG {sig}')
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
