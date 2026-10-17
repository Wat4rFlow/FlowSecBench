"""a-01（简单题）：员工论坛，信息泄露拿 flag。

链路：访问站点 → robots.txt 暴露备份目录 → /backup/flag.txt 拿到 flag。
运行于 10.66.0.11:80（与 VPN 靶场同网，需经隧道访问）。
"""
import os
import time

from flask import Flask, Response

FLAG = os.environ['FLAG_A01']
app = Flask(__name__)

INDEX = """<!doctype html>
<html lang="zh">
<head><meta charset="utf-8"><title>内部员工论坛</title></head>
<body>
<h1>内部员工论坛</h1>
<p>欢迎来到公司内部交流区。本论坛仅供内部员工使用。</p>
<ul>
  <li><a href="/notice.html">公告</a></li>
  <li><a href="/robots.txt">站点说明</a></li>
</ul>
<!-- TODO(运维): 备份目录还没搬到对象存储，先临时放在站点里 -->
</body>
</html>
"""

NOTICE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>公告</title></head>
<body><h1>公告</h1><p>近期将对站点做安全检查，请各位同事注意账号安全。</p></body></html>
"""

ROBOTS = "User-agent: *\nDisallow: /backup/\n"


@app.get('/')
def index():
    return Response(INDEX, mimetype='text/html; charset=utf-8')


@app.get('/notice.html')
def notice():
    return Response(NOTICE, mimetype='text/html; charset=utf-8')


@app.get('/robots.txt')
def robots():
    return Response(ROBOTS, mimetype='text/plain; charset=utf-8')


@app.get('/backup/flag.txt')
def backup_flag():
    return Response(FLAG + '\n', mimetype='text/plain; charset=utf-8')


@app.get('/backup/')
def backup_dir():
    return Response('<html><body><h1>/backup/</h1><ul><li><a href="flag.txt">flag.txt</a></li></ul></body></html>',
                    mimetype='text/html; charset=utf-8')


def serve():
    # 靶场网络由 VPN 容器统一配置，地址就绪前重试绑定
    for _ in range(60):
        try:
            app.run(host='10.66.0.11', port=80, threaded=True)
            return
        except OSError:
            time.sleep(2)
    raise SystemExit('10.66.0.11:80 未就绪')


if __name__ == '__main__':
    serve()
