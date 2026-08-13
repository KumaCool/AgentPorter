# AgentPorter Worker Readiness 与编排闭环优化实施计划

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

> **For Hermes:** 使用 `continuous-plan-orchestration`、`parallel-development-convergence` 与 `test-driven-development`，按本计划逐项执行；普通阶段边界是检查点，不是等待用户再次说“继续”的停止点。

**Goal:** 在不复制 Hermes Kanban、dispatcher、凭据系统或 workspace 引擎的前提下，把 AgentPorter 从“Profile 已安装、可作为 assignee”提升为“Worker 推理已验证、任务路由可回到原 Telegram 会话、主代理能依据真实运行证据自动接续、暂停恢复和并发文件所有权可验证”的稳定工作组。

**Architecture:** 保留一次性安装器与独立卸载器；新增的运行能力属于专用 AgentPorter orchestrator Profile 的薄控制面。安装仍保持零模型调用，运行激活在用户显式授权后执行真实、最小、无业务副作用的模型探针；任务、run、heartbeat、PID、通知订阅和 workspace 继续以 Hermes 原生 Kanban/Gateway 为权威。AgentPorter 只增加领域合同、写入前验证、只读聚合和安全操作编排，不新建任务数据库、dispatcher、常驻 daemon 或通用 CLI 命令体系。

**Current status:** Superseded by Plan 04 Phase A–F implementation. Runtime probe, dispatch planning/runtime, observation, activation lifecycle, and orchestrator integration now exist and pass offline contracts. Hermes v0.20 still returns `probe-unsupported` and `mutation-unsupported` before model/Kanban adapter calls, so real-model and live routing acceptance remain unperformed.

---

## 1. 当前证据与问题定位

### 1.1 仓库当前事实

1. `src/agentporter/resources/workers.yaml` 只声明模型、reasoning、description 与 instructions；两个 Worker 都没有 provider。
2. `src/agentporter/render.py:55-58` 只渲染 `model.default`、可选 `model.provider` 和 `agent.reasoning_effort`。
3. `src/agentporter/planning.py:26-31,132-165` 已区分：
   - `configuration-required`；
   - `selected-but-runtime-unvalidated`；
   - `configured-but-runtime-unvalidated`。
4. `InstallPlan.runtime_validated` 永远为 `False`，当前安装事务只证明静态 Profile 安装与读回。
5. `docs/00-solution-overview.md`、`docs/02-platform-adapters.md` 和 `docs/plan/02-multi-agent-orchestration.md` 已正确写明：安装成功不证明 provider/model 可调用，不复制 default Profile 的 `.env`、`auth.json`、私有 endpoint 或凭据。
6. 当前 Plan 02 已设计专用 orchestrator、写入前路由验证和 dispatcher 状态分层，但尚未把以下事故闭合为一等合同：
   - 真实模型探针；
   - 订阅读回；
   - creator session 唤醒；
   - `running` 的证据分级；
   - 主代理终态接续；
   - 项目级暂停/恢复；
   - 文件写所有权冻结。

### 1.2 当前 Hermes v0.20.0 已验证能力

以下事实来自本机 `hermes --help`、子命令帮助、官方 Kanban 文档与已安装源码：

- `hermes config check` 是静态配置检查，不执行主模型推理。
- `hermes -p <profile> -z <prompt> --usage-file <path>` 可执行真实 one-shot 并返回 model/provider/调用状态，但当前公开帮助未证明存在 `--no-tools`。
- `kanban.auto_subscribe_on_create=true` 只在有持久投递通道的 Gateway/TUI 会话内建卡时自动订阅；CLI/machine-output 创建会跳过自动订阅。
- CLI 提供 `notify-subscribe`、`notify-list`、`notify-unsubscribe`，并可精确携带 platform/chat/thread/notifier-profile。
- Gateway notifier 处理 `completed`、`blocked`、`gave_up`、`crashed`、`timed_out` 等事件；只有任务具有 creator `session_id` 时，终态通知才能进一步向原会话注入 wake 事件。
- `show --json`、`runs --json`、`log`、task/run PID、`last_heartbeat_at` 和 diagnostics 可共同形成真实运行证据。
- `hermes pause` 只停止新 dispatch/新 turn，不终止在途 Worker。
- `hermes kanban reclaim` 会终止对应 Worker 并把 claim 释放回 `ready`；因此暂停不能只调用 `hermes pause`。
- dispatcher-spawned Worker 会显式绑定 assignee Profile 的 `HERMES_HOME`、board、workspace、run ID、claim lock 和 Profile CLI toolsets。
- 当前 Hermes v0.20.0 的 task `running` 在 `claim` 后、子进程真正启动前即可出现；PID 回写也尚未以期望 `run_id + claim_lock` 做 CAS fence，故旧轮次 PID/ACK/heartbeat/terminal 更新必须列为兼容性门禁，而不是由 AgentPorter 推断安全。
- 当前 dispatcher 以 `dict(os.environ)` 构造 Worker 环境。切换 `HERMES_HOME` 不等于清除了 gateway、Telegram、GitHub、基础设施或其他 provider 的环境秘密；“没有复制 `.env`”不能覆盖进程环境继承风险。
- 当前 Hermes 的模型内 `kanban_create` 工具能同时写 creator session 和自动订阅；普通 CLI 建卡不具备这两个保证，Gateway `/kanban create` 虽可订阅，也未证明任务自身带 creator session。
- push 平台上“终态文本已发送”和“creator session 已 synthetic wake”不是同一保证：文本成功后 wake 仍可能 best-effort 失败。
- Hermes 已有结构性接续原语：把所有执行子卡作为根 orchestrator 卡的 parents，全部完成后根卡重新进入 `ready` 并产生新 run；这比仅依赖聊天 wake 更适合作为自动编排主链。
- 当前订阅继承需验证 `chat_type` 和 `delivery_metadata` 是否完整保留；只读回 platform/chat/thread/notifier-profile 不足以证明 DM/topic/reply anchor 路由等价。

### 1.3 核心结论

问题不是“重写 Kanban”，而是 AgentPorter 缺少一层**可验证的运行合同**：

```text
静态安装
→ 显式凭据绑定（由 Hermes/用户持有）
→ 真实 readiness 探针
→ 带 creator session 与精确路由的暂存建卡
→ 订阅/任务/工作区读回
→ 解锁 dispatch
→ 持续运行证据聚合
→ 终态 wake
→ 主代理接管、集成、门禁与交付
```

---

## 2. 语义不变量与禁止副作用

### 2.1 Readiness 不变量

1. `installed`、`configured`、`credential-authorized`、`runtime-validated`、`operational` 必须是五个不同维度；聚合结果取最弱维度，任何单一 `ready: true` 都不得抹平缺项。
2. `runtime-ready` 只能来自当前 Worker、当前期望 model/provider、当前 Hermes 版本上的真实成功响应。
3. `config check`、Profile 存在、Kanban assignee 可见、Gateway 运行均不得升级为 `runtime-ready`。
4. 默认禁止 readiness 期间 fallback；若实际 usage 中 model/provider 与期望绑定不一致，状态为 `unexpected-runtime-route`，不能算通过。
5. 502/503、认证失败、模型不存在、限流、超时和响应合同失败必须分别归类，不能合并为“Worker 崩溃”。
6. readiness 证据有时效，并绑定 Worker component、当前 Profile 名、Hermes 版本、期望 model/provider 与安全的配置版本指示；不能永久缓存“曾经通过”。
7. Codex Worker 未通过 readiness 时，机械任务必须阻塞为 `capability`；不得静默改派 Luna，也不得依赖 provider fallback 掩盖配置错误。
8. `runtime-ready` 只证明当前绑定的 canary；只有 dispatcher、route、continuity、workspace 和 run fencing 全部通过时，Worker 才能聚合为 `operational`。

### 2.2 凭据治理不变量

1. 安装器、orchestrator 和探针报告不得读取、复制、回显或提交 API key、token、OAuth 凭据、私有 base URL 或原始 provider 错误正文。
2. 不从 default Profile 克隆 `.env`、`auth.json`、`config.yaml` 或 shell credential 环境。
3. `workers.yaml` 只保存公开可发布的请求模型与可选非秘密 provider ID；不得保存 key 或私有 endpoint。
4. 凭据由用户使用 Hermes 原生机制配置到目标 Worker Profile：Profile-local `.env`/auth pool，或 Bitwarden/1Password 等外部秘密来源。
5. 首选“多个 Profile 引用同一外部秘密对象”，而不是把同一明文 key 复制多份；AgentPorter 只观察安全状态码，不接触秘密值。
6. 安装、升级、静态读回、补偿与卸载继续保持零模型调用、零凭据读取。
7. Worker 子进程环境默认拒绝继承：gateway、Telegram、GitHub、基础设施和非目标 provider 的秘密不得进入 Worker；目标 provider 凭据只能来自该 Worker Profile 的显式授权。
8. 如果目标 Hermes 版本不能证明上述最小环境与 provider grant 边界，AgentPorter 必须报告 `worker-env-isolation-unsupported` 并阻止 `operational`，不得以 Profile 隔离代替进程隔离。
9. 用户完成凭据授权或在 Profile 内产生自有数据后，即越过自动补偿删除安全点；后续 readiness 失败保留 Profile 并标记 degraded/configuration-required，不得自动删除。

### 2.3 任务与通知不变量

1. 产品支持的自动接续任务必须由专用 orchestrator 在其当前会话内调用模型工具路径 `kanban_create` 创建，从而同时写入 creator session 与来源订阅；普通 CLI 和 Gateway slash 建卡不得被推断为等价入口。
2. CLI 创建且只有 notify row、没有 creator `session_id` 的任务只能称为 `notification-only`，不能称为 `continuation-ready`。
3. 所有正式子任务先以不可 dispatch 状态暂存；任务合同、assignee、workspace、依赖、idempotency key、通知路由全部读回后才解锁。
4. 自动订阅配置值不等于订阅已存在；每张根卡和需要立即感知失败的子卡都必须以 `notify-list --json` 读回精确 platform/chat/chat-type/thread/notifier-profile/delivery-metadata 语义。
5. 路由信息只存在运行时与 Kanban；仓库、测试 fixture 和持久报告不得含真实 chat ID、thread ID、user ID 或 Telegram 话题内容。
6. 通知只是唤醒触发器；主代理接管前必须重新读取 task、runs、diagnostics、PID/heartbeat、log 与 worktree，不能把通知文本当最终事实。
7. 任务创建成功必须产出并读回一份 `DispatchReceipt`；只有 task ID、`ready` 或 `running` 不算派发成功。
8. 连续性保证必须分级记录为 `event-durable`、`user-notified`、`creator-woken`、`orchestrator-resumed`，后一级不得由前一级推断。
9. 自动编排主链使用“所有子卡完成 → 根 orchestrator 卡重新 ready → 新 orchestrator run”；聊天 wake 是异常通知和交互优化，不是唯一接续机制。

### 2.4 运行状态不变量

1. Kanban `running` 只表示 claim/启动状态，不能单独表述为“正在持续工作”。
2. 对外状态至少区分：`queued`、`launching`、`active`、`stale-or-wedged`、`blocked`、`crashed`、`timed-out`、`gave-up`、`completed`、`inconsistent`。
3. `active` 至少要求当前 run 为 running、PID 可归因且存活、heartbeat/activity 在阈值内。
4. worktree 文件变化、测试进程和日志新内容是进展证据，不是 task/run 权威；反之，只有 PID 存活也不能证明有进展。
5. Worker 已终态时必须停止使用旧的 running 快照；主代理在同一 wake turn 内接管或明确报告阻塞。
6. 无变化时不发送周期汇报；只在终态、状态降级、人工输入需求或用户主动查询时报告。
7. PID 回写、启动 ACK、heartbeat、complete、block、reclaim 和 terminal publication 必须带当前 `run_id + claim_lock` fence；旧轮次不得污染新 run。
8. 运行阶段至少区分 `claimed/starting`、`process-spawned`、`agent-booted`、`inference-ready`、`executing` 与 terminal；没有相应原生信号时只能报告较弱阶段。

### 2.5 暂停/恢复不变量

1. “暂停本项目”只暂停 AgentPorter 当前 board/tenant 的工作，不长期冻结其他 Hermes 项目。
2. 暂停过程使用短暂 global ESTOP 关闭竞态，然后：创建项目暂停 guard、reclaim 本项目运行任务、阻塞所有本项目非终态卡、验证进程和工作区静止，最后解除 global ESTOP 让无关项目继续。
3. `reclaim` 后任务回到 ready；在解除 global ESTOP 前必须把它们转为 blocked，避免立即重派。
4. 暂停不得 reset/clean/delete worktree，不得丢弃已提交或未提交候选。
5. 恢复前重新验证 readiness、Gateway/dispatcher owner、通知路由、task/run 一致性、worktree/base SHA 与无并发 writer；验证失败则保持 paused。
6. 恢复只解锁明确选中的任务，并保持依赖顺序；不能无差别恢复整个 board。

### 2.6 文件所有权不变量

1. 每个可写任务必须声明精确 `allowed_writes`；共享文件、生成物和文档的 owner 唯一。
2. 两轨不得创建同名测试文件；测试文件名在建卡前冻结。
3. 共享 DTO/合同先由主代理或基础轨冻结，依赖轨从该不可变 SHA 开始。
4. `docs/plan/00-index.md`、方案总览、README、CHANGELOG、版本和最终状态文档只由主代理在串行集成阶段修改。
5. Worker 交付时以 `git diff --name-only` 和 `git status --short` 验证实际路径是允许集合的子集；越界即拒绝候选，不靠 SOUL 自觉认定安全。
6. 两轨 focused tests 可并发，完整 pytest、ruff、pyright、build、release verifier、文档与隐私门禁串行运行。

---

## 3. 目标架构

### 3.1 不新增第二套运行系统

AgentPorter 只增加以下薄层：

```text
Worker manifest / installed marker
        ↓
RuntimeReadinessPlan（无秘密、不可变）
        ↓ 显式授权
Hermes-native minimal probe
        ↓ safe evidence
DispatchPlan（任务合同 + 文件所有权 + 路由来源）
        ↓ staged/blocked create
Hermes Kanban task graph + notify subscriptions
        ↓ readback 后 unblock
Gateway dispatcher + Worker runs
        ↓
RuntimeObservation（只读聚合）
        ↓ terminal wake
专用 orchestrator/main session 集成与交付
```

禁止新增：

- AgentPorter task DB；
- 自研 dispatcher/retry queue；
- AgentPorter 常驻 daemon；
- 通用 `agentporter <many-subcommands>` CLI 体系；
- 自有凭据保险库；
- 自有 Git worktree manager。

### 3.2 新领域对象

建议新建以下闭合模型，避免继续把所有状态塞进 `InstallPlan`：

#### `RuntimeBinding`

- `portable_id`
- `component_id`
- `current_profile_name`
- `expected_model`
- `expected_provider`
- `provider_source_kind`：`profile-config | task-override | unresolved`
- `fallback_policy`：首版固定 `forbidden`

不包含 base URL、key、auth path 或账号标识。

#### `ReadinessEvidence`

- `status`
- `safe_reason_code`
- `binding`
- `hermes_version`
- `probe_started_at` / `probe_finished_at`
- `actual_model` / `actual_provider`（只在 Hermes usage 安全字段内）
- `api_calls`
- `response_contract_passed`
- `tool_calls_observed`
- `fresh_until`

持久化只允许安全字段；原始 stdout/stderr/session trace 位于 0700 临时目录，归类后删除。

#### `OperationalReadiness`

由多个正交维度聚合，取最弱项而不是一个布尔值：

- `artifact`：`absent | installed | invalid`；
- `inference`：`unresolved | statically-resolved | runtime-resolved`；
- `credential`：`absent | explicitly-granted | expired | rejected`；
- `canary`：`not-authorized | pending | passed | failed`；
- `worker_environment`：`unverified | least-privilege | unsafe-inheritance`；
- `dispatcher`：`absent | alive | degraded`；
- `route`：`absent | persisted | delivery-verified`；
- `continuity`：`unsupported | armed | resumed | degraded`；
- `workspace`：`unverified | isolated | conflict`；
- `run_fencing`：`unsupported | verified | violated`；
- `aggregate`：`static-installed | configuration-required | canary-required | operational | degraded | blocked`。

若 Hermes 版本缺少安全环境过滤、run/claim fencing 或准确路由读回，维度保持 unsupported/unverified，聚合状态不得是 operational。

#### `DelegationContract`

- `goal`
- `allowed_reads`
- `allowed_writes`
- `forbidden_paths`
- `operations`
- `constraints`
- `acceptance_commands`
- `expected_outputs`
- `base_sha`
- `test_file_names`
- `shared_contract_owner`

#### `DispatchPlan`

- 目标 board/project/tenant 的安全句柄；
- creator session 存在性；
- root/child task spec；
- assignee 与 readiness evidence；
- workspace/branch；
- dependencies；
- notification route 的运行时句柄；
- idempotency keys；
- fingerprint；
- 初始状态固定为 blocked。

#### `DispatchReceipt`

- `board` / `task_id` / `task_status`；
- `assignee` / `session_id_attached`；
- subscription 的 platform/chat/chat-type/thread/notifier-profile/delivery-metadata 安全摘要；
- `workspace_kind` / `workspace_path` / `branch_name`；
- `parents` / `ownership_digest` / `base_sha`；
- `continuity_level`：`event-durable | user-notified | creator-woken | orchestrator-resumed`。

Receipt 是 staged graph 放行依据，不是新任务数据库；它由 Hermes 权威状态读回形成，敏感路由字段只在运行时比较，持久报告只保存安全摘要。

#### `RuntimeObservation`

- task status；
- current run status/outcome；
- PID presence/liveness；
- heartbeat age；
- latest event；
- diagnostics severity；
- log/worktree/test process 的二级证据；
- 派生状态与安全 reason code。

### 3.3 Readiness 状态机

```text
profile-missing
  └─> configuration-required
       └─ static config check pass
          └─> probe-required
               ├─> probe-running
               │    ├─> runtime-ready
               │    ├─> provider-not-configured
               │    ├─> authentication-failed
               │    ├─> model-unsupported
               │    ├─> endpoint-unavailable
               │    ├─> rate-limited
               │    ├─> probe-timeout
               │    ├─> response-contract-failed
               │    └─> unexpected-runtime-route
               └─ config/profile/Hermes version/freshness change
                    └─> probe-required
```

`runtime-ready` 是瞬时运行证据，不回写安装 marker，也不把安装状态升级为新的所有权 schema。

### 3.4 最小真实探针

固定合同：

- 由用户显式授权；
- 每个待使用 Worker 最多一次主调用；
- 固定 nonce prompt，只要求返回 `AGENTPORTER_READY:<nonce>`；
- 空临时 cwd；
- 硬超时；
- usage 文件写入 0700 临时目录；
- 禁止 fallback；
- 期望 API calls = 1；
- 期望 tool calls = 0；
- 只保留安全归类；
- 成功和失败都清理临时证据。

**关键能力门禁：** 当前 Hermes v0.20 公共 CLI 未证明存在强制 zero-tools one-shot。Phase A 必须先验证以下优先级，不能仅靠 prompt 宣称“无副作用”：

1. 首选目标 Hermes 的公开 tool-free one-shot/probe seam；
2. 次选经过真实验收的 profile-local空工具面，且不修改/读取用户凭据文件；
3. 再次选非特权 OS sandbox + 空 workspace + provider-only egress，并以 tool-call guard 判失败；
4. 以上均不可证明时，状态为 `probe-unsupported`，不执行模型调用，不用普通 one-shot 冒充安全探针。

该门禁允许向 Hermes 上游贡献最小 `--no-tools`/health-probe 能力，但 AgentPorter 不维护私有 fork。

### 3.5 凭据方案

按优先级支持：

1. **外部秘密来源引用：** 每个 Worker Profile 保存非秘密映射/引用，由 Bitwarden/1Password 在 Hermes 启动时解析；多个 Profile 可指向同一外部对象，AgentPorter 不复制明文。
2. **Profile-local Hermes auth pool：** 用户分别用 `hermes -p <profile> auth ...` 或模型设置流程配置。
3. **Profile-local `.env`：** 兼容但不推荐多份明文；由用户管理，AgentPorter 不读写。

AgentPorter 只提供按 Profile 的配置指引和安全状态，不自动把 default Profile 复制到 Worker。

### 3.6 建卡与订阅事务

正式任务必须采用以下顺序：

```text
readiness + creator session + gateway owner preflight
→ build immutable DispatchPlan
→ create root/children as blocked using idempotency keys
→ write exact DelegationContract bodies
→ link dependencies
→ subscribe exact source route to root and required children
→ read back task/session/assignee/workspace/dependencies/subscriptions
→ verify no file-ownership overlap
→ unblock only runnable roots
```

任何一步失败：

- 不启动 Worker；
- 已建卡保持 blocked 并带安全 reason；
- 不自动删除历史卡；
- 可按 idempotency key继续修复；
- 不把 `auto_subscribe_on_create=true` 当作成功证据。

正式入口固定为专用 orchestrator 当前会话中的 Hermes `kanban_create` 工具路径，以便同时保存 creator `session_id` 与来源订阅。Gateway slash 和纯 CLI 创建只作为运维兼容入口：即使另行订阅，也标为 `notification-only`，不承诺主会话自动接续。

### 3.7 结构性接续、异常通知与主代理接管

自动接续以 Hermes 任务图为主链：所有执行子卡都作为根 orchestrator 卡的 parents；子卡全部 `done` 后，Hermes 将根卡重新置为 `ready` 并启动新的 orchestrator run。根卡从权威 task/run/parent results 继续集成，不依赖某次聊天 wake 是否成功。

异常路径分开处理：子卡 `blocked/crashed/timed_out/gave_up` 通过订阅通知来源话题；push 平台 synthetic wake 在 Hermes 具备 durable cursor/ack 前只能标记 `creator-wake-best-effort`。通知已发送不等于 orchestrator 已恢复；若结构性根卡尚不能 ready，则保持可见阻塞，不伪称自动接续完成。

终态 wake 到达后，orchestrator/main session 必须在同一 turn：

1. `show --json` 读 task；
2. `runs --json` 读最新 run outcome；
3. 读取 diagnostics、PID/heartbeat 与 worker log；
4. 验证 worktree、branch、HEAD、允许路径和测试证据；
5. 按状态执行：
   - completed：审查并串行集成；
   - blocked：补信息或保持可见阻塞；
   - crashed/timed_out/gave_up：诊断、保留候选、决定原地恢复或重派；
   - inconsistent：fail closed，不集成；
6. 完整计划未完成时立即推进下一任务，不等待用户再次催促；
7. 只有真实授权边界（模型费用、gateway 服务变更、push、发布）才停下请求授权。

### 3.8 项目级暂停/恢复

使用 Hermes 原语组合，不新增 pause DB：

Hermes 原生 `pause` 的准确语义仅是 `pause-new-work / drain-running`。AgentPorter 的“暂停本项目”是在该原语之上执行的有界 quiesce 事务；只有 reclaim、block 和静止读回全部通过，才可以报告项目已暂停。

#### Pause

1. 短暂执行 global `hermes pause`，关闭 create/unblock/dispatch 竞态；
2. 在 AgentPorter board/tenant 建立带稳定 idempotency key 的 blocked pause-guard 卡；
3. 枚举本项目非终态卡；
4. 对 running 卡逐一 `reclaim`，验证 Worker PID/进程组退出；
5. 把 ready/todo/scheduled/reclaimed 卡全部 block；
6. 验证无 Worker、测试、集成或重型子进程继续运行，Git/worktree 在观察窗内稳定；
7. 解除 global ESTOP，让无关项目恢复；AgentPorter dispatch helper 看到 pause guard 时继续拒绝新卡/解锁。

#### Resume

1. pause guard 仍在时执行静态 preflight；
2. 重验所需 Worker readiness、Gateway/dispatcher owner、通知路由、base SHA、worktree 与无并发 writer；
3. 失败则保持 guard 和 blocked 卡；
4. 成功后归档/关闭 pause guard；
5. 只 unblock 用户指定或权威计划中的下一批卡；
6. 读回 run/route 后继续。

---

## 4. 文件设计

### 4.1 建议新增生产文件

- `src/agentporter/readiness.py`
  - `RuntimeBinding`、`ReadinessEvidence`、状态归类、freshness。
- `src/agentporter/runtime_probe.py`
  - Hermes capability negotiation、固定 probe、usage 安全解析、临时证据清理。
- `src/agentporter/delegation_contract.py`
  - 严格闭合的任务/文件所有权模型和 overlap 检查。
- `src/agentporter/dispatch_planning.py`
  - 不可变 DispatchPlan、fingerprint、blocked staging 计划。
- `src/agentporter/kanban_runtime.py`
  - 只通过经验证 Hermes 公共 seam 执行 create/link/subscribe/readback/unblock；不直写第二套 DB。
- `src/agentporter/runtime_observation.py`
  - task/run/PID/heartbeat/log/worktree 的只读聚合与状态派生。
- `src/agentporter/lifecycle_control.py`
  - pause guard、reclaim/block、resume preflight 的操作编排。
- `src/agentporter/resources/orchestrator/`
  - 专用 orchestrator Profile 的 SOUL、最小工具/技能或经验证薄适配资源；具体布局先通过 Hermes distribution attestation。

### 4.2 预计修改文件

- `src/agentporter/models.py`
  - 仅保留安装 schema；如扩展 Worker role/routing/execution，避免把运行状态混入 MarkerV1。
- `src/agentporter/identity.py`
  - 加入 Plan 02 已批准的永久 orchestrator component ID。
- `src/agentporter/render.py`
  - 渲染第三组件与最小 orchestrator 资源；继续禁止 credentials。
- `src/agentporter/planning.py`
  - 安装结果只报告“运行需要后续 readiness”，不得执行 probe。
- `src/agentporter/readback.py`
  - 读回 orchestrator owned artifacts；不读取用户凭据文件。
- `src/agentporter/hermes.py`
  - 扩展被观察 Hermes capability 集合，包括 notify/runs/heartbeat/reclaim/pause/resume 与 probe seam。
- `src/agentporter/install_workflow.py`、`src/agentporter/transaction.py`
  - 三组件安装/升级合同与既有 Plan 02 补偿语义。
- `src/agentporter/resources/workers.yaml`
  - 扩展公开 role/routing/execution 元数据；仍不放 key/base URL。
- `pyproject.toml`、`MANIFEST.in`、`scripts/verify_release.py`
  - 打包/验证新增 orchestrator 资源。

### 4.3 新增测试文件（名称先冻结，避免 add/add）

- `tests/test_readiness_contract.py`
- `tests/test_runtime_probe.py`
- `tests/test_delegation_contract.py`
- `tests/test_dispatch_planning.py`
- `tests/test_kanban_runtime.py`
- `tests/test_runtime_observation.py`
- `tests/test_lifecycle_control.py`
- `tests/test_phase7_real_hermes_orchestration.py`
- `tests/test_phase8_authorized_live_probe.py`

共享测试文件禁止由两个 Worker 同时修改。既有 `tests/test_browser_runtime_contract.py` 不作为本项目新轨共用入口。

### 4.4 文档同步

主代理串行更新：

- `docs/00-solution-overview.md`
- `docs/01-portable-worker-spec.md`
- `docs/02-platform-adapters.md`
- `docs/03-installation-and-uninstall-design.md`
- `docs/plan/00-index.md`
- `docs/plan/02-multi-agent-orchestration.md`
- `docs/plan/03-agent-validation-and-benchmark.md`
- `README.md`
- `README.zh-CN.md`
- `docs/04-installation-and-troubleshooting.md`
- `docs/04-installation-and-troubleshooting.zh-CN.md`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `CHANGELOG.md`

文档必须继续并列显示：安装结果、编排配置结果、readiness 结果、dispatcher 结果、live routing 结果；不得相互升级。

---

## 5. 分阶段实施计划

### Phase A：冻结能力矩阵与 RED 合同

**Objective:** 在生产代码前确认 Hermes v0.20 的真实公共 seam，并把事故家族完整转成 RED。

**Files:**
- Create: 上述九个独立测试文件中的 contract/fake 部分。
- Modify: `docs/plan/02-multi-agent-orchestration.md`（由主代理串行）。

**Steps:**

1. 记录 `hermes --version` 及 `config check`、`kanban create/show/runs/notify-*/heartbeat/reclaim`、`pause/resume`、one-shot usage 帮助。
2. 取证 tool-free probe 是否有公共实现；用 fake runner 先证明“能力缺失时零模型调用”。
3. 写 readiness 状态机 RED：missing provider、配置有效但实际 503、错误模型、unexpected fallback、成功 nonce、超时、过期证据。
4. 写路由 RED：Gateway creator session + exact subscription 通过；CLI-only route 必须是 notification-only；订阅缺 thread/notifier 时不解锁。
5. 写 running 证据 RED：running+dead PID、running+stale heartbeat、terminal run+旧 task 快照、PID live 但无进展、状态矛盾。
6. 写 pause RED：global pause 不终止 Worker；reclaim 后若未 block 会重新 dispatch；pause guard 阻止新任务；只影响目标 tenant。
7. 写 ownership RED：路径交集、同名测试、共享文档、DTO 双 owner、错误 base SHA 全部拒绝。
8. 写环境继承与 fencing RED：父 gateway 环境 secret sentinel 对 Worker 零可见；旧 run 的 PID/ACK/heartbeat/terminal 更新全部被拒绝。
9. 写 continuity RED：文本通知成功但 push wake 失败必须 degraded；全部子卡 done 后根卡仍能 ready 并产生新 run。
10. 写订阅继承 RED：chat_type、delivery_metadata、thread/reply anchor 全字段保真。
11. 集中语义复审一次；矩阵完整前不写生产实现。

**RED commands:**

```bash
python -m pytest \
  tests/test_readiness_contract.py \
  tests/test_runtime_probe.py \
  tests/test_delegation_contract.py \
  tests/test_dispatch_planning.py \
  tests/test_kanban_runtime.py \
  tests/test_runtime_observation.py \
  tests/test_lifecycle_control.py -v
```

Expected: 因生产模块/行为尚不存在而按预期失败，不得是 import typo 或 fixture 错误。

### Phase B：Readiness 与凭据边界

**Objective:** 实现安全状态分层和真实探针，不改变安装零调用合同。

**Files:**
- Create: `src/agentporter/readiness.py`
- Create: `src/agentporter/runtime_probe.py`
- Test: `tests/test_readiness_contract.py`
- Test: `tests/test_runtime_probe.py`

**Steps:**

1. 逐个测试执行 RED→GREEN，实现闭合状态枚举与 safe reason code。
2. 实现不可变 `RuntimeBinding` 和 `ReadinessEvidence`。
3. 实现 probe capability negotiation；缺少安全 seam 时返回 `probe-unsupported` 且 runner 调用数为 0。
4. 实现 nonce/usage/model/provider/api-call/tool-call/fallback 校验。
5. 原始 stdout/stderr 只在 0700 临时目录存活；归类后删除，异常/KeyboardInterrupt 也清理。
6. 持久报告仅保留 allowlist 字段；用 credential/private-endpoint sentinel 证明不泄露。
7. 保持 `run_installer()`、install transaction、uninstall path 调用 probe 的 guard 为零。

**Focused GREEN:**

```bash
python -m pytest tests/test_readiness_contract.py tests/test_runtime_probe.py -v
```

### Phase C：任务合同、文件所有权与暂存派发

**Objective:** 在 Worker 启动前冻结完整任务边界、文件 owner 和 notification route。

**Files:**
- Create: `src/agentporter/delegation_contract.py`
- Create: `src/agentporter/dispatch_planning.py`
- Create: `src/agentporter/kanban_runtime.py`
- Test: `tests/test_delegation_contract.py`
- Test: `tests/test_dispatch_planning.py`
- Test: `tests/test_kanban_runtime.py`

**Steps:**

1. RED→GREEN 实现 closed Pydantic models。
2. 路径规范化后拒绝相交 allowed writes、父目录逃逸、共享文档和同名测试。
3. DispatchPlan 必须绑定 readiness evidence、base SHA、workspace、idempotency key 与 creator session。
4. 所有 task 先 blocked create；graph/link/subscribe/readback 全通过后才 unblock。
5. 订阅读回精确比较 platform/chat/thread/notifier-profile；报告只输出安全 route code。
6. CLI-only 创建明确返回 `notification-only`，不伪称 wake-ready。
7. 失败保留 blocked card 并给 safe reason，不删除历史、不产生 Worker run。

**Focused GREEN:**

```bash
python -m pytest \
  tests/test_delegation_contract.py \
  tests/test_dispatch_planning.py \
  tests/test_kanban_runtime.py -v
```

### Phase D：运行观察、终态 wake 与主代理接续

**Objective:** 用当前 run 而非 task 快照判断运行状态，并让终态自动回到 creator session。

**Files:**
- Create: `src/agentporter/runtime_observation.py`
- Modify/Create: orchestrator Profile SOUL/skill/thin-adapter resources under `src/agentporter/resources/orchestrator/`
- Test: `tests/test_runtime_observation.py`
- Test: `tests/test_kanban_runtime.py`

**Steps:**

1. RED→GREEN 实现 task+run+PID+heartbeat+event+diagnostic 聚合。
2. `active`、`launching`、`stale-or-wedged`、terminal 与 inconsistent 的优先级固定。
3. Worker 指令要求长步骤前后发 heartbeat；不把 heartbeat note 当业务完成。
4. 以 root orchestrator 卡的 parent graph 作为 durable continuation：所有子卡 done 后验证根卡重新 ready 并产生新 run。
5. 对 blocked/crashed/timed_out/gave_up 的 Gateway 通知分开记录 `event-durable`、`user-notified`、`creator-woken`；push wake 未确认时显式 degraded。
6. Gateway terminal wake 后强制 re-read，再决定集成/阻塞/恢复。
7. 完成候选必须验证 Git diff allowlist、HEAD、测试证据；通知摘要不能替代读回。
8. 根计划未完成时同一 turn 继续下一卡；无变化不发周期消息。

**Focused GREEN:**

```bash
python -m pytest tests/test_runtime_observation.py tests/test_kanban_runtime.py -v
```

### Phase E：项目级暂停与恢复

**Objective:** 组合 ESTOP、pause guard、reclaim 和 block，确保“暂停开发”后真的静止且可恢复。

**Files:**
- Create: `src/agentporter/lifecycle_control.py`
- Test: `tests/test_lifecycle_control.py`

**Steps:**

1. RED→GREEN 实现 pause guard idempotency。
2. 短暂 global ESTOP 后，只选择目标 board/tenant 的任务。
3. running → reclaim → PID/process-group readback → blocked。
4. ready/todo/scheduled 全部 blocked；终态卡不改写。
5. worktree/HEAD/mtime/process 观察窗稳定后解除 global ESTOP。
6. resume 先做 readiness/route/base/worktree preflight，再删除 guard并按依赖 unblock。
7. 任一进程仍存活或状态不一致，结果为 `pause-incomplete`，不得声称已停止。

**Focused GREEN:**

```bash
python -m pytest tests/test_lifecycle_control.py -v
```

### Phase F：三组件部署与 orchestrator 接线

**Objective:** 把上述薄控制面作为 Plan 02 专用 orchestrator 的正式、可更新组件交付。

**Files:**
- Modify: `src/agentporter/identity.py`
- Modify: `src/agentporter/models.py`
- Modify: `src/agentporter/render.py`
- Modify: `src/agentporter/planning.py`
- Modify: `src/agentporter/readback.py`
- Modify: `src/agentporter/install_workflow.py`
- Modify: `src/agentporter/transaction.py`
- Modify: uninstall discovery/planning/execution files as required by Plan 02 legacy-two/current-three matrix。
- Modify: packaging/release files。

**Steps:**

1. 先执行 Plan 02 已冻结的 legacy 双组件→三组件兼容 RED。
2. 新 orchestrator 使用永久 component ID；旧 Worker marker/version 零改写。
3. orchestrator distribution 可拥有已验证的最小 skill/plugin/thin-adapter 路径；`.env`、`auth.json`、`local/` 仍 user-owned。
4. 安装只做到 `orchestration-configured` / `probe-required` / `dispatcher-not-running`，不执行 probe、不启动 gateway、不建卡。
5. 静态 readback 验证 resources、toolsets、description、marker、config allowlist。
6. 升级/补偿/卸载沿用 compare-before-restore 和 drift-safe 规则。

### Phase G：隔离真实 Hermes 静态 E2E

**Objective:** 在无凭据、零模型调用环境证明三组件、Kanban 命令面、blocked staging、notify readback 和暂停状态机。

**Files:**
- Test: `tests/test_phase7_real_hermes_orchestration.py`

**Scenarios:**

1. 三组件安装与静态读回；
2. legacy 双组件升级；
3. `config check` 通过仍保持 `probe-required`；
4. fake/no-model task blocked staging + exact notify row；
5. missing creator session 只能 notification-only；
6. 订阅继承完整保留 chat_type 与 delivery_metadata，DM/topic/reply anchor 不降级；
7. running/PID/heartbeat synthetic rows的状态归类，以及旧 run PID/heartbeat/terminal fencing；
8. root parent graph 在子卡全部 done 后结构性接续；
9. pause guard + reclaim + block；
10. 父进程注入 gateway/Telegram/GitHub/基础设施/非目标 provider sentinel secrets，Worker 环境零可见；
11. 全程模型调用 guard = 0、credential read guard = 0、default Profile 修改 = 0。

### Phase H：显式授权的真实探针与任务闭环

**Objective:** 在非特权 OS sandbox 中验证每个 Worker 的真实调用和 terminal wake→接管。

**Files:**
- Test: `tests/test_phase8_authorized_live_probe.py`
- Workflow: 新增手动、带费用确认的 CI/maintainer workflow；不得进入默认 offline CI。

**Prerequisites:**

- 用户明确授权模型调用与预算；
- 安全 tool-free probe seam 或等价 OS sandbox 已证明；
- credentials 由操作者在 sandbox 内使用 Hermes 原生机制准备；
- provider-only egress；
- 临时 HOME/HERMES_HOME/board/repo/worktree；
- 不挂载宿主 default Profile、项目私人规则或凭据；
- cleanup 计划可验证。

**Scenarios:**

1. Luna probe success 且 usage model/provider 精确匹配；
2. Codex endpoint 502/503 时归类 endpoint-unavailable，零 fallback；
3. 修复后 Codex probe success；
4. 两张 disjoint task 卡从 Gateway creator session 暂存、订阅读回、解锁；
5. 一个 Worker crash、一个 complete；原 session 收到两类 wake；
6. 人为让 push wake 失败，验证文本投递与 creator-woken 分级且不伪称接续；
7. 所有完成子卡使根 orchestrator 卡重新 ready，并产生新 run 完成结构性接续；
8. 主代理读取 runs/PID/heartbeat/log/worktree 后立即接管；
9. 两轨唯一测试文件、无 add/add 冲突；
10. pause/resume 中断并保留 worktree；
11. 所有临时 session、usage、board、gateway、Profile、workspace 和敏感 trace 清理。

未通过此阶段前不得宣称“稳定自动编排”。

### Phase I：文档、完整门禁、复审、提交与交付

1. 主代理串行同步所有权威文档和计划索引。
2. 运行 focused tests 后串行运行完整门禁。
3. 对 exact candidate 做一次集中语义复审；如 BLOCK，把完整 finding family 一次性修复，再做至多一次 closure review。
4. 隐私扫描覆盖 staged diff、构建产物、报告、fixture 和新增资源。
5. 通过后按项目规则 commit；push、真实模型调用、gateway 服务变更和发布分别遵守授权边界。
6. 若用户批准 push，push 后 fetch 并验证本地/远端零 divergence。

---

## 6. 并行实施所有权图

只有 Phase A 冻结共享合同后才并发。

| Track | Worker | 可写生产文件 | 独占测试文件 | 禁止修改 |
|---|---|---|---|---|
| A：Readiness/凭据/探针 | `luna_worker`（或 readiness 已通过的等价 bounded Worker） | `readiness.py`, `runtime_probe.py` | `test_readiness_contract.py`, `test_runtime_probe.py` | Kanban runtime、lifecycle、所有共享文档 |
| B：派发/通知/观察/暂停/所有权 | `codex-5-3-small-worker` 只承担机械测试/fixture；跨文件实现由 bounded Worker 或主代理承担 | `delegation_contract.py`, `dispatch_planning.py`, `kanban_runtime.py`, `runtime_observation.py`, `lifecycle_control.py` 中事先再拆分的非重叠子集 | 对应五个独立测试文件，禁止同名 | Readiness 文件、共享 DTO、所有共享文档 |
| Integration | 主代理 | `models.py`, `identity.py`, render/install/uninstall composition、orchestrator resources、packaging、docs | real-Hermes/E2E、完整门禁 | 不与 Worker 同时写 |

约束：

- Codex Worker 在其自身 readiness 通过前不得用于正式实现任务。
- 同一 Phase 若两个 Track 需要修改同一共享 DTO/构造器，则先串行冻结 DTO commit，再从该 SHA 派发；不得同时改。
- main worktree 仅用于集成；每个可写 Worker 使用独立 worktree/branch。
- 每张任务卡 body 必须包含 allowed/forbidden paths、base SHA、测试名和 acceptance commands。

---

## 7. 验收矩阵

### 7.1 Readiness 与凭据

| ID | 验收项 |
|---|---|
| READY-01 | Profile/install/config check 均不能单独产生 runtime-ready |
| READY-02 | 每个正式 assignee 在解锁任务前有新鲜真实 probe evidence |
| READY-03 | 实际 model/provider 不匹配即 unexpected-runtime-route，禁止 fallback 冒充成功 |
| READY-04 | 502/503、auth、model unsupported、rate limit、timeout 分类独立 |
| READY-05 | 缺少安全 tool-free/sandbox seam 时零模型调用并返回 probe-unsupported |
| READY-06 | install/upgrade/uninstall/static readback 模型调用始终为零 |
| READY-07 | operational 按 artifact/inference/credential/canary/environment/dispatcher/route/continuity/workspace/fencing 最弱维度聚合 |
| CRED-01 | 不读取、复制、回显 default/Worker 的 key/token/private endpoint |
| CRED-02 | 外部 secret source 只保存引用；明文不进入 repo、plan、report、logs |
| CRED-03 | 凭据轮换/配置变化使旧 readiness 失效或过期，不能永久复用 |
| CRED-04 | gateway/Telegram/GitHub/基础设施/非目标 provider 环境 sentinel 不得进入 Worker |
| CRED-05 | 凭据授权或用户数据落盘后 readiness 失败不自动补偿删除 Profile |

### 7.2 任务、订阅与接续

| ID | 验收项 |
|---|---|
| ROUTE-10 | 正式任务具有 creator session；CLI-only 任务标为 notification-only |
| ROUTE-11 | task graph 先 blocked staging，未读回订阅前 Worker run 数为零 |
| ROUTE-12 | 每张必要卡的 exact platform/chat/thread/notifier-profile 均读回 |
| ROUTE-13 | 订阅失败保留 blocked card，不自动删除、不 dispatch |
| ROUTE-14 | terminal event 唤醒原 creator session，不误投其他 Telegram 话题 |
| ROUTE-15 | wake 后主代理重新读取 show/runs/diagnostics/log/worktree 再行动 |
| ROUTE-16 | completed/crashed/blocked/timed_out 均触发即时接管或显式阻塞 |
| ROUTE-17 | DispatchReceipt 读回 task/session/subscription/workspace/parents/ownership；只有 task ID 或状态不算成功 |
| ROUTE-18 | 订阅继承完整保留 chat_type 与 delivery_metadata，DM/topic/reply anchor 不降级 |
| ROUTE-19 | event-durable、user-notified、creator-woken、orchestrator-resumed 分级，不相互推断 |
| ROUTE-20 | 所有执行子卡 done 后根 orchestrator 卡 ready 并产生新 run；push wake 失败不阻断结构性接续 |

### 7.3 运行观察

| ID | 验收项 |
|---|---|
| OBS-01 | task running + dead PID 不报告 active |
| OBS-02 | run terminal 优先于旧 task running 快照 |
| OBS-03 | PID live + heartbeat stale 报 stale-or-wedged，不报持续工作 |
| OBS-04 | worktree/log/test 只作为二级进展证据 |
| OBS-05 | 状态矛盾时 inconsistent 且禁止集成 |
| OBS-06 | 无变化不发送周期汇报；任务停止后不再报告 |
| OBS-07 | PID/ACK/heartbeat/terminal 的旧 run/claim 更新被拒绝，不污染当前 run |
| OBS-08 | claimed/starting、process-spawned、agent-booted、inference-ready、executing 不被压成一个 running |

### 7.4 暂停恢复

| ID | 验收项 |
|---|---|
| PAUSE-01 | global pause 后在途 Worker 仍存在的负控制成立，证明必须 reclaim |
| PAUSE-02 | pause 只选择目标 board/tenant，不影响其他项目卡 |
| PAUSE-03 | reclaim 后全部非终态 AgentPorter 卡 blocked，解除 ESTOP 后不重派 |
| PAUSE-04 | Worker/test/heavy process 和 Git/worktree 在观察窗内静止 |
| PAUSE-05 | dirty/committed worktree 保留，不 reset/clean/delete |
| PAUSE-06 | resume 前 readiness/route/base/worktree 任一失败都保持 paused |

### 7.5 文件所有权与集成

| ID | 验收项 |
|---|---|
| OWN-01 | 两轨 allowed_writes 不相交；同名测试在建卡前拒绝 |
| OWN-02 | shared DTO/合同 owner 唯一，依赖轨从冻结 SHA 开始 |
| OWN-03 | Worker 实际 diff 超出 allowlist 时拒绝候选 |
| OWN-04 | 共享文档、版本、CHANGELOG 只由主代理串行修改 |
| OWN-05 | focused tests 可并发，完整门禁/生成/发布串行 |
| OWN-06 | 集成后重跑联合测试，不能以 conflict-free cherry-pick 代替语义验证 |

### 7.6 产品边界与发布

| ID | 验收项 |
|---|---|
| BOUND-01 | 无新增 AgentPorter task DB、dispatcher、daemon、credential vault |
| BOUND-02 | 使用 Hermes 原生 task/run/notification/workspace 为权威 |
| BOUND-03 | 一次性安装器与独立卸载器边界保持，不增加通用 CLI 命令体系 |
| BOUND-04 | legacy 双组件与当前三组件安装/升级/卸载兼容矩阵通过 |
| BOUND-05 | default offline CI 零凭据、零模型、零 gateway 服务变更 |
| GATE-01 | format、lint、pyright、offline pytest、build、release verifier、Markdown links、privacy、diff-check 全通过 |
| GATE-02 | exact candidate 通过一次语义复审和至多一次 closure review |
| GATE-03 | 文档、计划索引、项目状态、实现和验收状态一致 |

---

## 8. 验证命令

### Focused

```bash
python -m pytest \
  tests/test_readiness_contract.py \
  tests/test_runtime_probe.py \
  tests/test_delegation_contract.py \
  tests/test_dispatch_planning.py \
  tests/test_kanban_runtime.py \
  tests/test_runtime_observation.py \
  tests/test_lifecycle_control.py -v
```

### 现有回归与完整离线门禁

```bash
python -m ruff format --check .
python -m ruff check .
python -m pyright
python -m pytest \
  --ignore=tests/test_phase3_real_hermes.py \
  --ignore=tests/test_phase4_real_hermes.py \
  --ignore=tests/test_phase5_formal_acceptance.py \
  --ignore=tests/test_phase5_stress_acceptance.py \
  --ignore=tests/test_phase7_real_hermes_orchestration.py \
  --ignore=tests/test_phase8_authorized_live_probe.py
python -m build
```

### 精确候选与隐私

```bash
git diff --check
git status --short
git diff --name-only <base-sha>...HEAD
python scripts/verify_release.py <按当前 release contract 的完整参数>
```

额外要求：

- 从当前 checkout 断言至少一个 `agentporter` import path，防止 editable env 指向兄弟 worktree。
- 扫描 added lines 与 wheel/sdist，拒绝 key/token/private endpoint/chat/thread/session/raw model output/绝对私人路径。
- Real Hermes static E2E 与 authorized live probe 分开；后者永不进入默认 CI。

---

## 9. 风险与取舍

1. **Hermes 当前缺少已证明的 tool-free one-shot seam。** 这是 readiness 的真实阻塞，不得用普通 prompt 假装安全；优先推动公共最小能力或使用可验证 OS sandbox。
2. **Gateway subscription row 不是投递成功本身。** 静态层只证明 `route-recorded`；只有隔离 live acceptance 可证明 `route-delivery-passed`。
3. **creator session 是自动接续的必要条件。** 只从外部 CLI 建卡即使能发 Telegram 文本，也不必然唤醒正确主会话。
4. **global ESTOP 是机器级。** 只把它作为暂停事务的短时竞态屏障；项目长期 paused 由 board pause guard + blocked tasks 表达。
5. **Profile 不是安全 sandbox。** readiness 和真实任务的强隔离仍需非特权 container/VM/等价 OS sandbox；worktree 只隔离 Git。
6. **凭据共享与 Profile 隔离存在张力。** 首选外部 secret reference；不要为“方便”复制 default `.env`。
7. **readiness 会产生一次真实调用和费用。** 必须显式显示调用数、预算和不启用 fallback；用户取消则零调用。
8. **Worker 的可用性可能在任务中途变化。** readiness 只证明 probe 时间点；run failure 状态机和终态接管仍是必要保障。

---

## 10. Definition of Done

仅当以下全部满足，才可称 AgentPorter 的两个新 Worker 达到“稳定自动编排”基础：

- 两个 Worker 均能在自己的 Profile 上通过当前、无 fallback 的真实 readiness；
- 凭据没有被 AgentPorter/default Profile复制或泄漏；
- Worker 子进程只继承目标 Profile 显式授权的必要 provider 凭据，不继承 gateway、Telegram、GitHub、基础设施或其他 provider 秘密；
- 正式任务从有 creator session 的 Gateway/orchestrator 路径创建；
- 每张必要卡的 DispatchReceipt 与精确话题订阅（含 chat type 和 delivery metadata 语义）已读回；
- Worker 未通过订阅/readiness/ownership preflight 前不会启动；
- `running` 报告由 current run、PID 和 heartbeat 支撑；
- PID/ACK/heartbeat/terminal 受 current run ID 与 claim lock fence 保护；
- 所有执行子卡完成后，根 orchestrator 卡可结构性重新运行并自动接续；
- crash/block/timeout/complete 事件能通知原话题；push wake 未确认时明确标为 best-effort/degraded，不伪称主代理已接管；
- pause 后 AgentPorter 项目无活跃 Worker/测试/集成写入，worktree 状态保留；
- resume 前重新验证 readiness、route 与 workspace；
- 两轨文件所有权冻结且联合集成无 add/add 冲突；
- 完整门禁、隐私扫描、真实 Hermes 静态 E2E、授权 live E2E 与文档同步通过；
- exact candidate 完成限定复审、提交，并在获得授权时 push/发布且读回同步。
