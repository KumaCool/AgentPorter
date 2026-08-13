# AgentPorter 计划索引

本目录按产品依赖顺序维护 AgentPorter 的实施与验收计划。状态必须区分历史交付、当前产品主线和后置质量验证。

| 顺序 | 计划 | 状态 | 权威范围 |
|---|---|---|---|
| 01 | [安装基础实施记录](01-installation-foundation.md) | v0.1.3 已发布；卸载完整自清理修复已完成托管制品回读验收 | Worker Profile 集合安装、静态读回、有限补偿、独立完整卸载、打包与发布 |
| 02 | [多代理编排与路由实施计划](02-multi-agent-orchestration.md) | 方案已落地，代码与真实任务验收未开始 | 工作组部署、任务分解、按职责路由、dispatcher 接线、端到端任务主链 |
| 02A | [Worker Readiness 与编排闭环优化方案](02a-worker-readiness-orchestration-closure.md) | 纯领域 readiness/delegation 合同已实现；运行绑定、真实探针和编排运行时未实现 | 基于实际安装使用反馈，冻结推理 readiness、凭据边界、派发收据、通知/结构性接续、运行证据、暂停恢复与文件所有权 |
| 03 | [Worker 验证与基准计划](03-agent-validation-and-benchmark.md) | 方案已确认，执行器与结果未实现；等待 Plan 04 | Worker 行为、质量、时延、资源、成本与稳定性统计评测 |
| 04 | [Runtime Readiness 与编排闭环落地计划](04-runtime-readiness-closure-implementation.md) | Phase A-F 已完成本地 0.1.4 发布候选；Hermes v0.20 真实 probe 与 Kanban mutation 不受支持且零调用；未发布/未 push | 实现可重放运行绑定、安全 canary、专用 orchestrator、任务订阅读回、派发收据、运行观察与发布闭环 |

## 依赖关系

```text
Plan 01 安装基础（已完成）
    ↓
Plan 02 多代理编排与路由（当前产品主线）
    ↓
Plan 02A Worker Readiness 与编排闭环（纯领域合同已实现）
    ↓
Plan 04 Runtime Readiness 与编排闭环落地（当前执行主线）
    ↓
Plan 03 Worker 质量与性能基准（后置）
```

- Plan 01 的发布成功不证明任务会自动分解、正确路由或真实执行。
- Plan 02 的确定性端到端通过才证明产品主链已经接通，但不证明 Worker readiness、凭据最小化、通知/结构性接续和暂停恢复已闭环。
- Plan 02A 已交付纯领域 readiness/delegation 合同，但不证明运行绑定、真实 canary、任务订阅或编排运行时已经接通。
- Plan 04 是当前获批执行主线；完成前不得把 Worker 标为 operational，也不得把静态 `config check` 当作真实 readiness。
- Plan 03 只在 Plan 04 关闭后运行；其统计结果不能补偿安装、readiness 或路由主链失败。
- 离线开发、测试、复审、提交和既定阶段交付持续执行；真实模型调用、gateway 服务变更和发布仍需各自明确授权。
