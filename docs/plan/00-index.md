# AgentPorter 计划索引

本目录按产品依赖顺序维护 AgentPorter 的实施与验收计划。状态必须区分历史交付、当前产品主线和后置质量验证。

| 顺序 | 计划 | 状态 | 权威范围 |
|---|---|---|---|
| 01 | [安装基础实施记录](01-installation-foundation.md) | v0.1.0 已实现、验收并发布 | Worker Profile 集合安装、静态读回、有限补偿、独立卸载、打包与发布 |
| 02 | [多代理编排与路由实施计划](02-multi-agent-orchestration.md) | 方案已落地，代码与真实任务验收未开始 | 工作组部署、任务分解、按职责路由、dispatcher 接线、端到端任务主链 |
| 02A | [Worker Readiness 与编排闭环优化方案](02a-worker-readiness-orchestration-closure.md) | 方案已完成，尚未进入开发 | 基于实际安装使用反馈，闭合推理 readiness、凭据边界、派发收据、通知/结构性接续、运行证据、暂停恢复与文件所有权 |
| 03 | [Worker 验证与基准计划](03-agent-validation-and-benchmark.md) | 方案已确认，执行器与结果未实现；等待 Plan 02 与 Plan 02A | Worker 行为、质量、时延、资源、成本与稳定性统计评测 |

## 依赖关系

```text
Plan 01 安装基础（已完成）
    ↓
Plan 02 多代理编排与路由（当前产品主线）
    ↓
Plan 02A Worker Readiness 与编排闭环（当前方案补强）
    ↓
Plan 03 Worker 质量与性能基准（后置）
```

- Plan 01 的发布成功不证明任务会自动分解、正确路由或真实执行。
- Plan 02 的确定性端到端通过才证明产品主链已经接通，但不证明 Worker readiness、凭据最小化、通知/结构性接续和暂停恢复已闭环。
- Plan 02A 是本次实际安装使用反馈形成的补强方案；其完成只代表设计已落地到文档，不代表代码或真实模型验收已执行。
- Plan 03 只在 Plan 02 与 Plan 02A 关闭后运行；其统计结果不能补偿安装、readiness 或路由主链失败。
- 所有真实模型调用、可能产生费用的验收、gateway 服务变更、push 和发布仍需各自明确授权。
