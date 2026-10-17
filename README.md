# FlowSecBench

TSecBench 兼容的本地模拟测试环境：一台实验机（Docker）内提供平台 API、VPN 入口与四道递进难度的靶场题，
用 Flow 的 TSecBench 插件做端到端验收（零插件修改）。

## 组成

| 组件 | 说明 |
|---|---|
| `platform/` | TSecBench 兼容平台（Flask）：list/start/hint/submit/close + `/healthz`、`/debug/state`、`/debug/reset` |
| `challenges/a01/` | easy / 100 分 / 1 flag：员工论坛 robots.txt → 备份目录泄露 |
| `challenges/b01/` | hard / 300 分 / 3 flag：门户凭据泄露 → 伪造 JWT → FastCGI 命令执行 → Redis |
| `challenges/c01/` | expert / 400 分 / 4 flag：七跳深链路（门户 → 认证 → 调度中继 → 档案 → 作业调度 → 审计网关 → 保险库） |
| `challenges/d02/` | expert / 420 分 / 3 flag：九跳零等待链路（门户 → 认证 → 中继 → 归档 → 票据/分区/冷库包三分区 → 网关 → 保险库） |
| `deploy/` | 一键部署、增量部署、题库校验、解题链路自检、日常回归、网络冲突缓解脚本 |
| `docs/` | `prepare_network` 路由冲突的根因分析与根治移交文档 |
| `HANDOFF.md` | 交接说明：拓扑、API 契约、踩坑清单、更新记录 |

## 拓扑要点

- 靶场网段 `10.66.0.0/24`（platform `.2`、a01 `.11`、b01 `.21–.23`、c01 `.31–.37`、d02 `.41–.49`、vpn `.10`）。
- VPN 隧道 `10.66.1.0/24`；因环境无 iptables，采用**静态回程路由**：每个题目容器
  `ip route add 10.66.1.0/24 via 10.66.0.10`。
- 插件侧按 `container_addr` 注入 `10.66.0.x/32 dev tun-flow proto static metric 42700`。

## 快速开始（实验机）

```bash
# 全量部署（幂等；会复用既有的 benchmark token / PKI / client.ovpn）
bash deploy/setup.sh

# 仅新增/更新 c01（不动平台与既有题目）
bash deploy/add-c01.sh

# 仅新增/更新 d02
bash deploy/add-d02.sh

# 平台契约自检
docker run --rm --network host -v /root/tsb-lab:/root/tsb-lab flow/dsh-env:0.6.0 \
  python3 /root/tsb-lab/deploy/verify-platform.py

# 解题链路自检（c01 含真实时序等待，d02 零等待；整体约 10–12 分钟）
docker run --rm --network tsb-lab --ip 10.66.0.50 -v /root/tsb-lab:/lab flow/dsh-env:0.6.0 \
  python3 /lab/deploy/solve-test.py

# 日常回归（verify + solve 串跑，日志 /root/tsb-lab/regression.log）
bash deploy/regression.sh
```

## 凭据与数据

仓库**不包含**任何运行时凭据：

- `runtime/benchmark.token`、`runtime/client.ovpn`（含客户端证书私钥）仅存在于实验机，已被 `.gitignore` 排除。
- `secrets/`（题目 flag、密钥、口令分段）由 `deploy/gen-c01-secrets.sh` 在部署期生成，不入库。
- `pki/`（CA/服务端/客户端证书）由 `deploy/gen-pki.sh` 在部署期生成，不入库。

## 已知限制

- `flow-dsh-live` 以 host 网络运行，靶场网桥的 `10.66.0.1/24` 会让插件 `prepare_network`
  返回 `TARGET_ROUTES_CONFLICT`。临时缓解见 `deploy/fix-bridge-conflict.sh`（网桥地址改 `/32`，
  非持久化）；根治方案与实施步骤见 `docs/PREPARE-NETWORK-HANDOFF.md`。
- 平台最多同时 active 3 题；使用 hint 后该题后续 flag 得分减半。
