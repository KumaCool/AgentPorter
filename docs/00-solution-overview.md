# AgentPorter 方案总览

## 1. 产品定位

AgentPorter 当前产品是 **Hermes Worker Profile 一次性安装器**，另附独立 `uninstall.py` 作为受保护清理入口。

- 主安装器启动一次，完成预检、计划、确认、安装、静态读回、有限失败补偿并退出；
- 不提供子命令、平台参数、静默安装、后台服务、升级、修复或任务调度；
- 卸载脚本不是管理界面，不改变主安装器的一次性产品形态；
- 当前 Phase 1 已实现领域模型、Hermes 环境只读检测、纯 staging 渲染与安全扫描，并已在临时 `HOME`/`HERMES_HOME` 中通过 Hermes v0.20 原生安装契约探针；正式安装事务、独立卸载行为、完整真实验收和发布仍未实现。

第一版安装两个 Profile：

- `luna_worker`：在目标、范围、约束和验收均已冻结时执行有界实现或分析；
- `codex-5-3-small-worker`：只执行严格更简单、更机械的工作。

## 2. 架构

```text
workers.yaml
    ↓ schema / 语义 / 能力预检
AgentPorter Hermes Adapter
    ↓ 两个临时 Profile distributions
Hermes 原生 profile install
    ↓
独立 Profile：config.yaml + SOUL.md + description + 安装标记
    ↓
直接调用或 Kanban assignee / worktree
```

AgentPorter 组合 Hermes 原生 Profile、distribution、description、Kanban 和 worktree，不自研 Profile 存储、任务队列或工作区隔离。

同一用户、同一 `HERMES_HOME` 下的普通目录和 Git worktree 共享 Profile，无需重复安装。不同用户、容器、Hermes 根或远端独立 Hermes 实例是不同安装目标。

## 3. 权威输入与产物

`workers.yaml` 是 Worker 语义的权威输入，并由 Hermes Adapter 派生为两个 Profile。字段 schema 和 artifact 规则见 [Worker 规范](01-portable-worker-spec.md)，Hermes 映射与读回见 [Hermes Adapter](02-platform-adapters.md)。模型/provider 字段只表达请求，不证明账号授权；第一版不发起模型请求。

## 4. 核心决策

1. 任一目标初始名已存在，安装整组零写入；不使用 `--force`，不修改 `default`。
2. 不复制凭证、会话、记忆、日志、私有 base URL 或默认 Profile 配置。
3. 安装与卸载共享名称无关的本地标记协议；用户可批量重命名 Profile，但名称永不建立所有权。
4. 安装只做有限、证据约束的失败补偿；独立卸载必须先消除歧义、警告并确认。完整算法只在 [安装、卸载与验收设计](03-installation-and-uninstall-design.md) 定义。
5. Hermes v0.20 原生删除按名称执行，不提供原子条件删除；产品必须如实报告残余竞态。
6. 临时 staging source 失效后不承诺原生 update；升级和修复不属于 AgentPorter。
7. “Codex 延后”只指 Codex CLI/平台 Adapter，不影响 Hermes Profile `codex-5-3-small-worker` 对模型 ID 的请求。

## 5. Worker 与调度边界

Worker tier、委派输入和行为不变量由 [Worker 规范](01-portable-worker-spec.md) 定义；Hermes Profile、Kanban、worktree 和直接调用的映射由 [Hermes Adapter](02-platform-adapters.md) 定义。总览不重复其字段或命令。

Plan 01 的安装与卸载交付始终零模型调用；安装后的真实 Worker 行为与性能只由独立 [Worker 验证与基准计划](plan/02-agent-validation-and-benchmark.md) 在显式授权、隔离环境和独立结果状态下评测，不构成产品子命令或安装成功条件。

## 6. 文档导航

- [可移植 Worker 规范](01-portable-worker-spec.md)：`workers.yaml` 与派生文件格式；
- [Hermes Adapter 方案](02-platform-adapters.md)：Hermes 原生能力映射和调用边界；
- [安装、卸载与验收设计](03-installation-and-uninstall-design.md)：安装事务、身份、卸载和验收的唯一权威设计；
- [实施计划](plan/01-implementation-plan.md)：安装器、卸载器、测试和发布的阶段顺序；
- [Worker 验证与基准计划](plan/02-agent-validation-and-benchmark.md)：安装完成后的独立代理行为、性能、成本和稳定性评测。
