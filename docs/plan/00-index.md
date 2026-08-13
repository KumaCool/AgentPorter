# AgentPorter 计划索引

本目录按产品依赖顺序维护 AgentPorter 的实施与验收计划。状态必须区分历史交付、当前产品主线和后置质量验证。

| 顺序 | 计划 | 状态 | 权威范围 |
|---|---|---|---|
| 01 | [安装基础实施记录](01-installation-foundation.md) | v0.1.3 已发布；卸载完整自清理修复已完成托管制品回读验收 | Worker Profile 集合安装、静态读回、有限补偿、独立完整卸载、打包与发布 |
| 02 | [多代理编排与路由实施计划](02-multi-agent-orchestration.md) | Phase A–F 离线实现完成；live 任务验收未执行 | 工作组部署、任务分解、按职责路由、dispatcher 接线、端到端任务主链 |
| 02A | [Worker Readiness 与编排闭环优化方案](02a-worker-readiness-orchestration-closure.md) | Phase A–F 离线实现完成；live probe 与 Kanban 不受支持 | 基于实际安装使用反馈，冻结推理 readiness、凭据边界、派发收据、通知/结构性接续、运行证据、暂停恢复与文件所有权 |
| 03 | [Worker 验证与基准计划](03-agent-validation-and-benchmark.md) | 仍因 live blocker 等待：v0.20 probe/Kanban unsupported | Worker 行为、质量、时延、资源、成本与稳定性统计评测 |
| 04 | [Runtime Readiness 与编排闭环落地计划](04-runtime-readiness-closure-implementation.md) | Phase A-F 离线实现完成，形成未发布、未打标签的 0.1.4 发布候选；Hermes v0.20 真实 probe 与 Kanban mutation 不受支持且零调用；未发布、未打标签 | 实现可重放运行绑定、安全 canary、专用 orchestrator、任务订阅读回、派发收据、运行观察与发布闭环 |

## 依赖关系

```text
Plan 01 安装基础（已完成）
    ↓
Plan 02 多代理编排与路由（Phase A–F 离线实现完成）
    ↓
Plan 02A Worker Readiness 与编排闭环（Phase A–F 离线实现完成）
    ↓
Plan 04 Runtime Readiness 与编排闭环落地（离线实现完成，live blocked）
    ↓
Plan 03 Worker 质量与性能基准（后置）
```

- Plan 01 的发布成功不证明任务会自动分解、正确路由或真实执行。
- Plan 02 的确定性端到端通过才证明产品主链已经接通，但不证明 Worker readiness、凭据最小化、通知/结构性接续和暂停恢复已闭环。
- Plan 02A/04 已交付运行绑定、probe、派发、订阅、观察与 orchestrator integration 的离线合同；这不证明真实 canary、Gateway 或 live routing 已接通。
- Plan 04 的 Phase A–F 离线实现已完成；Worker 仍不得标为 operational，静态 `config check` 也不是真实 readiness。
- Plan 03 只在 Plan 04 关闭后运行；其统计结果不能补偿安装、readiness 或路由主链失败。
- 离线开发、测试、复审、提交和既定阶段交付持续执行；真实模型调用、gateway 服务变更和发布仍需各自明确授权。
