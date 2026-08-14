# AgentPorter 职责型 Worker 身份与自定义推理绑定设计

- **状态：** Plan 06 已形成 v0.2.0 发布候选；正式发布与托管读回完成前 0.1.8 仍是正式发布版
- **目标版本：** v0.2.0 发布候选
- **依赖：** 已发布的 AgentPorter 0.1.8、Hermes 名称无关 Profile marker、现有运行绑定与真实 canary 合同
- **实施计划：** [Plan 06](plan/06-role-identities-and-configurable-model-binding.md)

## 1. 目标

Plan 06 离线代码候选已完成两项不可分割的产品语义修正：

1. Worker 的产品名称只表达职责，不再包含 `Luna`、`Codex`、`GPT`、模型版本或能力规模；
2. model/provider/endpoint 成为用户可配置的运行绑定，不再由打包清单写死，同时保持每个 Worker 的功能职责不变。

目标分层为：

```text
永久组件身份：component UUID
        ↓
固定职责：bounded | mechanical | orchestrator
        ↓
当前 Profile 名：初始职责名或用户自定义名
        ↓
用户可变推理绑定：model + provider + endpoint + Profile-owned credential
        ↓
当前绑定的真实 canary 与 readiness
```

名称、职责、模型和凭据不得互相推导。

## 2. 当前候选事实与发布/现场缺口

0.1.8 发布制品的三个历史默认 Profile 如下；当前候选的新写入不再使用这些名称：

| 当前 Portable ID | 当前初始 Profile 名 | 当前模型请求 | 职责 |
|---|---|---|---|
| `luna_worker` | `luna_worker` | `gpt-5.6-luna` | 有边界实现与分析 |
| `codex_5_3_small_worker` | `codex-5-3-small-worker` | `gpt-5.3-codex-spark` | 更窄的机械任务 |
| `agentporter_orchestrator` | `agentporter-orchestrator` | `gpt-5.6-luna` | Kanban 编排控制面 |

Plan 06 候选已将角色清单与运行绑定拆分：fresh install 使用职责名，三个 Profile 在 staging 前必须提供闭合的 model/provider/endpoint sealed selection；激活期可对三个 Profile 原子配置绑定。model/provider/endpoint 任一变化都会使 readiness、fingerprint 与依赖其派发证据失效。

现有 marker 已提供名称无关的固定 component UUID，且发现、激活和卸载可按当前 Profile 名工作。这是迁移的身份基础，不需要重建组件或修改 Hermes 源码。

## 3. 语义不变量与禁止副作用

### 3.1 身份与命名不变量

1. 两个执行 Worker 的永久 component UUID 保持不变；orchestrator UUID 也保持不变。
2. 新产品定义使用职责型 Portable ID、初始 Profile 名和显示名：

| 固定职责 | 新 Portable ID | 新初始 Profile 名 | 新显示名 |
|---|---|---|---|
| 有边界实现与分析 | `bounded_worker` | `agentporter-bounded-worker` | `Bounded Worker` |
| 机械化委派 | `mechanical_worker` | `agentporter-mechanical-worker` | `Mechanical Worker` |
| 编排控制面 | `agentporter_orchestrator` | `agentporter-orchestrator` | `AgentPorter Orchestrator` |

3. `luna_worker`、`codex_5_3_small_worker` 和 `codex-5-3-small-worker` 只可作为已发布版本的兼容别名或明确历史文本存在，不能继续作为当前产品角色。
4. component UUID 是所有权身份；Portable ID 是产品角色键；当前 Profile 名是可变运行地址。三者不得混用。
5. 不从 Profile 名、显示名、description 或 model ID 推导 component identity。

### 3.2 职责不变量

1. `bounded_worker` 完整继承原 `luna_worker` 的职责：父 Agent 已冻结目标、范围、约束和验收后，执行有边界实现、验证或分析。
2. `mechanical_worker` 完整继承原 `codex_5_3_small_worker` 的职责：只处理步骤、路径和变换规则明确、低判断量、机械可验的任务。
3. `agentporter_orchestrator` 仍只负责任务规范化、分解、路由、订阅、接续和结果综合，不执行实现任务。
4. 更换为更强或更弱的模型不得扩大、缩小或交换职责；能力不足时必须报告 blocker。
5. `tier`、routing description、`SOUL.md` 和路由验收矩阵是职责权威；模型不是职责权威。

### 3.3 推理绑定不变量

1. 三个 Profile 的 model 都必须可由用户显式配置；打包清单不得再写入供应商或项目私有的固定模型 ID。
2. model/provider/endpoint 作为一个绑定单元进入不可变计划、确认、配置事务、读回、binding fingerprint 和 canary。
3. 不从 default/main Profile、环境变量、Provider 默认值或另一个 Worker 隐式选择模型。
4. 不允许静默 fallback。真实 usage 中的 model/provider 必须等于当前绑定；不一致为 `unexpected-runtime-route`。
5. 模型或 provider/endpoint 变化立即使旧 readiness、派发收据和依赖其 fingerprint 的运行证据失效；重新通过当前绑定 canary 前不得派发。
6. 模型 ID 和 provider ID 可显示；endpoint 按现有安全摘要处理；凭据值不得进入计划、argv、日志、receipt、fingerprint 或文档。
7. 软件更新、静态读回、名称迁移和卸载继续保持零模型调用，并且不得打开、解析或复制 provider definition/credential。全新安装的 Profile 创建阶段也保持该边界；随后串联的 activation 是独立阶段，沿用 0.1.8 已发布的受控 custom-provider 定义继承和单独确认 canary 合同。
8. 0.1.8 可能已经把完整 custom-provider definition（包括操作者存放的 `api_key` 或 `key_env`）复制到两个执行 Worker。下一版本默认原样保留这些 Profile-owned 配置，不自动提取、删除、转换或再次复制；只有显式 activation 计划可按受控来源事务更新。

### 3.4 禁止副作用

- 不修改、fork 或 patch Hermes 源码；
- 不生成新的 component UUID 来代替旧 Worker；
- 不删除或重建旧 Profile 来完成重命名；
- 不覆盖用户已经自定义的 Profile 名；
- 不因软件升级覆盖用户现有 model/provider/endpoint；
- 不删除 Profile-owned credential、provider definition、session、memory、skills 或历史状态；
- 不用旧硬编码模型作为错误恢复 fallback；
- 不把名称迁移成功、静态 `config check` 或 provider 定义存在当作真实 inference readiness。

## 4. 名称迁移设计

### 4.1 正式入口、授权与迁移分类

普通 bootstrap 软件更新只更新 AgentPorter 软件和公共入口，**不自动重命名 Profile，也不强制配置**。更新成功后按既有产品流程串联公共 `agentporter-activate`；该正式入口先按固定 component UUID 发现唯一完整安装，再执行三个相互独立的授权门：

1. **名称迁移授权：** 仅当发现精确旧默认名或可证明的中断 mixed-name 集合时展示；拒绝或取消会保留原名，并以 `legacy-name-migration-required` 结束本次 activation，不继续写绑定或调用模型；
2. **绑定配置授权：** 名称已是新职责名或属于用户自定义名后，才允许修改 model/provider/endpoint/provider definition；
3. **真实 canary 授权：** 配置读回后单独披露调用数和费用。

因此“普通软件更新保留当前名称”与“旧默认名可迁移”不冲突：前者永远不隐式 rename；后者只能通过更新后自动串联或操作者稍后手动运行的 `agentporter-activate`，经独立确认到达。已安装集合在 `agentporter` 安装入口仍按当前合同返回 already-installed/升级指引，不另造通用命令树。

名称迁移计划对每个组件分类：

| 当前名称状态 | 行为 |
|---|---|
| 精确等于已发布旧默认名 | 计划迁移到新职责型初始名 |
| 已被用户改成其他合法名称 | 保留当前名称，不自动改名 |
| 已是新职责型名称 | 视为已迁移，继续读回身份 |
| 一个执行组件为新职责默认名、另一个仍为旧默认名，且有有效迁移 journal | 作为中断事务，仅允许显式继续或回退计划 |
| 同样的新/旧 mixed 集合但无有效 journal | `migration-state-ambiguous`，零写入；不得猜测为用户改名或事务残留 |
| 目标新名称被无关 Profile 占用 | 整组 fail closed，零重命名 |
| 集合缺失、重复、混合 installation ID 或未知组件 | fail closed，零重命名 |

旧默认名映射：

```text
luna_worker              -> agentporter-bounded-worker
codex-5-3-small-worker   -> agentporter-mechanical-worker
agentporter-orchestrator -> agentporter-orchestrator（无变化）
```

### 4.2 集合级事务

名称迁移必须是预确认、可重放、集合级事务：

```text
DISCOVERED
→ CLASSIFIED
→ TARGET_NAMES_PREFLIGHTED
→ PLAN_CONFIRMED
→ FIRST_RENAME_READ_BACK
→ SECOND_RENAME_READ_BACK
→ COMPLETE_SET_READ_BACK
→ ROLE_BINDINGS_RECORDED
→ COMPLETE
```

规则：

1. 确认前封印 Hermes 根、安装集合、marker、当前名称和全部目标名称状态；
2. 只调用 Hermes 公共 `profile rename`，不直接移动目录；
3. 每次 rename 前后按 component UUID、installation ID、路径和 marker 重新读回；
4. 第一项成功、第二项失败时，只在第一项仍精确绑定本事务结果时 compare-before-restore；
5. 补偿无法安全完成时保留 Profile，报告明确 mixed/partial 状态，不删除任何组件；
6. 首次 rename 前在 AgentPorter 私有安装根创建不含秘密的 descriptor-bound migration journal，记录 installation ID、固定 component UUID、旧/目标名、每步封印身份和状态；每次 rename/readback 后先持久化 journal，再进入下一步；
7. 重启后只有 journal 与当前完整集合、marker、名称和文件身份全部一致时，`agentporter-activate` 才能展示“继续剩余 rename”或“回退已完成 rename”的显式计划；无 journal、journal 漂移或身份不一致时零写入并报告 `migration-state-ambiguous`；
8. COMPLETE_SET_READ_BACK 后提交名称迁移 receipt，再删除 journal；删除失败为 bounded residue，不回退已完成迁移；
9. 用户自定义名不进入 rename journal，因为它们不应被修改；
10. 新 Portable ID 投影由 component UUID 决定，不要求修改旧 marker schema。

### 4.3 兼容期限

下一功能版本必须同时识别：

- 旧 Portable ID/旧默认名的已发布安装；
- 新 Portable ID/新职责名安装；
- 用户已批量重命名但 marker 完整的安装；
- 名称迁移中断后可判定的旧、新或 mixed 集合。

兼容别名只用于读取、发现和迁移。所有新写入、展示、计划和文档必须使用职责型名称。中断 mixed 集合不是普通兼容成功状态：必须由有效 journal 恢复，否则保持歧义阻塞。

## 5. 自定义模型设计

### 5.1 权威输入拆分

`workers.yaml` 继续作为角色清单，但角色定义与运行绑定分离：

```yaml
workers:
  bounded_worker:
    display_name: Bounded Worker
    tier: bounded
    reasoning_effort: max
    description: ...
    instructions: ...
```

目标 schema 不再把固定 `model` 当作角色字段。实际模型来自本次用户输入形成的 sealed selection。若 Hermes distribution schema 在安装时技术上要求 `model.default`，AgentPorter 必须在渲染前取得显式选择；不得写占位模型或仓库默认模型。

### 5.2 安装流程

全新安装的目标流程：

```text
发现 Hermes 与 Profile 冲突
→ 显示三个固定职责
→ 为每个 Profile 收集显式 model/provider/endpoint 绑定
→ 验证非空、闭合集合和 endpoint 安全格式
→ 形成包含三项绑定的不可变安装计划
→ 一次安装确认
→ 安装并读回三个 Profile
→ 保持零模型调用
→ 单独披露并确认最多三次真实 canary
→ 每个 Profile 独立产生 readiness
```

为减少重复输入，界面未来可以提供“复制上一项公开 model/provider/endpoint”的显式操作，但必须展示展开后的三项最终计划；不能使用隐式继承。

### 5.3 已发布 custom-provider 定义的承接

0.1.8 的 activation 会从 main/default Profile 封印并事务化复制完整 custom-provider definition 到两个执行 Worker；该定义可能包含 `api_key` 或 `key_env`。下一版本按以下规则承接，而不把历史事实改写为“从未复制凭据”：

- 名称迁移、普通软件更新和静态读取不得打开 provider definition；旧 Worker 中已有定义按字节和文件所有权原样保留；
- activation 必须先把每个 Profile 的 credential-grant 状态分类为 `existing-profile-definition`、`explicit-source-inheritance`、`profile-auth` 或 `configuration-required`，并在安全计划中只显示类别；
- 选择 `existing-profile-definition` 时只允许保留该 Profile 当前完整定义，不把它复制到另一个 Profile；选择更新时继续使用 0.1.8 的 descriptor-bound source seal、唯一 provider/endpoint 匹配、compare-before-write 和零披露合同；
- orchestrator 没有历史定义。操作者必须为它显式选择 `profile-auth` 或批准从 main/default 的精确 provider definition 继承；不得从两个 Worker 反向复制，也不得因模型/provider 相同推断 grant 可共用；
- 任一 provider definition 新写入和 model/provider/endpoint 配置属于同一 binding 授权与补偿边界；真实 canary 仍单独确认。

### 5.4 已安装集合重新绑定

`agentporter-activate` 对按 component UUID 发现的三个 Profile 显示：

- 职责型角色；
- 当前 Profile 名；
- 当前 model/provider；
- endpoint 安全摘要；
- 当前 readiness 是否会失效。

每项允许保留当前绑定或输入新绑定。任何变更都进入同一个 compare-before-write 配置事务；不得先写 model 后再等待 provider 输入。配置事务完成后，三个 Profile 各自执行独立 canary，不以其中一个成功替代其他组件。

### 5.5 Orchestrator

“不再写死模型”覆盖 orchestrator。它可使用与 bounded Worker 相同或不同的模型，但仍保持：

- 只持有最小 Kanban 控制面工具；
- 不执行实现任务；
- 不作为两个执行 Worker 的 readiness 代替；
- 自身模型变化使自身编排 readiness 失效，不直接改变其他组件的 inference evidence。

## 6. 状态与兼容

至少区分：

```text
role-identity-current
legacy-name-migration-required
name-conflict
binding-configuration-required
binding-configured
canary-required
route-proof-incomplete
runtime-ready
operational（仍要求 dispatcher/route/continuity）
```

普通软件更新本身始终保留当前 Profile 名、model/provider/endpoint 和 provider definition。名称迁移与强制配置只能由 `agentporter-activate` 的独立授权门触发；精确旧默认名在拒绝迁移后保持 `legacy-name-migration-required`，用户自定义名则视为职责身份有效。旧 readiness 只有在 Hermes 版本、config digest、binding fingerprint 和组件身份全部未变化时才可继续有效。

## 7. 验收矩阵

### 7.1 语义不变量与禁止副作用

| ID | 验收项 |
|---|---|
| ROLE-01 | 当前产品角色、初始名和显示名不包含模型、供应商或能力规模语义 |
| ROLE-02 | 三个 component UUID 与已发布版本完全一致；不修改 Hermes 源码或旧 marker schema |
| ROLE-03 | bounded、mechanical、orchestrator 的职责、拒绝条件和工具边界保持不变 |
| ROLE-04 | 任意模型选择都不能改变 tier、SOUL 或路由权限；能力不足只报告 blocker |
| ROLE-05 | 软件更新、Profile 创建、名称迁移、静态读回和卸载零模型调用、零 provider-definition/凭据访问、零 Gateway/Kanban mutation；串联 activation 另行授权 |
| ROLE-06 | 不覆盖用户自定义 Profile 名、绑定、凭据或 Profile-local 数据 |
| ROLE-07 | 不存在硬编码模型 fallback、Provider 默认模型 fallback 或跨 Worker readiness 借用 |

### 7.2 输出与状态

| ID | 验收项 |
|---|---|
| ROLE-08 | 安装/迁移/激活计划显示职责、当前/目标 Profile 名、model/provider 和 endpoint 安全摘要 |
| ROLE-09 | 状态独立表达名称迁移、绑定配置、canary、route proof 和 operational，不合并成一个 ready |
| ROLE-10 | 新写入和用户界面只使用职责型角色；旧名称仅在明确标记的兼容/历史上下文出现 |
| ROLE-11 | model/provider/endpoint 变化使旧 readiness、fingerprint 和依赖其派发证据失效 |

### 7.3 边界与兼容

| ID | 验收项 |
|---|---|
| ROLE-12 | 全新安装只创建 `agentporter-bounded-worker`、`agentporter-mechanical-worker`、`agentporter-orchestrator` |
| ROLE-13 | 旧默认名安装按固定 UUID 集合级迁移到职责名，读回 marker 与 installation ID 不变 |
| ROLE-14 | 用户已自定义名称的旧安装保留名称，但内部角色投影为新 Portable ID |
| ROLE-15 | 目标名称占用、partial、duplicate、mixed-ID、unknown component 在确认前 fail closed 且零重命名 |
| ROLE-16 | 中途失败只补偿本事务 rename；持久 journal 支持重启后显式继续/回退；无有效 journal 或漂移时零写并报告 ambiguous/mixed/partial |
| ROLE-17 | 旧名、新名和用户改名集合均可激活、派发验证和卸载；身份判断不依赖名称 |
| ROLE-18 | 三个 Profile 可选择相同或不同模型，并分别通过精确 model/provider canary |
| ROLE-19 | 普通软件升级默认保留用户当前名称与推理绑定 |

### 7.4 门禁

| ID | 验收项 |
|---|---|
| ROLE-20 | TDD 先覆盖身份别名、正式入口迁移可达性、集合 rename 事务和模型绑定全链路 |
| ROLE-21 | 完整离线门禁、隔离 Hermes rename/readback、制品检查、文档链接和隐私扫描通过 |
| ROLE-22 | 真实模型调用、Gateway、Kanban 和发布仍分别取得授权；离线通过不冒充 live acceptance |

## 8. 非目标

本设计不：

- 增加新的 Worker 职责或第四个 Profile；
- 提供任意动态 Worker 数量；
- 根据模型能力自动选择职责；
- 自动发现 Provider 模型目录并替用户决策；
- 修改 Hermes 的 Profile、auth、Gateway 或 Kanban 实现；
- 把 Profile 重命名变成通用 AgentPorter 管理命令；
- 在未单独授权时运行真实模型、变更 Gateway、执行 Kanban mutation、push 或发布版本。

## 9. 迁移、软件回滚与卸载连续性

回滚必须按当前名称状态和入口能力执行，不允许只切换软件版本：

| Profile/迁移状态 | 允许的软件回滚 | 必须保留的卸载入口 | 结果 |
|---|---|---|---|
| 旧默认名，尚未迁移 | 经 fixture 证明仍识别旧 UUID/名称的 0.1.8 或新版本 | 回滚目标自带的已验证 uninstaller | 可激活/卸载取决于该版本原合同 |
| 新职责名，迁移 complete receipt 已提交 | 仅回滚到经 fixture 证明按 component UUID 接受新当前名的版本 | **不得覆盖或移除新版本 `agentporter-uninstall`，除非目标版本卸载能力先读回通过** | 旧版本若不能激活则明确 `activation-unsupported-after-rollback`，但受支持卸载仍可达 |
| 用户自定义名 | 仅回滚到已证明名称无关发现的版本 | 同上 | 保留用户名称与绑定 |
| 有效 journal 的中断 mixed 状态 | 禁止软件回滚；先由当前版本显式继续或回退名称事务 | 当前版本 uninstaller 和私有环境必须保留 | 恢复到完整旧或完整新集合后再评估回滚 |
| 无有效 journal/漂移的 ambiguous mixed 状态 | 禁止回滚、激活和自动卸载 | 保留当前所有入口与证据 | 人工诊断，零自动写入 |

软件回滚事务必须先验证目标版本的 activation/discovery/uninstall 能力，再切换公共入口；失败时 compare-before-restore 当前新版本入口，不能留下“旧 activation + 无受支持 uninstaller”的混合集合。推理绑定和 provider definition 不随软件回滚迁移或覆盖，旧硬编码模型不得恢复。实施阶段必须以真实 0.1.8 fixture 验证旧默认名 → 新名 → 激活/卸载、中断恢复和入口回滚矩阵。

本文是 Plan 06 的权威设计。当前 v0.2.0 离线发布候选已经实现职责名、显式三 Profile 绑定、旧默认名 journaled Hermes-native rename、用户改名保留和 readiness 失效；正式发布与托管读回完成前 0.1.8 仍是正式发布制品。真实 model canary、Gateway、Kanban mutation/live routing、tag、release 与托管读回均未执行且分别需授权，不能声称 operational。
