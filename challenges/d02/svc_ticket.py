#!/usr/bin/env python3
"""d-02 分区 A：票据核验（10.66.0.47:9200）。

  GET /                    接口说明
  GET /verify?t=&code=     布尔查询：该票据是否存在（SQLite 直接拼接，历史实现）
  GET /claim?t=&code=      精确比对，成功返回分区 A 的种子片段

/verify 只回 true/false，且查询语句由字符串拼接构造——需要用布尔盲注逐位
还原 20 位票据码；/claim 在 Python 侧做精确相等，注入无法直接取片段。
仅 Python 标准库。
"""
import os
import sqlite3
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN = (os.environ.get('D02_TICKET_HOST', '10.66.0.47'),
          int(os.environ.get('D02_TICKET_PORT', '9200')))
DATA = os.environ.get('D02_TICKET_DATA', '/data')

PART_A = open(os.path.join(DATA, 'part_a'), encoding='utf-8').read().strip()
TICKET = open(os.path.join(DATA, 'branch_ticket_a'), encoding='utf-8').read().strip()

DB = sqlite3.connect(':memory:', check_same_thread=False)
DB.execute('CREATE TABLE tickets (id INTEGER PRIMARY KEY, code TEXT, note TEXT)')
DB.execute('INSERT INTO tickets (id, code, note) VALUES (1, ?, ?)',
           (PART_A, 'coldchain-branch-a'))
DB.commit()

INDEX = """冷库分区 A · 票据核验（10.66.0.47:9200）
================================================
GET /verify?t=<分区票据>&code=<票据码>   布尔查询（只回 match）
GET /claim?t=<分区票据>&code=<票据码>    精确比对，成功返回种子片段

实现说明：/verify 为 2024 年遗留的布尔核验接口（未参数化），
查询异常时统一返回 match=false。
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype='text/plain; charset=utf-8'):
        raw = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, code, obj):
        import json
        self._send(code, json.dumps(obj, ensure_ascii=False), 'application/json; charset=utf-8')

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip('/') or '/'
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        if path == '/':
            return self._send(200, INDEX)

        ticket = (query.get('t') or [''])[0]
        if not ticket or ticket != TICKET:
            return self._json(403, {'error': 'branch ticket required'})

        code = (query.get('code') or [''])[0]

        if path == '/verify':
            sql = f"SELECT 1 FROM tickets WHERE code = '{code}' LIMIT 1"
            try:
                rows = DB.execute(sql).fetchall()
            except Exception:
                return self._json(200, {'match': False, 'error': 'query failed'})
            return self._json(200, {'match': bool(rows)})

        if path == '/claim':
            if code == PART_A:
                return self._json(200, {'part': PART_A})
            return self._json(403, {'error': 'code mismatch'})

        return self._json(404, {'error': 'not found'})


if __name__ == '__main__':
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
