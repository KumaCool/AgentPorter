# AgentPorter 方案总览

## 1. 当前产品定位

AgentPorter 第一阶段是 **Hermes Worker Profile 一键安装器**。

产品只有一个启动入口，没有子命令、平台参数或长期运行模式。用户启动一次，即安装仓库中声明的完整 Worker 集合。第一版包含：

- `luna_worker`：目标、范围、约束和验收已冻结后的有界补全型 Worker；
- `codex-5-3-small-worker`：严格比 Luna 更简单、更机械的 Worker。

当前仓库只有设计和 Worker 清单，尚无可运行安装器或已安装产物。

## 2. 架构决策

### 2.1 Hermes 原生能力是运行基础设施

AgentPorter 不自研 Profile 存储、Git 分发、任务队列或 worktree 管理，而是组合 Hermes 原生能力：

```text
workers.yaml
    ↓ 语义校验、名称映射、能力预检
AgentPorter Hermes Adapter
    ↓ 渲染到临时 staging
Hermes Profile distributions
    ↓ hermes profile install
独立 Profile + description + config.yaml + SOUL.md
    ↓
直接调用或 Kanban assignee/worktree
```

每个 Worker 对应一个独立 Hermes Profile；Profile 是独立 Hermes Home，而不是提示词文件或项目目录。

### 2.2 一次性安装的边界

“一次性”表示用户只启动一次 AgentPorter，安装器完成整个 Worker 集的预检、确认、安装、读回和失败收口，然后退出。AgentPorter 不提供命令体系，不驻留后台，也不承担后续升级、修复、卸载或任务调度。

它不表示：

- 静默覆盖同名 Profile；
- 从默认 Profile 或仓库复制 `.env`、`auth.json`、API key、会话或记忆；
- 自动发起付费模型调用；
- 在模型未授权时声称运行有效；
- 自动安装、配置或验证 Codex。

### 2.3 安装集合一致性

Hermes 原生 distribution 每次安装一个 Profile。AgentPorter 负责在一次安装运行中编排两个 distribution：

1. 在任何写入前完成全部 Worker、名称、版本、目标冲突和 staging 校验；
2. 默认发现同名 Profile 即 fail closed，不调用 `--force`；
3. 安装命令成功后立即把目标记入“已确认创建集合”，不等待后续读回；
4. 只有 distribution 名、目标名和本事务 staging 来源均读回一致的 Profile 才进入“允许自动删除集合”；
5. 后续失败时只删除“允许自动删除集合”；已确认创建但身份无法读回的 Profile 进入“不确定残留集合”，明确要求人工处理；
6. 预先存在的 Profile、用户数据和默认 Profile始终不进入自动回滚集合。

这不是跨进程强事务。第一版只承诺对身份可证明的本次新建 Profile 做补偿；任何创建结果或身份不确定状态都必须以“补偿不完整”失败退出，不能宣称整组已回滚。

## 3. 权威语义与派生产物

`workers.yaml` 是 Worker 职责、层级、模型偏好和指令的权威输入。Hermes 产物是派生物：

| Portable 字段 | Hermes 产物 |
|---|---|
| Worker ID | Profile 名称（经稳定映射） |
| `description` | Profile description，供 Kanban 路由和人工识别 |
| `instructions` | `SOUL.md` |
| `model` | `config.yaml → model.default` |
| `provider`（若显式配置） | `config.yaml → model.provider` |
| `reasoning_effort` | `config.yaml → agent.reasoning_effort` |

模型字段表达请求，不证明安装机账号有使用权。静态安装成功与真实模型调用成功必须分开报告。

## 4. 首批 Worker 不变量

1. Worker 不得改变主任务目标；
2. Worker 不得自行扩大文件、模块、系统或部署范围；
3. `codex_5_3_small_worker` 的任务必须严格简单于 `luna_worker`；
4. 缺少目标、范围、约束或验收信息时，必须报告阻塞；
5. 指定模型不可用时不得静默替换；
6. `SOUL.md` 只提供行为约束，不被描述为文件系统安全边界；真正的代码隔离由 Kanban worktree、`hermes -w` 或明确 workspace 提供。

## 5. 调度模型

### 稳定 Worker 路由

首选 Hermes Profile + Kanban：

```text
hermes kanban create "<title>" \
  --assignee luna_worker \
  --workspace worktree \
  --body "<完整目标、范围、约束和验收>"
```

Kanban 可按 Profile description 路由，并提供 scratch、目录或 worktree 工作区。

### 直接调用

```text
hermes -p luna_worker chat -q "<边界完整的任务>"
```

### 临时子任务

普通 `delegate_task` 是父会话内的轻量隔离机制，默认继承父模型或统一使用 `delegation.*`。它不能替代按名称选择独立 Profile 的稳定 Worker 路由。

## 6. 可见性和分发

- 同一用户、同一 `HERMES_HOME` 根下的不同项目目录或 Git worktree：无需重复安装；
- SSH 仅作为本机 Hermes 的终端后端：通常无需在远端安装 Profile；
- 不同用户、不同 Hermes 根、容器或远端独立 Hermes：是独立实例，需要单独执行安装；
- `hermes profile export/import` 用于本地备份恢复；
- Git Profile distribution 适合从稳定 Git source 安装和更新；第一版 AgentPorter 使用临时本地 staging，只承诺全新安装，不承诺安装后的原生 `profile update`。

## 7. Codex 保留边界

Codex 仅保留 `PlatformAdapter` 接口位置和未来研究记录，不进入第一版实现、安装入口、发布门禁或完成状态。

未来启用 Codex 前必须取得：

- 明确支持的真实 Codex CLI 版本；
- Agent 注册与发现机制证据；
- 配置字段和原生校验命令；
- 临时 HOME 中的非破坏安装、发现、运行和回滚测试。

在这些证据存在前，不生成猜测性 TOML，不宣称兼容。
