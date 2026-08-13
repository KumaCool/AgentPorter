# 可移植 Worker 规范

## 0. 0.1.4 发布候选状态（Phase F）

| 维度 | 当前证据状态 |
|---|---|
| installation | fresh 三 Profile 与 legacy 双 Worker → 三 Profile 的安装、升级、读回、改名、卸载已通过离线及隔离 Hermes v0.20 验证。 |
| binding | `agentporter-activate` 的 snapshot/确认/精确写入读回/compare-before-restore 事务已离线通过；只作用两个 Worker。 |
| credential | 由操作者授权并由 Hermes/用户持有；AgentPorter 不读取、复制或持久化秘密。 |
| canary | v0.20 为 `probe-unsupported`，在模型适配调用前关闭，零模型调用；未达到 runtime-ready。 |
| dispatcher | 专用 orchestrator 配置静态读回通过；未启动 Gateway，未验收 live dispatcher。 |
| route | v0.20 为 `mutation-unsupported`，在 Kanban adapter 调用前关闭，零 Kanban mutation 调用。 |
| continuity | DispatchReceipt、任务级订阅、运行观察、结构性恢复合同仅离线通过；未验收真实投递/接续。 |

`hermes config check` 仅证明静态配置可解析。无任务时 `notify-list == []` 正常；只有正式任务创建后，精确 task/subscription 读回与安全 `DispatchReceipt` 才是解锁 dispatch 的必要条件。本候选未发布、未打标签，不声称 `operational`、真实 canary 或 live routing passed。

> **当前状态：** 0.1.4 候选 schema 定义两个执行 Worker 和一个专用 orchestrator；三组件生命周期已验证，但 activation 仍只绑定两个 Worker。v0.20 的 probe 与 Kanban mutation 均 fail closed 为 unsupported，本文不得被理解为编排主链已真实接通。

## 1. 权威文件

打包资源 `src/agentporter/resources/workers.yaml` 是第一版 Worker 集的唯一权威输入：

```yaml
version: 1
project: agentporter
workers:
  <portable_id>:
    display_name: <human-readable name>
    tier: bounded | mechanical
    model: <requested model id>
    provider: <optional provider id>
    reasoning_effort: none | minimal | low | medium | high | xhigh | max | ultra
    description: <routing description>
    instructions: <strict worker instructions>
```

`provider` 可省略；省略时安装计划必须明确要求用户选择、沿用已验证环境配置或在安装后配置，不能猜测 Provider。仓库不得携带 API key、私有 base URL 或账号配置。

## 2. 标识符与 Hermes 映射

Portable ID 使用：

```text
^[a-z][a-z0-9_]{0,63}$
```

Hermes Profile 名必须满足当前 Hermes 原生约束：

```text
[a-z0-9][a-z0-9_-]{0,63}
```

同时拒绝当前 Hermes 保留名。第一版初始映射：

| Portable ID | Hermes Profile |
|---|---|
| `luna_worker` | `luna_worker` |
| `codex_5_3_small_worker` | `codex-5-3-small-worker` |

映射只用于安装计划、初始目标寻址和结果展示，不构成所有权身份；事务与补偿规则见 [安装、卸载与验收设计](03-installation-and-uninstall-design.md)。

## 3. Tier 语义

### `bounded`

- 主代理已经冻结目标、范围、约束和验收要求；
- Worker 可以在边界内实现、验证或分析；
- 不允许重设目标、扩展文件集或引入邻近工作。

### `mechanical`

- 步骤、路径、筛选条件或变换规则必须明确；
- 只允许低判断量、低风险、机械可验的工作；
- 需要架构、产品或多方案权衡时必须退回；
- 任务复杂度必须严格低于 `bounded` Worker。

## 4. 委派契约

委派至少包含：

```yaml
goal: 单一目标
scope:
  files: [允许读取或修改的路径]
  operations: [允许执行的操作]
constraints: [禁止事项]
acceptance: [完成判据与验证命令]
output: [返回格式]
```

边界不完整时 Worker 必须阻塞，而不是自行扩大范围。

## 5. Hermes 派生规则

每个 Worker 渲染为独立 distribution staging：

```text
<staging>/<profile-name>/
├── distribution.yaml
├── config.yaml
├── SOUL.md
└── agentporter-profile.json
```

第一版不捆绑 cron、MCP 或额外 skills，避免扩大权限和更新面。`agentporter-profile.json` 使用固定 product/component ID 与共享随机 installation ID；名称无关身份、安装补偿和批量重命名卸载规则由 [安装、卸载与验收设计](03-installation-and-uninstall-design.md) 统一定义。

### `distribution.yaml`

至少包含：

- 安装时初始 Profile 名，仅供 Hermes 安装和诊断，不构成 AgentPorter 所有权身份；
- AgentPorter distribution 版本；
- 路由描述；
- 可选的最低 Hermes 版本约束；只有兼容矩阵证明真实支持下限后才允许加入，Phase 1 不因开发机版本而作出最低版本承诺；
- MIT 许可证声明；
- 显式 `distribution_owned`，第一版只允许 `SOUL.md`、`config.yaml` 与 `agentporter-profile.json`。

### `config.yaml`

只包含实现 Worker 所需的最小非秘密字段：

- `model.default`；
- 可选 `model.provider`；
- `agent.reasoning_effort`；
- 后续经批准的最小工具配置。

不得渲染 API key、token、私有 base URL、个人路径、默认工作目录、网关凭证或默认 Profile 的无关配置。

### `SOUL.md`

必须完整保留：

- Worker 的允许职责；
- 不改变目标；
- 不扩大范围；
- 缺信息即阻塞；
- 不用虚构结果替代真实执行；
- `mechanical` Worker 的更窄复杂度边界。

`SOUL.md` 是行为指令，不是文件系统隔离机制。

## 6. 编排扩展边界

当前 `tier + description + instructions` 足以渲染两个有职责差异的 Profile，也足以让 Hermes roster 暴露静态 routing description，但不足以单独冻结完整工作组编排。Plan 02 已决定加入专用 orchestrator；只有该新组件可以采用扩展后的角色、路由、workspace、toolset 和 skill 字段，v0.1.0 两个 Worker 的 marker schema 与 distribution version 不回写。新 orchestrator 必须拥有永久 component ID、继续使用当前可解析的 `MarkerV1`，并按与 legacy 双组件共享的 installation ID 进入兼容发现、补偿和卸载矩阵；不得通过复制同质 Profile 或仅修改名称扩充数量。

## 7. Artifact 验证边界

本规范只要求打包内 `workers.yaml`、distribution、config、SOUL 和 marker 的 schema/映射可验证。安装状态、补偿、模型调用边界和独立卸载均由 [安装、卸载与验收设计](03-installation-and-uninstall-design.md) 定义。

任务分解、assignee 选择与 dispatcher 主链由 [Plan 02](plan/02-multi-agent-orchestration.md) 验证；真实 tier、正确拒绝、任务质量和性能由后置 [Worker 验证与基准计划](plan/03-agent-validation-and-benchmark.md) 评测。两者均不能反向把静态安装状态改写为运行成功。
