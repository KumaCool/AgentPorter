# 可移植 Worker 规范

## 1. 权威文件

仓库根目录 `workers.yaml` 是第一版 Worker 集的权威输入：

```yaml
version: 1
project: agentporter
workers:
  <portable_id>:
    display_name: <human-readable name>
    tier: bounded | mechanical
    model: <requested model id>
    provider: <optional provider id>
    reasoning_effort: none | minimal | low | medium | high | xhigh | max | ultra
    description: <routing description>
    instructions: <strict worker instructions>
```

`provider` 可省略；省略时安装计划必须明确要求用户选择、沿用已验证环境配置或在安装后配置，不能猜测 Provider。仓库不得携带 API key、私有 base URL 或账号配置。

## 2. 标识符与 Hermes 映射

Portable ID 使用：

```text
^[a-z][a-z0-9_]{0,63}$
```

Hermes Profile 名必须满足当前 Hermes 原生约束：

```text
[a-z0-9][a-z0-9_-]{0,63}
```

同时拒绝当前 Hermes 保留名。第一版稳定映射：

| Portable ID | Hermes Profile |
|---|---|
| `luna_worker` | `luna_worker` |
| `codex_5_3_small_worker` | `codex-5-3-small-worker` |

映射必须进入本次安装计划和事务内所有权记录。失败补偿只能作用于本次安装事务确认创建且身份匹配的 Profile；记录随安装结束报告输出，不构成长期管理状态。

## 3. Tier 语义

### `bounded`

- 主代理已经冻结目标、范围、约束和验收要求；
- Worker 可以在边界内实现、验证或分析；
- 不允许重设目标、扩展文件集或引入邻近工作。

### `mechanical`

- 步骤、路径、筛选条件或变换规则必须明确；
- 只允许低判断量、低风险、机械可验的工作；
- 需要架构、产品或多方案权衡时必须退回；
- 任务复杂度必须严格低于 `bounded` Worker。

## 4. 委派契约

委派至少包含：

```yaml
goal: 单一目标
scope:
  files: [允许读取或修改的路径]
  operations: [允许执行的操作]
constraints: [禁止事项]
acceptance: [完成判据与验证命令]
output: [返回格式]
```

边界不完整时 Worker 必须阻塞，而不是自行扩大范围。

## 5. Hermes 派生规则

每个 Worker 渲染为独立 distribution staging：

```text
<staging>/<profile-name>/
├── distribution.yaml
├── config.yaml
└── SOUL.md
```

第一版不捆绑 cron、MCP 或额外 skills，避免扩大权限和更新面。

### `distribution.yaml`

至少包含：

- 稳定 Profile 名；
- AgentPorter distribution 版本；
- 路由描述；
- 经真实验证的最低 Hermes 版本；
- MIT 许可证声明；
- 显式 `distribution_owned`，第一版只允许 `SOUL.md` 与 `config.yaml`。

### `config.yaml`

只包含实现 Worker 所需的最小非秘密字段：

- `model.default`；
- 可选 `model.provider`；
- `agent.reasoning_effort`；
- 后续经批准的最小工具配置。

不得渲染 API key、token、私有 base URL、个人路径、默认工作目录、网关凭证或默认 Profile 的无关配置。

### `SOUL.md`

必须完整保留：

- Worker 的允许职责；
- 不改变目标；
- 不扩大范围；
- 缺信息即阻塞；
- 不用虚构结果替代真实执行；
- `mechanical` Worker 的更窄复杂度边界。

`SOUL.md` 是行为指令，不是文件系统隔离机制。

## 6. 有效性分层

安装报告必须区分：

1. **Manifest 有效：** AgentPorter schema 与 Hermes distribution manifest 可解析；
2. **Profile 已安装：** Hermes 原生安装成功，Profile 可枚举；
3. **配置静态有效：** 指定 Profile 下的 Hermes 配置检查通过，模型/provider 字段读回一致；
4. **路由有效：** Profile description 可读回，Kanban 可识别 assignee；
5. **运行有效：** 显式授权的最小真实模型调用成功。

前四项不能替代第五项。默认安装不执行第五项。

## 7. 所有权与更新

- 默认遇到同名 Profile 即拒绝，不覆盖；
- 第一版安装不使用原生 `--force`；
- 用户的 `.env`、`auth.json`、记忆、会话、状态库和日志不属于 AgentPorter；
- 第一版从临时本地 staging 安装，因此只承诺全新安装；临时 source 删除后不能依赖原生 `profile update`；
- 安装后的升级、修复和卸载不属于 AgentPorter；后续管理由 Hermes 原生 Profile 能力和用户承担。
