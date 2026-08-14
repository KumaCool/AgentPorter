# AgentPorter 方案总览

> **Unreleased 拓扑修正（当前权威）：** 当前产品恰好只有 `bounded_worker` 与 `mechanical_worker` 两个 Worker Profile；主 Hermes agent 是 orchestrator，不再有独立 orchestrator Profile。v0.2.0 确实发布了错误的第三个 `agentporter-orchestrator`；下文三 Profile 叙述仅是历史发布/阶段证据。legacy 组件现在仅支持发现/卸载，以及单独确认的迁移删除。fresh install、activation、canary 均闭合为两个 binding/call。


## 0. 当前发布与实施状态

| 维度 | 当前证据状态 |
|---|---|
| installation | v0.2.0 已正式发布；精确 tag、7 个托管 assets、校验和/verifier、fresh HTTPS clone、隔离 wheel import 与 `latest` bootstrap 字节回读均通过。 |
| public entries | bootstrap 已发布 `agentporter`、`agentporter-activate`、`agentporter-uninstall` 三个公共入口。 |
| binding | custom Provider 配置继承与受控 binding 已实现；真实凭据可用性仍须由单独授权的 one-shot 证明。 |
| credential | 凭据与 Provider 定义仍由 Hermes Profile/操作者持有；AgentPorter 不得在输出、argv、fingerprint 或 receipt 中披露秘密。 |
| live call | v0.2.0 发布不声称已执行带凭据的真实 canary；`config check=0` 仍只证明静态配置。 |
| route proof | Hermes v0.20 `--usage-file`可报告 model/provider/api_calls，但不报告 tool_calls/fallback；未来成功调用应分层为 `live-call-passed + route-proof-incomplete`。 |
| dispatcher | 专用 orchestrator静态配置已读回；未启动 Gateway，未验收 live dispatcher/Kanban。 |

0.1.5–0.1.8 已交付运行激活基础。v0.2.0 已正式发布，其权威主线是[职责型 Worker 身份与自定义推理绑定设计](06-role-identities-and-configurable-model-binding-design.md)及[Plan 06](plan/06-role-identities-and-configurable-model-binding.md)：保持永久 component UUID 与 Worker 职责不变，将模型语义名称迁移为职责型名称，并让三个 Profile 的 model/provider/endpoint 由用户显式配置。Plan 06 代码/离线门禁、tag、非预发布 GitHub Release、7 个托管 assets 与外部读回均已闭合；`latest` 已选择 v0.2.0，不得修改或 import Hermes 源码，也不得据此声称 operational。

## 1. 产品定位

AgentPorter 的核心产品是 **Hermes 多代理工作组的一键部署与任务路由方案**：把一组职责明确、能力边界不同的 Worker Profile 作为一个可移植工作组安装到 Hermes，并依托 Hermes 原生 Profile description、Kanban、decomposer、dispatcher 与 workspace，把任务分解、路由和执行到合适的 Worker。

一次性安装器与独立卸载器是该产品的交付和回收入口，不是产品价值本身。它们负责把工作组安全、可验证地放入 Hermes；安装后的任务编排由 Hermes 原生运行时承担，AgentPorter 不复制任务数据库、dispatcher 或 workspace 引擎。

当前状态分层如下：

- **已发布版本（v0.2.0）：** 三 Profile 生命周期、三公共入口、custom Provider binding 和离线派发/观察合同已发布。
- **仍待真实验收：** 带凭据的真实 canary、完整 route proof、Gateway/Kanban mutation、通知接续和 live routing。
- **已发布 Plan 06：** [Plan 06](plan/06-role-identities-and-configurable-model-binding.md) 离线实现已完成；fresh install 使用 bounded/mechanical/orchestrator 职责名，三个 Profile 在 staging 前显式封闭 model/provider/endpoint。
- **证据边界：** Hermes v0.20 可通过 usage报告 model/provider/api_calls，但不提供 tool_calls/fallback证明；成功调用最多先达到 `live-call-passed + route-proof-incomplete`。
- **仍不受支持：** revision-safe Kanban mutation和完整 live routing；不得声称 `operational`。

首个工作组当前包含：

- `bounded_worker` / `agentporter-bounded-worker`：在目标、范围、约束和验收均已冻结时执行有界实现或分析；
- `mechanical_worker` / `agentporter-mechanical-worker`：只执行严格更简单、更机械的工作。

以上是 v0.2.0 正式发布版的当前代码事实；0.1.8 历史发布制品使用旧默认名。旧默认名由 `agentporter-activate` 独立确认后以 Hermes-native journaled rename 迁移；用户改名保持不变。名称迁移不改变 component UUID/职责，也不重建或删除 Profile。

Plan 02 已冻结下列兼容设计，Phase A 先以 RED 和当前代码取证证明其可实现性：新增 orchestrator 取得独立永久 component ID，并继续使用当前可解析的 `MarkerV1`；既有两个 Worker 的 marker schema 与 v0.1.0 distribution version 不回写；完整无歧义的 v0.1.0 双组件集合可按同一 installation ID 附加第三组件；空环境直接安装三组件；legacy 双组件和当前三组件都可由卸载器识别。升级失败采用 drift-safe compare-before-restore：无漂移时恢复并补偿本事务新增 orchestrator，发生漂移则保留用户新值与承载它的 orchestrator Profile 并报告 residue；旧 Worker 始终不删除。卸载三组件默认保留共享 Kanban boards/tasks，并在专用 gateway/dispatcher、任何非终态任务或 owner 不明时 fail closed。具体 RED 与状态矩阵见 [Plan 02 Phase A](plan/02-multi-agent-orchestration.md#phase-a兼容路由与事务合同先-red)。

## 2. 目标架构

本文所称“一键部署”只负责静态安装与编排配置，最多达到 `dispatcher-not-running`；gateway/runtime 激活是部署后的独立显式授权动作。完整目标闭环如下：

```text
src/agentporter/resources/workers.yaml
    ↓ Worker schema / 语义 / 路由描述 / 安装预检
AgentPorter 工作组部署入口
    ↓ 每个 Worker 一个临时 Profile distribution
Hermes 原生 profile install + description readback
    ↓
独立 Worker Profiles：config.yaml + SOUL.md + description + 安装标记
    ↓
Hermes 共享 Kanban board
    ↓ triage task
AgentPorter 路由控制面（调用 Hermes decomposer、验证候选 assignees）
    ↓ 仅将通过职责/存在性检查的 task graph + dependencies 写入共享 board
Hermes gateway 内置 dispatcher
    ↓
按 Profile 启动 Worker，并使用 scratch / worktree / dir workspace
    ↓
结构化完成、阻塞、重试与父任务汇总
```

AgentPorter 负责定义和部署工作组、配置专用 orchestrator 控制面、验证 Hermes decomposer 的候选路由并验证端到端合同；Hermes 负责 Profile 状态、共享 Kanban 数据、任务状态机、分解器、dispatcher 和工作区执行。路由控制面只做 AgentPorter 领域的职责/存在性政策验证，不复制任务数据库、依赖图或通用调度器。

当前普通 Hermes 布局中，同一用户、同一 Hermes 根下的普通目录和 Git worktree 共享 Profile 与 Kanban board，无需重复安装。不同用户、容器、Hermes 根或远端独立 Hermes 实例是不同部署目标；特殊容器/自定义根必须显式取证 board 解析，不能仅凭 Profile 可见推断 board 共享。

## 3. 权威输入与产物

`src/agentporter/resources/workers.yaml` 在 Plan 06 发布版中只拥有职责；model/provider/endpoint 来自用户显式 sealed binding，三个 Profile 未形成闭合选择前不得进入 staging。字段 schema 和 artifact 规则见 [Worker 规范](01-portable-worker-spec.md)，目标设计见[职责型 Worker 身份与自定义推理绑定设计](06-role-identities-and-configurable-model-binding-design.md)，Hermes 映射与读回见 [Hermes Adapter](02-platform-adapters.md)。

面向编排的后续 schema 必须继续以 Worker 定义为单一角色来源，并显式补齐：

- Worker 是否可接收实现任务、机械任务或仅负责编排；
- 允许的 workspace 类型、工具集与技能；
- 路由优先级、明确拒绝条件和 fallback 语义；
- 专用 orchestrator Profile 拥有根编排任务，但不得把它误写成内置 decomposer 的模型来源；
- 安装后需要写入的非秘密 Kanban 配置及其原值快照/补偿规则。

模型/provider 字段只表达请求，不证明账号授权。v0.1.0 安装路径不发起模型请求；编排部署的离线配置与真实运行验收必须继续分层。

## 4. 核心决策

1. **工作组优先。** 产品完成不能只由“Profile 安装成功”定义；还必须有可验证的任务路由与执行路径。
2. **复用 Hermes 原生编排。** 不自研任务数据库、dispatcher、decomposer、重试队列或 workspace 管理器。
3. **职责驱动路由。** Profile description 是 Hermes decomposer 的路由标签；`SOUL.md` 约束 Worker 行为，但二者都不是安全 sandbox。
4. **不把用户现有 default Profile 当作专用代理。** 目标方案部署独立 orchestrator Profile 作为根任务 owner 和唯一控制面；不得修改 default Profile 的人格、凭证、记忆、skills、工具集或编排配置，也不得依赖执行时 sticky active Profile。
5. **Profile 配置写入必须绑定明确 owner。** Hermes 共享的是 Kanban board，不是 `config.yaml`。只有冻结 allowlist 中的 `kanban.auto_decompose`、`kanban.orchestrator_profile`、`kanban.max_in_progress_per_profile`、`auxiliary.kanban_decomposer` 与 orchestrator toolsets 可以写入并从专用 orchestrator Profile 读回；`kanban.default_assignee` 明确禁止写入。补偿采用 compare-before-restore，配置 drift 时保留用户新值和承载它的 orchestrator Profile，并报告 residue。
6. **自动路由必须显式授权真实调用。** 首版固定 `auto_decompose=false`，只允许 AgentPorter 写入前验证 seam 驱动的手动路由入口；Hermes 目标版本没有经验证 preview seam 时自动路由保持 unsupported。dispatcher 会启动 Worker，故离线安装和静态验证不得自动创建任务、启动 gateway、调用模型或产生费用。
7. **未知路由不得静默落到错误代理。** Hermes v0.20 的内置 `default_assignee` resolver 无法通过 null/空值禁用，故 AgentPorter 不写该键，且生产路由薄适配不得调用该 resolver；任何候选子任务在写共享 board 前验证职责与 assignee。未知 Profile、空 assignee 或不支持任务进入可见阻塞/人工分流；若目标 Hermes 没有可证明的写入前 seam，自动路由保持 unsupported。
8. **安装/卸载安全合同继续有效。** 现有名称无关 marker、预检、有限补偿和独立卸载设计仍是工作组生命周期基础。
9. **运行控制面必须可归因。** 写任何 orchestrator 配置前枚举全部 Profile gateway、machine-global dispatcher lock、standalone dispatcher 与全部共享 board 状态；其他 owner、owner 不明或含非终态任务的 board 时零写入。专用 orchestrator 只有在后续显式启动并读回 PID、Profile config、singleton ownership 和目标 board DB 后，才算 dispatcher-ready。
10. **Codex CLI 仍不在范围内。** `codex-5-3-small-worker` 是 Hermes Profile 名称与模型请求，不代表已提供 Codex CLI Adapter。
11. **角色身份与推理绑定分离。** 下一功能版本以固定 component UUID 识别组件，以 bounded/mechanical/orchestrator 表达职责，以当前 Profile 名寻址，以用户选择的 model/provider/endpoint 表达运行绑定；四者不得互相推导。

## 5. 安装、编排与验收边界

### 5.1 安装基础层

现有 [安装、卸载与验收设计](03-installation-and-uninstall-design.md) 只证明工作组组件可安全安装、读回和卸载。它不证明：

- Kanban 已初始化；
- 自动分解或 dispatcher 已启用；
- 一个用户任务会被合理拆分；
- 子任务会被分配给正确 Worker；
- Worker 能完成、阻塞、重试或汇总；
- gateway 当前正在运行；
- 真实模型/provider 已可用。

### 5.2 编排层

[多代理编排与路由实施计划](plan/02-multi-agent-orchestration.md) 负责把已安装 Profile 接入 Hermes 原生任务流，并以离线 fake-Hermes、隔离真实 Hermes 和显式授权真实模型三层证据关闭状态。

计划必须至少证明：

- Profile roster 与 routing descriptions 完整且唯一；
- 目标 Hermes 存在可验证的写入前候选 seam；若不存在则自动路由明确 unsupported；
- triage 候选在任何 board 写入前通过职责、assignee 存在性和 fallback 校验，再生成有依赖关系的子任务图；
- 机械任务优先给 Small Worker，有界实现/分析给 Luna；
- 架构、产品或含糊任务不会错误派给 Small Worker；
- 路由规则首版来自精确任务族与 accepts/rejects 断言；只能证明冻结矩阵内的确定性路由，不宣称可正确处理任意自然语言任务；
- dispatcher 只启动已安装、已验证、可路由的 Profile；
- workspace、重试、阻塞、完成和父任务回收沿用 Hermes 原生语义；
- 取消或配置失败不会留下任务、gateway、模型调用或未经授权的 Profile 配置变化。

### 5.3 行为与性能层

[Worker 验证与基准计划](plan/03-agent-validation-and-benchmark.md) 继续负责 Worker 质量、边界行为、成本、时延和稳定性，但其执行顺序调整为依赖编排层先完成。路由正确性既是产品主链合同，也是后续基准的质量维度；基准不能替代编排接通。

## 6. 文档导航

- [可移植 Worker 规范](01-portable-worker-spec.md)：打包内 `workers.yaml` 与派生文件格式；
- [Hermes Adapter 方案](02-platform-adapters.md)：Hermes Profile、Kanban、decomposer、dispatcher 与 workspace 的原生映射；
- [安装、卸载与验收设计](03-installation-and-uninstall-design.md)：工作组组件安装事务、身份、补偿与卸载的权威设计；
- [安装基础实施记录](plan/01-installation-foundation.md)：v0.1.0 已交付安装/卸载基础；
- [多代理编排与路由实施计划](plan/02-multi-agent-orchestration.md)：历史设计与当前离线合同；最终状态以 [Plan 04](plan/04-runtime-readiness-closure-implementation.md) 为准；
- [Worker 验证与基准计划](plan/03-agent-validation-and-benchmark.md)：运行激活闭环后的真实代理质量、性能、成本和稳定性评测；
- [0.1.5 运行激活与真实调用闭环设计](05-runtime-activation-and-live-call-design.md)：公共入口、凭据接续、真实 one-shot、分层 readiness 与升级/卸载边界；
- [0.1.5 运行激活与真实调用闭环计划](plan/05-runtime-activation-and-live-call-closure.md)：0.1.5–0.1.8 运行激活基础的实施记录；
- [职责型 Worker 身份与自定义推理绑定设计](06-role-identities-and-configurable-model-binding-design.md)：v0.2.0 的命名、身份迁移、自定义模型与兼容权威；
- [职责型 Worker 身份与自定义推理绑定计划](plan/06-role-identities-and-configurable-model-binding.md)：代码/离线门禁、发布与托管读回已闭合；live 验收仍待单独授权。

## 当前两 Worker 与 canary 修正合同

- `bounded_worker`：仅完成目标、约束、范围、文件和验收均由主 Hermes agent 固定的边界明确工作；信息不足或越界时停止，不猜测、不扩张。
- `mechanical_worker`：只处理更简单的机械委派——极简单操作脚本、大输出读取/过滤/摘要、按精确规则批量编辑；需要更广判断时返回歧义。
- 主 Hermes agent 负责 orchestrate、分解、路由与集成，不是 AgentPorter 安装的第三个 Profile。
- 每 Worker canary 默认 30 秒，可显式配置为 90 秒；授权短语与调用上限均为两个 Worker。
- inherited `key_env` 未解析时返回 `credential-required`，除非目标 Profile 自有 `.env` 可解析。canonical `custom` 只映射封印的具体定义；exit-zero 且 usage `failed=true` 仍按封闭原因失败。
- 失败原因保持封闭：`authentication-failed`、`model-unsupported`、`endpoint-unavailable`、`rate-limited`、`probe-timeout`、`response-contract-failed`、`usage-evidence-invalid`、`unexpected-runtime-route`。
