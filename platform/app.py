"""TSecBench 兼容测试平台（最小实现）。

严格按 Flow 插件 plugins/tsecbench/src/client.js 的契约实现五个端点：
  GET  /openapi/v1/challenges                      列题
  POST /openapi/v1/challenges/start?unique_code=    开题
  GET  /openapi/v1/challenges/hint?unique_code=     提示（影响后续 flag 得分）
  POST /openapi/v1/challenges/submit               提交 flag（JSON body）
  POST /openapi/v1/challenges/close?unique_code=   关题

认证：请求头 BENCHMARK_TOKEN。错误响应为 {code, message}；422 由插件视为参数校验失败。
业务错误码限于：task_not_found / challenge_not_found / invalid_state / duplicate /
resource_unavailable / internal_error。submit 回执字段与 client.js 的 RESPONSE_FIELDS 严格一致。
"""
import json
import os
import threading
import time

from flask import Flask, request, jsonify

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.environ.get('TSB_STATE_FILE', os.path.join(BASE_DIR, 'state.json'))
CHALLENGES_FILE = os.environ.get('TSB_CHALLENGES_FILE', os.path.join(BASE_DIR, 'challenges.json'))
HINT_FACTOR = float(os.environ.get('TSB_HINT_FACTOR', '0.5'))


def _read_tokens():
    # 令牌只从环境或受限文件解析，不回显、不写日志
    file_path = os.environ.get('TSB_TOKEN_FILE')
    if file_path and os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as fh:
            return [line.strip() for line in fh if line.strip()]
    return [t for t in os.environ.get('TSB_TOKENS', '').split(',') if t]


TOKENS = _read_tokens()

app = Flask(__name__)
_lock = threading.RLock()
_state = None


# ---------------------------------------------------------------- 状态持久化

def _load():
    global _state
    with _lock:
        if _state is not None:
            return _state
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as fh:
                _state = json.load(fh)
        else:
            _state = {'challenges': {}, 'events': []}
        return _state


def _save():
    with _lock:
        tmp = DATA_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(_state, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)


def _event(kind, detail):
    with _lock:
        _load()['events'].append({'t': round(time.time(), 3), 'kind': kind, 'detail': detail})
        _save()


def _definitions():
    with open(CHALLENGES_FILE, 'r', encoding='utf-8') as fh:
        rows = json.load(fh)
    return {row['unique_code']: row for row in rows}


def _entry(code, defs):
    state = _load()
    entry = state['challenges'].get(code)
    if entry is None:
        entry = {'container_status': 'stopped', 'container_addr': [],
                 'awarded_flags': [], 'hint_used': False, 'score': 0}
        state['challenges'][code] = entry
        _save()
    return entry


# ---------------------------------------------------------------- 认证与错误

def _auth():
    token = request.headers.get('BENCHMARK_TOKEN', '')
    return bool(token) and token in TOKENS


def _fail(code, message, status=400):
    resp = jsonify({'code': code, 'message': message})
    resp.status_code = status
    return resp


def _need_code():
    code = request.args.get('unique_code', '')
    if not code:
        return None, _fail('validation_error', 'unique_code is required.', 422)
    return code, None


def _award(entry, defs_row):
    """单个 flag 的实际得分：使用过提示则打折扣（对应'提示会扣减后续 flag 得分'）。"""
    per = defs_row['total_score'] // defs_row['flag_count']
    return int(per * HINT_FACTOR) if entry['hint_used'] else per


# ---------------------------------------------------------------- 五个端点

@app.get('/openapi/v1/challenges')
def list_challenges():
    if not _auth():
        return _fail('task_not_found', 'BENCHMARK_TOKEN is invalid or not authorized for this task.', 401)
    defs = _definitions()
    out = []
    for code, row in defs.items():
        entry = _entry(code, defs)
        out.append({
            'unique_code': code,
            'description': row.get('description'),
            'difficulty': row['difficulty'],
            'level': row['level'],
            'total_score': row['total_score'],
            'flag_count': row['flag_count'],
            'correct_flag_count': len(entry['awarded_flags']),
            'is_completed': len(entry['awarded_flags']) >= row['flag_count'],
            'container_status': entry['container_status'],
            'container_addr': list(entry['container_addr']),
        })
    return jsonify(out)


@app.post('/openapi/v1/challenges/start')
def start_challenge():
    if not _auth():
        return _fail('task_not_found', 'BENCHMARK_TOKEN is invalid or not authorized for this task.', 401)
    code, err = _need_code()
    if err:
        return err
    defs = _definitions()
    if code not in defs:
        return _fail('challenge_not_found', f'Challenge {code} does not exist in this task.', 404)
    row = defs[code]
    with _lock:
        entry = _entry(code, defs)
        if entry['container_status'] in ('available', 'pending'):
            return _fail('duplicate', 'Challenge is already started.', 409)
        active = [c for c, e in _load()['challenges'].items()
                  if e['container_status'] in ('available', 'pending')]
        if len(active) >= 3:
            return _fail('resource_unavailable', 'At most three challenges may be active at the same time.', 409)
        entry['container_status'] = 'available'
        entry['container_addr'] = list(row['container_addr'])
        _save()
    _event('start', {'code': code})
    return jsonify({'unique_code': code, 'container_addr': list(row['container_addr'])})


@app.get('/openapi/v1/challenges/hint')
def hint_challenge():
    if not _auth():
        return _fail('task_not_found', 'BENCHMARK_TOKEN is invalid or not authorized for this task.', 401)
    code, err = _need_code()
    if err:
        return err
    defs = _definitions()
    if code not in defs:
        return _fail('challenge_not_found', f'Challenge {code} does not exist in this task.', 404)
    with _lock:
        entry = _entry(code, defs)
        if entry['container_status'] not in ('available', 'pending'):
            return _fail('invalid_state', 'Challenge is not started.', 409)
        entry['hint_used'] = True  # 只影响后续 flag 得分，不直接改当前分
        _save()
    _event('hint', {'code': code})
    return jsonify({'unique_code': code, 'hint': defs[code].get('hint')})


@app.post('/openapi/v1/challenges/submit')
def submit_flag():
    if not _auth():
        return _fail('task_not_found', 'BENCHMARK_TOKEN is invalid or not authorized for this task.', 401)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _fail('validation_error', 'JSON body with unique_code and flag is required.', 422)
    code = body.get('unique_code')
    flag = body.get('flag')
    if not isinstance(code, str) or not code or not isinstance(flag, str) or not (1 <= len(flag) <= 4096):
        return _fail('validation_error', 'unique_code and flag are required.', 422)
    defs = _definitions()
    if code not in defs:
        return _fail('challenge_not_found', f'Challenge {code} does not exist in this task.', 404)
    row = defs[code]
    with _lock:
        entry = _entry(code, defs)
        if entry['container_status'] not in ('available', 'pending'):
            return _fail('invalid_state', 'Challenge is not started.', 409)
        matched = None
        for idx, expected in enumerate(row['flags']):
            if flag == expected and idx not in entry['awarded_flags']:
                matched = idx
                break
        awarded = 0
        if matched is not None:
            awarded = _award(entry, row)
            entry['awarded_flags'].append(matched)
            entry['score'] = entry.get('score', 0) + awarded
            _save()
        snapshot = dict(entry)
    _event('submit', {'code': code, 'correct': matched is not None,
                      'correct_flag_count': len(snapshot['awarded_flags'])})
    return jsonify({
        'correct': matched is not None,
        'awarded': awarded,
        'cumulative_score': snapshot.get('score', 0),
        'correct_flag_count': len(snapshot['awarded_flags']),
        'total_flag_count': row['flag_count'],
        'matched_flag_index': matched,
    })


@app.post('/openapi/v1/challenges/close')
def close_challenge():
    if not _auth():
        return _fail('task_not_found', 'BENCHMARK_TOKEN is invalid or not authorized for this task.', 401)
    code, err = _need_code()
    if err:
        return err
    defs = _definitions()
    if code not in defs:
        return _fail('challenge_not_found', f'Challenge {code} does not exist in this task.', 404)
    with _lock:
        entry = _entry(code, defs)
        closed = entry['container_status'] in ('available', 'pending', 'stop_pending')
        entry['container_status'] = 'stopped'
        entry['container_addr'] = []
        _save()
    _event('close', {'code': code, 'closed': closed})
    return jsonify({'unique_code': code, 'closed': closed})


# ---------------------------------------------------------------- 运维辅助（非 TSecBench 契约）

@app.get('/healthz')
def healthz():
    return jsonify({'ok': True, 'challenges': len(_definitions())})


@app.get('/debug/state')
def debug_state():
    return jsonify(_load())


@app.post('/debug/reset')
def debug_reset():
    with _lock:
        global _state
        _state = {'challenges': {}, 'events': []}
        _save()
    return jsonify({'ok': True})


if __name__ == '__main__':
    _load()
    app.run(host='0.0.0.0', port=int(os.environ.get('TSB_PORT', '3090')), threaded=True)
