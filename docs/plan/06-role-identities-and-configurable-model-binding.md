# AgentPorter 职责型 Worker 身份与自定义推理绑定实施计划

> **Unreleased 拓扑修正（当前权威）：** 当前产品恰好只有 `bounded_worker` 与 `mechanical_worker` 两个 Worker Profile；主 Hermes agent 是 orchestrator，不再有独立 orchestrator Profile。v0.2.0 确实发布了错误的第三个 `agentporter-orchestrator`；下文三 Profile 叙述仅是历史发布/阶段证据。legacy 组件现在仅支持发现/卸载，以及单独确认的迁移删除。fresh install、activation、canary 均闭合为两个 binding/call。


> **状态：** Plan 06 已随 v0.2.0 正式发布。代码/离线门禁、tag `v0.2.0`、非预发布 GitHub Release、7 个托管 assets 与外部读回均闭合；真实 model canary、Gateway、Kanban mutation/live routing 未执行，仍不 operational。

**Goal:** 在保持三个 Worker 职责、component UUID 和 Hermes 原生边界不变的前提下，把模型语义名称迁移为职责型身份，并让三个 Profile 的 model/provider/endpoint 由用户显式配置和真实验证。

**Architecture:** 使用固定 component UUID 作为跨版本身份，将当前名称分类为旧默认名、新职责名或用户自定义名；旧默认名通过集合级 Hermes-native rename 事务迁移，新安装直接使用职责名。角色清单不再写死模型，安装和激活把 model/provider/endpoint 作为 sealed binding，通过现有 compare-before-write、fingerprint、usage readback 和 readiness 合同闭环。

**权威设计：** [职责型 Worker 身份与自定义推理绑定设计](../06-role-identities-and-configurable-model-binding-design.md)

---

## 1. 执行约束

1. 开发开始前集中读取设计、当前 identity/manifest/planning/render/activation/readiness/dispatch/uninstall 代码及现有测试，建立 ROLE-01…ROLE-22 验收追踪表。
2. 先写 RED，再实现；不得用批量字符串替换代替身份迁移设计。
3. 固定 component UUID 不变；不得修改 Hermes 源码。
4. 两个隔离实施轨可并发：
   - **轨 A：** 名称无关身份、兼容别名、正式入口迁移、Hermes rename 事务；
   - **轨 B：** 角色清单 schema、显式模型选择、安装/激活绑定、readiness/dispatch 失效。
5. `identity.py`、共享 DTO、打包清单 schema、本文档、设计、README、CHANGELOG 和版本由主代理串行拥有；两轨不得并发编辑共享文件。
6. focused tests 可并发；完整 pytest、ruff、pyright、build、release verifier 和文档门禁串行。
7. 每个开发事项最多一次独立复审。复审前完成实现、自检和完整门禁；复审提出的 BLOCK 逐项关闭，不递归复审。
8. 已批准开发一旦开始，应持续执行至测试、审查、提交、明确授权后的 push、发布和读回；本次文档任务不启动该执行链。
9. 正式入口冻结为更新后自动串联或操作者手动运行的 `agentporter-activate`。普通 bootstrap 软件更新不 rename、不 force-config；名称迁移、binding 配置、真实 canary 是三个独立授权门。旧默认名拒绝迁移时以 `legacy-name-migration-required` 停止 activation。

## 2. Phase A：冻结职责身份与兼容读取合同

### TASK A1：新增 RED 身份注册合同

**目标：** 证明产品当前键必须变为职责型名称，而永久 UUID 保持不变。

**主要文件：**

- Modify: `tests/test_domain.py`
- Modify: `tests/test_planning.py`
- Modify: `tests/test_render.py`
- Modify: `tests/test_packaging_contract.py`
- Future modify: `src/agentporter/identity.py`
- Future modify: `src/agentporter/resources/workers.yaml`
- Future modify: `src/agentporter/models.py`

**RED：**

- `COMPONENT_IDS` 的键为 `bounded_worker`、`mechanical_worker`，值与旧 UUID 完全一致；
- `INSTALL_COMPONENT_IDS` 顺序为 bounded、mechanical、orchestrator；
- 新 manifest 不包含固定模型 ID；
- 新初始 Profile 名符合设计；
- 新 display name 不含 `Luna`、`Codex`、`GPT`、数字模型版本；
- tier、description、instructions 与旧职责语义等价；
- 打包资源只包含职责型当前定义。

**Focused gate：**

```bash
pytest -q tests/test_domain.py tests/test_planning.py tests/test_render.py tests/test_packaging_contract.py
```

### TASK A2：定义旧身份别名与单向规范化

**目标：** 旧 Portable ID/旧默认名只进入兼容读取，不进入新写入。

**主要文件：**

- Create: `tests/test_identity_compatibility.py`
- Future modify: `src/agentporter/identity.py`
- Future modify: discovery/planning modules that consume registry keys

**RED：**

- 旧 UUID 可投影为新 Portable ID；
- `luna_worker`、`codex_5_3_small_worker` 作为 legacy key 可读取但不可新写；
- 旧默认 Profile 名、新默认名、任意合法用户改名都由 marker UUID 得到相同职责；
- unknown、duplicate、mixed installation ID fail closed；
- 新 receipt、计划、marker projection 和用户显示不写旧 Portable ID。

## 3. Phase B：集合级 Profile 名称迁移

### TASK B1：正式入口迁移分类可达

**目标：** 从真实安装/升级入口发现已有完整集合并分类，而不是只新增孤立 helper。

**主要文件：**

- Create: `tests/test_role_name_migration_application.py`
- Future modify: installer/update composition root
- Future modify: `src/agentporter/uninstall_discovery.py` or a narrow shared discovery projection
- Future create: role-name migration application module if needed

**RED 矩阵：**

| 安装状态 | 预期 |
|---|---|
| absent | 新职责名 fresh plan |
| 完整旧默认名 | activation 展示独立名称迁移确认；拒绝则保留原名并停止后续 activation |
| 完整新职责名 | no-op/readback，进入独立 binding 授权 |
| 用户改名完整集合 | 保留名称，更新角色投影 |
| 旧名与用户改名混合但身份完整 | 只迁移精确旧默认名，用户名不入 journal |
| 一个新职责默认名 + 一个旧默认名，且 journal 有效 | 显式 continue/rollback 恢复计划 |
| 同样 mixed 但 journal 缺失或漂移 | `migration-state-ambiguous`，零写入 |
| 新目标名被外部 Profile 占用 | confirmation 前 conflict |
| partial/duplicate/mixed/unknown | fail closed |

必须通过真实 `agentporter-activate` composition root 证明 helper 可达，覆盖 bootstrap 更新后串联与手动重跑两条路径；`agentporter` 对已安装集合仍返回 already-installed/升级指引。计划指纹包含完整分类和目标状态，并证明 software update、rename、force-config、canary 四种副作用不会共享一次确认。

### TASK B2：Hermes-native rename 事务

**目标：** 对旧默认名执行可补偿、compare-before-restore 的集合级迁移。

**主要文件：**

- Create: `tests/test_role_name_migration_transaction.py`
- Future modify: `src/agentporter/native.py`
- Future create: migration transaction module
- Future modify: execution/receipt modules as required

**RED：**

- 首次 rename 前 descriptor-bound 持久化无秘密 migration journal，记录 installation/component UUID、旧/目标名、封印身份和步骤；
- 命令参数严格为 Hermes `profile rename <current> <target>`；
- 第一项前、每项后和集合完成后读回 marker UUID/installation ID/path/current name；
- 第二项失败时只补偿仍与本事务结果一致的第一项；
- 用户并发 rename、replace、占名或 marker drift 阻断补偿并报告 residue；
- 重启后 journal 与完整集合精确一致时才展示 continue/rollback；无 journal、journal 漂移或身份不符时零写入；
- complete receipt 提交后才删除 journal，删除失败只报告 bounded residue；
- 取消、预检失败和确认错误为零 rename；
- 不删除 Profile、不直接移动目录、不触碰凭据或 Profile-local 文件。

### TASK B3：隔离真实 Hermes 迁移验收

**目标：** 使用临时 HERMES_HOME 和已验证 Hermes 版本证明真实 rename/readback，不访问模型。

**验收：**

- fresh 新名安装；
- 旧 release fixture 安装后迁移；
- 三组件 marker/installation ID 保持；
- 用户改名保持；
- 占名冲突零写；
- 进程终止/断电后 old+new mixed 集合能凭 journal 显式继续或回退；无有效 journal 时零写入；
- 中断/补偿路径无误删；
- 迁移后发现、激活计划和卸载仍按当前名工作；
- `model calls == 0`、`provider-definition reads == 0`、`credential reads == 0`、`Kanban mutations == 0`、`Gateway changes == 0`。

## 4. Phase C：角色清单与显式模型选择

### TASK C1：从角色 schema 移除固定模型

**目标：** `workers.yaml` 只拥有固定职责；模型是运行选择。

**主要文件：**

- Modify: `tests/test_domain.py`
- Modify: `tests/test_security.py`
- Modify: `tests/test_render.py`
- Future modify: `src/agentporter/models.py`
- Future modify: `src/agentporter/resources/workers.yaml`
- Future modify: `src/agentporter/render.py`

**RED：**

- manifest 拒绝角色层固定 `model` 字段，或按明确 schema version 只在 legacy decoder 接受；
- 角色层仍冻结 tier/reasoning/description/instructions；
- render 未收到 sealed model selection 时 fail closed 且不创建 staging；
- 不存在占位模型、空字符串模型或仓库默认模型；
- 安全扫描覆盖 model/provider/endpoint 与 credential 字段边界。

### TASK C2：安装计划增加三项 sealed binding

**目标：** 用户显式选择 model/provider/endpoint，并将其纳入预检、确认和指纹。

**主要文件：**

- Modify: `tests/test_planning.py`
- Modify: `tests/test_workflow.py`
- Modify: `tests/test_install_workflow.py`
- Future modify: `src/agentporter/planning.py`
- Future modify: `src/agentporter/workflow.py`
- Future modify: installer interaction/composition root

**RED：**

- 三个 Profile 均要求非空 model；
- selection key 集合闭合，unknown/missing/duplicate/whitespace fail closed；
- 三项可使用相同或不同模型；
- 计划显示每项职责、Profile 名、model/provider 和 endpoint 安全摘要；
- endpoint 原值不进入 fingerprint 输出、日志或异常；
- preview → materialize 之间任何 binding 变化使计划 stale；
- 安装和静态读回零模型调用。

## 5. Phase D：激活与原子重新绑定

### TASK D0：承接 0.1.8 custom-provider definition 与 credential grant

**目标：** 对历史两个 Worker 已复制的完整 provider definition 和没有历史定义的 orchestrator 建立显式、零披露的升级合同。

**主要文件：**

- Modify: `tests/test_activation_entry_runtime.py`
- Modify: `tests/test_activation_application.py`
- Future modify: activation application/entry and provider-definition transaction modules

**RED：**

- 普通更新和名称迁移不打开、解析、删除或复制现有 `custom_providers` / keyed `providers` 定义；
- 每个 Profile 只投影安全 grant 类别：`existing-profile-definition`、`explicit-source-inheritance`、`profile-auth`、`configuration-required`；
- 旧 Worker 可显式保留自身定义，但不得把定义复制给另一个 Profile；
- orchestrator 必须显式选择 Profile auth 或批准从 main/default 的精确定义继承，不得从 Worker 反向复制；
- 新写入沿用 descriptor-bound source seal、唯一 provider/endpoint 匹配、compare-before-write、零 argv/输出/receipt 披露；
- provider definition 与 model/provider/endpoint 同属 binding 配置授权，canary 仍是第三个独立授权门。

### TASK D1：激活输入加入 model 并覆盖三个 Profile

**目标：** `agentporter-activate` 允许保留或更换每个 Profile 的模型，且覆盖 orchestrator。

**主要文件：**

- Modify: `tests/test_activation_entry_runtime.py`
- Modify: `tests/test_activation_application.py`
- Future modify: `src/agentporter/activation_entry.py`
- Future modify: `src/agentporter/activation_application.py`
- Future modify: `src/agentporter/runtime_binding.py`

**RED：**

- activation 按 component UUID 投影三个职责，不按旧键或当前名称排序推导；
- 每项输入包含 model/provider/endpoint 和安全 credential-grant selection；
- 空输入可显式表示“保留当前值”，但不能隐式继承另一 Profile；
- model/provider/endpoint 在一个 payload 和一个 compare-before-write 事务中更新；
- 任一输入或目标 drift 在首写前 fail closed；
- orchestrator 参与 binding，但不因此取得实现职责。

### TASK D2：绑定变化与 readiness 失效

**目标：** 新绑定只有当前实际路由通过 canary 后才可派发。

**主要文件：**

- Modify: `tests/test_runtime_binding.py`
- Modify: `tests/test_runtime_probe.py`
- Modify: `tests/test_readiness_contract.py`
- Modify: dispatch planning/runtime tests
- Future modify: readiness/dispatch modules only where current contract lacks reachability

**RED：**

- fingerprint 包含职责型 Portable ID、固定 component UUID、当前 Profile 名、model/provider、endpoint digest、config digest 和 Hermes version；
- model/provider/endpoint 任一变化使旧 evidence 无效；
- actual model/provider 不一致为 `unexpected-runtime-route`；
- fallback telemetry 为 true 时失败；
- bounded 成功不能替代 mechanical/orchestrator；
- orchestrator 未 ready 时只阻断编排，不伪造两个执行 Worker 的状态；
- 机械 Worker 未 ready 时不得静默改派 bounded Worker。

### TASK D3：配置补偿与 Profile-owned 状态

**RED：**

- canary 失败保留已确认的配置和 Hermes-owned credential/session，状态降级为 canary-required/failed；
- 配置写入中途失败只补偿未漂移的 AgentPorter 写入，不删除 Profile；
- receipt 不保存 endpoint 原文、provider definition、credential 值或 `key_env` 引用；
- 重新运行 activation 可安全重试。

## 6. Phase E：路由、升级、卸载和制品兼容

### TASK E1：路由词汇职责化

**目标：** 当前代码、测试、用户输出和路由合同使用 bounded/mechanical，不使用模型名称表达职责。

**主要文件：**

- routing/dispatch tests and modules
- Worker SOUL/description rendering tests
- architecture guards

**RED：**

- 新生产路径和当前用户输出禁止模型语义角色名；
- 旧词只允许出现在 legacy alias、迁移 fixture、历史文档和明确的负面 guard；
- mechanical 的拒绝合同和 bounded 的边界合同保持；
- orchestrator 实现任务继续 fail closed。

### TASK E2：升级和卸载跨版本矩阵

**RED：**

- 0.1.8 旧默认名集合可升级、激活、卸载；
- 新职责名集合可更新、激活、卸载；
- 用户改名集合可更新、激活、卸载；
- 普通更新不覆盖当前 name/model/provider/endpoint；
- force-config 的范围、确认和 readiness 失效显式；
- 回滚矩阵覆盖旧默认名、新职责名、用户改名、有效-journal mixed、ambiguous mixed；
- 新职责名/用户改名回滚前先读回目标版本按 UUID 的发现与卸载能力；目标不兼容时保留新版本 uninstaller 和私有环境；
- 有效 journal 或 ambiguous mixed 状态禁止软件入口回滚；
- 入口切换失败 compare-before-restore，不能留下旧 activation 且无受支持 uninstaller；
- 老版本回滚限制有真实 0.1.8 fixture，而非仅文档声明。

### TASK E3：制品与隐私合同

**RED：**

- wheel/sdist 只包含新角色 manifest；
- release verifier 扫描旧当前名称、硬编码模型、credential 和私有 endpoint；
- legacy fixture 保持最小、无秘密并明确标注；
- README/设计/计划与代码生成物一致。

## 7. ROLE 验收追踪与唯一关闭责任

设计矩阵是语义权威；下表是唯一执行归属，TASK 不得自行改写 ROLE 含义：

| ROLE | Owner TASK | 必须证据 | 最终关闭 |
|---|---|---|---|
| ROLE-01 | A1, E1 | 新 manifest/名称 guard、用户输出检查 | E1 |
| ROLE-02 | A1, A2 | UUID 等值、marker schema/源码边界 guard | A2 |
| ROLE-03 | A1, E1 | SOUL/description/routing 拒绝合同 | E1 |
| ROLE-04 | C1, E1 | 模型变化不改变 tier/SOUL/权限的负面测试 | E1 |
| ROLE-05 | B2, B3 | 调用即失败 guard + 隔离 Hermes 零 model/provider-definition/credential/Gateway/Kanban 证据 | B3 |
| ROLE-06 | B1, B2, D0, D3 | 用户名、binding、provider definition、Profile-local 数据保持与漂移测试 | D3 |
| ROLE-07 | C1, D2 | 默认/占位/fallback/跨 Worker readiness 负面测试 | D2 |
| ROLE-08 | C2, D1 | 安装/迁移/激活安全投影快照 | D1 |
| ROLE-09 | B1, D2 | 名称、binding、canary、route、operational 独立状态测试 | D2 |
| ROLE-10 | A2, E1 | legacy allowlist + repository/current-output guard | E1 |
| ROLE-11 | D2 | model/provider/endpoint/fingerprint 失效矩阵 | D2 |
| ROLE-12 | A1, B3 | fresh 三职责名真实静态安装读回 | B3 |
| ROLE-13 | B1, B2, B3 | 0.1.8 旧默认名 UUID/journal/rename/readback | B3 |
| ROLE-14 | A2, B1, B3 | 用户改名零 rename + 新角色投影 | B3 |
| ROLE-15 | B1, B2 | 占名/partial/duplicate/mixed-ID/unknown 首写前阻断 | B2 |
| ROLE-16 | B2, B3 | journal crash recovery、continue/rollback、ambiguous 零写、漂移 residue | B3 |
| ROLE-17 | B3, E2 | old/new/user-renamed 激活/派发验证/卸载矩阵 | E2 |
| ROLE-18 | C2, D1, D2 | 三 Profile 相同/不同绑定与独立 canary | D2 |
| ROLE-19 | B1, D0, E2 | 软件更新零 rename/零 binding/provider-definition 覆盖 | E2 |
| ROLE-20 | A1–E2 | RED provenance、正式入口 reachability、合同 inventory | E2 |
| ROLE-21 | B3, E3, F | 全门禁、制品、链接、隐私、隔离 Hermes | F |
| ROLE-22 | F | 授权 ledger 与 offline/live 状态分离 | F |

Phase F 收口前必须逐行读回证据；任一 ROLE 不能用另一行或笼统 APPROVE 代替。

## 8. Phase F：代码/离线、发布与托管读回已闭合

执行顺序：

1. 两轨各自 focused tests；
2. 主代理串行集成共享 identity/schema/文档；
3. 运行完整门禁：

```bash
ruff format --check .
ruff check .
pyright
pytest -q
python -m build --outdir <empty-temp-dir>
python scripts/verify_release.py --help
# 按发布契约使用实际版本和临时制品执行 verifier
git diff --check
```

4. 在隔离 Hermes 中执行零模型 rename/install/update/uninstall matrix；
5. 若确有必要，进行唯一一次独立复审，范围冻结为 ROLE-01…ROLE-22 和最终候选；
6. 关闭复审 BLOCK，重跑受影响 focused tests 和完整门禁，不进行递归复审；
7. 同步设计、本文计划、计划索引、方案总览、Worker 规范、README、CHANGELOG、安装指南和发布状态；
8. 隐私扫描、提交身份检查、明确路径 staging、提交；
9. push 和发布前取得用户明确授权；
10. 发布后从托管制品重新安装，验证新名、用户模型选择、静态读回、迁移与卸载；真实 canary 仍使用独立授权。

## 9. 阶段验收与停止条件

- **Phase A 停止条件：** UUID/新角色/legacy alias 合同和 RED 完整；不得先改生产注册表。
- **Phase B 停止条件：** 正式入口迁移可达、集合级补偿和隔离 Hermes rename 通过；不得用直接目录 rename。
- **Phase C 停止条件：** 安装不存在默认/占位模型，sealed selection 贯穿 preview/materialize/render/readback。
- **Phase D 停止条件：** 三 Profile 原子 binding、精确 canary 和旧 readiness 失效闭合。
- **Phase E 停止条件：** old/new/user-renamed 跨版本矩阵及制品隐私门禁通过。
- **Phase F 完成状态：** 完整门禁、唯一复审 BLOCK、发布提交、push、tag、非预发布 GitHub Release、7 个托管 assets 与托管读回已闭合。真实模型/Gateway/Kanban 验收仍分别报告为未执行。

## 10. v0.2.0 发布关闭状态

- 设计与计划：已同步到 Plan 06 发布事实；
- 代码/schema/tests：最终发布 commit `be31eb2af67660780593c716d488ca88e508f710` 包含已完成的离线实现；唯一集中复审提出的四项确定性代码 BLOCK 已全部关闭；
- fresh install：使用 bounded/mechanical/orchestrator 职责名；三个 Profile 必须在 staging 前显式封闭 model/provider/endpoint；
- legacy：精确旧默认名通过 `agentporter-activate` 独立确认的 Hermes-native journaled rename 迁移；用户改名保留；
- readiness：model/provider/endpoint 任一变化都会使旧 readiness 与 binding-dependent evidence 失效；持久 authority 会从 marker/config/endpoint 重算职责与 fingerprint，拒绝 receipt 篡改；
- ROLE-01…ROLE-22：代码与离线证据已逐项关闭，摘要见下节；
- 唯一独立复审：已完成，结论为 BLOCK；已关闭 rename effect/journal、逐 Profile credential-grant、三 Profile canary 授权计数和 readiness authority 重建四项问题。按用户要求不进行第二次或递归复审；
- 复审关闭后完整门禁：`894 passed, 1 skipped`；Ruff format/check、Pyright 与 `git diff --check` 通过。唯一 skip 是 Hermes v0.20 无可证明禁用 tools/fallback 的 live-probe seam，不构成 live acceptance；
- 本机正式 Profile、真实 model canary、Gateway、Kanban mutation/live routing：未执行，分别需授权；
- v0.2.0 已正式发布：tag 精确指向 `be31eb2af67660780593c716d488ca88e508f710`；GitHub Release `AgentPorter 0.2.0` 于 `2026-08-14T05:54:56Z` 发布，为非 draft/非 prerelease，7 个托管 assets、checksum/verifier、fresh HTTPS clone、隔离 wheel import 与 `latest` bootstrap 字节回读均通过。真实 model canary、Gateway、Kanban mutation/live routing 未执行，不能称为 `operational`。

## 11. ROLE-01…ROLE-22 离线关闭证据摘要

- **ROLE-01…04：** 当前 manifest、职责名和用户输出使用 bounded/mechanical/orchestrator；固定 UUID、tier、SOUL、路由职责与拒绝边界保持。
- **ROLE-05…07：** install/update/rename/static readback/uninstall 的零 live-side-effect guard、无默认/占位/fallback 模型、用户配置与 Profile-owned 数据保持合同闭合。
- **ROLE-08…11：** 安装/迁移/activation 安全投影、分层状态及 model/provider/endpoint/fingerprint 变化导致 readiness 失效已有离线覆盖。
- **ROLE-12…16：** fresh 三职责名、0.1.8 legacy UUID 兼容、用户改名保留、冲突/partial/duplicate/mixed-ID/unknown fail-closed，以及持久 journal continue/rollback/漂移 residue 已由隔离 Hermes/事务测试覆盖。
- **ROLE-17…19：** old/new/user-renamed 激活与生命周期兼容、三个 Profile 独立相同/不同绑定、普通软件更新保留名称与绑定合同闭合。
- **ROLE-20…22：** RED provenance、正式入口 reachability、focused/full offline gates、制品/链接/隐私边界与 offline/live 授权 ledger 已闭合；发布/托管读回已验收，真实模型、Gateway、Kanban 仍明确未验收。

## 当前两 Worker 与 canary 修正合同

- `bounded_worker`：仅完成目标、约束、范围、文件和验收均由主 Hermes agent 固定的边界明确工作；信息不足或越界时停止，不猜测、不扩张。
- `mechanical_worker`：只处理更简单的机械委派——极简单操作脚本、大输出读取/过滤/摘要、按精确规则批量编辑；需要更广判断时返回歧义。
- 主 Hermes agent 负责 orchestrate、分解、路由与集成，不是 AgentPorter 安装的第三个 Profile。
- 每 Worker canary 默认 30 秒，可显式配置为 90 秒；授权短语与调用上限均为两个 Worker。
- inherited `key_env` 未解析时返回 `credential-required`，除非目标 Profile 自有 `.env` 可解析。canonical `custom` 只映射封印的具体定义；exit-zero 且 usage `failed=true` 仍按封闭原因失败。
- 失败原因保持封闭：`authentication-failed`、`model-unsupported`、`endpoint-unavailable`、`rate-limited`、`probe-timeout`、`response-contract-failed`、`usage-evidence-invalid`、`unexpected-runtime-route`。

## Unreleased 修正 ledger（替代当前三 Profile 目标）

1. 当前交付集合固定为 `bounded_worker`、`mechanical_worker` 两组件；主 Hermes agent 是编排 owner。
2. 本计划中新增/配置/绑定/探测独立 orchestrator Profile 的任务作为 v0.2.0 及阶段历史保留，不再是当前目标。
3. `agentporter-orchestrator` 只允许进入 legacy discovery/uninstall 与单独确认的 removal migration；不得进入 fresh manifest、staging、activation binding 或 canary 集合。
4. fresh install、activation、readiness 聚合、确认计数及 canary 上限均为两个 Worker。
5. canary 默认 30 秒并支持 90 秒；未解析 inherited `key_env` 在目标 Profile 无可解析 `.env` 时为 `credential-required`；canonical `custom` 只映射封印定义；exit-zero failed usage 保持封闭失败原因。

## v0.2.2 本地候选当前修正 ledger

已集成的 activation 修复作为未打 tag、未 push、未发布的 v0.2.2 本地候选准备；v0.2.1 仍是不可变的正式发布版。当前产品恰好只有两个 Worker。安装对每个 Worker 的 model、provider、endpoint 各询问一次，并只在进程内把 sealed selection 传给 activation，不进入 argv、环境变量或输出。用户显式授权 source inheritance 后，activation 只把选定 `key_env` 的精确 assignment 复制到对应 Worker 的 0600 `.env`，并与 provider definition 处于同一事务和补偿边界。API key 不进入输出、日志、argv、环境、fingerprint 或 receipt。`failed`、`credential-required`、`canary-required` 均保持非零，bootstrap 不得为这些状态报告 completed。真实 canary 仍需独立明确确认，本候选未执行。
