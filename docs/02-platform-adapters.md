# 平台 Adapter 方案

## 1. 当前范围

第一版只实现 `HermesAdapter`。`PlatformAdapter` 保留为内部边界，避免核心语义和 Hermes CLI 调用耦合，但不为未验证平台制造通用框架。

目标生命周期：

```text
detect → inspect → negotiate → render → plan → apply → validate → report
```

- `detect`：定位真实 `hermes`、版本和目标 Hermes 根；
- `inspect`：只读枚举 Profile、配置和冲突；
- `negotiate`：检查版本、名称、模型/provider 配置条件；
- `render`：为每个 Worker 生成临时 distribution；
- `plan`：输出集合级变更、限制与验证级别；
- `apply`：通过 Hermes 原生 distribution install 安装；
- `validate`：枚举、配置检查、字段与 description 读回；
- `report`：区分安装、静态、路由和运行状态。

## 2. HermesAdapter 权威实现

### 2.1 一次产品命令、多个原生 distribution

Hermes Profile distribution 原生以一个仓库根 manifest 安装一个 Profile。AgentPorter 第一版包含两个 Worker，因此不会把整个 AgentPorter 仓库伪装成单一 Profile distribution。

目标命令：

```text
agentporter install hermes
```

内部为每个 Worker 渲染独立本地 staging，并调用等价于：

```text
hermes profile install <staging/luna_worker> --name luna_worker --yes
hermes profile install <staging/codex-5-3-small-worker> \
  --name codex-5-3-small-worker --yes
```

`--yes` 只跳过 Hermes 的第二层确认；AgentPorter 在此前必须展示并确认集合级计划。非交互模式要求显式 `--yes`。

### 2.2 Profile 产物

```text
<HERMES_HOME>/profiles/luna_worker/
<HERMES_HOME>/profiles/codex-5-3-small-worker/
```

每个 Profile 安装：

- `distribution.yaml`：版本、来源和所有权；
- `config.yaml`：最小模型、provider 和 reasoning 配置；
- `SOUL.md`：职责与禁止事项；
- Profile description：由 AgentPorter 使用 `hermes profile describe --text` 设置并读回。

Profile description 不能只存在于 distribution manifest；必须验证 Hermes 路由实际读取的 description。

### 2.3 检测与版本

Adapter 不硬编码 `~/.hermes`：

- 优先尊重调用环境的 `HERMES_HOME`；
- 使用目标 Profile/Hermes CLI 的实际路径和版本；
- 执行真实 `hermes --version`、`hermes profile ... --help` 和配置校验；
- `distribution.yaml.hermes_requires` 只写入经过 CI 和真实安装验收的最低版本。

当前开发机 Hermes v0.20.0、schema v33 是设计取证基线，不自动等于最终最低支持版本。

### 2.4 模型与凭证

仓库中的模型是请求值，不是授权证明。

- 若 Worker 显式给出 provider，只写非秘密 provider ID；
- 若 provider 未指定，计划要求 `--provider` 或在安装后配置；
- 不从默认 Profile 复制 `config.yaml`、`.env`、`auth.json` 或私有 base URL；
- 不把当前开发机 `custom` Provider 当作公开默认值；
- 安装后无可用凭证时，状态是“Profile 已安装，运行配置待完成”，而不是失败伪装或静默模型替换；
- `--live-check` 才允许最小模型请求，并在执行前说明可能产生费用。

### 2.5 冲突与补偿回滚

默认规则：

- 任一目标 Profile 已存在，整组安装在写入前拒绝；
- 不使用 `hermes profile install --force`；
- 不修改 `default` Profile；
- 原生安装命令成功后立即记录“已确认创建”，后续读回成功后再记录“身份已验证”；
- 后续失败时只逆序删除身份已验证的本次新建 Profile；
- 已确认创建但读回失败的 Profile 不自动删除，进入“不确定残留”并令事务以“补偿不完整”退出；
- 删除前再次确认 Profile 的 distribution 名、来源/事务标记与目标名；
- 身份不一致时停止自动删除并报告人工处理，不猜测所有权。

临时 staging 会被删除，Hermes manifest 中记录的本地 source 随后不可用于原生 update。因此第一版只支持全新安装。未来的 `upgrade` 必须采用稳定 Git source 或重新渲染的独立升级事务；`repair`、`uninstall` 也各自拥有独立命令和验收面。

## 3. Hermes 调用与路由

### 直接调用

```text
hermes -p luna_worker chat -q "<完整任务 brief>"
```

### Kanban

```text
hermes kanban create "<任务标题>" \
  --assignee luna_worker \
  --workspace worktree \
  --body "<完整目标、范围、约束和验收>"
```

Kanban 可以按卡片覆盖模型和 provider，但这是任务级显式覆盖，不应反向修改 Profile 配置。

### delegate_task 限制

普通 `delegate_task` 有独立上下文和终端，但默认继承父模型或使用统一的 `delegation.*`。第一版不把它包装成按 Profile 选择器。若未来需要 `delegate_luna_worker` 一类工具，必须作为单独插件设计，并验证进程、工作区、取消和结果协议。

## 4. 可见性

- Profile 属于 Hermes 配置根，不属于某个 Git 仓库；
- 同配置根的普通目录和 Git worktree 无需重复安装；
- Profile 本身不构成 sandbox；需要隔离修改时使用 Kanban worktree、`hermes -w` 或明确 workspace；
- 远端只是本机 Hermes 的 SSH 终端后端时通常无需安装；
- 远端独立启动 Hermes、容器或不同 Hermes 根时必须分别安装。

## 5. Codex 接口保留

代码结构可保留 `PlatformAdapter` 协议和 `unsupported platform` 结果，但第一版：

- CLI 不公开 `--platform codex`；
- 不生成 Codex TOML；
- 不创建 `~/.codex`；
- 不把 Codex 纳入 CI、发布门禁或完成状态；
- 文档仅记录未来需要真实版本取证后另行设计。
