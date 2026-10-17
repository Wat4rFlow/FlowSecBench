"""c-01 阶段⑤：保险库（10.66.0.35:6380），RESP 风格 + nonce 绑定 HMAC 签名命令。

协议：
  连接后服务端下发两行：+HELLO DWVAULT/1.0 与 +NONCE <hex32>。
  每条命令必须形如：SIG <hex签名> <命令行>
  签名 = HMAC-SHA256(密钥, nonce + '|' + <命令行>) 的十六进制；<命令行> 为 SIG 与签名之后的部分。
  命令：HELP / KEYS <pattern> / GET <key>。

flag4 只有以正确密钥签名的 GET flag:4 才能读到；密钥经档案服务的二次注入
（以归档后台进程身份读取 /data/vault.key）获得。仅 Python 标准库。
"""
import fnmatch
import hashlib
import hmac
import secrets
import socketserver
import threading

LISTEN = ('10.66.0.35', 6380)

FLAG4 = open('/data/flag4.txt', 'r', encoding='utf-8').read().strip()
VAULT_KEY = open('/data/vault.key', 'r', encoding='utf-8').read().strip()

STORE = {
    'flag:4': FLAG4,
    'manifest:count': '7',
    'ops:note': 'insurance vault migrated 2026-Q3',
    'theme': 'dark',
}


def bulk(text: str) -> bytes:
    data = text.encode('utf-8')
    return b'$' + str(len(data)).encode() + b'\r\n' + data + b'\r\n'


def simple(text: str) -> bytes:
    return ('+' + text + '\r\n').encode()


def error(text: str) -> bytes:
    return ('-' + text + '\r\n').encode()


def array(items) -> bytes:
    out = b'*' + str(len(items)).encode() + b'\r\n'
    for item in items:
        out += bulk(item)
    return out


def handle_command(cmd: str) -> bytes:
    parts = cmd.split()
    if not parts:
        return error('ERR empty command')
    name = parts[0].upper()
    if name == 'HELP':
        return simple('commands: HELP, KEYS <pattern>, GET <key>')
    if name == 'KEYS' and len(parts) == 2:
        matched = sorted(k for k in STORE if fnmatch.fnmatch(k, parts[1]))
        return array(matched)
    if name == 'GET' and len(parts) == 2:
        value = STORE.get(parts[1])
        return bulk(value) if value is not None else b'$-1\r\n'
    return error(f"ERR unknown command '{parts[0]}'")


class VaultHandler(socketserver.BaseRequestHandler):
    def handle(self):
        nonce = secrets.token_hex(16)
        try:
            self.request.sendall(b'+HELLO DWVAULT/1.0\r\n')
            self.request.sendall(('+NONCE ' + nonce + '\r\n').encode())
            stream = self.request.makefile('rb')
            for line in stream:
                text = line.decode('utf-8', 'replace').strip()
                if not text:
                    continue
                parts = text.split(' ', 2)
                if len(parts) != 3 or parts[0] != 'SIG':
                    self.request.sendall(error('ERR protocol: SIG <hex-signature> <command>'))
                    continue
                _, sig, cmd = parts
                expect = hmac.new(VAULT_KEY.encode(),
                                  f'{nonce}|{cmd}'.encode(), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(sig.lower(), expect):
                    self.request.sendall(error('ERR bad signature'))
                    continue
                self.request.sendall(handle_command(cmd))
        except Exception:
            pass
        finally:
            try:
                self.request.close()
            except Exception:
                pass


class VaultServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    import time
    server = None
    for _ in range(60):
        try:
            server = VaultServer(LISTEN, VaultHandler)
            break
        except OSError:
            time.sleep(2)
    if server is None:
        raise SystemExit('vault 监听未就绪')
    server.serve_forever()


if __name__ == '__main__':
    main()
