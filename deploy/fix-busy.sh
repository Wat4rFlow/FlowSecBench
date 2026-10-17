#!/bin/bash
# 查询进度绑定并结束所有 active 绑定（解除 busy）
set -eu
DSH=http://10.100.12.56:3081
API=$DSH/api/flow/tsecbench
DSH_TOKEN=$(cut -d= -f2 /root/tsb-lab-dsh-token.tmp)
JAR=/tmp/tsb-dsh-cookie.txt

echo "=== 进度快照 ==="
curl -s -b "$JAR" "$API/progress" > /tmp/progress.json
docker run --rm -i -v /tmp:/tmp flow/dsh-env:0.6.0 python3 - <<'PYEOF'
import json
data = json.load(open('/tmp/progress.json'))
snap = data.get('data', {})
print('version:', snap.get('version'))
for item in snap.get('items', []):
    print('item:', item.get('unique_code'), 'score:', item.get('score'),
          'flags:', item.get('correct_flag_count'), '/', item.get('total_flag_count') if item.get('total_flag_count') is not None else item.get('flag_count'))
for b in snap.get('bindings', snap.get('sessions', [])) or []:
    print('binding:', json.dumps(b, ensure_ascii=False)[:300])
# 兜底：任何 active 字段的对象都打出来
def walk(obj, path=''):
    if isinstance(obj, dict):
        if obj.get('status') == 'active':
            print('ACTIVE at', path, ':', json.dumps(obj, ensure_ascii=False)[:300])
        for k, v in obj.items():
            walk(v, f'{path}.{k}')
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk(v, f'{path}[{i}]')
walk(snap)
PYEOF
echo "=== 结束 active 绑定 ==="
IDS=$(docker run --rm -i -v /tmp:/tmp flow/dsh-env:0.6.0 python3 - <<'PYEOF'
import json
data = json.load(open('/tmp/progress.json'))
snap = data.get('data', {})
ids = []
def walk(obj):
    if isinstance(obj, dict):
        if obj.get('status') == 'active' and obj.get('id'):
            ids.append(obj['id'])
        for v in obj.values():
            walk(v)
    elif isinstance(obj, list):
        for v in obj:
            walk(v)
walk(snap)
print('\n'.join(ids))
PYEOF
)
if [ -n "${IDS:-}" ]; then
  for id in $IDS; do
    echo "ending binding $id"
    curl -s -b "$JAR" -X POST "$API/progress/end" \
      -H 'Content-Type: application/json' -H 'X-Flow-Client: 1' \
      -d "{\"id\":\"$id\"}"; echo
  done
else
  echo "no active bindings found"
fi
echo "=== 复查状态 ==="
curl -s -b "$JAR" "$API/status"; echo
