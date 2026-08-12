# AgentPorter Runtime Readiness 与编排闭环落地计划

> **For Hermes:** 使用 `continuous-plan-orchestration`、`parallel-development-convergence` 与 `test-driven-development` 持续执行；先冻结共享合同，再开两条隔离轨，focused tests 可并发，完整门禁串行。本文是实施计划，不代表任何代码或运行验收已经完成。

**Goal:** 修复 AgentPorter 0.1.3 的假绿：让两个 Worker 在不复制或泄露凭据的前提下获得可重放的显式推理绑定，通过真实模型 canary，并在正式任务创建时闭合 Kanban 并发、订阅、终态通知和结构性接续。

**Architecture:** 将“发布制品静态配置”和“安装实例运行绑定”拆成两个所有权层。Distribution 继续拥有角色、模型默认值、reasoning、SOUL 和身份标记；用户/运维拥有 provider、base URL 和凭据授权。新增专用、确认门控的 `agentporter-activate` 生命周期入口：它只写非秘密运行绑定、调用 Hermes 原生凭据机制、执行最小真实 canary，并生成安全 readiness evidence；安装/升级/卸载仍零模型调用。编排由第三个专用 orchestrator Profile 及 Hermes 原生 Kanban/Gateway 承担；AgentPorter 不新建任务数据库、dispatcher、凭据库或常驻 daemon。

**Tech Stack:** Python 3.11+、Pydantic 2、PyYAML、Hermes Agent v0.20 公共 CLI/Profile Distribution/Kanban、pytest、ruff、pyright、setuptools。

---

## 0. 当前证据与设计修正

### 已确认事实

- 当前候选：AgentPorter `0.1.3`，仓库 `main` 与 `origin/main` 同步，工作树干净。
- 两个 Worker 的 `config.yaml` 只有 `model.default` 和 `agent.reasoning_effort`；`model.provider`、`model.base_url` 均未设置。
- 两个真实 one-shot 都以 `No inference provider configured`、退出码 `1` 失败。
- `hermes config check` 返回 `0` 只证明配置可解析，不能证明主模型调用成功。
- `src/agentporter/readiness.py` 目前只有纯领域合同；`runtime_probe.py`、运行绑定、派发/订阅读回、运行观察尚未实现。
- Hermes v0.20 的 Profile Distribution **更新默认保留已有 `config.yaml`**；只有 fresh install 或显式 force-config 才覆盖。0.1.3 的“删除后重装”是 fresh install，因此会丢失人工修复。不能依赖手改完整 `config.yaml`。
- `notify-list == []` 在尚无正式任务时是正常状态：Kanban 订阅是**任务级**记录，不应在安装时制造虚假全局订阅。真正缺口是“每次建卡后未做订阅读回”。
- dispatcher 使用运行 Gateway 的 Profile 配置；不能把 Kanban 控制键散写到两个 Worker Profile 并期待影响当前 Gateway。

### 冻结结论

1. **不把私有 endpoint 或 key 写进发布仓库、`workers.yaml`、Distribution 或安装标记。**
2. **不把完整 `config.yaml` 当作长期手工修复面。** 运行绑定必须由 AgentPorter 的可重放激活事务产生。
3. **不修改 Hermes 的 `config check` 语义。** AgentPorter 自己新增 `static-valid` 与 `runtime-ready` 两层状态，后者只接受真实 canary。
4. **安装与激活分离。** 安装保持零模型调用；激活会产生最多每 Worker 一次调用，必须单独确认。
5. **订阅在任务事务中创建。** 安装后空订阅不判失败；正式任务没有精确订阅读回则不得解锁 dispatch。
6. **首版关闭自动分解并限制并发。** `kanban.auto_decompose=false`、`kanban.max_in_progress_per_profile=1`；不得保留 `null`。
7. **`dispatch_interval_seconds` 不是可靠终态唤醒机制。** 设置为较短的安全值（首版建议 `10` 秒，仅作用于专用 orchestrator Gateway），同时以 terminal event + task subscription 和父任务结构性重新 ready 为主链。

---

## 1. 语义不变量与禁止副作用

### 1.1 推理与凭据

- `installed`、`static-valid`、`credential-authorized`、`runtime-ready`、`operational` 五态不得合并。
- 只有当前 component、当前 Profile 名、当前 Hermes 版本、当前 model/provider 绑定上的真实成功 canary 才能生成 `runtime-ready`。
- `config check=0`、`.env exists`、Profile 可枚举、Gateway running 均不能升级为 `runtime-ready`。
- 实际 model/provider 与期望不一致时为 `unexpected-runtime-route`；禁止 fallback 冒充成功。
- AgentPorter 不读取、复制、打印、记录或提交 API key、token、OAuth 内容、私有 base URL 原文。
- 不从 default Profile 克隆 `.env`、`auth.json`、`config.yaml` 或 shell credential 环境。
- 凭据优先由 Hermes 外部 secrets 集成或 Profile-local auth pool 管理；AgentPorter只持有不含秘密值的 grant 类型与安全状态。
- 运行绑定变化、Hermes 版本变化或 freshness 过期后必须重新 canary。
- 凭据授权后 canary 失败不得自动删除 Profile。

### 1.2 配置所有权

- Distribution-owned：`SOUL.md`、角色/模型静态默认、reasoning、`agentporter-profile.json`、orchestrator 资源。
- Instance-owned：`model.provider`、`model.base_url`、凭据授权、Kanban 路由来源、readiness evidence。
- Fresh install 后必须显式进入 `configuration-required`，不能默认为可用。
- Update 不得 force 覆盖 instance-owned 绑定；若静态模型变更，激活状态失效并要求重验。
- 激活写配置采用“读取 typed snapshot → 不可变计划 → 一次确认 → compare-before-write → 原生写入 → 精确读回 → canary”；失败按 compare-before-restore 恢复未漂移键。
- 不将 base URL 放入命令行参数、公开日志、计划 fingerprint 明文或错误正文；写入适配需使用受控输入/文件 API，报告仅保存 endpoint 摘要（scheme + public/private 分类 + hash，不保存原值）。

### 1.3 Kanban、通知与接续

- 正式任务必须先 blocked/staged，任务合同、assignee、workspace、parents、creator session 和 subscription 全部读回后才 unblock。
- 每个正式根卡和需即时感知失败的子卡都要 `notify-subscribe` 并 `notify-list --json` 精确读回 platform/chat/chat_type/thread/notifier_profile/delivery metadata 语义。
- CLI-only 卡即使有 notify row，也只标记 `notification-only`；自动接续要求 creator session 或结构性 orchestrator parent graph。
- 所有执行子卡完成后，根 orchestrator 卡重新 ready 并产生新 run；Telegram wake 是异常通知与交互优化，不是唯一接续机制。
- `running` 只代表 claim/启动快照；`active` 至少要求 current run、可归因存活 PID、有效 heartbeat/activity。
- 无变化不发送周期消息；终态、降级、人工输入或用户查询才报告。

### 1.4 安全与产品边界

- 不新增 AgentPorter task DB、dispatcher、daemon、credential vault 或通用多子命令 CLI。
- `agentporter-activate` 是单一专用生命周期入口，与已有 `agentporter` / `agentporter-uninstall` 对称；无子命令树。
- 默认安装/升级/卸载/静态 CI：零模型、零任务、零 gateway 启停、零凭据读取。
- 真实 canary、Gateway 服务变更、push、发布分别需要明确授权。
- 所有提交和构建制品不得含 key/token、私人路径、真实 chat/thread/session ID、私有 endpoint、原始模型输出。

---

## 2. 目标配置模型

### 2.1 发布层：静态 Worker 定义

`src/agentporter/resources/workers.yaml` 保留可公开字段：

```yaml
model: gpt-5.6-luna
reasoning_effort: max
provider: null
```

`provider: null` 表示发布者不声明部署环境的 provider，不代表可运行。不得新增 base URL、key、账号或私有 provider 默认值。

### 2.2 实例层：运行绑定

新增闭合模型 `RuntimeBindingPlan`（内存中可含私有 endpoint，`repr=False`，禁止持久化原值）：

```text
portable_id
component_id
current_profile_name
expected_model
provider_id
endpoint_value (private, repr=False, never persisted in reports)
endpoint_digest
credential_grant_kind: external-secret | profile-auth | profile-env
credential_state: unresolved | operator-authorized
fallback_policy: forbidden
hermes executable/home/profile identity
config typed snapshot
fingerprint
```

非秘密激活收据 `RuntimeBindingReceipt`：

```text
component_id
profile_name
model
provider
endpoint_digest
credential_grant_kind
config_readback_passed
canary_status
hermes_version
fresh_until
```

不得含 key、endpoint 原文、auth path、用户/账号标识。

### 2.3 凭据来源支持顺序

1. **External secret manager（首选）**：用户先通过 `hermes secrets bitwarden|onepassword` 配置目标 Profile 的启动解析；多个 Profile 可引用同一外部对象，AgentPorter不接触明文。
2. **Profile-local Hermes auth pool**：用户分别在两个 Profile 上执行 Hermes 原生 `auth add/status`；AgentPorter只调用安全状态 seam，不读 `auth.json`。
3. **Profile-local `.env`（兼容）**：由用户自行维护；AgentPorter只提示并将状态保持为 operator-asserted，绝不读取文件内容。

如果目标 Hermes 对 custom provider 的 base URL 只能从 `config.yaml` 读取，则 activation 事务写 `model.provider` 与 `model.base_url`；API key仍只通过上述凭据来源提供。

---

## 3. 分阶段实施

## Phase A：冻结失败家族与共享合同（已实现并通过离线门禁）

**Status:** 已完成。Phase A 只冻结并实现纯领域/runtime probe 合同；真实配置写入、安装/update 生命周期接线和 authorized live canary 仍分别属于 Phase B/C。

**Objective:** 一次性覆盖本次事故的完整 finding family，避免逐补丁复审。

**Files:**
- Modify: `src/agentporter/readiness.py`
- Create: `src/agentporter/runtime_binding.py`
- Create: `src/agentporter/runtime_probe.py`
- Create: `tests/test_runtime_binding.py`
- Create: `tests/test_runtime_probe.py`
- Modify: `tests/test_readiness_contract.py`

**Steps:**

1. 写 RED：provider 缺失时 `config check=0` 仍是 `configuration-required`。
2. 写 RED：provider 有值但 base URL 缺失/无效时不得启动 canary。
3. 写 RED：auth missing、401/403、404/model unsupported、429、502/503、timeout、非 nonce 输出分别归类。
4. 写 RED：usage 实际 provider/model 不匹配为 `unexpected-runtime-route`。
5. 写 RED：fresh install 删除旧手工 config 后，不得继承旧 `runtime-ready`。
6. 写 RED：正常 update 不覆盖 instance binding；显式 force-config 或模型静态变化使 readiness 失效。
7. 写 RED：endpoint/key/private path sentinel 不进入 `repr`、JSON receipt、stdout/stderr、异常 note、fingerprint payload。
8. 写 RED：安装、升级、卸载、静态 readback 的 model runner 调用即失败。
9. 写 RED：任意取消、timeout、`KeyboardInterrupt` 后临时 usage/stdout/stderr 均删除。
10. 集中做一次语义复审；finding family 未完整前不写生产实现。

**RED command:**

```bash
python -m pytest \
  tests/test_readiness_contract.py \
  tests/test_runtime_binding.py \
  tests/test_runtime_probe.py -v
```

Expected: 因生产行为尚不存在而失败，不能是 import/fixture 错误。

**GREEN evidence:**

```text
44 passed
Ruff check/format: passed
Pyright strict: 0 errors, 0 warnings
Offline full pytest at candidate worktree: 437 passed, 2 warnings
```

覆盖结果：配置/凭据/probe-support 零调用门控、HTTP/timeout/nonce 安全分类、实际 route/fallback/API/tool 校验、按 component 的双 Worker 聚合、freshness 与生命周期失效、敏感值排除以及取消/timeout/`KeyboardInterrupt`/`BaseException` 清理合同均已通过。安装、update、卸载与静态 readback 的真实组合根接线仍由后续 Phase B 生命周期测试关闭。

## Phase B：可重放运行绑定事务

**Objective:** 让重装后不再依赖人工编辑完整 `config.yaml`。

**Files:**
- Create: `src/agentporter/runtime_binding.py`
- Create: `src/agentporter/activation_application.py`
- Create: `src/agentporter/activation_entry.py`
- Modify: `src/agentporter/native.py`
- Modify: `pyproject.toml`
- Test: `tests/test_runtime_binding.py`
- Test: `tests/test_activation_application.py`
- Modify: `tests/test_entrypoints.py`

**Steps:**

1. 新增专用 console entry：`agentporter-activate=agentporter.activation_entry:main`；不接受任意目标 Profile，只发现同一 installation ID 的完整 AgentPorter 集合。
2. 只读发现两个 Worker 的名称无关身份、Hermes executable/home/profile root 与当前 config typed snapshot。
3. 交互选择每个 Worker 的非秘密 provider ID、endpoint 输入来源及 credential grant kind；默认不猜测、不继承 default Profile。
4. endpoint 从 `/dev/tty` 或权限受限临时文件读取；计划展示只显示安全摘要，不回显原值。
5. 构造不可变 binding plan，并一次性确认精确目标、model/provider、endpoint 摘要、最多调用次数与费用提示。
6. compare-before-write 后通过 Hermes 原生配置 seam 写 `model.provider`、`model.base_url`；如果 Hermes 公共 seam 会把私有值暴露在 argv/process list，则先贡献/采用 stdin 或受控文件 seam，否则 activation 标记 `unsupported`，不得降级到带明文 argv。
7. 精确读回 resolved config；读回比较在内存中完成，输出只给布尔与摘要。
8. 失败时只恢复当前值仍等于本事务写入值的键；配置 drift 保留用户新值并返回 `compensation-incomplete`。
9. 不创建或修改 `.env`、`auth.json`；凭据未由用户授权时停止于 `credential-required`，不执行 canary。
10. 激活成功不改变安装 marker；收据写入 user-owned `local/agentporter/runtime-binding.json`，只含安全字段。Distribution update不得删除 `local/`。

**Focused GREEN:**

```bash
python -m pytest \
  tests/test_runtime_binding.py \
  tests/test_activation_application.py \
  tests/test_entrypoints.py -v
```

## Phase C：真实 canary 与 readiness evidence

**Objective:** 用真实调用取代 `config check` 假绿。

**Files:**
- Modify: `src/agentporter/readiness.py`
- Create: `src/agentporter/runtime_probe.py`
- Modify: `src/agentporter/activation_application.py`
- Test: `tests/test_runtime_probe.py`
- Create: `tests/test_phase8_authorized_live_probe.py`

**Steps:**

1. capability negotiation：优先使用 Hermes 公共 tool-free one-shot/probe seam。
2. 若无 tool-free seam，只允许在非特权 OS sandbox、空 cwd、最小环境、provider-only egress 下运行；否则返回 `probe-unsupported` 且模型调用数为 0。
3. 每 Worker 固定随机 nonce，要求严格返回 `AGENTPORTER_READY:<nonce>`。
4. 硬超时；usage/stdout/stderr 位于 0700 临时目录；成功/失败/中断都清理。
5. 验证 API calls=1、tool calls=0、fallback=false、实际 model/provider 等于 binding。
6. 将失败映射为安全 reason code，不持久化 provider 原始错误正文。
7. `fresh_until` 首版设为短期运维窗口；配置摘要、Hermes 版本或模型绑定变化立即失效。
8. 两个 Worker 均通过才将 inference 聚合为 `runtime-ready`；任一失败则该 Worker不可派发，禁止相互 fallback。

**Authorized live acceptance:**

```bash
python -m pytest tests/test_phase8_authorized_live_probe.py -v
```

前置：用户明确授权调用与预算、凭据已在 sandbox/Profile 内由操作者准备、provider-only egress、临时 HOME/HERMES_HOME、cleanup 可验证。

## Phase D：第三组件 orchestrator 与安全 Kanban 配置

**Objective:** 把控制面放在专用 Gateway owner，而不是两个执行 Worker。

**Files:**
- Modify: `src/agentporter/identity.py`
- Modify: `src/agentporter/models.py`
- Modify: `src/agentporter/resources/workers.yaml`
- Modify: `src/agentporter/render.py`
- Modify: `src/agentporter/planning.py`
- Modify: `src/agentporter/readback.py`
- Modify: install/compensation/uninstall collection files
- Create: `src/agentporter/resources/orchestrator/SOUL.md`
- Create/Modify: `tests/test_phase7_real_hermes_orchestration.py`

**Steps:**

1. 先写 legacy 双组件→当前三组件的身份、升级、补偿、卸载 RED。
2. 新 orchestrator 使用永久 component ID；旧两个 Worker marker 不重写。
3. orchestrator Profile 成为唯一 Kanban 控制面；Worker Profile 不拥有 dispatcher 配置。
4. 首版写入并读回：
   - `kanban.auto_decompose=false`
   - `kanban.max_in_progress_per_profile=1`
   - `kanban.dispatch_interval_seconds=10`
   - `kanban.orchestrator_profile=<dedicated orchestrator>`
   - 最小 `platform_toolsets.cli`
5. 不写 `kanban.default_assignee`；unknown/missing assignee 在任何 board 子任务写入前 fail closed。
6. `auto_subscribe_on_create=true` 仅作为辅助默认值，不能替代实际 notify row readback。
7. 安装不启动 Gateway、不建卡、不调用模型；静态结果最多是 `orchestration-configured / dispatcher-not-running / canary-required`。
8. runtime activation 时再读回专用 Gateway PID、Profile config、singleton dispatcher ownership 和同一 board。

**Focused GREEN:**

```bash
python -m pytest \
  tests/test_render.py \
  tests/test_planning.py \
  tests/test_install_workflow.py \
  tests/test_compensation.py \
  tests/test_uninstall_* \
  tests/test_phase7_real_hermes_orchestration.py -v
```

## Phase E：任务级订阅、DispatchReceipt 与结构性接续

**Objective:** 修复“订阅为空”和终态不唤醒，但不在无任务时伪造订阅。

**Files:**
- Create: `src/agentporter/dispatch_planning.py`
- Create: `src/agentporter/kanban_runtime.py`
- Create: `src/agentporter/runtime_observation.py`
- Create: `tests/test_dispatch_planning.py`
- Create: `tests/test_kanban_runtime.py`
- Create: `tests/test_runtime_observation.py`

**Steps:**

1. DispatchPlan 绑定 fresh readiness evidence、creator session、board/tenant、workspace、base SHA、allowed writes、parents 和 route source。
2. 根卡/子卡先 blocked 创建；缺 fresh canary 的 assignee直接 `capability` 阻塞。
3. 建立依赖后，对根卡及需要即时失败感知的子卡执行 exact `notify-subscribe`。
4. 用 `notify-list --json` 精确比较 platform、chat、chat_type、thread、notifier_profile 和 delivery metadata 语义；真实 ID 只在内存中比较。
5. 读回 task/session/assignee/workspace/parents/subscriptions 后生成 `DispatchReceipt`；只有全部通过才 unblock。
6. 收据持久层只保存 route digest/状态，不保存 Telegram ID、thread ID、session ID。
7. 所有执行子卡作为根 orchestrator 卡的 parents；全部 done 后验证根卡重新 ready 并产生新 run。
8. terminal wake 后重新读取 `show --json`、`runs --json`、diagnostics、PID/heartbeat、log、worktree，再决定集成/恢复/阻塞。
9. `running + dead PID`、stale heartbeat、旧 run terminal、状态矛盾都不得报告 active。
10. 无变化不发送轮询消息；terminal、degraded、needs-input 才通知。

**Focused GREEN:**

```bash
python -m pytest \
  tests/test_dispatch_planning.py \
  tests/test_kanban_runtime.py \
  tests/test_runtime_observation.py -v
```

## Phase F：文档、打包、门禁与发布候选

**Objective:** 使代码、计划索引、用户文档和发行契约一致。

**Files:**
- Modify: `docs/00-solution-overview.md`
- Modify: `docs/01-portable-worker-spec.md`
- Modify: `docs/02-platform-adapters.md`
- Modify: `docs/03-installation-and-uninstall-design.md`
- Modify: `docs/plan/00-index.md`
- Modify: `docs/plan/02-multi-agent-orchestration.md`
- Modify: `docs/plan/02a-worker-readiness-orchestration-closure.md`
- Modify: `README.md`, `README.zh-CN.md`
- Modify: `docs/04-installation-and-troubleshooting*.md`
- Modify: `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`
- Modify: `pyproject.toml`, `MANIFEST.in`, `scripts/verify_release.py`

**Steps:**

1. 文档并列展示：installation、binding、credential、canary、dispatcher、route、continuity 状态。
2. 明确 `config check` 是静态检查；给出 `agentporter-activate` 的安全流程与失败恢复。
3. 明确空 `notify-list` 在无任务时正常；任务创建后必须有 task-specific receipt。
4. 升版本并更新 wheel/sdist/entry-point verifier；不提前声称 live routing passed。
5. 对 exact candidate 做一次集中语义复审；如 BLOCK，一次性修完整 finding family，再做至多一次 closure review。
6. 通过后 commit。push、真实模型验收、Gateway 服务变更和发布分别按授权执行；若获准 push，fetch 后证明本地/远端零 divergence。

---

## 4. 并行所有权图

共享 DTO 与入口先由主代理串行冻结并提交一个 base SHA，然后两轨并行：

| Track | Worker | 独占生产文件 | 独占测试 | 禁止修改 |
|---|---|---|---|---|
| A：binding/readiness/probe | readiness 已通过的 `luna_worker`；未通过前由主代理实现 | `runtime_binding.py`, `runtime_probe.py`, `activation_application.py`, `activation_entry.py` | `test_runtime_binding.py`, `test_runtime_probe.py`, `test_activation_application.py` | Kanban runtime、共享文档、版本 |
| B：dispatch/notify/observation | bounded Worker；Small 只做明确机械 fixture | `dispatch_planning.py`, `kanban_runtime.py`, `runtime_observation.py` | 三个同名独占测试文件 | binding/readiness、共享 DTO、共享文档 |
| Integration | 主代理 | identity/models/render/install/uninstall/orchestrator resources/packaging/docs | real-Hermes/E2E | 不与 Worker 同时写 |

- 两个 Worker 当前均未 runtime-ready，因此**第一批修复不得派给它们**；先由主代理完成最小 readiness 闭环或使用已验证等价执行者。
- focused tests 可并发；完整 pytest、ruff、pyright、build、release verifier、隐私扫描串行。
- `docs/plan/00-index.md`、README、CHANGELOG、版本只由主代理串行修改。

---

## 5. 验收矩阵

### 5.1 Readiness / 凭据

| ID | 验收项 |
|---|---|
| READY-01 | `config check=0` + provider missing 仍为 configuration-required |
| READY-02 | provider/base URL/credential grant 任一缺失时零 canary |
| READY-03 | 每个可派发 Worker 有新鲜、当前绑定、无 fallback 的真实 canary |
| READY-04 | 实际 model/provider 不匹配为 unexpected-runtime-route |
| READY-05 | auth/model/429/502/503/timeout/response-contract 分类独立 |
| READY-06 | 安装/升级/卸载/静态 readback 模型调用始终为零 |
| READY-07 | fresh install 不继承旧 readiness；update 保留 instance binding但静态模型变化使其失效 |
| CRED-01 | 不复制 default `.env`/`auth.json`/config/shell secrets |
| CRED-02 | key/private endpoint 不进入 repo、argv、日志、异常、receipt、构建制品 |
| CRED-03 | 外部 secret reference 或 Profile auth 由 Hermes/用户持有，AgentPorter只观察安全状态 |
| CRED-04 | 凭据授权后 probe 失败不自动删 Profile |

### 5.2 Config ownership / lifecycle

| ID | 验收项 |
|---|---|
| CFG-01 | Distribution 静态配置与 instance runtime binding 分层明确 |
| CFG-02 | activation 写入前 snapshot，写后精确读回，失败 compare-before-restore |
| CFG-03 | concurrent drift 被保留并报告 residue |
| CFG-04 | update 不 force 覆盖 instance config；fresh reinstall 明确要求重新 activation |
| CFG-05 | `agentporter-activate` 只处理唯一完整 AgentPorter installation set |

### 5.3 Kanban / 通知 / 运行

| ID | 验收项 |
|---|---|
| KAN-01 | 专用 orchestrator 配置 `auto_decompose=false`、per-profile cap=1、interval=10 并读回 |
| KAN-02 | Worker Profiles 不承担 dispatcher 控制配置 |
| ROUTE-01 | 正式任务先 blocked；readiness/receipt 未通过时 run 数为零 |
| ROUTE-02 | task-specific subscription 全字段读回；无任务时空列表不判失败 |
| ROUTE-03 | CLI-only 路由标为 notification-only，不伪称 creator-woken |
| ROUTE-04 | 所有子卡 done 后根 orchestrator 卡 ready 并产生新 run |
| OBS-01 | task running + dead PID 不报告 active |
| OBS-02 | terminal run 优先于旧 running 快照 |
| OBS-03 | PID live + heartbeat stale 报 stale-or-wedged |
| OBS-04 | wake 后重读 task/run/diagnostic/log/worktree，不信通知摘要 |
| OBS-05 | 无变化不发周期消息；终态后停止报告 |

### 5.4 兼容 / 安全 / 发布

| ID | 验收项 |
|---|---|
| COMP-01 | legacy 双组件可发现、升级、卸载；当前三组件使用同 installation ID |
| COMP-02 | 旧 Worker marker 不因加入 orchestrator 被改写 |
| BOUND-01 | 无自研 task DB/dispatcher/daemon/credential vault |
| SEC-01 | default Profile、私人路径、真实 Telegram/session/endpoint 不进入提交或制品 |
| GATE-01 | format、lint、strict type、offline pytest、build、release verifier、Markdown links、privacy、diff-check 全通过 |
| GATE-02 | exact candidate 一次语义复审、至多一次 closure review |
| GATE-03 | 实现、计划索引、项目状态、README/指南、CHANGELOG 同步 |

---

## 6. 完整验证命令

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
git diff --check
```

额外门禁：

- 从当前 checkout 断言 `agentporter` import provenance，防止测试命中旧 wheel/兄弟 worktree。
- 对 staged diff、wheel、sdist、fixture 和持久报告扫描：key/token/password/cookie、私有 endpoint、绝对私人路径、chat/thread/session ID、原始模型输出。
- `scripts/verify_release.py` 必须包含新增 `agentporter-activate` entry point 与新增资源契约。
- Real Hermes static E2E 与 authorized live probe 分开；后者永不进入默认 CI。
- 真实探针必须分别得到严格 nonce、退出码 `0`、API calls=1、tool calls=0、实际 model/provider 精确匹配。
- 正式任务 E2E 必须读回 DispatchReceipt、terminal notify、根卡结构性恢复、PID/heartbeat/run 与 workspace 证据。

---

## 7. 风险与取舍

1. **Hermes v0.20 未证明安全的 tool-free probe seam。** 若无法取得公共 seam，必须用非特权 OS sandbox；两者都不可用时 fail closed，不执行普通 one-shot。
2. **custom base URL 的安全写入 seam 可能不足。** 不能把私有 endpoint 放 argv；若 Hermes 只有 argv 配置入口，应先补上游 stdin/file API，再实现 activation。
3. **Profile Distribution 的 update 与 fresh reinstall 语义不同。** update 默认保留 config；删除重装不会。文档和测试必须分别覆盖，不能笼统说“重装会/不会覆盖”。
4. **外部 secret manager 共享引用依赖 Hermes 实际 Profile 作用域。** 实现前必须用最小非秘密 fixture 验证；不能仅凭文档假定共享行为。
5. **订阅记录不等于投递成功。** 静态层只到 route-recorded；live acceptance 才能到 delivery-verified/creator-woken。
6. **10 秒 dispatcher interval 只是恢复延迟上限之一。** 事件通知和结构性父任务恢复才是主链，不能靠缩短轮询冒充闭环。
7. **当前 Worker 不可用。** 修复初期不能使用它们实现自身修复；先由主代理完成最小闭环，随后才能恢复双轨 Worker 开发。

---

## 8. Definition of Done

只有以下全部成立，才能宣布 AgentPorter Worker 可投入开发：

- 两个 Worker 都有显式、可重放、非秘密的 runtime binding；
- 凭据由 Hermes/用户或外部 secret manager持有，未被 AgentPorter/default Profile复制或泄漏；
- 两个 Profile 各自真实 canary 成功，严格输出 nonce，退出码 0，实际 model/provider 匹配且无 fallback/tool call；
- `config check` 在所有输出中只标为 static-valid，不再作为 readiness 证明；
- fresh reinstall/update 的配置所有权和 readiness 失效语义均有测试；
- 专用 orchestrator 读回 `auto_decompose=false`、per-profile cap=1、interval=10，并成为唯一 dispatcher owner；
- 正式任务在 blocked staging 后生成并读回精确 DispatchReceipt 和 task subscription；
- completed/blocked/crashed/timed_out 能通知原来源，所有子卡完成后根 orchestrator 卡可结构性继续；
- 对外“仍在工作”由 current run、PID、heartbeat 和活动证据支持；
- 完整门禁、集中语义复审、closure review、隐私扫描、提交、获批 push 后远端读回全部闭合；
- 文档状态与真实实现/验收一致，未执行 live acceptance 前绝不声称 operational 或 live-routing-passed。
