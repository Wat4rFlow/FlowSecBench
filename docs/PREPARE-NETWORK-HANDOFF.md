# 移交文档：根治 `prepare_network` 的 TARGET_ROUTES_CONFLICT（交后续 Agent 执行）

> 结论先行：这是**运行环境拓扑**问题，不是插件 bug，也不是靶场配置错误。要根治，必须让承载 Flow 实例的
> DSH 进程不再与靶场网段共享宿主网络命名空间。本文给出根因证据、三个方案对比、推荐实施步骤、验收与回滚。
> 在完成前，现有验收采用"应用层直连验证可达后继续"的临时处理，且已在两轮 E2E 中记录在案。

## 1. 现象

`flow.main` 会话调用 TSecBench 插件的 `prepare_network` 时，控制器返回：

```
TARGET_ROUTES_CONFLICT: A target conflicts with a local address, gateway or existing route.
```

随后 `network.state=failed / targets=[]`，执行者若严格按"控制器失败 = 网络前置缺失"策略会中止并要求人工恢复。
实测 5/7 个目标在 TCP 层可直接连通（HTTP 200、TCP 建连 1–8ms），说明网络本身可用，冲突是**路由注入被拒绝**。

## 2. 根因（代码级证据）

插件源码（实例内 `/dsh-home/profiles/flow-live/node_modules/@flow/dsh-tsecbench/src/target-routes.js`）
在执行 `prepare` 时对每个目标做两条硬性检查：

```js
// (1) 目标落在本机非 VPN 接口的地址段内 → 冲突
if (forbidden.has(target) ||
    locals.some((entry) => entry.name !== interfaceName && contains(entry, target)))
  throw fault('TARGET_ROUTES_CONFLICT');

// (2) 目标被非 VPN 接口的 link-scope 路由覆盖 → 冲突
const matches = routes.filter((route) => route.prefix !== 0 && contains(route, target));
if (matches.some((route) => route.raw.dev !== interfaceName &&
    (route.raw.scope === 'link' || route.raw.scope === 253)))
  throw fault('TARGET_ROUTES_CONFLICT');
```

而 `flow-dsh-live` 以 `--network host` 运行（`docker inspect` 显示 `HostConfig.NetworkMode=host`），
宿主上存在靶场网桥：

```
10.66.0.1/24 dev br-e7cd29f12fdc proto kernel scope link src 10.66.0.1
```

因此：
- `locals` 里 `br-e7cd29f12fdc = 10.66.0.1/24` 覆盖所有 `10.66.0.3x/4x` 目标 → 规则 (1) 必然命中；
- 该路由 `dev != tun-flow` 且 `scope=link` → 规则 (2) 也必然命中。

结论：**只要 Flow 进程在宿主 netns 内、靶场又是宿主上的 docker bridge，`prepare_network` 就不可能成功**。

## 3. 为什么"换靶场网段"无效

docker bridge 网络会在**宿主 netns**里创建 `br-xxxx` 并分配网关地址（如 `10.66.0.1/24`）。
无论靶场换成 `10.77.0.0/24` 还是别的 RFC1918 段，宿主 netns 里都会出现对应的 `scope link` 网关路由，
插件两条规则照样命中。换网段只能改变命中的字面值，不能消除冲突。

## 4. 方案对比

| 方案 | 做法 | 优点 | 代价/风险 | 结论 |
|---|---|---|---|---|
| **A. 独立网络命名空间（推荐）** | 把 `flow-dsh-live` 从 `host` 改为专用 bridge 网络；Web 端口用 `-p 10.100.12.56:3081:3082` 发布，DSH 监听 `0.0.0.0`；保留 NET_ADMIN 与 `/dev/net/tun` | 插件检查天然通过；执行者流量真实走 tun-flow；与平台/靶场解耦 | 需要重建容器（停机窗口）；启动命令、健康检查、trusted-host 需同步调整 | 推荐 |
| B. macvlan 承载靶场 | 靶场容器改用 macvlan，不在宿主建 bridge 网关 | 宿主路由表无 10.66 段 | 宿主默认无法直接访问 macvlan 子容器，需要额外 shim；平台 `-p 3090` 发布方式受影响；Kernel 3.10 行为需实测 | 不推荐 |
| C. 接受现状 | 文档化"冲突无害"，靠应用层直连验证 | 零改动 | `prepare_network` 永远 failed，控制器备网语义缺失；换执行者/策略可能再次中止 | 现状兜底 |

### 4.1 临时缓解（已在 2026-10-17 实施，可回滚）

在不迁移实例的前提下，把靶场网桥地址从 `/24` 改为 `/32` 即可让插件的两条规则同时通过，
同时保留容器默认网关与平台/VPN 可达性：

```bash
BR=$(ip -o link show | awk '$2 ~ /^br-/ {print $2}' | cut -d: -f1 | while read -r b; do
       ip -4 addr show "$b" | grep -q 'inet 10\.66\.0\.1/' && echo "$b"; done | head -1)
ip addr del 10.66.0.1/24 dev "$BR"
ip addr add 10.66.0.1/32 dev "$BR"
ip route add 10.66.0.2/32  dev "$BR"     # 平台
ip route add 10.66.0.10/32 dev "$BR"     # VPN 网关
```

脚本：`deploy/fix-bridge-conflict.sh`。效果与限制：

- `locals` 中只剩 `10.66.0.1/32`，不再覆盖 `.31–.37`；`/24` 的 link-scope 路由消失，
  插件可正常注入 `10.66.0.3x/32 dev tun-flow proto static metric 42700`。
- 容器默认网关仍是 `10.66.0.1`（地址存在），平台端口映射与 VPN 均正常。
- **非持久化**：宿主机重启、docker 网络重建、`docker network rm/create` 后失效，需要重新执行；
  它不替代方案 A，只是让控制器备网在现有拓扑下可用。

## 5. 推荐实施步骤（方案 A）

前置（只读，先取证）：

```bash
docker inspect flow-dsh-live --format '{{.HostConfig.NetworkMode}} {{json .Config.Cmd}}'
docker exec flow-dsh-live ip -br addr show tun-flow
ss -tlnp | grep 308
```

1. **准备停机窗口**（建议 10 分钟）。确认没有正在进行的 E2E：`GET /debug/state` 无 `available` 题，
   插件 `status` 的 `busy/connectionBusy=false`。
2. **记录可回滚的启动参数**（现状，原样保存）：
   ```
   --network host
   sh -c "(set -C; : > /dsh-home/.flow-start-consumed) 2>/dev/null || { echo FLOW_FRESH_RUN_REQUIRED >&2; exit 78; }; \
          node /usr/local/bin/lan-proxy.mjs 10.100.12.56 3081 127.0.0.1 3082 & \
          exec node /opt/dsh020/bin/dsh --profile flow-live --host 127.0.0.1 --port 3082 \
               --no-open --trusted-host 10.100.12.56:3081"
   ```
   挂载（必须原样保留，勿动数据）：
   - `/opt/dsh020:/opt/dsh020:ro`
   - `/root/dsh-workspace/Flow/environment/opencode-session-preload.mjs:/flow-runtime/opencode-session-preload.mjs:ro`
   - `/root/dsh-workspace/Flow/.runtime/runs/<run-id>/dsh-home:/dsh-home`
   - `/root/dsh-workspace/Flow/.runtime/runs/<run-id>/task:/task`
3. **创建专用网络**（例如 `flow-net`，`172.30.0.0/24`，注意不要与现有 bridge 冲突）：
   ```bash
   docker network create --subnet 172.30.0.0/24 flow-net
   ```
4. **重建容器**（关键差异）：
   - 去掉 `--network host`，改 `--network flow-net`
   - 端口发布：`-p 10.100.12.56:3081:3082`
   - DSH 监听改为 `--host 0.0.0.0 --port 3082 --trusted-host 10.100.12.56:3081`
   - 删除 `lan-proxy`（端口映射替代它）；启动命令改为
     `exec node /opt/dsh020/bin/dsh --profile flow-live --host 0.0.0.0 --port 3082 --no-open --trusted-host 10.100.12.56:3081`
   - 增加 `--cap-add NET_ADMIN --device /dev/net/tun`（openvpn 需要）
   - **注意哨兵文件**：启动脚本用 `set -C` 创建 `/dsh-home/.flow-start-consumed`，文件存在时会以 78 退出
     （`FLOW_FRESH_RUN_REQUIRED`）。重建前需确认该文件是否允许删除/替换；这是启动器的防重复运行保护，
     不要绕过，应与 Flow 侧确认正确的重建流程。
5. **重连 VPN**：`POST /api/flow/tsecbench/connect`，确认 `vpn.state=connected`（容器内 `ip -br addr show tun-flow`）。
6. **验证备网**：`POST /api/flow/tsecbench/prepare_network`（或会话内工具）应返回 `state=ready`、
   `targets` 为 7 个地址；容器内 `ip route show | grep 10.66.0.` 应出现
   `10.66.0.3x/32 dev tun-flow proto static metric 42700`。

## 6. 验收标准

1. `prepare_network` 返回 `state=ready`，targets 覆盖 c01 的 7 个地址（10.66.0.31–37）。
2. 容器内 `ip route get 10.66.0.31` 显示 `dev tun-flow`（证明流量走隧道，而不是宿主 bridge）。
3. 断开 VPN 后目标不可达、重连后恢复（证明依赖隧道而非直连）。
4. flow.main 会话完成一次 c01 全流程（list→start→prepare_network→delegate→submit×4→close），
   平台回执 4/4、400 分、未用 hint。
5. 不修改 TSecBench 插件任何文件；baseUrl/token/ovpn 三件套不变。

## 7. 约束与禁止

- 不修改 Flow 的 TSecBench 插件代码；不改 `plugins/tsecbench` 下任何文件。
- 不动 `blackrabbit-*` 容器与日常助手 profile/实例。
- 不重新生成 benchmark token 与 `client.ovpn`（`setup.sh` 已改为存在即复用）；ovpn 的 `float` 指令必须保留。
- 环境无 iptables，不要引入 NAT/端口转发方案；静态回程路由 `10.66.1.0/24 via 10.66.0.10` 是定稿。
- 端口可达性用应用层协议直连验证，禁止把 nmap 当判据。

## 8. 风险与回滚

- 风险：Web 端口发布后监听地址变化导致 3081 不可达；`trusted-host` 未同步导致鉴权失败；openvpn 在非 host
  网络下无法创建 tun（缺 `--cap-add NET_ADMIN` / `/dev/net/tun`）。
- 回滚：按第 2 步记录的原始命令与挂载重建 `flow-dsh-live`（`--network host` + lan-proxy），
  恢复 `--host 127.0.0.1`，重连 VPN 并确认 3081 可访问。
- 变更前建议导出 `docker inspect flow-dsh-live > flow-dsh-live.inspect.json` 与
  `docker network inspect <各网络> > networks.json` 作为对照。

## 9. 交接给执行 Agent 的最小动作清单

1. 只读复核本文第 2 节的代码与路由证据（命令已给出）。
2. 与 Flow 维护方确认容器重建流程（含 `.flow-start-consumed` 哨兵）。
3. 在停机窗口内实施方案 A，逐项执行第 5、6 节验证。
4. 将结果（成功/失败、耗时、回执）回写本文件末尾"执行记录"。
5. 若失败，按第 8 节回滚，并在"执行记录"中写明失败点与证据。

## 执行记录（由执行 Agent 填写）

- 执行时间：
- 执行人/Agent：
- 变更摘要：
- 验证结果（prepare_network / 路由 / 断线重连 / E2E）：
- 遗留问题：
