# 安装与验证方案

> 本文命令是 AgentPorter 第一版目标接口；当前仓库尚未实现 CLI。

## 1. 用户流程

交互式安装：

```text
agentporter install hermes
```

自动化环境：

```text
agentporter install hermes --yes
```

可选运行验证：

```text
agentporter verify hermes --live-check
```

默认安装只做静态与路由验证，不执行模型请求。

## 2. 集合级安装流程

```text
只读发现 Hermes/版本/HERMES_HOME/现有 Profiles
→ 校验 workers.yaml 和稳定名称映射
→ 校验所有目标名均无冲突
→ 为每个 Worker 渲染独立 distribution staging
→ 解析 staging 并运行秘密/路径扫描
→ 展示完整集合计划和能力限制
→ 用户一次确认
→ 逐个调用 Hermes 原生 profile install
→ 设置并读回 Profile description
→ 对每个 Profile 做枚举、配置和字段读回
→ 输出集合报告
```

任何写入前必须完成所有可前置的失败检查，避免已知错误进入半安装状态。

## 3. 计划输出

安装前至少显示：

- Hermes 可执行文件和版本；
- 目标 Hermes 配置根；
- Worker → Profile 映射；
- 将创建的每个 Profile 和 distribution-owned 文件；
- provider、模型和凭证准备状态；
- 不会复制或修改的用户数据；
- 是否存在冲突；
- 默认静态验证与可选 live check 的区别；
- 失败时哪些新建 Profile 可自动补偿删除。

`--yes` 只接受已生成的同一计划，不得跳过预检、staging 校验、秘密扫描或验证。

## 4. Provider 与运行准备

第一版支持以下明确状态：

- **ready**：provider、模型字段和所需非秘密配置完整，凭证由目标 Hermes 环境提供；
- **configuration-required**：Profile 可安全安装，但用户仍需配置 provider、base URL 或凭证；
- **unsupported**：当前 Hermes 版本不支持所需配置或命令；
- **conflict**：目标 Profile 已存在；
- **invalid**：Worker 或生成 distribution 不满足 schema/安全规则。

`configuration-required` 不得被报告为运行有效。公开仓库不得为当前开发机写入 `custom` base URL 或 API key。

## 5. 验证矩阵

### 语义不变量与禁止副作用

| ID | 验收项 |
|---|---|
| INV-01 | 两个 Worker 均禁止改变整体目标和扩大范围 |
| INV-02 | mechanical Worker 的允许任务严格窄于 bounded Worker |
| INV-03 | 模型或 provider 不可用时不静默替换 |
| INV-04 | 默认遇到任一同名 Profile 时整组写入为零 |
| INV-05 | 不修改 default Profile 或任何预先存在的 Profile |
| INV-06 | 不复制或提交 `.env`、`auth.json`、API key、私有 base URL、记忆、会话、日志和状态库 |
| INV-07 | `SOUL.md` 不被描述或测试为 sandbox；代码隔离使用 workspace/worktree |
| INV-08 | 默认不发起真实模型调用或产生模型费用 |
| INV-09 | Codex 未实现路径不创建 `~/.codex`、不生成 TOML、不进入完成判定 |

### 输出与可观察性

| ID | 验收项 |
|---|---|
| OUT-01 | 一次计划列出 Hermes 路径、版本、配置根、全部 Profile、冲突和能力状态 |
| OUT-02 | 每个 Worker 的 distribution staging 和最终目标均可追踪 |
| OUT-03 | 报告分开显示 manifest、安装、静态配置、路由和运行五级状态 |
| OUT-04 | 补偿回滚逐项报告删除、保留、身份不一致和人工处理状态 |
| OUT-05 | `configuration-required` 给出非秘密的后续配置指引，不回显凭证 |

### 边界、兼容与交付

| ID | 验收项 |
|---|---|
| BND-01 | Hermes 未安装或版本不支持时只诊断，不写配置 |
| BND-02 | 尊重实际 `HERMES_HOME`，所有测试使用临时 Hermes 根 |
| BND-03 | 同配置根的不同目录/worktree 不重复安装 |
| BND-04 | 不同 Hermes 根和远端独立实例被视为独立目标 |
| BND-05 | 第二个 Profile 安装/验证失败时，只补偿删除本事务新建且身份匹配的 Profile |
| CMP-01 | 最低 Hermes 版本由 CI 夹具和真实 CLI 验收共同确定 |
| CMP-02 | 未知 manifest、CLI 或配置行为变化时 fail closed |
| CMP-03 | Profile 名使用 Hermes 原生校验与保留名规则 |
| DEL-01 | schema、单元、临时 HOME 集成、CLI 静态验证和文档链接检查通过 |
| DEL-02 | 构建包在干净环境完成 `install hermes --yes` 演练 |
| DEL-03 | 安装后 `hermes profile list/show/info`、description 和配置字段读回一致 |
| DEL-04 | staged/index 隐私扫描和构建产物内容检查通过 |

## 6. 补偿回滚

第一版仅支持全新安装的自动补偿：

1. 保存安装前 Profile 集合；
2. 原生安装命令成功后立即记入“已确认创建集合”；
3. 随后读取 manifest、目标名和本事务 staging 来源，完全匹配后才记入“允许自动删除集合”；
4. 若读回失败或身份不匹配，记入“不确定残留集合”，不自动删除；
5. 若后续步骤失败，只逆序删除“允许自动删除集合”；
6. 删除失败、身份变化或存在不确定残留时，以“补偿不完整”退出并报告人工处理路径；
7. 预先存在的 Profile 永不进入任何删除集合。

不能用“目录存在”作为所有权证明。

## 7. 运行验证

`--live-check` 是单独授权边界：

- 执行前列出将使用的 Profile、模型和 provider；
- 不展示凭证值；
- 对每个 Profile执行最小只读 Prompt；
- 分别记录成功、认证失败、模型无权、网络失败和响应超时；
- 一个 Worker 的失败不被另一个 Worker 的成功掩盖；
- live check 失败不自动删除静态安装成功的 Profile，除非用户明确要求全有或全无的运行验收模式。

## 8. 升级与卸载

第一版从临时本地 staging 安装，只交付全新安装。Hermes 会把本地 staging 路径记录为 source，而 staging 在事务后删除，因此这些 Profile 不能直接依赖 `hermes profile update`。

后续命令必须在稳定 Git source 或 AgentPorter 重新渲染升级事务设计完成后再公开：

```text
agentporter upgrade hermes
agentporter uninstall hermes
```

升级默认保留用户 `config.yaml`，但不能在临时 source 已失效时盲目调用原生 update；卸载必须依赖 AgentPorter 所有权记录和 Hermes distribution 身份，不能按名称猜测。
