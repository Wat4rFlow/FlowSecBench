#!/usr/bin/env python3
"""d-02 分区 C：冷库包服务（10.66.0.49:9400），行协议 + 二进制包。

  +PACK CTRL1 / +NEED TICKET
  OPEN <ticket>   → +OK
  HELP            → +RULE ...（包格式与有效记录判定）
  GET             → +LEN <n>\\r\\n 后紧跟 n 字节包

包格式：
  header  magic 'CSPK'(4) + version u8(=1) + count u16be
  record  id u8 + flags u8 + size u8 + crc8 u8 + payload[size]
  flags   bit0=有效, bit1=已删除
  crc8    多项式 0x07、初值 0
有效记录 = flags 有效位为 1、删除位为 0、crc8 与载荷一致；取 id 最大者的
payload 作为分区片段。包内含 CRC 错误的高 id 诱饵与已删除记录。仅标准库。
"""
import os
import random
import socketserver

LISTEN = (os.environ.get('D02_PACK_HOST', '10.66.0.49'),
          int(os.environ.get('D02_PACK_PORT', '9400')))
DATA = os.environ.get('D02_PACK_DATA', '/data')

PART_C = open(os.path.join(DATA, 'part_c'), encoding='utf-8').read().strip()
TICKET = open(os.path.join(DATA, 'branch_ticket_c'), encoding='utf-8').read().strip()

BANNER = b'+PACK CTRL1\r\n+NEED TICKET\r\n'
RULE = ('+RULE header=CSPK+ver u8+count u16be; record=id u8,flags u8,size u8,'
        'crc8 u8,payload; flags bit0=valid bit1=deleted; crc8 poly=0x07 init=0; '
        'pick the highest id among valid & not deleted & crc-matched records')


def crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def build_packet() -> bytes:
    rng = random.Random(0xC0FFEE)
    records = []

    def add(rid, flags, payload, bad_crc=False):
        crc = crc8(payload)
        if bad_crc:
            crc ^= 0x5A
        records.append(bytes([rid, flags, len(payload), crc]) + payload)

    add(3, 0x01, bytes(rng.choice(b'0123456789abcdef') for _ in range(20)))
    add(9, 0x01, bytes(rng.choice(b'0123456789abcdef') for _ in range(20)))
    add(11, 0x00, bytes(rng.choice(b'0123456789abcdef') for _ in range(20)))
    add(19, 0x03, bytes(rng.choice(b'0123456789abcdef') for _ in range(20)))
    add(23, 0x01, bytes(rng.choice(b'0123456789abcdef') for _ in range(20)), bad_crc=True)
    add(17, 0x01, PART_C.encode())
    records.sort(key=lambda rec: rec[0])
    body = b''.join(records)
    return b'CSPK' + bytes([1]) + len(records).to_bytes(2, 'big') + body


PACKET = build_packet()


class Session(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(BANNER)
        self.wfile.flush()
        opened = False
        for raw in self.rfile:
            line = raw.decode('utf-8', 'replace').strip()
            if not line:
                continue
            parts = line.split(' ', 1)
            verb = parts[0].upper()

            if verb == 'OPEN':
                ticket = parts[1].strip() if len(parts) > 1 else ''
                if ticket != TICKET:
                    self._send('-ERR bad ticket')
                    continue
                opened = True
                self._send('+OK')
                continue

            if verb == 'HELP':
                self._send(RULE)
                continue

            if verb == 'GET':
                if not opened:
                    self._send('-ERR open first')
                    continue
                self._send(f'+LEN {len(PACKET)}')
                self.wfile.write(PACKET)
                self.wfile.flush()
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
