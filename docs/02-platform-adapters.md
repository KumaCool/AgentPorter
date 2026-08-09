# 平台 Adapter 方案

## 1. Adapter 接口

每个平台 Adapter 最终实现统一生命周期：

```text
detect → inspect → negotiate → render → diff → apply → validate → report
```

- `detect`：发现 CLI、版本和配置根；
- `inspect`：只读枚举已有配置和 Agent；
- `negotiate`：比较平台能力与 Worker 需求；
- `render`：生成平台原生文件到 staging；
- `diff`：展示目标变化；
- `apply`：只写托管文件/配置段；
- `validate`：调用当前版本原生命令或解析器；
- `report`：说明可见范围、兼容降级和是否需要复制。

## 2. Codex Adapter

### 目标映射

预期文件：

```text
~/.codex/agents/luna-worker.toml
~/.codex/agents/codex-5-3-small-worker.toml
```

预期角色文件采用当前 Codex 支持的字段语义：

```toml
model = "..."
model_reasoning_effort = "max"
developer_instructions = """..."""
```

Agent 的路由描述可能需要由主 `config.toml` 的 `[agents.<name>]` 表注册，并通过 `config_file` 指向角色 TOML。Adapter 必须根据**已安装 Codex 版本**检查当前发现/注册机制，不能只创建角色文件后就宣称可见。

### 非破坏规则

- 若 `~/.codex/config.toml` 已存在，只追加或更新 AgentPorter 管理的 `[agents.*]` 条目；
- 不覆盖其他 profile、provider、sandbox、MCP 或未知 Agent；
- 若当前版本支持目录自动发现，则仍需验证实际列表或启动结果；
- 若 CLI 未安装，输出 `unsupported: codex CLI not installed`，不猜测兼容性；
- 模型 ID 是否可用必须与 TOML 是否可解析分开报告。

### 可见性

用户级 `CODEX_HOME` 下的 Agent 通常对共享该配置根的本机 Codex 会话可见；项目级配置只在对应工作区生效。Adapter 必须读出实际 `CODEX_HOME`，不能永远假定为 `~/.codex`。另一台机器或独立容器拥有不同配置根，需要单独安装。

## 3. Hermes Adapter

### 推荐映射

Hermes 不使用 Codex Agent TOML。推荐把 Worker 映射成独立 Profile：

```text
~/.hermes/profiles/luna_worker/
~/.hermes/profiles/codex-5-3-small-worker/
```

每个 Profile 包含：

- `config.yaml`：模型、provider、reasoning 和允许的工具；
- `SOUL.md`：Worker instructions；
- Profile description：供 Kanban 路由和人工识别；
- 可选 skills：仅加载完成职责所需的最小技能。

`luna_worker` 的 Hermes Profile 名合法。Portable ID `codex_5_3_small_worker` 也合法，但为跨平台展示一致和可读性，Hermes 目标名建议映射为 `codex-5-3-small-worker`。

### 调用方式

临时显式调用：

```text
hermes -p luna_worker chat -q "<complete bounded task brief>"
```

持久任务路由：通过 Kanban 创建任务并指定 Profile assignee。普通 `delegate_task` 目前适合轻量隔离子任务，但其模型由父会话继承或全局 `delegation.model/provider` 统一覆盖，不能自然表达“每次调用按名称选不同 Profile”。

### 可见性

Profile 是用户级 Hermes 配置，不属于某个项目工作区。同一主机、同一 Hermes 配置根下的普通目录与 Git worktree 无需复制。若远端只作为 Hermes 的 SSH 命令后端，也不需要复制；只有远端独立启动 Hermes 时才需要安装 Profile。

## 4. 通用 Prompt-only Adapter

对于没有命名 Agent 或 Profile 的平台，生成：

```text
adapters/prompt-only/<worker-id>.md
```

内容包括 description、instructions、委派契约和模型建议。该模式只能帮助人工选择和粘贴 Prompt，不能宣称平台具备原生命名路由、模型隔离或全局可见性。

## 5. 后续平台

后续可按同一接口增加 Claude Code、OpenCode、Cursor、IDE Agent、MCP 驱动 Agent 或企业内部平台。每个 Adapter 都必须提交能力矩阵、原生验证器和至少一组非破坏合并测试，禁止只增加模板文件而没有检测与验证路径。
