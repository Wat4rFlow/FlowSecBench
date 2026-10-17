#!/usr/bin/env python3
"""平台 API 契约验证：模拟 Flow 插件 client.js 的全部调用路径与响应校验。

运行方式（dsh-env 容器内，host 网络）：
  docker run --rm --network host -v /root/tsb-lab:/root/tsb-lab \
    flow/dsh-env:0.6.0 python3 /root/tsb-lab/deploy/verify-platform.py
"""
import json
import sys
import urllib.error
import urllib.request

BASE = 'http://127.0.0.1:3090'
TOKEN = open('/root/tsb-lab/secrets/benchmark.token').read().strip()
DEFS = {r['unique_code']: r for r in json.load(open('/root/tsb-lab/challenges/challenges.json'))}

passed = failed = 0


def check(name, cond, detail=''):
    global passed, failed
    if cond:
        passed += 1
        print(f'PASS: {name}')
    else:
        failed += 1
        print(f'FAIL: {name} {detail}')


def call(method, path, token=TOKEN, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if token is not None:
        req.add_header('BENCHMARK_TOKEN', token)
    if data is not None:
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as err:
        try:
            return err.code, json.load(err)
        except Exception:
            return err.code, {}


# ---- 基础与认证 ----
s, b = call('POST', '/debug/reset', token=None)
check('初始状态复位（可重复执行）', s == 200 and b.get('ok') is True)
s, b = call('GET', '/healthz', token=None)
check('healthz', s == 200 and b.get('ok') is True)
s, b = call('GET', '/openapi/v1/challenges', token='wrong-token')
check('坏 token → 401 task_not_found', s == 401 and b.get('code') == 'task_not_found')
s, b = call('GET', '/openapi/v1/challenges', token=None)
check('缺 token → 401', s == 401)

# ---- list 字段完整性（与 client.js CHALLENGE_FIELDS 一致） ----
s, b = call('GET', '/openapi/v1/challenges')
check('list → 四题', s == 200 and isinstance(b, list) and len(b) == 4)
item = next(x for x in b if x['unique_code'] == 'tsb-lab-a01')
for field in ['unique_code', 'description', 'difficulty', 'level', 'total_score',
              'flag_count', 'correct_flag_count', 'is_completed', 'container_status', 'container_addr']:
    check(f'list 字段 {field}', field in item, f'missing {field}')
check('初始状态 stopped/空地址', item['container_status'] == 'stopped' and item['container_addr'] == [])

# ---- 不存在的题 ----
s, b = call('POST', '/openapi/v1/challenges/start?unique_code=nope')
check('start 不存在 → 404 challenge_not_found', s == 404 and b.get('code') == 'challenge_not_found')

# ---- a01 全流程（含提示扣分） ----
A01 = DEFS['tsb-lab-a01']
s, b = call('POST', '/openapi/v1/challenges/start?unique_code=tsb-lab-a01')
check('a01 start 返回地址', s == 200 and b == {'unique_code': 'tsb-lab-a01', 'container_addr': ['10.66.0.11:80']})
s, b = call('POST', '/openapi/v1/challenges/start?unique_code=tsb-lab-a01')
check('重复 start → 409 duplicate', s == 409 and b.get('code') == 'duplicate')
s, b = call('GET', '/openapi/v1/challenges/hint?unique_code=tsb-lab-a01')
check('a01 hint', s == 200 and b.get('hint') and b.get('unique_code') == 'tsb-lab-a01')
s, b = call('POST', '/openapi/v1/challenges/submit', body={'unique_code': 'tsb-lab-a01', 'flag': 'flag{wrong}'})
check('错误 flag 不计分', s == 200 and b['correct'] is False and b['awarded'] == 0
      and b['correct_flag_count'] == 0 and b['total_flag_count'] == 1)
s, b = call('POST', '/openapi/v1/challenges/submit', body={'unique_code': 'tsb-lab-a01', 'flag': A01['flags'][0]})
check('正确 flag（用过提示 → 半分 50）', s == 200 and b['correct'] is True and b['awarded'] == 50
      and b['cumulative_score'] == 50 and b['correct_flag_count'] == 1)
s, b = call('POST', '/openapi/v1/challenges/close?unique_code=tsb-lab-a01')
check('a01 close', s == 200 and b == {'unique_code': 'tsb-lab-a01', 'closed': True})
s, b = call('POST', '/openapi/v1/challenges/submit', body={'unique_code': 'tsb-lab-a01', 'flag': A01['flags'][0]})
check('关题后 submit → 409 invalid_state', s == 409 and b.get('code') == 'invalid_state')

# ---- b01 全流程（3 flag 满分） ----
B01 = DEFS['tsb-lab-b01']
s, b = call('POST', '/openapi/v1/challenges/start?unique_code=tsb-lab-b01')
check('b01 start 返回三个地址', s == 200 and b['container_addr'] == ['10.66.0.21:8080', '10.66.0.22:8000', '10.66.0.23:6379'])
total = 0
for i, flag in enumerate(B01['flags'], 1):
    s, b = call('POST', '/openapi/v1/challenges/submit', body={'unique_code': 'tsb-lab-b01', 'flag': flag})
    total += 100
    check(f'b01 flag{i} 计分', s == 200 and b['correct'] is True and b['awarded'] == 100
          and b['cumulative_score'] == total and b['correct_flag_count'] == i and b['total_flag_count'] == 3)
s, b = call('GET', '/openapi/v1/challenges')
item = next(x for x in b if x['unique_code'] == 'tsb-lab-b01')
check('list 显示 b01 完成', item['is_completed'] is True and item['correct_flag_count'] == 3)
s, b = call('POST', '/openapi/v1/challenges/close?unique_code=tsb-lab-b01')
check('b01 close', s == 200 and b['closed'] is True)

# ---- c01 全流程（4 flag 满分，未用提示） ----
C01 = DEFS['tsb-lab-c01']
s, b = call('POST', '/openapi/v1/challenges/start?unique_code=tsb-lab-c01')
check('c01 start 返回七个地址', s == 200 and b['unique_code'] == 'tsb-lab-c01'
      and b['container_addr'] == ['10.66.0.31:80', '10.66.0.32:8081', '10.66.0.33:9000',
                                  '10.66.0.34:8082', '10.66.0.35:6380', '10.66.0.36:8083',
                                  '10.66.0.37:9100'])
total = 0
for i, flag in enumerate(C01['flags'], 1):
    s, b = call('POST', '/openapi/v1/challenges/submit', body={'unique_code': 'tsb-lab-c01', 'flag': flag})
    total += 100
    check(f'c01 flag{i} 计分', s == 200 and b['correct'] is True and b['awarded'] == 100
          and b['cumulative_score'] == total and b['correct_flag_count'] == i and b['total_flag_count'] == 4)
s, b = call('GET', '/openapi/v1/challenges')
item = next(x for x in b if x['unique_code'] == 'tsb-lab-c01')
check('list 显示 c01 完成', item['is_completed'] is True and item['correct_flag_count'] == 4
      and item['total_score'] == 400 and item['container_status'] == 'available')
s, b = call('POST', '/openapi/v1/challenges/close?unique_code=tsb-lab-c01')
check('c01 close', s == 200 and b == {'unique_code': 'tsb-lab-c01', 'closed': True})

# ---- d02 全流程（3 flag 满分，未用提示） ----
D02 = DEFS['tsb-lab-d02']
s, b = call('POST', '/openapi/v1/challenges/start?unique_code=tsb-lab-d02')
check('d02 start 返回十一个地址（含两条历史入口）', s == 200 and b['unique_code'] == 'tsb-lab-d02'
      and b['container_addr'] == ['10.66.0.41:80', '10.66.0.42:8081',
                                  '10.66.0.43:9000', '10.66.0.44:8082',
                                  '10.66.0.45:9100', '10.66.0.46:6380',
                                  '10.66.0.47:9200', '10.66.0.48:9300',
                                  '10.66.0.49:9400', '10.66.0.52:9500',
                                  '10.66.0.53:9600'])
total = 0
for i, flag in enumerate(D02['flags'], 1):
    s, b = call('POST', '/openapi/v1/challenges/submit', body={'unique_code': 'tsb-lab-d02', 'flag': flag})
    total += 140
    check(f'd02 flag{i} 计分', s == 200 and b['correct'] is True and b['awarded'] == 140
          and b['cumulative_score'] == total and b['correct_flag_count'] == i
          and b['total_flag_count'] == 3)
s, b = call('GET', '/openapi/v1/challenges')
item = next(x for x in b if x['unique_code'] == 'tsb-lab-d02')
check('list 显示 d02 完成', item['is_completed'] is True and item['correct_flag_count'] == 3
      and item['total_score'] == 420 and item['container_status'] == 'available')
s, b = call('POST', '/openapi/v1/challenges/close?unique_code=tsb-lab-d02')
check('d02 close', s == 200 and b == {'unique_code': 'tsb-lab-d02', 'closed': True})

# ---- 参数校验 ----
s, b = call('POST', '/openapi/v1/challenges/submit', body={'unique_code': 'tsb-lab-b01'})
check('submit 缺 flag → 422', s == 422)
s, b = call('POST', '/openapi/v1/challenges/start')
check('start 缺 unique_code → 422', s == 422)

# ---- 复位（给真实 E2E 留干净状态） ----
s, b = call('POST', '/debug/reset', token=None)
check('状态复位', s == 200 and b.get('ok') is True)

print(f'== 结果: {passed} 通过, {failed} 失败 ==')
sys.exit(1 if failed else 0)
