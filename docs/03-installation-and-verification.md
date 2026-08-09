# 安装、迁移与验证方案

> 本文命令是 AgentPorter 的目标 CLI 设计；当前版本尚未实现 CLI。

## 1. 傻瓜式流程

用户最终只需执行：

```text
agentporter doctor
agentporter plan --platform codex --scope user
agentporter apply --platform codex --scope user
agentporter verify --platform codex --scope user
```

`plan` 必须先输出：

- 检测到的平台和版本；
- 实际配置根；
- 已有 Agent；
- 将创建、修改和保持不变的内容；
- 能力差异与无法满足的字段；
- 完整 diff；
- 是否需要 live check。

默认 `apply` 在交互终端要求确认；CI 中使用 `--yes`，但仍不得跳过快照和静态验证。

## 2. 安装事务

```text
只读发现
→ staging 生成
→ 语法校验
→ diff/确认
→ 快照受影响文件
→ 原子替换托管文件
→ 平台原生验证
→ 成功清单
```

若最后两步失败：

```text
恢复快照 → 再次解析验证 → 报告失败和恢复结果
```

不能用“已经写入文件”代替“配置有效”。

## 3. Diff 规则

- 新文件使用 unified diff 展示；
- 已有文件只展示 AgentPorter 管理块变化；
- secret/token/value-like 字段在输出中脱敏；
- 无关配置必须是零变化；
- `--check` 在存在未应用变化时返回非零，便于 CI 检查漂移。

## 4. 验证矩阵

### 语义不变量与禁止副作用

| ID | 验收项 |
|---|---|
| INV-01 | 两个 Worker 均禁止修改整体任务目标和扩大范围 |
| INV-02 | Small Worker 的允许任务严格窄于 Luna Worker |
| INV-03 | 模型不可用时不静默替换 |
| INV-04 | 已有无关 Agent 和配置字节级保持不变，除非格式化器是平台强制行为 |
| INV-05 | 不向未授权远程主机复制配置 |
| INV-06 | 卸载不删除非 AgentPorter 托管内容 |

### 输出与可观察性

| ID | 验收项 |
|---|---|
| OUT-01 | `plan` 显示版本、配置根、能力报告和 diff |
| OUT-02 | `apply` 记录快照与安装清单 |
| OUT-03 | `verify` 分开报告静态有效和运行有效 |
| OUT-04 | `where` 说明 Worker 对哪些本机工作区/Agent 实例可见 |

### 边界、兼容与交付

| ID | 验收项 |
|---|---|
| BND-01 | 未安装平台 CLI 时只生成明确诊断，不修改配置 |
| BND-02 | 自定义配置根环境变量得到尊重 |
| BND-03 | 同机 worktree 不重复安装 |
| BND-04 | 独立远程 Agent 实例被识别为单独目标 |
| CMP-01 | 支持的最低平台版本有固定测试夹具 |
| CMP-02 | 平台新版本未知字段或机制变化时 fail closed |
| DEL-01 | 格式、单元、集成和文档链接检查通过 |
| DEL-02 | 发布包可在干净临时 HOME 中完成 plan/apply/verify/rollback 演练 |

## 5. 本机与其它工作区判断

目标命令：

```text
agentporter where --platform codex
agentporter where --platform hermes
```

输出必须基于实际配置根和运行方式判断：

- **同用户、同配置根：** 所有项目目录和 Git worktree 通常可见，无需复制；
- **同主机、不同 HOME/容器卷：** 视为不同实例，需要安装；
- **SSH 仅执行命令：** 若 Agent 在本机运行，不复制；
- **远端独立运行 Agent：** 需要在远端目标上单独 plan/apply；
- **共享网络 HOME：** 可共享，但应提示并发写和版本差异风险。

## 6. 远程迁移

第一版不自动扫描网络。用户显式声明目标：

```text
agentporter plan --platform hermes --target ssh://host --scope user
```

安全要求：

- 先在远端只读 detect/inspect；
- 不复制认证文件、token 或整份 HOME；
- 只传输生成配置与 AgentPorter 清单；
- 在远端使用其平台版本重新生成或至少重新验证；
- 不把本机绝对路径写入远端配置；
- 远端失败不影响本机安装。
