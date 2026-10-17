"""c-01 阶段③：调度中继（10.66.0.33:9000），自定义二进制帧协议 MES1。

协议帧：b'MES1' + type(1字节) + length(4字节大端) + payload(utf-8)。
类型：HELLO=0x01 CHALLENGE=0x02 ROUTE=0x03 GRANT=0x04 ERROR=0x05。

解题链路：
  1) HELLO 携带认证中心签发的 attestation（id.hmac，5 分钟内单次有效，本服务用共享密钥校验）。
  2) CHALLENGE 返回 XOR 加密的路由表（hex）与密钥提示：sha256(attestation + nonce) 摘要前 16 字节。
  3) 解密路由表得 route_code / 档案服务地址与口令前半段；ROUTE 回发 route_code → GRANT 发 flag3。
仅 Python 标准库。
"""
import hashlib
import hmac
import json
import secrets
import socket
import socketserver
import struct
import threading

LISTEN = ('10.66.0.33', 9000)
FLAG3 = open('/data/flag3.txt', 'r', encoding='utf-8').read().strip()
ATTEST_KEY = open('/data/attest.key', 'r', encoding='utf-8').read().strip()
ROUTE_INFO = json.load(open('/data/route.json', 'r', encoding='utf-8'))

T_HELLO, T_CHALLENGE, T_ROUTE, T_GRANT, T_ERROR = 1, 2, 3, 4, 5
ATTEST_TTL = 300

_used_attest = set()
_used_lock = threading.Lock()


def frame(ftype: int, payload: bytes) -> bytes:
    return b'MES1' + bytes([ftype]) + struct.pack('>I', len(payload)) + payload


def xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def verify_attestation(attestation: str):
    try:
        ident, sig = attestation.strip().split('.')
        expect = hmac.new(ATTEST_KEY.encode(), ident.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig.lower(), expect):
            return False
        issued = int(ident[:10], 16)
        if abs(__import__('time').time() - issued) > ATTEST_TTL:
            return False
        with _used_lock:
            if ident in _used_attest:
                return False
            _used_attest.add(ident)
        return True
    except Exception:
        return False


class RelayHandler(socketserver.BaseRequestHandler):
    def _recv_exact(self, n: int) -> bytes:
        buf = b''
        while len(buf) < n:
            part = self.request.recv(n - len(buf))
            if not part:
                raise ConnectionError('connection closed')
            buf += part
        return buf

    def _read_frame(self):
        head = self._recv_exact(9)
        if head[:4] != b'MES1':
            raise ValueError('bad magic')
        ftype = head[4]
        length = struct.unpack('>I', head[5:9])[0]
        return ftype, self._recv_exact(length)

    def _send_frame(self, ftype: int, payload: bytes):
        self.request.sendall(frame(ftype, payload))

    def handle(self):
        try:
            ftype, payload = self._read_frame()
            if ftype != T_HELLO:
                self._send_frame(T_ERROR, json.dumps({'error': '首帧必须是 HELLO'}).encode())
                return
            attestation = payload.decode('utf-8', 'replace').strip()
            if not verify_attestation(attestation):
                self._send_frame(T_ERROR, json.dumps(
                    {'error': 'attestation 无效、过期或已被使用'}).encode())
                return
            nonce = secrets.token_hex(8)
            key = hashlib.sha256((attestation + nonce).encode()).digest()[:16]
            blob = xor_bytes(json.dumps(ROUTE_INFO).encode(), key).hex()
            challenge = {
                'nonce': nonce,
                'route_blob': blob,
                'hint': '路由表 XOR 密钥 = sha256(attestation + nonce) 摘要的前 16 字节',
            }
            self._send_frame(T_CHALLENGE, json.dumps(challenge).encode())

            ftype, payload = self._read_frame()
            if ftype != T_ROUTE:
                self._send_frame(T_ERROR, json.dumps({'error': '期待 ROUTE 帧'}).encode())
                return
            route_code = payload.decode('utf-8', 'replace').strip()
            if route_code != ROUTE_INFO['route_code']:
                self._send_frame(T_ERROR, json.dumps({'error': 'route_code 不匹配'}).encode())
                return
            grant = {
                'flag': FLAG3,
                'note': '档案口令前半段在路由表（archive_pass_part_a），后半段在认证中心 attest 回执。',
            }
            self._send_frame(T_GRANT, json.dumps(grant).encode())
        except Exception:
            pass
        finally:
            try:
                self.request.close()
            except Exception:
                pass


class RelayServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    import time
    server = None
    for _ in range(60):
        try:
            server = RelayServer(LISTEN, RelayHandler)
            break
        except OSError:
            time.sleep(2)
    if server is None:
        raise SystemExit('mesh 监听未就绪')
    server.serve_forever()


if __name__ == '__main__':
    main()
