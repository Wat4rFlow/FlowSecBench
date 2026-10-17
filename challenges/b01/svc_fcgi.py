"""b-01 阶段②：FastCGI 后端（10.66.0.22:8000），实现 responder 帧的最小解析。

/exec 接口执行 QUERY_STRING（或 STDIN）里的 cmd，不做过滤（预留命令注入面）。
flag2 在 /data/flag2.txt（仅能经命令执行读取）；本机另有 /srv/preview/redis.auth
可读到缓存层口令，作为通往 flag3 的跳板。
"""
import socket
import struct
import subprocess
import threading
import time
import urllib.parse

LISTEN = ('10.66.0.22', 8000)


def parse_nv(data: bytes) -> dict:
    out = {}
    i = 0
    while i < len(data):
        def read_len():
            nonlocal i
            first = data[i]
            if first < 128:
                i += 1
                return first
            value = struct.unpack('>I', data[i:i + 4])[0] & 0x7FFFFFFF
            i += 4
            return value
        nlen = read_len()
        vlen = read_len()
        name = data[i:i + nlen].decode('latin-1')
        i += nlen
        out[name] = data[i:i + vlen].decode('latin-1')
        i += vlen
    return out


def handle_request(params: dict, stdin: bytes) -> bytes:
    query = params.get('QUERY_STRING', '')
    cmd = ''
    for part in query.split('&'):
        if part.startswith('cmd='):
            cmd = urllib.parse.unquote_plus(part[4:])
    if not cmd and stdin:
        cmd = stdin.decode('latin-1')
    if not cmd:
        body = 'usage: cmd=<command>'
    else:
        try:
            proc = subprocess.run(['sh', '-c', cmd], capture_output=True, timeout=15)
            body = proc.stdout.decode('utf-8', 'replace') + proc.stderr.decode('utf-8', 'replace')
        except Exception as exc:
            body = f'exec error: {exc}'
    return f'Status: 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}'.encode()


def record(rtype: int, req_id: int, content: bytes) -> bytes:
    pad = (8 - len(content) % 8) % 8
    return struct.pack('>BBHHBx', 1, rtype, req_id, len(content), pad) + content + b'\0' * pad


def client_thread(sock):
    stream = sock.makefile('rb')
    try:
        params = {}
        stdin = b''
        req_id = 1
        while True:
            head = b''
            while len(head) < 8:
                part = sock.recv(8 - len(head))
                if not part:
                    return
                head += part
            _, rtype, rid, length, pad = struct.unpack('>BBHHBx', head)
            content = b''
            while len(content) < length:
                part = sock.recv(length - len(content))
                if not part:
                    return
                content += part
            if pad:
                sock.recv(pad)
            if rid:
                req_id = rid
            if rtype == 4 and content:      # PARAMS
                params.update(parse_nv(content))
            elif rtype == 5:                # STDIN
                if content:
                    stdin += content
                else:
                    out = handle_request(params, stdin)
                    sock.sendall(record(6, req_id, out))
                    sock.sendall(record(6, req_id, b''))
                    sock.sendall(record(3, req_id, struct.pack('>IB3x', 0, 0)))
                    params = {}
                    stdin = b''
    except Exception:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass


def main():
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
        raise SystemExit('fcgi 监听未就绪')
    while True:
        conn, _ = server.accept()
        threading.Thread(target=client_thread, args=(conn,), daemon=True).start()


if __name__ == '__main__':
    main()
