# 可移植 Worker 规范

> **Unreleased 拓扑修正（当前权威）：** 当前产品恰好只有 `bounded_worker` 与 `mechanical_worker` 两个 Worker Profile；主 Hermes agent 是 orchestrator，不再有独立 orchestrator Profile。v0.2.0 确实发布了错误的第三个 `agentporter-orchestrator`；下文三 Profile 叙述仅是历史发布/阶段证据。legacy 组件现在仅支持发现/卸载，以及单独确认的迁移删除。fresh install、activation、canary 均闭合为两个 binding/call。


## 0. Plan 06 v0.2.0 正式发布状态（Phase F）

| 维度 | 当前证据状态 |
|---|---|
| installation | Plan 06 fresh 三职责名与 legacy 旧默认名迁移已通过离线及隔离 Hermes 验证；v0.2.0 tag、7 个托管 assets 与外部读回已通过。 |
| binding | fresh install 在 staging 前要求 bounded/mechanical/orchestrator 三个 Profile 的显式 sealed model/provider/endpoint；activation 原子 binding 已离线覆盖。 |
| credential | 由操作者授权并由 Hermes/Profile 持有；计划、日志与 receipt 不披露秘密。 |
| canary | v0.2.0 未执行真实 model canary；绑定变化会使旧 readiness 失效，未达到 operational。 |
| dispatcher | 专用 orchestrator 配置静态读回通过；未启动 Gateway，未验收 live dispatcher。 |
| route | v0.20 为 `mutation-unsupported`，在 Kanban adapter 调用前关闭，零 Kanban mutation 调用。 |
| continuity | DispatchReceipt、任务级订阅、运行观察、结构性恢复合同仅离线通过；未验收真实投递/接续。 |

`hermes config check` 仅证明静态配置可解析。v0.2.0 已正式发布且 `latest` 已选择该版本；tag、托管 assets 与外部读回已通过，但真实 model canary、Gateway、Kanban mutation/live routing 均未执行。本文不得被理解为 Worker 已 operational。

> **当前发布版：** 新写入定义 `bounded_worker`、`mechanical_worker`、`agentporter_orchestrator`，固定 component UUID 与职责不变；fresh install 在 staging 前要求三个 Profile 分别显式封闭 model/provider/endpoint。

> **迁移边界：** 精确旧默认名只经 `agentporter-activate` 独立确认的 Hermes-native journaled rename 迁移；用户改名保持不变。model/provider/endpoint 任一变化都会使旧 readiness 和 binding-dependent dispatch evidence 失效。

## 1. 权威文件

打包资源 `src/agentporter/resources/workers.yaml` 是第一版 Worker 集的唯一权威输入：

```yaml
version: 1
project: agentporter
workers:
  <portable_id>:
    display_name: <human-readable name>
    tier: bounded | mechanical
    reasoning_effort: none | minimal | low | medium | high | xhigh | max | ultra
    description: <routing description>
    instructions: <strict worker instructions>
```

角色清单不得携带固定 model/provider/endpoint。安装调用者必须为三个职责提供闭合、非空、显式 sealed binding；缺失、未知或变化的选择在 staging 前 fail closed。仓库不得携带 API key、私有 base URL 或账号配置。

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

下一功能版本的目标初始映射为：

| 固定职责 | 新 Portable ID | 新 Hermes Profile | 兼容身份 |
|---|---|---|---|
| 有边界实现与分析 | `bounded_worker` | `agentporter-bounded-worker` | 保留原执行 Worker component UUID |
| 机械化委派 | `mechanical_worker` | `agentporter-mechanical-worker` | 保留原机械 Worker component UUID |
| 编排控制面 | `agentporter_orchestrator` | `agentporter-orchestrator` | 保留 orchestrator component UUID |

旧 Portable ID/旧默认名只作为兼容读取与迁移别名。用户已自行修改的 Profile 名不得被自动覆盖。

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

下一功能版本不得从角色清单直接渲染固定 `model.default`。若 Hermes 安装 schema 要求该字段，渲染前必须取得用户对该 Profile 的显式 model 选择，并将 model/provider/endpoint 作为同一不可变 binding 纳入确认、读回与 readiness；禁止占位模型、仓库默认模型或跨 Profile 隐式继承。

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

## 当前两 Worker 与 canary 修正合同

- `bounded_worker`：仅完成目标、约束、范围、文件和验收均由主 Hermes agent 固定的边界明确工作；信息不足或越界时停止，不猜测、不扩张。
- `mechanical_worker`：只处理更简单的机械委派——极简单操作脚本、大输出读取/过滤/摘要、按精确规则批量编辑；需要更广判断时返回歧义。
- 主 Hermes agent 负责 orchestrate、分解、路由与集成，不是 AgentPorter 安装的第三个 Profile。
- 每 Worker canary 默认 30 秒，可显式配置为 90 秒；授权短语与调用上限均为两个 Worker。
- inherited `key_env` 未解析时返回 `credential-required`，除非目标 Profile 自有 `.env` 可解析。canonical `custom` 只映射封印的具体定义；exit-zero 且 usage `failed=true` 仍按封闭原因失败。
- 失败原因保持封闭：`authentication-failed`、`model-unsupported`、`endpoint-unavailable`、`rate-limited`、`probe-timeout`、`response-contract-failed`、`usage-evidence-invalid`、`unexpected-runtime-route`。
