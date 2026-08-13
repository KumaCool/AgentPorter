# AgentPorter 运行激活与真实调用闭环设计

**状态：** 0.1.5 离线实现与安全 Hermes CLI 组合验收已完成；真实模型调用待单独授权
**目标版本：** 0.1.5
**依赖：** 已发布的 AgentPorter 0.1.4、Hermes Agent v0.20 公共 CLI
**实施计划：** [Plan 05](plan/05-runtime-activation-and-live-call-closure.md)

## 1. 目标与职责边界

AgentPorter 必须通过自身的安装、激活和自动配置流程，让两个 Worker 获得实际可用的推理连接。不得把修改、fork 或 patch Hermes 源码作为解决路径。

AgentPorter 只依赖目标 Hermes 的公开产品合同：

- Profile 安装、枚举和配置文件格式；
- Profile-scoped `auth add/status`；
- `-z/--oneshot`、显式 model/provider、`--usage-file`；
- Profile-local 配置、凭据和状态隔离。

这里的“公开合同”不等于所有写入都必须通过 Hermes CLI。Hermes v0.20 的 `config set KEY VALUE` 会把私有 endpoint 放入 argv，因此0.1.5继续使用 AgentPorter已有的 descriptor-bound、`O_NOFOLLOW`、compare-before-write配置事务，直接更新目标 Profile 的公开 `config.yaml` schema。该 writer 是 **AgentPorter兼容适配层**，不是“Hermes原生配置 seam”，也不得 import Hermes内部模块。凭据认证和真实调用仍只使用 Hermes公共 CLI。

若 Hermes 公共接口不能证明某项强语义，AgentPorter必须明确降级，而不是伪造证明，也不能因此放弃能够完成的真实配置和调用验收。

本设计解决以下现有问题：

1. 0.1.4 只安装静态 Profile，两个 Worker 缺少 `model.provider`、`model.base_url` 和已授权凭据；
2. `hermes config check=0` 被误读为 Worker 可用；
3. `agentporter-activate` 只存在于私有虚拟环境，没有公共命令入口；
4. 激活入口固定返回 `probe-unsupported`，不会执行真实模型调用；
5. 安装成功、绑定完成、凭据可用、真实调用成功和可派发状态没有形成可执行接续。

## 2. 当前证据

### 2.1 AgentPorter 0.1.4

- 三个 Profile 已成功安装：两个 Worker 和一个专用 orchestrator；
- 两个 Worker 只有静态 model 与 reasoning 配置；
- bootstrap 私有环境包含 `agentporter`、`agentporter-activate`、`agentporter-uninstall` 三个 entry point；
- `${XDG_BIN_HOME:-$HOME/.local/bin}` 只发布 `agentporter-uninstall`；
- `activation_entry.py` 固定协商为 `probe-unsupported`，并使用空 `ProbeObservation`；
- 配置事务、摘要、读回和 compare-before-restore 已有离线基础。

### 2.2 Hermes v0.20 公共能力

Hermes v0.20 已公开：

```text
hermes -p <profile> auth add <provider>
hermes -p <profile> auth status <provider>
hermes -p <profile> -z <prompt> \
  --model <model> --provider <provider> --usage-file <path>
```

`--usage-file` 当前提供至少：

- `model`；
- `provider`；
- `api_calls`；
- token/cost 字段；
- `completed` / `failed`。

但它不直接提供：

- `tool_calls`；
- `fallback_used`；
- 独立的网络路由证明。

`auth status` 在 logged-out 时仍可退出 0，因此退出码不是凭据可用证明；其文本只能作为提示，最终必须由真实调用裁决。

## 3. 语义不变量与禁止副作用

### 3.1 状态不得合并

状态按以下顺序独立表达：

```text
installed
→ configuration-required
→ binding-configured
→ profile-auth-approved
→ auth-status-observed
→ live-credential-verified + live-call-passed
→ route-proof-incomplete | runtime-ready
→ operational
```

规则：

- `config check=0` 最多得到 `static-valid`，不能升级任何运行状态；
- Profile 存在、`.env` 存在、Gateway running 均不能证明真实调用；
- `live-call-passed` 必须来自当前 Profile、当前 model/provider/binding 上的一次真实调用；
- `runtime-ready` 只在所有强证明字段均可机器验证时产生；
- Hermes v0.20 缺少 tool/fallback 明细时，成功结果为 `live-call-passed + route-proof-incomplete`；
- `operational` 仍要求后续 Gateway、Kanban、订阅、workspace 和接续验收，本设计不自动授予。

### 3.2 凭据边界

AgentPorter不得：

- 读取、复制、打印、记录或提交 API key、OAuth token、`auth.json` 或 `.env` 内容；
- 从 default Profile 隐式继承任何凭据或私有 endpoint；
- 把秘密放入 argv、receipt、fingerprint、日志或异常正文；
- 根据用户输入的 `operator-authorized` 字符串直接认定凭据可用。

AgentPorter可以：

- 让用户选择凭据来源；
- 在真实 TTY 中调用 Hermes 原生 Profile-scoped `auth add`；
- 调用 `auth status` 给出辅助提示；
- 通过真实 one-shot 判断所选凭据是否真正可用。

Hermes 原生认证产生的 Profile-local 凭据属于用户/Hermes。激活取消或 canary 失败时，AgentPorter不得删除或恢复这些凭据。

### 3.3 安装与运行副作用分离

安装、升级、静态读回和卸载继续保证：

- 零模型调用；
- 零 Gateway 启停；
- 零 Kanban mutation；
- 零凭据读取或复制。

激活阶段使用三个独立授权门，不能用一次确认覆盖不同副作用：

1. **配置授权：** 写两个 Worker的 provider/base URL；
2. **凭据授权：** 是否分别调用目标 Profile的 Hermes `auth add`；
3. **真实调用授权：** 展示 model/provider、最多两次调用、可能费用和Hermes-owned Profile-local状态变化。

Gateway服务变更和Kanban mutation不属于本激活流程，继续分别要求独立授权。

每个授权计划必须明确展示：

- 两个目标 Worker；
- model/provider 与 endpoint 安全摘要；
- 预计最多真实调用次数；
- 可能产生费用；
- 凭据变更由 Hermes 持有且不纳入 AgentPorter 配置补偿。

真实调用必须单独确认。没有确认时为零模型调用。

### 3.4 真实 one-shot 的持久副作用

Hermes v0.20 one-shot不是无状态 RPC。即使 AgentPorter删除自身的usage/stdout/stderr临时文件，Hermes仍可能在目标 Worker Profile内创建或更新：

- session/state记录；
- usage/insights计数；
- 启用中的memory provider状态；
- hooks、rules、skills或MCP相关运行记录。

因此真实调用确认必须明确披露这些 **Hermes-owned Profile-local副作用**。0.1.5首版不直接操作 Hermes `state.db`，也不声称 canary后“零持久残留”。默认保留本次 session作为运行证据；receipt不保存session ID。若未来需要清理，只能通过 Hermes公开的session删除接口精确删除本次会话，并在清理失败时报告residue。

调用前后应采集不含凭据内容的安全清单，至少区分AgentPorter临时文件/子进程是否完全清理，以及Hermes-owned状态是否新增。

## 4. 产品流程

## 4.1 安装

Fresh install 继续安装三个 Profile，但最终结果必须明确为：

```text
Profiles installed
Runtime state: configuration-required
Next: agentporter-activate
```

bootstrap 必须在公共 bin 目录发布并读回：

```text
agentporter
agentporter-activate
agentporter-uninstall
```

三个链接必须绑定同一版本私有环境，纳入同一 ownership receipt 和卸载计划。任一名称冲突都必须在发布前 fail closed。

`agentporter` 仍是一次性安装入口，不新增子命令树。对已安装集合再次运行时只报告 `already-installed`/升级指引，不覆盖 Profile。

## 4.2 0.1.4 → 0.1.5 软件升级

0.1.5 必须支持已发布 0.1.4 bootstrap 布局，而不能要求用户先卸载三个 Profile。

升级边界：

1. 安全识别 0.1.4 私有环境、v1 bootstrap receipt 和现有 uninstaller 链接；
2. 验证现有链接确由 0.1.4 receipt 拥有；
3. 在私有 staging 安装并验证 0.1.5；
4. 创建新的 `agentporter`、`agentporter-activate` 链接，并将 uninstaller 切换到 0.1.5；
5. 读回全部三个链接与新 receipt；
6. 只有新入口集合完整后，才移除旧 0.1.4 私有环境；
7. 任一漂移或冲突均 fail closed，不覆盖用户文件。

### 4.2.1 三入口集合级升级状态机

升级以一个预确认不可变计划和逐步journal执行，不能把三次symlink操作当作松散命令：

```text
PREPARED
→ STAGED_015_VERIFIED
→ RECEIPT_V2_STAGED
→ AGENTPORTER_PUBLISHED
→ ACTIVATE_PUBLISHED
→ UNINSTALLER_SWITCHED
→ ENTRY_SET_READBACK_PASSED
→ RECEIPT_V2_COMMITTED
→ OLD_014_QUARANTINED
→ COMPLETE
```

规则：

1. 确认前封印v1 receipt、0.1.4根、旧uninstaller以及三个目标公共名称的设备/inode/type/target；
2. 每一步只记录本事务刚创建或替换的对象，下一步前重验已发布集合；
3. `agentporter`、`agentporter-activate`先以exclusive create发布；旧uninstaller最后通过同目录临时symlink + rename切换；
4. v2 receipt先在0.1.5私有根staging，只有三个入口全部读回后才提交为authority；
5. 失败补偿按journal逆序并执行compare-before-restore：只移除仍指向本事务0.1.5目标的新入口，只在当前uninstaller仍是本事务目标时恢复封印的0.1.4链接；
6. 补偿成功后的唯一期望集合是：旧0.1.4 uninstaller可执行，新增两个入口不存在，v1 receipt与0.1.4私有根保留；
7. 补偿无法安全完成时停止并报告明确mixed/partial状态，保留至少一个经身份验证的uninstaller，不删除任一私有根，也不声称升级成功；
8. 只有v2 receipt提交和三入口集合读回后才能隔离0.1.4根；旧根删除失败是bounded residue，不回滚已提交的新集合。

旧0.1.4 uninstaller不需要理解v2；切换后所有卸载都由0.1.5 uninstaller按v2执行。

由于修复集中在bootstrap、activation和probe，升级复用已安装的0.1.4三Profile，不强制重装或force-config。0.1.5 activation必须兼容由0.1.4 marker标识的完整三组件集合；fresh 0.1.5 install才安装0.1.5 Distribution。

## 4.3 激活输入

`agentporter-activate` 只处理名称无关身份发现出的两个 Worker，不处理 orchestrator，也不接受任意 Profile 参数。

每个 Worker 收集：

- provider ID；
- 私有 endpoint（隐藏输入）；
- 0.1.5唯一受支持的凭据接续：`profile-auth`；
- 是否现在调用 Hermes 原生认证流程。

Endpoint 只在内存和目标 Profile `config.yaml` 中存在；输出和 receipt 只保存分类与 digest。

`profile-env` 和 `external-secret` 不作为0.1.5可自动验收的grant种类。AgentPorter无法在“不读取/复制秘密”和“最小环境”边界下证明它们如何准确注入目标Worker子进程，因此遇到这些来源只能报告 `credential-source-unsupported` 并保持零模型调用。未来只有在Hermes公开、Profile-scoped且可机器验证的secret-reference解析路径可用后，才能单独增加支持。

## 4.4 凭据授权

0.1.5只支持 `profile-auth`：

1. AgentPorter调用 Profile-scoped `auth status` 作为非权威提示；
2. 未登录或用户要求更新时，在独立凭据授权门后，以真实 TTY 调用 Profile-scoped `auth add`；
3. 不使用 `--api-key` argv 参数；
4. 再次显示 `auth-status-observed: logged-in/logged-out/unknown`；
5. 不把 status 文本或退出码升级为凭据可用；
6. 只有后续真实 one-shot成功才产生 `live-credential-verified`。

状态轴固定为：

```text
credential_grant: not-requested | profile-auth-approved
credential_status: unobserved | logged-out | logged-in | unknown
credential_verification: not-run | live-verified | live-failed
```

不得使用笼统的 `credential-authorized` 表示凭据可用。

## 4.5 绑定事务

绑定事务沿用并加强现有实现：

```text
安全发现
→ typed snapshot
→ 不可变计划
→ 一次配置确认
→ 全集合重验
→ 两 Worker compare-before-write
→ 精确读回
→ 写安全 binding receipt
```

配置发布失败时，对本事务已写入且未漂移的值执行 compare-before-restore。

两 Worker 配置均写入并读回后，绑定成为可重放的 instance-owned 状态。后续 canary 失败不自动撤销 provider/base URL；这样用户可修复凭据或网络后重试。Canary receipt记录失败类别，并保持不可派发。

## 4.6 真实调用

每个 Worker最多执行一次受控 one-shot：

```text
hermes -p <worker> -z <nonce-prompt> \
  --model <expected-model> \
  --provider <expected-provider> \
  --usage-file <private-temp-path> \
  --toolsets <validated-minimal-toolset>
```

要求：

- 固定绝对 Hermes executable 与目标 Profile 身份；
- argv 中无 endpoint、key 或 token；
- 最小非秘密环境，不继承 default Profile credential 状态；
- 0700 临时目录，usage/stdout/stderr 有界；
- 30 秒默认硬超时，终止并回收整个子进程；
- prompt 使用随机 nonce，输出严格等于 `AGENTPORTER_READY:<nonce>`；
- usage 必须 `failed=false`、`completed=true`；
- `model`、`provider` 与 binding 精确一致；
- `api_calls == 1`；
- 任意失败或中断后清理全部 **AgentPorter-owned** 临时证据，并单独报告Hermes-owned Profile状态。

0.1.4 只保证安装时的静态安全边界，并不使 one-shot无副作用。`-z/--oneshot`会正常加载目标Profile的tools、memory、rules、hooks与MCP配置，并可能写session/usage状态；授权提示和验收不得把它描述为“无业务副作用”或“零持久残留”。

Hermes v0.20 不接受空的显式 toolset；`safe` 也不等于零工具 schema。因此 0.1.5 不把 `--toolsets safe` 解释为 `tool_calls=0` 证明。`api_calls==1` 加严格 nonce 是强的单调用证据，但仍不替代显式工具遥测。

## 5. 能力协商与分层结果

能力协商必须基于结构化capability record，而不是硬编码 `version == 0.20`。至少记录：

```text
oneshot_supported
usage_file_supported
usage_model_provider_supported
usage_api_calls_supported
tool_call_telemetry_supported
fallback_telemetry_supported
profile_scoped_auth_supported
```

数据来自实际Hermes help/版本和一次性运行输出；参数存在但输出字段缺失仍不得升级能力。未知未来版本只按已观测字段授予authority。

### 5.1 `live-call-passed`

必须满足：

- binding 配置与读回通过；
- 实际 one-shot 成功；
- nonce 精确匹配；
- usage 的 model/provider 精确匹配；
- `api_calls == 1`；
- 未观察到失败、超时或路由不一致。

### 5.2 `route-proof-incomplete`

当真实调用通过，但 Hermes 机器可读输出没有同时提供以下字段时产生：

- `tool_calls == 0`；
- `fallback_used == false`。

该状态证明 Worker 已能真实调用，不等于完整 `runtime-ready`。默认不得自动解锁 Kanban 派发，但允许用户明确授权的直接/受限使用。

### 5.3 `runtime-ready`

仅当目标 Hermes 的公开接口未来能提供并验证：

- 实际 model/provider；
- API calls=1；
- tool calls=0；
- fallback=false；
- nonce 与同一次调用绑定；

才产生严格 `runtime-ready`。AgentPorter不得通过读取 Hermes 内部数据库或修改 Hermes 源码补齐证明。

## 6. 失败分类

至少区分：

- `provider-not-configured`；
- `credential-required`；
- `authentication-failed`；
- `model-unsupported`；
- `endpoint-unavailable`；
- `rate-limited`；
- `probe-timeout`；
- `response-contract-failed`；
- `unexpected-runtime-route`；
- `usage-evidence-invalid`；
- `route-proof-incomplete`。

外部 stderr/异常正文不得原样进入持久化 receipt。只保存 allowlist reason code、非秘密摘要和时间边界。

## 7. Receipt 与状态展示

每个 Worker receipt 至少包含：

```text
component_id
profile_name
installation_id
distribution_version
agentporter_runtime_version
model
provider
endpoint_digest
credential_grant_kind
credential_status_observed
credential_verification_status
config_readback_passed
live_call_status
route_proof_status
api_calls
probe_started_at
probe_finished_at
fresh_until
hermes_version
```

禁止包含：

- endpoint 原文；
- credential path/value；
- session ID；
- prompt/模型原始输出；
-用户、账号、主机或私人工作区路径。

用户输出必须明确显示：

```text
Installed: yes
Binding configured: yes/no
Credential grant: not-requested/profile-auth-approved
Auth status observed: logged-in/logged-out/unknown
Credential verification: not-run/live-verified/live-failed
Live call: passed/failed/not-run
Route proof: complete/incomplete
Dispatch eligibility: blocked/restricted/eligible
```

## 8. 公共入口与完整卸载

bootstrap receipt升级为可兼容读取 v1、写入 v2：

```text
schema_version: 2
product
version
public_entries:
  agentporter
  agentporter-activate
  agentporter-uninstall
```

每个入口都必须冻结绝对路径、目标和身份。完整卸载顺序：

1. 删除并读回三个 AgentPorter Profile；
2. 重新验证三个公共入口与私有环境；
3. 原子隔离入口和版本根；
4. 删除精确版本私有环境；
5. 确认三个链接均不存在；
6. 保留其他版本和无关文件。

任一入口漂移时不得误删替代文件，也不得报告完整卸载成功。

## 9. 派发政策

0.1.5 的默认派发门禁：

- `configuration-required`、`credential-required`、live call失败：禁止派发；
- `live-call-passed + route-proof-incomplete`：默认禁止自动 Kanban 派发，只允许用户明确授权的受限直接调用；
- `runtime-ready`：仅解除推理 readiness 门禁；
- `operational`：仍需 Plan 02/04 的 Gateway、Kanban mutation、订阅读回与接续验收。

不得把 Luna 作为 Codex Worker 配置失败时的静默 fallback。

## 10. 兼容与非目标

### 兼容

- 支持 fresh 0.1.5 install；
- 支持 bootstrap 0.1.4 → 0.1.5 软件升级且保留已有三 Profile；
- 支持重命名后的 0.1.4/0.1.5 AgentPorter Profile；
- 不覆盖已有 instance-owned binding；
- force-config 或静态模型变化使旧 readiness receipt失效。

### 非目标

- 不修改或 import Hermes 源码/内部模块；
- 认证和真实调用只使用 Hermes公共 CLI；非秘密 binding只通过 AgentPorter受控兼容 writer写公开 Profile配置schema；
- 不新增 AgentPorter credential vault；
- 不复制 default Profile 凭据；
- 不自动启动 Gateway；
- 不创建真实 Kanban 任务；
- 不把普通终端文本解析包装成长期稳定的完整 probe seam；
- 不声称 0.1.5 自动达到 `operational`。

## 11. 发布验收

0.1.5 发布候选至少满足：

1. fresh install 与 0.1.4 upgrade 都发布并读回三个公共入口；
2. 取消安装、升级或激活时，未授权阶段零模型调用；
3. 激活不读取、复制或输出凭据；
4. provider/base URL 写入、读回、漂移和补偿事务通过；
5. logged-out `auth status` 退出 0 不被误判为凭据可用；
6. 两 Worker 的模拟/隔离真实 one-shot 能验证 nonce、model、provider、api_calls；
7. 缺失 tool/fallback 遥测时只报告 `route-proof-incomplete`；
8. 配置、认证、模型、429、endpoint、timeout、usage 损坏分别归类；
9. 卸载删除三个公共入口和精确私有环境；
10. 完整测试、Ruff、Pyright、build、隐私扫描和外部 release asset readback 通过；
11. 真实模型调用、Gateway 或 Kanban mutation仅在用户分别授权后执行。
