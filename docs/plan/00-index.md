# AgentPorter 计划索引

本目录按产品依赖顺序维护 AgentPorter 的实施与验收计划。状态必须区分历史交付、当前产品主线和后置质量验证。

| 顺序 | 计划 | 状态 | 权威范围 |
|---|---|---|---|
| 01 | [安装基础实施记录](01-installation-foundation.md) | v0.1.3 已发布；卸载完整自清理修复已完成托管制品回读验收 | Worker Profile 集合安装、静态读回、有限补偿、独立完整卸载、打包与发布 |
| 02 | [多代理编排与路由实施计划](02-multi-agent-orchestration.md) | Phase A–F 离线实现完成；live 任务验收未执行 | 工作组部署、任务分解、按职责路由、dispatcher 接线、端到端任务主链 |
| 02A | [Worker Readiness 与编排闭环优化方案](02a-worker-readiness-orchestration-closure.md) | Phase A–F 离线实现完成；live probe 与 Kanban 不受支持 | 基于实际安装使用反馈，冻结推理 readiness、凭据边界、派发收据、通知/结构性接续、运行证据、暂停恢复与文件所有权 |
| 03 | [Worker 验证与基准计划](03-agent-validation-and-benchmark.md) | 等待 Plan 06 完成职责型身份与显式推理绑定；Kanban live 仍受阻 | Worker 行为、质量、时延、资源、成本与稳定性统计评测 |
| 04 | [Runtime Readiness 与编排闭环落地计划](04-runtime-readiness-closure-implementation.md) | Phase A–F 离线实现已随 0.1.4 正式发布；真实 probe 与 Kanban mutation 仍未验收 | 0.1.4 的可重放绑定、fail-closed probe、专用 orchestrator、派发收据与运行观察历史闭环 |
| 05 | [0.1.5 运行激活与真实调用闭环计划](05-runtime-activation-and-live-call-closure.md) | Phase A–F 离线实现完成；真实模型验收待单独授权 | 发布三公共入口、0.1.4 软件升级、Hermes 原生凭据接续、真实 one-shot 与分层 readiness |
| 06 | [职责型 Worker 身份与自定义推理绑定计划](06-role-identities-and-configurable-model-binding.md) | 离线代码候选与代码/离线门禁已闭合；唯一复审结果待主代理写入；未发布 | 用职责型名称替代模型语义名称，保持 component UUID/职责不变，并让三个 Profile 的 model/provider/endpoint 由用户显式配置 |

## 依赖关系

```text
Plan 01 安装基础（已完成）
    ↓
Plan 02 多代理编排与路由（Phase A–F 离线实现完成）
    ↓
Plan 02A Worker Readiness 与编排闭环（Phase A–F 离线实现完成）
    ↓
Plan 04 Runtime Readiness 与编排闭环落地（0.1.4 已发布，live blocked）
    ↓
Plan 05 运行激活与真实调用闭环（0.1.5–0.1.8 已交付的运行绑定基础）
    ↓
Plan 06 职责型身份与自定义推理绑定（离线候选已实现，待复审结果/发布授权）
    ↓
Plan 03 Worker 质量与性能基准（后置）
```

- Plan 01 的发布成功不证明任务会自动分解、正确路由或真实执行。
- Plan 02 的确定性端到端通过才证明产品主链已经接通，但不证明 Worker readiness、凭据最小化、通知/结构性接续和暂停恢复已闭环。
- Plan 02A/04 已交付运行绑定、probe、派发、订阅、观察与 orchestrator integration 的离线合同；这不证明真实 canary、Gateway 或 live routing 已接通。
- Plan 04 的 Phase A–F 离线合同已随 0.1.4 发布；实际安装证明公共 activation 链路和真实调用仍未闭合。
- Plan 05 已形成 0.1.5–0.1.8 的运行激活基础：只修改 AgentPorter；认证/one-shot 使用 Hermes 公共 CLI，binding 使用 AgentPorter 受控配置事务；不修改或 import Hermes 源码。
- Plan 06 是下一功能版本的已批准设计与实施权威：永久 component UUID 和三个职责保持不变；当前模型语义名称迁移为 `bounded_worker` / `mechanical_worker` 及对应职责型 Profile 名；三个 Profile 的 model/provider/endpoint 改为用户显式绑定。当前候选已实现这些目标：fresh install 使用职责名，三个 Profile 在 staging 前显式封闭绑定；旧默认名经 `agentporter-activate` 独立确认的 Hermes-native journaled rename 迁移，用户改名保留，绑定变化使 readiness 失效。
- Hermes v0.20 缺少 tool/fallback 遥测时，成功结果必须为 `live-call-passed + route-proof-incomplete`，默认仍阻止自动 Kanban 派发。
- Plan 03 只在 Plan 06 完成职责型身份、显式推理绑定和当前绑定 readiness 后运行；其统计结果不能补偿安装、迁移、readiness 或路由主链失败。
- 离线开发、测试、复审、提交和既定阶段交付持续执行；真实模型调用、Gateway 服务变更、Kanban mutation和发布仍需各自明确授权。

## 0.1.7 runtime-activation release candidate

Plan 05 is amended for Hermes v0.20 custom providers: skip unsupported bare-provider auth, inherit the exact main/default Profile provider definition transactionally from either the current keyed `providers` schema or compatible `custom_providers` schema, and chain activation immediately after installation. Offline implementation is complete; live credentialed canary remains separately authorized and unperformed.

## 下一功能版本：职责型身份与可配置模型

[Plan 06](06-role-identities-and-configurable-model-binding.md) 已形成完成的离线代码候选。新设计以固定 component UUID 作为跨版本身份，将旧默认名称安全迁移到职责型名称，同时保留用户自定义 Profile 名；model/provider/endpoint 成为三个 Profile 各自的显式运行绑定，任何变化都必须使旧 readiness 失效并重新通过精确 canary。设计权威见[职责型 Worker 身份与自定义推理绑定设计](../06-role-identities-and-configurable-model-binding-design.md)。
