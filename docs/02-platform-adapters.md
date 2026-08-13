# Hermes Adapter 方案

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

`hermes config check` 仅证明静态配置可解析。无任务时 `notify-list == []` 正常；只有正式任务创建后，精确 task/subscription 读回与安全 `DispatchReceipt` 才是解锁 dispatch 的必要条件。本候选未发布、未 tag、未 push，不声称 `operational`、真实 canary 或 live routing passed。

## 1. 范围与职责

第一阶段已经实现 `HermesAdapter` 的 Profile distribution 安装、静态读回、补偿和删除映射。下一阶段继续以 Hermes 为唯一平台，但把 Adapter 职责扩展为 **工作组部署与原生编排接线**；`PlatformAdapter` 仍只是内部隔离边界，不为未验证平台制造通用框架。

```text
Profile 基础：detect → inspect → negotiate → render → plan → apply → validate → report
编排扩展：inspect orchestration → plan config → apply config → static routing readback
运行主链：triage → decompose → assign → dispatch → work → handoff → aggregate
```

- `detect`：定位 Hermes 可执行文件、版本和实际 Hermes 根；
- `inspect`：只读枚举 Profile、冲突、Kanban 命令面与现有编排配置；
- `negotiate`：检查版本、名称、provider/model 和编排准备状态；
- `render`：为每个 Worker 生成独立 staging；
- `plan`：输出工作组集合计划、专用 orchestrator Profile 配置变更和限制；
- `apply`：调用 Hermes 原生 Profile distribution 安装，并最小写入专用 orchestrator Profile 的获批编排键；
- `validate`：枚举并读回配置、description、安装标记、assignee roster 与编排配置；
- `report`：区分安装、静态配置、路由接线、dispatcher readiness 和真实任务运行。

安装事务、名称无关身份、补偿和卸载的权威契约见 [安装、卸载与验收设计](03-installation-and-uninstall-design.md)。编排扩展由 [Plan 02](plan/02-multi-agent-orchestration.md) 实施。

## 2. Distribution 映射

Hermes 一个 distribution 安装一个 Profile。AgentPorter 当前为两个 Worker 分别渲染本地 staging，并在用户确认集合计划后内部调用等价操作：

```text
hermes profile install <staging/luna> --yes
hermes profile install <staging/small> --yes
```

内部 `--yes` 只跳过 Hermes 的二次确认；AgentPorter 产品级确认仍由 [安装权威设计](03-installation-and-uninstall-design.md) 定义。

每个 Profile 安装：

- `distribution.yaml`：Hermes 名称、版本、要求及 `distribution_owned` 等安装元数据；
- `config.yaml`：最小模型、provider 和 reasoning 配置；
- `SOUL.md`：Worker 职责与禁止事项；
- `agentporter-profile.json`：名称无关安装标记；
- Profile description：使用 `hermes profile describe --text` 写入并读回。

Profile description 是 Hermes decomposer 的路由标签。`SOUL.md` 是 Worker 行为约束。两者都不是 filesystem/process sandbox，也不证明任务已被正确路由。

Plan 02 已冻结加入专用 orchestrator Profile。它必须作为新的 distribution/component 正式进入安装、补偿和卸载集合；不得临时创建无 marker Profile，也不得修改或依赖 default/active Profile 冒充编排控制面。

## 3. 检测与兼容

Adapter 不硬编码 `~/.hermes`：

- 尊重实际 `HERMES_HOME`，并识别 named Profile 下的共享默认 Hermes 根；
- 读取真实 Hermes 路径、版本和 Profile 根；
- 核对目标版本的 `profile install/delete/describe/list/info` 与 `kanban init/create/assignees/decompose/dispatch` 命令面；
- Profile 名使用 Hermes 原生规范化、保留名和合法性规则；
- `hermes_requires` 只写经 CI 与真实验收证明的最低版本。

当前 Hermes v0.20.0 是已观察基线，不自动成为永久兼容承诺。官方当前事实包括：

- Profile description 用于 Kanban 路由；
- Kanban board 在同一 Hermes 根的 Profiles 间共享；特殊容器/自定义根必须取证证明同一 board，必要时由用户在 orchestrator 服务环境显式设置 `HERMES_KANBAN_HOME`，AgentPorter 不静默写 shell/全局环境；
- gateway 默认承载 dispatcher；
- decomposer 可读取 Profile roster + descriptions 并生成 task graph 候选；AgentPorter 必须在写入共享 board 前验证 assignee/职责/fallback，不能把候选直接视为正确路由；
- `kanban.orchestrator_profile` 控制根任务 owner，不改变 decomposer 的模型/提示；
- Profile 本身不提供 workspace sandbox。

每次发布必须重新核对这些事实，不能只引用旧文档。

## 4. Provider、模型与凭证

- Worker 显式给出 provider 时，只写非秘密 provider ID；
- provider 未指定时，在部署计划中选择非秘密 ID，或明确接受安装后通过 Hermes 原生配置补齐；
- 不从 default Profile 复制 `config.yaml`、`.env`、`auth.json`、私有 base URL 或账号状态；
- 不把当前开发机 provider 当作公开默认值；
- 无凭证时报告“Profiles/编排静态接线完成，运行配置待完成”，不能声称运行有效；
- 安装、静态读回、配置补偿和卸载路径禁止模型请求，并用调用即失败 guard 锁定。

Hermes 内置 decomposer 使用 `auxiliary.kanban_decomposer`，Worker 使用各自 Profile 的模型/provider。它们是两个独立 readiness 条件。`kanban.orchestrator_profile` 不把该 Profile 的模型或 SOUL 注入内置 decomposer。

## 5. Profile、Kanban 与工作区映射

### 5.1 直接调用

```text
hermes -p <current-profile-name> chat -q "<完整且有边界的任务>"
```

直接调用适合诊断或显式委派，不等于自动路由。

### 5.2 已明确 assignee 的 Kanban 任务

```text
hermes kanban create "<任务标题>" \
  --assignee <current-profile-name> \
  --workspace worktree \
  --body "<完整目标、范围、约束和验收>"
```

这证明按指定 Profile 执行的路径，不证明系统能从自然任务自动选择它。

### 5.3 自动分解与路由

目标主链组合 Hermes triage/decomposer 与 AgentPorter 最小路由验证层：

```text
提交 triage task
→ 专用 orchestrator 调用 Hermes decomposer 取得候选 task graph
→ 写入前验证职责、assignee 存在性、fallback 禁令和 dependencies
→ 仅将通过验证的任务写入共享 board；否则根任务可见阻塞
→ gateway 内置 dispatcher 启动 named Profile
→ Worker 使用 task-scoped kanban tools 完成/阻塞/请求复核
→ 根任务在子任务完成后恢复并汇总
```

Plan 02 已冻结：

- 新 orchestrator 首版固定 manual decompose（`auto_decompose=false`），不提供 Auto 选项；
- 专用 orchestrator Profile 作为根任务 owner 和 dispatcher/decomposer 配置 owner；
- `default_assignee` 不写入：Hermes v0.20 内置 decomposer 会把 null/空/无效值回落 active/default Profile；AgentPorter 薄适配绕开该 resolver，并在任何 board 子任务写入前阻止 unknown/missing assignee 与矩阵外任务；
- per-profile 并发与 scratch/worktree/dir 使用规则由 Hermes 原生字段执行；
- gateway 未运行、Profile 缺失、provider 未就绪时使用分层状态。

Adapter 负责接线、Profile 配置读回、写入前领域路由验证和证据采集；不复制 Hermes 的 board、dispatcher、依赖图或重试逻辑。若目标 Hermes 没有可证明的写入前候选 seam，自动路由保持 unsupported。

### 5.4 工具集

Dispatcher-spawned Worker 会获得 task-scoped Kanban lifecycle tools。专用 orchestrator 只拥有完成路由所需的最小 toolsets；其精确配置必须基于目标 Hermes 版本验证。普通 `delegate_task` 仍是匿名、进程内委派，不作为按 AgentPorter Profile 选择或持久任务编排的实现。

### 5.5 工作区

Profile 属于 Hermes 配置根，不属于某个 Git 仓库。Profile 本身不是 sandbox：

- `scratch`：临时、任务完成后清理；
- `worktree`：适合隔离 Git 写任务；
- `dir:<path>`：只在明确授权共享/持久目录时使用。

同一写工作区不得被多个并行 Worker 无保护共享。安全隔离需要 OS/container 等独立机制，不能靠 SOUL 或 Profile 名称宣称。

## 6. Orchestrator Profile 配置事务

Hermes 共享 Kanban board，但不共享 Profile `config.yaml`。Plan 02 只允许在专用 orchestrator Profile 中写入冻结 allowlist：

- `kanban.auto_decompose`（首版固定为 `false`；该键由 Hermes gateway 每个 dispatcher tick 动态重读，部署和运行验收都必须从专用 runtime 的最终解析配置读回为 false；目标 Hermes 有经验证的 preview seam 前不得启用）；
- `kanban.orchestrator_profile`（固定为专用 orchestrator 自身）；

- `kanban.max_in_progress_per_profile`（正整数）；
- `platform_toolsets.cli`（Phase A 按目标 Hermes schema 冻结的最小 board-control 集）；
- `auxiliary.kanban_decomposer`（仅用户显式选择的非秘密 provider/model ID）。

规则：

1. 在任何写入前读取“键存在性 + typed value”；
2. 与 Profile 集合一起展示一份部署计划；
3. 只写 allowlist 键；
4. 精确读回；
5. 后续失败时对每个键执行 compare-before-restore：仅当前 typed value 仍等于本事务写入值才恢复原存在性/原值；drift 时保留用户新值、报告 residue，并保留承载残留配置的 orchestrator Profile。只有配置恢复完整或尚未写入配置时，才按身份重验补偿本事务新建 Profile；
6. 原本不存在的键恢复为不存在，而不是写入当前默认值；
7. 已有冲突配置默认 fail closed，不静默覆盖。

`kanban.dispatch_in_gateway` 不在写入 allowlist 中，只从专用 orchestrator Profile 读回。写配置前必须枚举全部 Profile gateway 的实时 PID/dispatcher 配置、machine-global singleton lock、standalone dispatcher 迹象及全部 board 非终态计数；其他 owner、无法归因或含非终态任务的 board 均为 `runtime-conflict` 且零写入。AgentPorter 默认不自动启动或安装 gateway 服务；后续只有专用 orchestrator runtime 的 PID、配置、lock ownership 与目标 board DB 一致读回，才报告 dispatcher-ready。

## 7. 删除能力与平台限制

独立卸载器当前内部调用：

```text
hermes profile delete --yes <current-profile-name>
```

当前名称只在名称无关身份发现完成后作为执行参数。Hermes 原生 delete 会移除整个 Profile；AgentPorter 不在原生命令失败后使用目录强删兜底。

编排扩展若修改专用 orchestrator Profile 的冻结 allowlist 配置，后续卸载语义必须单独设计：删除 orchestrator Profile 不应默认删除共享 Kanban board 或用户任务；只有可证明仍等于 AgentPorter 写入值的 allowlist 配置键才有资格恢复，发生用户修改时必须保留并报告 drift；`kanban.default_assignee` 从不由 AgentPorter 写入或恢复。当前 v0.1.0 卸载器尚不管理第三组件或这些键，因此 Plan 02 实现前不得宣称编排配置可完整卸载。

## 8. Codex 保留边界

本节的 Codex 指 **Codex CLI/平台 Adapter**，不指 Hermes Profile `codex-5-3-small-worker` 请求的模型 ID。当前：

- 唯一部署入口不提供 Codex CLI 平台选择；
- 不生成 Codex TOML，不创建 `~/.codex`；
- 不把 Codex CLI 纳入测试、CI、发布门禁或完成状态。

只有取得真实、受支持 Codex CLI 的发现、配置、验证和非破坏安装证据后，才另行设计 Adapter。
