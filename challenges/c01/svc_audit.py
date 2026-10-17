"""c-01 阶段⑥：审计网关（10.66.0.37:9100），行协议 + 轮换窗口的多轮挑战应答。

解题链路：
  1) 用调度作业 blob 中的审计种子 AUTH 建会话。
  2) 服务端 READY rounds=10 interval=15，并下发 ROUND <n> <challenge>。
  3) 每轮必须在窗口（interval 秒）之后应答 ANSWER <sha256(challenge + seed)>；
     窗口内答复返回 WAIT <sec>（不推进轮次），答错返回 ERR。
  4) 全部轮次通过后 GRANT 返回保险库密钥前半段。
仅 Python 标准库。
"""
import hashlib
import math
import secrets
import socketserver
import time

LISTEN = ('10.66.0.37', 9100)
ROUNDS = 10
INTERVAL = 15

SEED = open('/data/audit_seed', 'r', encoding='utf-8').read().strip()
PART_A = open('/data/vault_part_a', 'r', encoding='utf-8').read().strip()


def answer_for(challenge: str) -> str:
    return hashlib.sha256((challenge + SEED).encode()).hexdigest()


class AuditHandler(socketserver.BaseRequestHandler):
    def send(self, text: str):
        self.request.sendall(text.encode('utf-8'))

    def handle(self):
        try:
            self.send('AUDIT/1 session=%s\n' % secrets.token_hex(4))
            stream = self.request.makefile('rb')
            seed = None
            round_no = 0
            challenge = ''
            issued_at = 0.0
            for line in stream:
                text = line.decode('utf-8', 'replace').strip()
                if not text:
                    continue
                if text.startswith('AUTH '):
                    candidate = text[5:].strip()
                    if candidate != SEED:
                        self.send('ERR bad seed\n')
                        return
                    seed = candidate
                    round_no = 1
                    challenge = secrets.token_hex(12)
                    issued_at = time.time()
                    self.send(f'READY rounds={ROUNDS} interval={INTERVAL}\n')
                    self.send(f'ROUND {round_no} {challenge}\n')
                    continue
                if seed is None:
                    self.send('ERR AUTH required\n')
                    continue
                if not text.startswith('ANSWER '):
                    self.send('ERR unknown command\n')
                    continue
                wait = INTERVAL - (time.time() - issued_at)
                if wait > 0:
                    self.send(f'WAIT {math.ceil(wait)}\n')
                    continue
                if text[7:].strip().lower() != answer_for(challenge):
                    self.send('ERR bad answer\n')
                    continue
                round_no += 1
                if round_no > ROUNDS:
                    self.send(f'GRANT {PART_A} note=保险库密钥前半段；后半段在调度作业 blob\n')
                    return
                challenge = secrets.token_hex(12)
                issued_at = time.time()
                self.send(f'ROUND {round_no} {challenge}\n')
        except Exception:
            pass
        finally:
            try:
                self.request.close()
            except Exception:
                pass


class AuditServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    server = None
    for _ in range(60):
        try:
            server = AuditServer(LISTEN, AuditHandler)
            break
        except OSError:
            time.sleep(2)
    if server is None:
        raise SystemExit('audit 监听未就绪')
    server.serve_forever()


if __name__ == '__main__':
    main()
