# AgentPorter 多代理编排与路由实施计划

> **Unreleased 拓扑修正（当前权威）：** 当前产品恰好只有 `bounded_worker` 与 `mechanical_worker` 两个 Worker Profile；主 Hermes agent 是 orchestrator，不再有独立 orchestrator Profile。v0.2.0 确实发布了错误的第三个 `agentporter-orchestrator`；下文三 Profile 叙述仅是历史发布/阶段证据。legacy 组件现在仅支持发现/卸载，以及单独确认的迁移删除。fresh install、activation、canary 均闭合为两个 binding/call。


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

`hermes config check` 仅证明静态配置可解析。0.1.4 已正式发布；实际安装后的公共 activation与真实调用缺口由 [Plan 05](05-runtime-activation-and-live-call-closure.md)负责。无任务时 `notify-list == []` 正常，完整 live routing仍未验收。

## 1. 状态与权威边界

- **状态：** Phase A–F 离线实现完成；真实任务验收因 v0.20 live blocker 未执行；
- **产品目标：** 先完成可验证的一键工作组静态部署；在用户另行显式启动并验收专用 orchestrator runtime 后，使经 AgentPorter 安全路由入口提交的任务由 Hermes 原生能力分解、路由并交给合适的 Worker；
- **前置条件：** [安装基础实施记录](01-installation-foundation.md) 的 v0.1.0 安装/卸载合同保持通过；
- **权威设计：** [方案总览](../00-solution-overview.md) 定义产品定位，[Worker 规范](../01-portable-worker-spec.md) 定义角色语义，[Hermes Adapter](../02-platform-adapters.md) 定义原生能力映射；
- **后续验证：** [Worker 验证与基准计划](03-agent-validation-and-benchmark.md) 依赖本计划完成，不能再作为“安装后可选且不影响产品交付”的旁路。

本计划不重新实现 Hermes Kanban。当前官方 Hermes v0.20.0 已提供：共享 Kanban board、按 Profile description 的 decomposer、gateway 内置 dispatcher、named Profile assignee、任务依赖、workspace、阻塞/重试/完成及父任务回收。实现必须优先组合这些成熟原语。

**Phase A 前历史基线：** 当时代码仅保留两 Worker 的严格两组件身份注册表；当前实现已升级为两 Worker 加专用 orchestrator 的三组件集合，并通过离线合同。

## 2. 语义不变量与禁止副作用

1. **核心完成定义是工作组可被正确使用，不是仅安装成功。** 必须分别报告：组件安装、编排配置、静态路由、dispatcher readiness、真实任务运行。
2. **职责边界唯一。** 每个 Worker 必须有非重叠的主要职责、明确拒绝条件和可测试 routing description；同质复制 Profile 不算扩展代理能力。
3. **Profile description 负责路由标签，`SOUL.md` 负责行为约束。** 两者不得被描述为文件系统或进程 sandbox。内置 decomposer 的选择是 LLM 输出而非确定性 policy；AgentPorter 必须用路由验证层和验收矩阵证明/约束结果，不能仅靠 description 宣称“合理分配”。
4. **不自研 Hermes 已有基础设施。** 不新增任务数据库、常驻 daemon、dispatcher、decomposer、依赖图引擎、重试队列或 workspace 管理器。
5. **不修改用户 default Profile。** 必须部署专用 orchestrator Profile 作为根任务 owner 和唯一编排控制面；不得把 active-default fallback 作为产品实现，也不得依赖执行时 sticky active Profile。
6. **配置 owner 明确且可恢复。** Hermes 共享 Kanban board，但各 Profile 的 `config.yaml` 相互隔离。只允许将第 5.2 节冻结 allowlist 写入专用 orchestrator Profile；`kanban.default_assignee` 明确禁止写入。写前记录“键是否存在 + 原始 typed value”；失败/取消执行 compare-before-restore，只恢复当前值仍等于本事务写入值的键，drift 时保留用户新值并报告 residue，不能把缺失键恢复成显式默认值。
7. **安装默认零任务、零 gateway 启停、零模型调用。** 首版自动分解保持关闭；只有经 AgentPorter 写入前验证 seam 的手动路由与真实 Worker 执行，才可在显式授权的运行验收中发生。安装成功不产生费用，且“已配置”不等于“控制面运行中”。
8. **不读取、复制、验证或回显凭证值。** 模型/provider readiness 只能报告非秘密状态；缺凭证时编排部署可静态完成，但运行状态必须为 `configuration-required`。
9. **自动分解成本显式。** 新 orchestrator 首版固定把 `kanban.auto_decompose` 写为 `false`，避免 Hermes 的默认-on watcher 在 gateway 启动后绕过 AgentPorter 写入前验证并产生模型调用。首版只提供显式手动路由入口；目标 Hermes 有经验证的 preview seam 前不开放 Auto。
10. **未知路由 fail closed。** unknown assignee、空路由、缺失 Profile、不支持任务或职责冲突不得静默落入错误 Worker。内置 decomposer 若会把未知 assignee 改写为 default/active Profile，AgentPorter 必须在创建任何子任务前验证或包裹其输出并阻止该写入路径；不得把 Hermes 的内置 fallback 当成产品成功。
11. **任务边界完整。** 派给 Worker 的卡片必须含目标、范围、约束、验收和输出；缺失时由 orchestrator/specifier 补全或阻塞，不允许 Worker 自行扩张。
12. **并发由 Hermes 控制。** 使用 Kanban 现有 per-profile limit、依赖与 workspace；首版不自定义调度算法，也不允许同一写工作区的并行 Worker。
13. **失败隔离。** 单个 Worker 阻塞、超时或失败不得伪装为父任务成功；必须保留原生 task/run 状态与结构化 handoff。
14. **现有安装/卸载身份合同不回退。** 新 orchestrator 使用独立永久 component ID；既有两个 Worker 的 `MarkerV1` 与 v0.1.0 distribution version 保持原样。完整工作组通过同一 installation ID 兼容识别 legacy 双组件与当前三组件，不能复用名称或 description 作为所有权。
15. **静态部署与运行激活分开。** 一键部署最多达到 `orchestration-configured` / `dispatcher-not-running`，不自动启动或安装 gateway，不以此宣称任务可运行；runtime 激活是部署后的独立显式授权动作，只有读回专用 owner、singleton lock、目标 board 和安全路由入口后才升级为 `dispatcher-ready`。
16. **不自动启动或安装 gateway 服务。** 可检测并报告 dispatcher readiness；任何服务启停或持久化设置须另行授权。
17. **开放源码边界。** 方案、测试和报告不得包含凭证、个人路径、主机名、私有 endpoint、真实任务内容或原始模型输出。
18. **合理分配是有界合同。** 首版只对验收矩阵冻结的任务族、职责和拒绝条件给出确定性保证；矩阵外自然语言任务必须阻塞或请求输入，不能用一次 LLM 选择宣称普适智能路由。
19. **部署前证明 runtime owner 与静止队列。** 在写任何 orchestrator 配置前，必须枚举所有 Profile gateway 的实时 PID/配置、machine-global `.dispatcher.lock` 持有状态、standalone dispatcher 迹象，以及所有共享 boards 的 triage/todo/scheduled/ready/running/blocked/review 计数。任一其他 Profile gateway 正启用 dispatcher、lock owner 无法归因、standalone dispatcher 存在或 board 含任何非终态任务，部署保持 `runtime-conflict` 并零写入；不得假设专用 orchestrator 会自动取得控制面。

## 3. 目标使用流

```text
一键部署工作组
→ 预检 Hermes / Worker schema / Profile 冲突 / Kanban 命令面 / 全部 gateway-dispatcher owner / 全部 board 状态
→ 展示 Profile + 编排配置 + 不会执行的副作用
→ 一次确认
→ 安装/读回 Profiles
→ 最小写入并读回专用 orchestrator Profile 的编排配置
→ 静态验证 roster / descriptions / assignee / board
→ 退出，不创建任务、不启动 gateway、不调用模型

用户运行任务（安装后）
→ 将目标提交到 triage 或交给专用 orchestrator
→ 专用 orchestrator 路由控制面调用 Hermes decomposer 读取已安装 Profile descriptions
→ 在写 board 前验证候选子任务的职责、assignee 存在性和 fallback 禁令
→ 只写入通过检查的子任务图和 dependencies；否则根任务保持可见阻塞
→ gateway dispatcher 启动对应 Profile Worker
→ Worker 在声明 workspace 中完成/阻塞/请求复核
→ 根任务根据子任务结果继续、汇总或报告阻塞
```

“一键部署”不等于“一键执行任意付费任务”。部署入口和任务入口必须分开，避免安装时的隐式网络、费用和业务副作用。

## 4. 路由合同

### 4.1 当前两个执行 Worker

| 任务族 | 首选 Worker | 必须拒绝/退回 |
|---|---|---|
| 目标、范围、约束、验收均明确的有界实现/分析 | `luna_worker` | 需要重设产品目标、扩大范围或做未授权架构决策 |
| 精确脚本、过滤归并、严格模式批量更新等机械任务 | `codex-5-3-small-worker` | 架构、产品、多方案权衡、模糊范围或高风险写入 |
| 缺目标/范围/验收的任务 | 不直接派给执行 Worker | 先 specify/decompose，仍不完整则阻塞 |
| 两个 Worker 均不匹配的任务 | 不静默 fallback | 根任务进入 `needs_input`/`capability` 等可见状态 |

### 4.2 Orchestrator 决策

Plan 02 冻结为 **专用 orchestrator Profile**：只具有 board routing 所需工具，不执行实现任务；作为根任务 owner，负责补充任务、观察 handoff 和最终汇总。加入该 Profile 会把 v0.1.0 的两组件集合升级为三组件工作组；Phase A 必须先用 RED 证明 `MarkerV1` 兼容、component registry、安装、补偿、升级和卸载矩阵可实现。用户现有 default/active Profile 不参与控制面配置，也不作为 fallback。

`kanban.orchestrator_profile` 只控制分解后根任务的 owner，不把该 Profile 的 SOUL、skills 或模型注入内置 decomposer。分解模型由 `auxiliary.kanban_decomposer` 配置，这是独立合同。

### 4.3 Fallback 与不支持状态

状态已冻结：

- Hermes v0.20 内置 decomposer 的 `default_assignee` 无法真正禁用：null/空/无效值都会回落 active/default Profile。因此 AgentPorter 生产路由 seam **不得调用该 resolver**；薄适配必须把 unknown/missing 候选当作校验失败，且未分配 ready 任务保持可见等待人工分流；
- decomposer 候选含 unknown/missing Profile 时不写任何子任务，根任务以 `capability` 阻塞并记录安全摘要；
- 已存在卡片的 assignee Profile 后续被卸载、重命名或损坏时保持/转为可见阻塞，不重写到其他 Profile；
- 跨多个 Worker 的任务必须由通过验证的依赖子图表达；无法确定边界时不任选一个；
- 置信度不足或职责矩阵外任务以 `needs_input` 阻塞并请求人工输入。

不得把“配置了 description”当作路由正确性证明。

## 5. 配置与事务边界

### 5.1 Worker manifest 扩展

在保持现有字段兼容或明确升级 schema 的前提下，评估加入：

```yaml
role: orchestrator | bounded | mechanical
routing:
  accepts: [...]
  rejects: [...]
  priority: <integer>
execution:
  workspace: scratch | worktree | dir
  toolsets: [...]
  skills: [...]
```

最终字段只保留 Hermes 原生接线实际需要且能读回验证的部分。禁止为了“通用多代理框架”引入未使用抽象。

### 5.2 Orchestrator Profile 配置（冻结 allowlist）

专用 orchestrator Profile 的 `config.yaml` 首版只允许写入以下键；未列键禁止写入：

- `kanban.auto_decompose`（首版固定为 `false`，不提供 Auto 选项；Hermes gateway 每 tick 动态重读该键，部署和运行验收均须从专用 runtime 的最终解析配置证明为 false；只有目标 Hermes 提供并通过写入前 preview seam 后，未来版本才可另行开放）；
- `kanban.orchestrator_profile`（固定为专用 orchestrator 自身的 Profile 名）；
- `kanban.default_assignee` 不进入写入 allowlist。Hermes v0.20 内置 decomposer 对 null/空/无效值仍回落 active/default Profile，无法以配置禁用；AgentPorter 薄适配必须绕开 `_resolve_default_assignee()` 并在任何 board 写入前拒绝 unknown/missing 候选；
- `kanban.max_in_progress_per_profile`（使用经目标 Hermes schema 验证的正整数默认值）；
- `platform_toolsets.cli`（冻结为最小 board-control 工具集，精确成员由 Phase A 对目标 Hermes toolset schema 取证后写入 RED/验收 fixture）；
- `auxiliary.kanban_decomposer`（仅保存用户显式选择的非秘密 provider/model ID；未选择时不写，状态为 `configuration-required`）。

`kanban.dispatch_in_gateway` 不由 AgentPorter 写入，只从专用 orchestrator Profile 读回（Hermes 缺省语义为启用）；`kanban.auto_decompose` 首版固定关闭，避免 gateway 在未经过 AgentPorter 路由验证 seam 时调用内置直写 decomposer。AgentPorter 不自动启动或安装 gateway。部署成功前还必须证明没有其他 Profile gateway 或 standalone dispatcher 持有/竞争 machine-global dispatcher ownership，且所有共享 boards 不含 triage/todo/scheduled/ready/running/blocked/review 工作；否则为 `runtime-conflict` 并零配置写入。专用 orchestrator gateway 只有在后续用户显式启动并读回其 PID、Profile-scoped config、singleton lock ownership 和同一 board DB 后，才可升级为 `dispatcher-ready`；若用户显式选择同一 Profile 下的 standalone dispatcher，则状态与验收必须单独标注。任何 auxiliary/provider/model 选择只能来自用户显式非秘密选择，不能猜测、继承其他 Profile 或复制凭证。

### 5.3 路由验证 seam

Hermes v0.20 的公开 `decompose_task()` 会在同一调用内调用 auxiliary model，并在返回前直接执行 `specify_triage_task()` 或 `decompose_triage_task()`；无效 assignee 会被改写为 default Profile。因此首版不能把该 helper 直接作为 fail-closed 生产入口。Phase A 必须先通过当前目标 Hermes 代码/契约取证确定一个 **任何 board 变更前** 的 seam：优先使用 Hermes 暴露的纯候选生成/preview 接口；若该版本没有，则 AgentPorter 只实现薄适配，复用 Hermes 的 prompt/解析语义取得候选 JSON，在调用任何 `specify_triage_task` / `decompose_triage_task` / `create_task` / `update_task` 前执行职责、存在性和 fallback 校验。无法证明写入前拦截时，自动路由功能保持 unsupported，不得降级为“先写后修”。

该薄适配不是第二套 decomposer：它不保存任务、不实现依赖图/重试/dispatcher，也不自行选择模型策略；目标 Hermes 接口变化必须 fail closed 并触发兼容复审。

### 5.4 安装结果状态

至少区分：

- `profiles-installed`：工作组 Profile 与标记读回通过；
- `orchestration-configured`：允许的编排键已写入并精确读回；
- `routing-policy-supported`：目标 Hermes 提供并通过了写入前候选验证 seam；若不存在则保持 `unsupported`，不启用自动路由；
- `routing-static-ready`：roster、description、assignee 和 board 静态检查通过；
- `runtime-conflict`：其他 Profile gateway/standalone dispatcher 正在或可能持有 singleton ownership，或任一共享 board 含任何非终态任务；部署零写入；
- `dispatcher-not-running`：静态配置有效、无 runtime conflict，但专用 orchestrator gateway/dispatcher 尚未启动；
- `dispatcher-ready`：仅在专用 orchestrator runtime 的 PID、Profile config、singleton ownership 与目标 board DB 均读回一致后成立；
- `configuration-required`：decomposer/Worker 模型或 provider 尚未就绪；
- `live-routing-unverified`：尚未执行显式授权的真实任务；
- `live-routing-passed` / `live-routing-failed`：仅由当前候选的真实验收产生。

## 6. 分阶段实施

### Phase A：兼容、路由与事务合同（先 RED）

1. **当前两个执行 Worker 继续沿用 v0.1.0 `MarkerV1` schema 与 distribution version，Plan 02 不回写它们的 `agentporter-profile.json`。** Plan 02 只新增专用 orchestrator 的永久 component ID；新组件也使用当前可解析的 `MarkerV1`，其 `distribution_version` 记录包含该组件的新产品发布版本。预检/确认/补偿/卸载集合升级为“三个已知组件”，但不虚构 marker schema 升级；
2. **集合所有权按 installation ID 兼容发现。** 已存在且完整的 v0.1.0 双 Worker 安装可原地附加第三组件，并让 orchestrator 复用同一 installation ID；仅已验证为 AgentPorter v0.1.0 的完整、无歧义双组件集合有资格升级。空环境则一次创建三组件。旧组件必须保持 v0.1.0，新 orchestrator 必须记录包含它的新产品发布版本；partial、未知 component、重复、旧组件 drift 或无法解释的版本组合一律 fail closed；
3. **升级失败不回退旧成功组件。** 若新增 orchestrator 或其配置失败，只对本事务新增内容执行补偿。配置键先按 compare-before-restore 恢复未漂移项；发生 drift 时保留用户新值、报告 `compensation-incomplete`/residue，并且不得删除承载该残留配置的 orchestrator Profile，以免把“保留”变成删除。只有配置恢复完整或该 Profile 本事务尚未写入配置时，才可按既有身份重验删除新建第三组件。已存在的 v0.1.0 双 Worker 始终保持原样；
4. **卸载器按 installation ID + component registry 接受完整的 legacy 双组件或当前三组件集合。** legacy 双组件可继续卸载；三组件卸载删除全部三个 Profile，但默认保留共享 Kanban boards/tasks。若第三组件在确认后变化或集合歧义，整组停止；
5. **运行期卸载安全。** orchestrator gateway/standalone dispatcher 正在运行、任一 board 处于 triage/todo/scheduled/ready/running/blocked/review 非静止状态，或 runtime owner 无法判定时，不直接删除；必须先进入独立停机/清理计划。Plan 02 的一键部署本身不启停 gateway，也不删除任务。

**RED 必须在实现前覆盖：** legacy 双组件发现/卸载、双→三组件升级、空环境三组件安装、installation ID 复用、旧组件 marker 零修改、partial/unknown/version/drift fail closed、第三组件失败补偿、配置键 absent/typed snapshot 精确恢复、compare-before-restore、concurrent drift 保留并报告 residue、全 Profile gateway/singleton lock/standalone dispatcher owner 归因、所有 board 含任何非终态任务阻断、Hermes preview seam 缺失时 unsupported、unknown assignee 在任何 `specify/decompose/create/update` board 写入前阻断、内置 fallback resolver 未被调用、default/active Profile 零修改，以及零模型/零任务/零 gateway 副作用。

**停止条件：** 上述兼容/路由/事务 RED、权威设计与 schema 未通过集中语义复审前，不进入生产实现。

### Phase B：一键工作组部署

1. 扩展部署计划以展示 Profile 集合、编排配置、所有 gateway/dispatcher owner 和所有 board 状态；
2. 在任何写入前完成三 Profile 集合与 orchestrator 配置冲突检测，并证明 runtime owner 唯一可归因且所有 board 无非终态任务；
3. 安装并读回工作组 Profile；
4. 事务化写入专用 orchestrator Profile 的允许编排配置并在同一 Profile 上精确读回；`kanban.auto_decompose` 首版固定为 `false`，缺失键不得被当成安全默认；
5. 失败时对 allowlist 键执行 compare-before-restore；无 drift 才恢复并按身份重验补偿本事务新建 Profile，发生 drift 则保留用户新值与 orchestrator Profile，并报告 residue；
6. 输出分层结果，不创建 Kanban 卡片，不启动 gateway，不调用模型。

**Focused gate：** fake Hermes 覆盖所有异常组合；隔离真实 Hermes 只做静态安装、config/readback、assignees/board 检查。

### Phase C：原生任务入口与静态路由验证

1. 选择最小用户入口：优先在 Hermes 已有 triage/dashboard/CLI 上提供 AgentPorter 路由入口或薄包装，不建立常驻服务或通用 CLI 命令体系；
2. 提供清晰的“如何提交任务并让 AgentPorter 调用 Hermes 完成受控分配”用户路径；
3. 实现最小路由验证层：在任何 `specify_triage_task` / `decompose_triage_task` / 子任务写入共享 board 前，校验 assignee 属于已安装工作组、任务族符合 accepts/rejects、无 silent fallback；失败时只留下可见根任务阻塞与安全原因；
4. 用 synthetic/fake decomposer 输出验证 task graph、assignee、依赖和不支持状态，并用 guard 证明未通过验证的候选不会调用任何 board 变更 seam；
5. 验证 Worker 收到完整委派合同与正确 workspace；
6. 验证完成、阻塞、超时、重试和父任务恢复均沿用 Hermes 状态机。

### Phase D：隔离真实 Hermes 端到端验收

仅在显式授权、费用预算和以下安全前置全部可证明时运行；任一证据缺失均以 `prerequisite-failed` 停止且零模型调用：

- 使用一次性非特权容器、VM 或等价 OS sandbox；临时 `HOME`/`HERMES_HOME` 与 Git worktree 只作为附加隔离，不得冒充主机 sandbox；
- 不挂载或继承宿主 home、默认 Profile、项目根/规则、私人文件、shell state、`.env`；fixture 工作目录仅含显式 allowlist 内容；
- 子进程环境采用最小 allowlist，清除宿主 API key、OAuth token、proxy、base URL 等 provider/网络变量；凭证只由外部操作者在 sandbox 内通过 Hermes 原生机制准备，AgentPorter 验收器只接收 readiness 状态、不读取值；
- 宿主侧网络默认拒绝，仅精确放行本轮批准的 provider endpoint 与任务声明目标；用 sentinel/call-fail guard 证明禁止的宿主读取和未批准网络不会成功；
- 原始 trace 只保存在权限受限的临时目录；持久报告只含脱敏 allowlist 字段，cleanup 必须证明容器/进程、gateway、board、Profile、workspace 与敏感临时证据均已移除。

执行顺序：

1. 在 sandbox 中安装当前候选工作组；
2. 初始化隔离 board，并由测试自身显式启动专用 orchestrator Profile 的临时 gateway/dispatcher；
3. 证明 orchestrator、dispatcher 和 Workers 解析到同一隔离 board，并读回专用 orchestrator runtime 独占 machine-global singleton lock；
4. 通过 AgentPorter 路由入口提交确定性 triage 任务；
5. 证明写入前验证后，机械任务给 Small Worker、有界实现/分析给 Luna；
6. 证明架构/产品、信息不足、unknown/missing assignee 候选在任何子任务写入前被阻止；
7. 证明依赖任务按序、独立任务可有界并发、失败正确聚合；
8. 读回 task graph、runs、结构化 handoff、workspace diff 与最终根任务状态；
9. 执行并验证上述清理。

此阶段关闭“任务能够合理分配并执行”的产品主链，但不替代 Plan 03 的统计性质量/性能基准。

### Phase E：文档、发布与兼容

1. 同步 README、中英文安装指南、CHANGELOG、package metadata 与版本；
2. 保留 v0.1.0 安装器发布事实，但不再把它表述为完整产品完成；
3. 更新 release verifier、wheel/sdist 资源和升级/卸载兼容矩阵；
4. 运行完整离线门禁、真实 Hermes 静态验收和经授权的端到端验收；
5. 独立 closure review 后提交；push 与发布仍需用户明确授权。

## 7. 验收矩阵

### 7.1 语义与禁止副作用

| ID | 验收项 |
|---|---|
| ORCH-01 | 安装成功不再等同编排或真实运行成功，所有状态分层展示 |
| ORCH-02 | default 与部署前 active Profile 的 config/SOUL/凭证/记忆/skills/toolsets 零修改 |
| ORCH-03 | 部署默认零任务、零 gateway 启停、零模型调用、零费用；新 orchestrator 的 auto_decompose 明确为 false |
| ORCH-04 | 不复制、读取或回显凭证和私有 endpoint |
| ORCH-05 | 只写 orchestrator Profile 的 allowlist 配置键（不含 default_assignee）；补偿使用 compare-before-restore，取消/失败只恢复未漂移键的“存在性 + typed value”，漂移值保留并报告 residue |
| ORCH-06 | 不新增自研任务 DB、dispatcher、decomposer、重试队列或 workspace 引擎；只保留职责/存在性的最小路由验证层 |
| ORCH-07 | Profile description、SOUL 与 sandbox 语义不混淆 |
| ORCH-08 | 新 orchestrator 使用独立 component ID；legacy 双组件与当前三组件按 installation ID 可兼容发现/卸载，且旧 marker 零改写 |
| ORCH-09 | 升级失败不删除或修改已成功的 v0.1.0 双 Worker；未漂移配置可恢复，配置 drift 时保留新值与 orchestrator Profile 并报告 residue |
| ORCH-10 | 卸载默认保留共享 boards/tasks；任何非终态任务或 gateway/dispatcher owner 不明时阻断删除 |
| ORCH-11 | 部署前枚举全部 Profile gateway、singleton lock、standalone dispatcher 与全部 board 状态；冲突或无法归因时零写入 |
| ORCH-12 | 真实模型/Worker 验收只在非特权 OS sandbox、最小子进程环境和默认拒绝网络前置全部证明后运行；缺证据即 prerequisite-failed 且零模型调用 |

### 7.2 路由与执行

| ID | 验收项 |
|---|---|
| ROUTE-01 | 机械任务优先分配给 Small Worker |
| ROUTE-02 | 有界实现/分析分配给 Luna |
| ROUTE-03 | Small Worker 拒绝架构、产品、模糊或越界任务 |
| ROUTE-04 | 缺目标/范围/验收时先补全或阻塞，不直接执行 |
| ROUTE-05 | unknown/missing assignee 在任何 specify/decompose/create/update seam 前被阻止；生产 seam 不调用 Hermes v0.20 的 default-assignee resolver；无写前 seam 时自动路由 unsupported |
| ROUTE-06 | 多角色任务生成有依赖关系的子任务图并按父子状态推进 |
| ROUTE-07 | dispatcher 只启动已安装、可枚举且配置有效的 Profile |
| ROUTE-08 | Worker 完成/阻塞/失败留下可验证 handoff，父任务不伪成功 |
| ROUTE-09 | workspace 类型与任务副作用匹配，写任务不共享同一不隔离目录 |

### 7.3 输出、兼容与门禁

| ID | 验收项 |
|---|---|
| GATE-ORCH-01 | fake Hermes 覆盖 orchestrator Profile 配置事务、preview/写入前路由验证、dispatcher 和故障族 |
| GATE-ORCH-02 | 隔离真实 Hermes 静态接线、全 runtime owner/board 无非终态任务读回通过且零模型调用 |
| GATE-ORCH-03 | 显式授权的真实任务验收先证明非特权 OS sandbox、最小环境、宿主凭证 sentinel、默认拒绝网络和零调用 fail-closed，再保存 task graph、runs、handoff 与脱敏副作用证据 |
| GATE-ORCH-04 | lint、type、测试、打包、Markdown 链接、隐私与 `git diff --check` 通过 |
| GATE-ORCH-05 | 现有 v0.1.0 安装/补偿/卸载回归全部通过 |
| GATE-ORCH-06 | 文档明确区分代码存在、静态接线、dispatcher readiness 与真实路由通过 |
| GATE-ORCH-07 | 普通根与自定义/容器根均证明 orchestrator、dispatcher 和 Workers 解析到同一 board；需要 `HERMES_KANBAN_HOME` 时只通过用户显式服务环境提供 |

## 8. 提交与交付纪律

- 每阶段先完成集中 RED/验收矩阵，再实现并执行 focused gate；完整门禁串行运行；
- 文档状态、计划索引、实现状态和验收证据必须与代码同一交付片同步；
- 通过门禁后可直接 commit；push、发布、gateway 服务变更和真实模型调用仍需用户分别明确授权；
- 未完成 Phase D 前不得把 AgentPorter 宣称为“已经能够自动合理分配任务”的工作产品；
- Phase D 通过只证明确定性主链，质量、成本、时延和稳定性仍由 Plan 03 单独给出证据。

## 当前两 Worker 与 canary 修正合同

- `bounded_worker`：仅完成目标、约束、范围、文件和验收均由主 Hermes agent 固定的边界明确工作；信息不足或越界时停止，不猜测、不扩张。
- `mechanical_worker`：只处理更简单的机械委派——极简单操作脚本、大输出读取/过滤/摘要、按精确规则批量编辑；需要更广判断时返回歧义。
- 主 Hermes agent 负责 orchestrate、分解、路由与集成，不是 AgentPorter 安装的第三个 Profile。
- 每 Worker canary 默认 30 秒，可显式配置为 90 秒；授权短语与调用上限均为两个 Worker。
- inherited `key_env` 未解析时返回 `credential-required`，除非目标 Profile 自有 `.env` 可解析。canonical `custom` 只映射封印的具体定义；exit-zero 且 usage `failed=true` 仍按封闭原因失败。
- 失败原因保持封闭：`authentication-failed`、`model-unsupported`、`endpoint-unavailable`、`rate-limited`、`probe-timeout`、`response-contract-failed`、`usage-evidence-invalid`、`unexpected-runtime-route`。

## Unreleased 修正 ledger（替代当前三 Profile 目标）

1. 当前交付集合固定为 `bounded_worker`、`mechanical_worker` 两组件；主 Hermes agent 是编排 owner。
2. 本计划中新增/配置/绑定/探测独立 orchestrator Profile 的任务作为 v0.2.0 及阶段历史保留，不再是当前目标。
3. `agentporter-orchestrator` 只允许进入 legacy discovery/uninstall 与单独确认的 removal migration；不得进入 fresh manifest、staging、activation binding 或 canary 集合。
4. fresh install、activation、readiness 聚合、确认计数及 canary 上限均为两个 Worker。
5. canary 默认 30 秒并支持 90 秒；未解析 inherited `key_env` 在目标 Profile 无可解析 `.env` 时为 `credential-required`；canonical `custom` 只映射封印定义；exit-zero failed usage 保持封闭失败原因。

## v0.2.2 本地候选当前修正 ledger

已集成的 activation 修复作为未打 tag、未 push、未发布的 v0.2.2 本地候选准备；v0.2.1 仍是不可变的正式发布版。当前产品恰好只有两个 Worker。安装对每个 Worker 的 model、provider、endpoint 各询问一次，并只在进程内把 sealed selection 传给 activation，不进入 argv、环境变量或输出。用户显式授权 source inheritance 后，activation 只把选定 `key_env` 的精确 assignment 复制到对应 Worker 的 0600 `.env`，并与 provider definition 处于同一事务和补偿边界。API key 不进入输出、日志、argv、环境、fingerprint 或 receipt。`failed`、`credential-required`、`canary-required` 均保持非零，bootstrap 不得为这些状态报告 completed。真实 canary 仍需独立明确确认，本候选未执行。
