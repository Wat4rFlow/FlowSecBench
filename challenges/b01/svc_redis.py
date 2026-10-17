"""b-01 阶段③：缓存服务（10.66.0.23:6379），实现 RESP 协议子集。

内存键值表预置业务键；flag:3 只有通过 AUTH 之后才能读到（未认证一律拒绝）。
口令来自 /srv/preview/redis.auth（只有经上一跳命令执行读到它才可能通过认证）。
支持命令：AUTH / ECHO / PING / INFO / GET / SET / KEYS / COMMAND。
"""
import fnmatch
import os
import socket
import struct
import threading
import time

LISTEN = ('10.66.0.23', 6379)
PASSWORD = open('/srv/preview/redis.auth', 'r', encoding='utf-8').read().strip()

STORE = {
    'session:admin': 'sess-9d41b2',
    'theme': 'dark',
    'counter': '17',
}


def encode_simple(text: str) -> bytes:
    return ('+' + text + '\r\n').encode()


def encode_error(text: str) -> bytes:
    return ('-' + text + '\r\n').encode()


def encode_bulk(text: str) -> bytes:
    data = text.encode()
    return b'$' + str(len(data)).encode() + b'\r\n' + data + b'\r\n'


def encode_array(items) -> bytes:
    out = b'*' + str(len(items)).encode() + b'\r\n'
    for item in items:
        out += encode_bulk(item)
    return out


def handle_command(args, authed: bool):
    if not args:
        return encode_error('ERR empty command'), authed
    name = args[0].upper()
    if name == 'COMMAND':
        return encode_array([]), authed
    if name == 'AUTH':
        if len(args) == 2 and args[1] == PASSWORD:
            return encode_simple('OK'), True
        return encode_error('ERR invalid password'), authed
    if name == 'PING':
        return encode_simple('PONG'), authed
    if not authed:
        return encode_error('NOAUTH Authentication required.'), authed
    if name == 'ECHO' and len(args) == 2:
        return encode_bulk(args[1]), authed
    if name == 'INFO':
        return encode_bulk('# Server\r\nredis_version:7.0.0\r\nredis_mode:standalone\r\n'), authed
    if name == 'GET' and len(args) == 2:
        value = STORE.get(args[1])
        return (encode_bulk(value) if value is not None else b'$-1\r\n'), authed
    if name == 'SET' and len(args) == 3:
        STORE[args[1]] = args[2]
        return encode_simple('OK'), authed
    if name == 'KEYS' and len(args) == 2:
        matched = [key for key in STORE if fnmatch.fnmatch(key, args[1])]
        return encode_array(sorted(matched)), authed
    return encode_error(f"ERR unknown command '{args[0]}'"), authed


def read_command(stream):
    line = stream.readline()
    if not line:
        return None
    if line.startswith(b'*'):
        count = int(line[1:])
        args = []
        for _ in range(count):
            header = stream.readline()
            if not header.startswith(b'$'):
                return None
            length = int(header[1:])
            data = stream.read(length)
            stream.read(2)  # CRLF
            args.append(data.decode('utf-8', 'replace'))
        return args
    return line.decode('utf-8', 'replace').strip().split() or []


def client_thread(sock):
    stream = sock.makefile('rb')
    authed = False
    try:
        while True:
            args = read_command(stream)
            if args is None:
                return
            resp, authed = handle_command(args, authed)
            sock.sendall(resp)
    except Exception:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass


def main():
    STORE['flag:3'] = open('/data/flag3.txt', 'r', encoding='utf-8').read().strip()
    for _ in range(60):
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(LISTEN)
            server.listen(16)
            break
        except OSError:
            time.sleep(2)
    else:
        raise SystemExit('redis 监听未就绪')
    while True:
        conn, _ = server.accept()
        threading.Thread(target=client_thread, args=(conn,), daemon=True).start()


if __name__ == '__main__':
    main()
