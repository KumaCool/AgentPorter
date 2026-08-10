# 安装与验证方案

> 本文描述 AgentPorter 第一版的一次性安装体验；当前仓库尚未实现安装器。

## 1. 用户流程

用户启动 AgentPorter 安装器，查看一次集合级计划并确认。安装器完成两个 Hermes Profile 的安装和静态读回后退出。

第一版没有子命令、参数模式、静默安装、独立 verify 入口或后续管理界面。默认只做静态与路由验证，不执行模型请求。

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
- 默认且唯一的静态验证边界，以及“不会发起模型请求”的保证；
- 失败时哪些新建 Profile 可自动补偿删除。

确认动作只接受当前已生成的同一计划，不得跳过预检、staging 校验、秘密扫描或验证。

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
| CMP-01 | 最低 Hermes 版本由 CI 夹具和真实 Hermes 原生接口验收共同确定 |
| CMP-02 | 未知 manifest、Hermes 原生接口或配置行为变化时 fail closed |
| CMP-03 | Profile 名使用 Hermes 原生校验与保留名规则 |
| DEL-01 | schema、单元、临时 HOME 集成、Hermes 原生静态验证和文档链接检查通过 |
| DEL-02 | 安装产物在干净环境完成一次启动、确认、安装和退出演练 |
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

## 7. 运行验证边界

第一版不提供运行验证，也不发起任何模型请求。测试必须对模型调用路径设置调用即失败 guard，证明安装、静态读回和失败补偿均不触达模型。真实模型验证若有需要，由用户在安装完成后通过 Hermes 原生能力自行执行，不属于 AgentPorter。

## 8. 安装后的职责边界

AgentPorter 理论上只使用一次：完成全新安装后退出，不维护常驻状态，也不提供升级、修复或卸载入口。

Hermes 会把本地 staging 路径记录为 source，而 staging 在安装后删除，因此这些 Profile 不能直接依赖该 source 执行 `hermes profile update`。后续管理由 Hermes 原生 Profile 能力和用户承担；AgentPorter 不按名称猜测所有权，也不承诺后续生命周期操作。
