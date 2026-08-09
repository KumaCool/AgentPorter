# AgentPorter 实施计划

## 状态

- **设计：** 已落地，待复审；
- **代码：** 未实现；
- **平台真实验证：** 未执行；
- **发布：** 未开始。

## Phase 1：Schema 与核心渲染

### 交付

- `workers.yaml` JSON Schema；
- Python 包和 `agentporter` CLI 骨架；
- Worker 语义校验；
- portable ID 与平台 ID 稳定映射；
- staging、unified diff 和管理清单；
- `doctor`、`plan`、`where` 的只读实现。

### 验收

- 非法 tier、reasoning、ID 或空 instructions 被拒绝；
- Small Worker 比 Luna Worker 更窄的规则由静态策略测试锁定；
- `plan` 不写用户配置；
- 所有测试使用临时 HOME。

## Phase 2：Codex Adapter

### 前置证据

- 安装受支持的 Codex 版本；
- 读取该版本 `--help` 和配置 schema/源码；
- 确认 Agent 发现或 `[agents.*]` 注册机制；
- 确认角色文件 instruction 字段名。

### 交付

- detect/inspect/capability negotiation；
- 两个角色 TOML 的渲染；
- 主配置的结构化、非破坏注册；
- 当前版本原生静态验证；
- 可选 live check；
- rollback/uninstall。

### 验收

- 预置未知 Codex 配置在 apply 后保持不变；
- 两个 Worker 均被当前 CLI 实际发现；
- 错误模型与错误 TOML 分开报告；
- 验证失败自动恢复。

## Phase 3：Hermes Adapter

### 交付

- Profile detect/inspect；
- Profile config、description 和 `SOUL.md` 渲染；
- `hermes config check` 与 Profile 枚举验证；
- Kanban assignee 示例和显式调用封装；
- Profile export/import 或 distribution 打包。

### 验收

- 不修改 default Profile 的无关配置；
- 两个 Worker Profile 在任意同配置根工作区可见；
- 每个 Profile 的模型、provider、reasoning 和职责读回一致；
- 明确报告普通 `delegate_task` 的按 Profile 选择限制。

## Phase 4：迁移与 Prompt-only Adapter

### 交付

- Prompt-only Markdown 输出；
- 本机其它 HOME/容器实例检测；
- 显式 SSH target 支持；
- 远端 dry-run、apply、verify 和 rollback；
- 跨平台迁移报告。

### 验收

- 不扫描或写入未声明主机；
- 不复制凭证；
- 远端按远端版本验证；
- 同机 worktree 不被误判为远端实例。

## Phase 5：产品化

### 交付

- 安装包、版本策略和变更日志；
- 干净 HOME 端到端测试；
- Linux/macOS/Windows CI；
- Codex/Hermes 版本兼容矩阵；
- 示例自定义 Worker；
- 发布前复核现有 `LICENSE`、`CONTRIBUTING.md` 与 `SECURITY.md`，并为首个可执行版本补齐版本支持范围和真实私密漏洞报告渠道。

### 完整门禁

1. schema 和策略测试；
2. Adapter 单元测试；
3. 临时 HOME 集成测试；
4. 非破坏 diff 与 rollback 测试；
5. 平台 CLI 静态验证；
6. Markdown 相对链接检查；
7. 隐私与密钥扫描；
8. 包构建和干净环境安装测试。

## 关键风险

- 平台私有或实验性配置格式变化；
- 模型 ID 存在但账号无权限；
- 平台格式化器重写用户配置，造成无关 diff；
- 多个工具同时管理同一 Agent 条目；
- 远程配置根、HOME 或平台版本与本机不同。

处理原则：版本检测、结构化合并、显式所有权、fail closed、快照回滚、静态与运行验证分离。
