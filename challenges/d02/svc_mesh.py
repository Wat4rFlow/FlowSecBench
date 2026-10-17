#!/usr/bin/env python3
"""d-02 阶段③：调度中继（10.66.0.43:9000）。

自定义二进制帧协议 CHN2，连接后先下发一行协议提示，再进入帧循环：
  帧 = b'CHN2' + type:u8 + len:u16be + crc16:u16be + payload
  crc16 为 CCITT-FALSE（init 0xFFFF, poly 0x1021），覆盖 type|len|payload
  1 HELLO(payload='MESH1'+seed) → 2 CHALLENGE(nonce8|mask8)
  3 RESP(xor(sha256(nonce+seed)[:8], mask)) → 4 OPEN(sid4|blob512)
  5 ROUTE(code4|digest8) → 7 GRANT(json)
  6 ERROR(text)
路由表用 sha256(sid|seed) 前 16 字节循环异或，条目 digest 需自行验算。
仅 Python 标准库。
"""
import hashlib
import json
import os
import socketserver

LISTEN = (os.environ.get('D02_MESH_HOST', '10.66.0.43'),
          int(os.environ.get('D02_MESH_PORT', '9000')))
DATA = os.environ.get('D02_MESH_DATA', '/data')

MESH_SEED = open(os.path.join(DATA, 'mesh_seed'), encoding='utf-8').read().strip()
ARCHIVE_PASS_B = open(os.path.join(DATA, 'archive_pass_b'), encoding='utf-8').read().strip()
GATE_ADDR = '10.66.0.45:9100'
BLOB_LEN = 512

BANNER = (b'CHN2 relay | frame=magic(CHN2)+type:u8+len:u16be+crc16:u16be '
          b'(CCITT-FALSE over type|len|payload)+payload | '
          b'1=HELLO(MESH1+seed) 2=CHALLENGE(nonce8|mask8) '
          b'3=RESP(xor(sha256(nonce|seed)[:8],mask)) 4=OPEN(sid4|blob512) '
          b'5=ROUTE(code4|digest8) 7=GRANT(json) 6=ERROR(text) | '
          b'blob=xor(json padded to 512, sha256(sid|seed)[:16] repeated) | '
          b'route digest = sha256(sid|code|seed)[:16] hex; stale entries fail\n')


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def pack(ftype: int, payload: bytes = b'') -> bytes:
    head = bytes([ftype]) + len(payload).to_bytes(2, 'big')
    return b'CHN2' + head + crc16(head + payload).to_bytes(2, 'big') + payload


def xor_stream(raw: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))


class Session(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(BANNER)
        stage = 'hello'
        nonce = b''
        mask = b''
        sid = b''
        routes = []
        while True:
            head = self._read_exact(9)
            if head is None:
                return
            if head[:4] != b'CHN2':
                return self._error('bad magic')
            ftype = head[4]
            length = int.from_bytes(head[5:7], 'big')
            crc = int.from_bytes(head[7:9], 'big')
            payload = self._read_exact(length) if length else b''
            if payload is None:
                return
            if crc16(head[4:7] + payload) != crc:
                self._error('bad crc')
                return

            if stage == 'hello':
                if ftype != 1 or not payload.startswith(b'MESH1'):
                    return self._error('expected HELLO')
                seed = payload[5:].decode('utf-8', 'replace')
                if seed != MESH_SEED:
                    return self._error('bad seed')
                nonce, mask = os.urandom(8), os.urandom(8)
                stage = 'resp'
                self.request.sendall(pack(2, nonce + mask))
                continue

            if stage == 'resp':
                if ftype != 3 or len(payload) != 8:
                    return self._error('expected RESP')
                expect = bytes(a ^ b for a, b in zip(
                    hashlib.sha256(nonce + MESH_SEED.encode()).digest()[:8], mask))
                if payload != expect:
                    return self._error('bad response digest')
                sid = os.urandom(4)
                routes = self._routes(sid)
                blob = json.dumps({'routes': routes}, separators=(',', ':')).encode()
                if len(blob) > BLOB_LEN:
                    return self._error('route table overflow')
                blob = blob.ljust(BLOB_LEN, b' ')
                key = hashlib.sha256(sid + MESH_SEED.encode()).digest()[:16]
                stage = 'route'
                self.request.sendall(pack(4, sid + xor_stream(blob, key)))
                continue

            if stage == 'route':
                if ftype != 5 or len(payload) != 12:
                    return self._error('expected ROUTE')
                code, digest = payload[:4], payload[4:]
                match = next((r for r in routes if bytes.fromhex(r['code']) == code), None)
                if match is None:
                    return self._error('unknown route')
                expect = hashlib.sha256(sid + code + MESH_SEED.encode()).hexdigest()[:16]
                if expect != match['digest'] or digest.hex() != expect:
                    return self._error('stale route')
                stage = 'done'
                self.request.sendall(pack(7, json.dumps({
                    'archive_pass_b': ARCHIVE_PASS_B,
                    'gate': GATE_ADDR,
                }, separators=(',', ':')).encode()))
                continue

            return self._error('session finished')

    def _routes(self, sid):
        """8 条路由，仅 1 条 digest 自洽；其余为陈旧条目。"""
        valid_index = 3
        out = []
        for i in range(8):
            code = os.urandom(4)
            if i == valid_index:
                digest = hashlib.sha256(sid + code + MESH_SEED.encode()).hexdigest()[:16]
            else:
                digest = os.urandom(8).hex()
            out.append({'code': code.hex(), 'dest': 'n%02d' % (i + 1), 'digest': digest})
        return out

    def _read_exact(self, size):
        buf = b''
        while len(buf) < size:
            chunk = self.request.recv(size - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def _error(self, message):
        try:
            self.request.sendall(pack(6, message.encode()))
        except Exception:
            pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == '__main__':
    Server(LISTEN, Session).serve_forever()
