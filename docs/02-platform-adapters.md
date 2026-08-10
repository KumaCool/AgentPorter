# Hermes Adapter 方案

## 1. 范围与职责

第一版只实现 `HermesAdapter`。`PlatformAdapter` 只是内部隔离边界，不为未验证平台制造通用框架。

```text
detect → inspect → negotiate → render → plan → apply → validate → report
```

- `detect`：定位 Hermes 可执行文件、版本和实际 `HERMES_HOME`；
- `inspect`：只读枚举 Profile 和冲突；
- `negotiate`：检查版本、名称和 provider/model 准备状态；
- `render`：为每个 Worker 生成独立 staging；
- `plan`：输出集合级计划和限制；
- `apply`：调用 Hermes 原生 Profile distribution 安装；
- `validate`：枚举并读回配置、description 和安装标记；
- `report`：区分安装、静态配置、路由和运行状态。

安装事务、名称无关身份、补偿和卸载的权威契约见 [安装、卸载与验收设计](03-installation-and-uninstall-design.md)。本文只描述 Hermes 原生能力映射。

## 2. Distribution 映射

Hermes 一个 distribution 安装一个 Profile。AgentPorter 在一次安装运行中，为两个 Worker 分别渲染本地 staging，并在用户确认集合计划后内部调用等价操作：

```text
hermes profile install <staging/luna> --name luna_worker --yes
hermes profile install <staging/small> --name codex-5-3-small-worker --yes
```

内部 `--yes` 只跳过 Hermes 的二次确认；AgentPorter 产品级确认要求由 [权威设计](03-installation-and-uninstall-design.md) 定义。

每个 Profile 安装：

- `distribution.yaml`：Hermes 名称、版本、要求及 `distribution_owned` 等安装元数据；安装完成后 Hermes 会把解析后的 source 和安装时间写回该 manifest。该 source 可用于安装事务读回与诊断，但不作为日后 AgentPorter 所有权身份；
- `config.yaml`：最小模型、provider 和 reasoning 配置；
- `SOUL.md`：Worker 职责与禁止事项；
- `agentporter-profile.json`：名称无关安装标记；
- Profile description：使用 `hermes profile describe --text` 写入并读回。

`distribution_owned` 第一版只包含 `config.yaml`、`SOUL.md` 和 `agentporter-profile.json`；`distribution.yaml` 是必需 manifest，不属于 payload allowlist。

## 3. 检测与兼容

Adapter 不硬编码 `~/.hermes`：

- 尊重实际 `HERMES_HOME`；
- 读取真实 Hermes 路径、版本和 Profile 根；
- 核对当前版本的 `profile install/delete/describe/list/info`、`--` 参数终止行为、命令参数及配置校验能力；
- Profile 名使用 Hermes 原生规范化、保留名和合法性规则；
- `hermes_requires` 只写经 CI 与真实验收证明的最低版本。

当前开发机 Hermes v0.20.0、schema v33 只是设计取证基线，不自动成为永久兼容承诺。

## 4. Provider、模型与凭证

- Worker 显式给出 provider 时，只写非秘密 provider ID；
- provider 未指定时，在一次安装界面中选择非秘密 ID，或明确接受安装后通过 Hermes 原生配置补齐；
- 不从默认 Profile 复制 `config.yaml`、`.env`、`auth.json`、私有 base URL 或账号状态；
- 不把当前开发机的 `custom` provider 当作公开默认值；
- 无凭证时报告“Profile 已安装，运行配置待完成”，不能声称运行有效；
- 第一版禁止模型请求，并用调用即失败 guard 锁定。

这里的模型禁令覆盖 AgentPorter 安装、静态读回、补偿、卸载和 Plan 01 集成验收。Plan 01 完成后，[Worker 验证与基准计划](plan/02-agent-validation-and-benchmark.md) 可在专用隔离环境中显式调用按 marker 发现的当前 Profile；这里“调用当前 Profile”只指在每次启动参数中使用其当前名称定位该名称对应的 Hermes Profile 环境，不表示名称建立 AgentPorter 所有权。它不是 Adapter 安装流程，也不改变安装结果。

## 5. Profile 调用与工作区

直接调用：

```text
hermes -p <current-profile-name> chat -q "<完整且有边界的任务>"
```

Kanban：

```text
hermes kanban create "<任务标题>" \
  --assignee <current-profile-name> \
  --workspace worktree \
  --body "<完整目标、范围、约束和验收>"
```

Profile 属于 Hermes 配置根，不属于某个 Git 仓库。Profile 本身不是 sandbox；隔离修改使用 Kanban worktree、`hermes -w` 或明确 workspace。

普通 `delegate_task` 有独立上下文和终端，但默认继承父模型或统一 `delegation.*` 配置。第一版不把它包装为按 Profile 选择器。

## 6. 删除能力与平台限制

独立卸载器内部调用：

```text
hermes profile delete --yes <current-profile-name>
```

当前名称只在名称无关身份发现完成后作为执行参数，并须满足“原生 normalize 后与 basename 完全一致 + 原生 validate”。Hermes v0.20 的 argparse 支持标准 `--` 参数终止符；实现可以同时使用它，但不能用它替代名称规范化、校验与对象重验。

Hermes 原生 delete 会停止该 Profile 的服务/后端、移除 wrapper 并递归删除 Profile 目录；“禁止目录强删兜底”是指 AgentPorter 不在原生命令失败后自行调用 `rm -rf` 或扩大删除范围。

Hermes v0.20 没有“仅当目录/标记身份匹配时删除”的原子条件接口。集合级重验、结果状态和 TOCTOU 产品语义由 [权威设计](03-installation-and-uninstall-design.md) 定义；本文只记录该平台事实。

## 7. Codex 保留边界

本节的 Codex 指 **Codex CLI/平台 Adapter**，不指 Hermes Profile `codex-5-3-small-worker` 请求的模型 ID。第一版：

- 唯一安装入口不提供 Codex CLI 平台选择；
- 不生成 Codex TOML，不创建 `~/.codex`；
- 不把 Codex 纳入测试、CI、发布门禁或完成状态。

只有取得真实、受支持 Codex CLI 的发现、配置、验证和非破坏安装证据后，才另行设计 Adapter。
