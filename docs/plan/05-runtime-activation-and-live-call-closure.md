# AgentPorter 0.1.5 运行激活与真实调用闭环实施计划

> **For Hermes:** 使用 `continuous-plan-orchestration`、`parallel-development-convergence` 与 `test-driven-development` 执行本计划。先冻结共享合同和路径 owner，再以两个隔离 worktree 并行推进；focused tests 可并发，完整门禁与发布串行。不得修改 Hermes 源码。

**状态：** Phase A–F 离线实现完成；真实模型验收 Phase G 待单独授权
**Goal:** 让AgentPorter在不修改/import Hermes源码的前提下完成两个Worker的推理binding、Profile-local凭据授权接续和真实one-shot验收：认证/调用使用Hermes公共CLI，非秘密provider/endpoint使用AgentPorter受控配置事务；并发布完整公共入口生命周期。
**Architecture:** 保留安装与激活分离。bootstrap 负责三 Profile 与三个公共入口的可验证安装/升级；`agentporter-activate` 负责编排 Hermes 原生认证、事务化写入非秘密 binding、执行真实 one-shot 并产生分层 evidence。Hermes v0.20 无 tool/fallback 遥测时报告 `route-proof-incomplete`，不伪造严格 `runtime-ready`。
**Tech Stack:** Python 3.11+、PyYAML、Pydantic 2、POSIX shell、Hermes v0.20 public CLI、pytest、Ruff、Pyright、setuptools。
**Source design:** [运行激活与真实调用闭环设计](../05-runtime-activation-and-live-call-design.md)

---

## 0. 验收矩阵

### 0.1 语义不变量与禁止副作用

| ID | 验收合同 |
|---|---|
| INV-01 | AgentPorter 不修改、fork、patch 或 import Hermes 源码/内部模块；认证与调用只使用公共 CLI，非秘密运行 binding 通过 AgentPorter受控兼容 writer写公开 Profile配置schema。 |
| INV-02 | 安装、升级、静态读回、取消和卸载保持零模型调用、零 Gateway 启停、零 Kanban mutation。 |
| INV-03 | AgentPorter 不读取、复制、打印、记录或提交 `.env`、`auth.json`、key/token 或 endpoint 原文。 |
| INV-04 | 不从 default Profile 隐式继承 provider、endpoint、凭据或 fallback。 |
| INV-05 | `config check=0` 只能证明 `static-valid`，不能产生 `live-call-passed`、`runtime-ready` 或 `operational`。 |
| INV-06 | `auth status` 文本/退出码不能证明凭据可用；状态拆为grant、observed status和live verification，只有one-shot成功产生`live-verified`。 |
| INV-06A | 0.1.5只支持Hermes `profile-auth`；`profile-env`/`external-secret`在没有公开Profile-scoped可验证解析路径时返回unsupported且零模型调用。 |
| INV-07 | 配置、Profile auth与真实调用使用三个独立确认门；真实调用限制为每 Worker最多一次，未确认时runner调用数为0。 |
| INV-07A | one-shot可能写Hermes-owned session/usage/memory等Profile-local状态；确认前必须披露，AgentPorter不得声称零持久残留或直接改state.db。 |
| INV-08 | 实际 model/provider/API calls 与绑定不一致时禁止通过。 |
| INV-09 | 缺少 tool/fallback 机器证据时只能得到 `route-proof-incomplete`，不得伪造 `runtime-ready`。 |
| INV-10 | 真实调用失败不删除 Profile、凭据或已成功读回的绑定；配置失败只恢复未漂移的本事务写入。 |
| INV-11 | `live-call-passed + route-proof-incomplete` 默认仍阻止自动 Kanban 派发。 |
| INV-12 | 任一公共入口发生身份漂移时，升级/卸载 fail closed，不覆盖或删除用户替代文件。 |

### 0.2 输出、边界、兼容与门禁

| ID | 验收合同 |
|---|---|
| OUT-01 | 安装结束明确输出 `configuration-required` 与下一步 `agentporter-activate`。 |
| OUT-02 | 用户状态分别展示 installed、binding、credential、live call、route proof、dispatch eligibility。 |
| OUT-03 | receipt 只持久化 allowlist 字段和 endpoint digest，不含 session/prompt/output/private path。 |
| BND-01 | `agentporter-activate` 只发现同一 installation ID 的两个 Worker，不接受任意 Profile。 |
| BND-02 | orchestrator 不参与推理绑定或 Worker canary。 |
| BND-03 | Profile auth 由 Hermes 原生 TTY 流程拥有；AgentPorter不使用 `--api-key` argv。 |
| CMP-01 | fresh 0.1.5 安装可用；0.1.4 bootstrap 可原位升级软件并保留已有三 Profile。 |
| CMP-02 | bootstrap receipt v2 写三入口；卸载兼容识别 v1/v2，但 v1 只删除其实际拥有的旧入口。 |
| CMP-03 | update 保留 instance binding；force-config、模型变化或 Hermes 版本变化使旧 evidence 失效。 |
| CMP-04 | Hermes executable与公共入口封印设备/inode/type/target；确认后任一authority替换都在下一项mutation前停止并报告partial/residue。 |
| GATE-01 | focused/full pytest、Ruff、Pyright、build、release verifier、隐私扫描全部通过。 |
| GATE-02 | release assets 外部下载、checksum、入口集合和版本读回通过。 |
| GATE-03 | 真实模型、Gateway、Kanban mutation分别需要用户明确授权；未授权发布门禁使用受控 fake/隔离 fixture。 |

---

## 1. 路径所有权与并行轨

### Track A：Bootstrap、升级与完整卸载

**Owner paths:**

- `install.sh`
- `src/agentporter/self_cleanup.py`
- `src/agentporter/uninstall_entry.py`
- `tests/test_bootstrap_installer.py`
- `tests/test_self_cleanup.py`
- `tests/test_release_verifier.py`
- `scripts/verify_release.py`

### Track B：Activation、auth 编排与真实 one-shot

**Owner paths:**

- `src/agentporter/activation_entry.py`
- `src/agentporter/activation_application.py`
- `src/agentporter/runtime_binding.py`
- `src/agentporter/runtime_probe.py`
- `src/agentporter/readiness.py`
- `tests/test_activation_application.py`
- `tests/test_runtime_binding.py`
- `tests/test_runtime_probe.py`
- 新增的 auth/probe adapter tests

### 主代理串行 owner

- `src/agentporter/__init__.py`
- `pyproject.toml`
- `CHANGELOG.md`
- `README.md` / `README.zh-CN.md`
- `docs/`
- `SECURITY.md` / `CONTRIBUTING.md`
- 版本、构建、完整门禁、集成、提交、push、tag、release 与外部读回

共享 DTO 的修改先由主代理冻结签名；两轨不得并发编辑同一路径或同名测试。

---

## Phase A：冻结状态、receipt 与 capability 合同

**Objective:** 在修改生产入口前，以 RED 一次覆盖完整 finding family。

**Files:**

- Modify: `src/agentporter/readiness.py`
- Modify: `src/agentporter/runtime_binding.py`
- Modify: `src/agentporter/runtime_probe.py`
- Modify: `tests/test_readiness_contract.py`
- Modify: `tests/test_runtime_binding.py`
- Modify: `tests/test_runtime_probe.py`

**Steps:**

1. 写 RED：新增 `live-call-passed`、`route-proof-incomplete` 与 dispatch eligibility 分层。
2. 写 RED：`config check=0`、Profile 存在、`.env` 存在均不能升级状态。
3. 写 RED：Hermes usage 有 model/provider/api_calls 但缺 tool/fallback 时只得到 incomplete proof。
4. 写 RED：只有完整 tool/fallback 遥测才允许严格 `runtime-ready`。
5. 写 RED：receipt拒绝 endpoint、credential path、session ID、prompt/output 和 private path。
6. 写 RED：fresh/update/force-config/Hermes version/model change 的 evidence失效矩阵。
7. 为每次生命周期事件接入正式invalidation producer并跑完整矩阵：fresh install/reinstall、Hermes version变化、model/provider/base URL/config digest或binding fingerprint变化、freshness过期、force-config、Profile rename和uninstall。
8. 最小 GREEN，实现纯领域和解析合同，不接真实 subprocess。
9. 集中语义复审一次，覆盖状态提升、负面副作用、错误归类和持久化边界。

**Focused command:**

```bash
PYTHONPATH=src:. python -m pytest -p no:cacheprovider -q \
  tests/test_readiness_contract.py \
  tests/test_runtime_binding.py \
  tests/test_runtime_probe.py
```

**Acceptance:** INV-05、INV-08、INV-09、INV-11、OUT-03、CMP-03。

---

## Phase B：Hermes public auth/oneshot adapter

**Objective:** 只通过现有 Hermes 公共 CLI，提供凭据接续和机器可读 one-shot observation。

**Files:**

- Create: `src/agentporter/hermes_runtime.py`
- Create: `tests/test_hermes_runtime.py`
- Modify: `src/agentporter/activation_entry.py`

**Steps:**

1. 写 RED：adapter argv 固定绝对 Hermes executable、`-p <profile>`、精确 allowlist 子命令。
2. 写 RED：`auth status` 的 logged-out exit 0不能认定 authorized。
3. 写 RED：`auth add` 必须继承真实 TTY，不接受或生成 `--api-key` 参数。
4. 写 RED：最小环境不包含 default Profile credential 环境变量；目标 Profile 由 `-p` 明确绑定。
5. 写 RED：one-shot argv包含显式 model/provider、随机 nonce 和私有 `--usage-file`，不包含 endpoint/secret。
6. 写 RED：usage JSON schema、有界大小、常规文件、no-follow、model/provider/api_calls/completed/failed 精确解析。
7. 写 RED：退出码、timeout、malformed/missing usage、nonce mismatch、route mismatch、429/auth/model/endpoint 错误安全分类。
8. 写 RED：任何返回、异常、中断都清理 stdout/stderr/usage 临时文件并回收子进程。
9. 最小 GREEN；外部 stderr只在内存分类，不持久化原文。
10. 证明没有 import Hermes 内部 Python 模块、读取 `auth.json/.env` 或修改 Hermes 源码的路径。

**Focused command:**

```bash
PYTHONPATH=src:. python -m pytest -p no:cacheprovider -q \
  tests/test_hermes_runtime.py tests/test_runtime_probe.py
```

**Acceptance:** INV-01、INV-03、INV-04、INV-06、INV-08、BND-03。

---

## Phase C：激活事务与真实调用接续

**Objective:** 将配置、Hermes auth 和真实 one-shot组装成一个可重放、分段确认的产品流程。

**Files:**

- Modify: `src/agentporter/activation_entry.py`
- Modify: `src/agentporter/activation_application.py`
- Modify: `src/agentporter/runtime_binding.py`
- Modify: `src/agentporter/runtime_probe.py`
- Modify: `tests/test_activation_application.py`
- Create: `tests/test_activation_entry_runtime.py`

**Steps:**

1. 写 RED：只处理两个 Worker，保持 component 顺序，不读取 orchestrator config/auth。
2. 写 RED：收集provider、隐藏endpoint，唯一支持的credential grant为`profile-auth`；`profile-env`/`external-secret`确定性unsupported且零调用，不再接受用户自报可用状态。
3. 写 RED：配置计划、每个Profile的auth授权和真实调用计划使用独立确认；拒绝任一阶段后没有越界副作用。
4. 写 RED：两 Worker配置全集合读回后才生成 binding receipt。
5. 写 RED：auth 流程只在用户选择 `profile-auth` 且需要时调用 Hermes。
6. 写 RED：真实调用前展示每Worker一次、最多两次调用、可能费用和Hermes-owned session/usage/memory副作用。
7. 写 RED：调用前后采集安全状态清单；AgentPorter临时文件/子进程必须清理，Hermes-owned状态默认保留且明确报告，禁止直接操作state.db。
8. 写 RED：一个 Worker失败不触发第二次重试、fallback或改派；另一个Worker按冻结计划执行或按明确all-or-nothing策略跳过，策略在首次RED中唯一确定。
9. 写 RED：canary失败保留成功读回的binding与用户/Hermes凭据，写安全failure receipt。
10. 写 RED：两者live-call通过但proof incomplete时聚合为restricted，不可自动派发。
11. 最小 GREEN，删除固定 `ProbeCapability(False, ...)` 和空 observation正式接线，但保留 capability 降级。
12. closure review最多一次，重点检查正式 `main()`、公开构造器和直接执行 seam。

**Focused command:**

```bash
PYTHONPATH=src:. python -m pytest -p no:cacheprovider -q \
  tests/test_activation_application.py \
  tests/test_activation_entry_runtime.py \
  tests/test_runtime_probe.py
```

**Acceptance:** INV-07、INV-10、BND-01、BND-02、OUT-02。

---

## Phase D：三公共入口、0.1.4 升级与完整卸载

**Objective:** 让安装后的激活命令真实可发现，并闭合三个入口的安装、升级、补偿与卸载。

**Files:**

- Modify: `install.sh`
- Modify: `src/agentporter/self_cleanup.py`
- Modify: `src/agentporter/uninstall_entry.py`
- Modify: `tests/test_bootstrap_installer.py`
- Modify: `tests/test_self_cleanup.py`

**Steps:**

1. 写 RED：fresh install预检三个公共名称，任一冲突时零公开入口写入。
2. 写 RED：发布三个链接后逐项 readlink、可执行和版本读回。
3. 写 RED：receipt v2记录三个入口，parser只接受 exact schema；v1保持兼容。
4. 写 RED：安装器成功输出 `configuration-required` 和下一步命令。
5. 写 RED：0.1.4 → 0.1.5 只升级 AgentPorter软件，保留现有三 Profile字节/mtime/marker与凭据。
6. 写 RED：用逐步journal冻结状态机 `PREPARED → STAGED → RECEIPT_STAGED → 两新入口发布 → UNINSTALLER_SWITCHED → ENTRY_SET_READBACK → RECEIPT_COMMITTED → OLD_ROOT_QUARANTINED`；每个故障点均断言唯一最终集合。
7. 写 RED：每步补偿按journal逆序、compare-before-restore；成功补偿必须恢复“旧uninstaller可用+两个新入口不存在+v1/root保留”，无法安全补偿时保留经验证uninstaller和两个私有根并报告mixed/partial。
8. 写 RED：同字节 inode替换、rename-and-occupy、入口漂移、receipt漂移、Hermes executable替换和旧环境漂移均fail closed；第一个mutation后发生变化时停止剩余操作并报告partial/residue。
9. 写 RED：卸载验证并删除三个拥有的入口和精确版本环境；v1只删除旧 receipt声明的入口。
10. 最小 GREEN，保持 shell bootstrap不可绕过交互计划。
11. 运行真实隔离 `$HOME` bootstrap E2E，不触碰当前已安装产品。

**Focused command:**

```bash
PYTHONPATH=src:. python -m pytest -p no:cacheprovider -q \
  tests/test_bootstrap_installer.py tests/test_self_cleanup.py
```

**Acceptance:** INV-02、INV-12、OUT-01、CMP-01、CMP-02。

---

## Phase E：隔离 Hermes v0.20 组合验收

**Objective:** 在不使用真实凭据/模型的前提下，验证 AgentPorter 与 Hermes v0.20 公共 CLI 的组合形状；真实调用另行授权。

**Files:**

- Create: `tests/test_phase10_hermes_v020_activation_integration.py`
- Create/Modify: `tests/fixtures/` 下的非秘密隔离 fixture
- Modify: relevant CI workflow if repository already has an isolated-Hermes lane

**Steps:**

1. 以临时 `HOME/HERMES_HOME` 安装 0.1.5 三 Profile并读回三个公共入口。
2. 使用 fake provider endpoint/受控 runner证明 argv、usage、nonce、分类和清理，不读取机器凭据。
3. 证明 `auth status` logged-out exit 0保持 credential unresolved。
4. 证明配置写入后 Hermes Profile实际解析 provider/base URL，但不发送真实请求。
5. 证明 one-shot usage包含 model/provider/api_calls时获得 live-call evidence；缺 tool/fallback字段时为 incomplete。
6. 证明所有默认路径不启动 Gateway、不创建 Kanban task。
7. 记录 Hermes exact version/commit和当前限制，不能把 fixture称为真实模型验收。

**Focused command:**

```bash
PYTHONPATH=src:. python -m pytest -p no:cacheprovider -q \
  tests/test_phase10_hermes_v020_activation_integration.py
```

**Acceptance:** INV-01–INV-12 的组合根证据；不关闭 GATE-03 的真实调用授权。

---

## Phase F：文档、发布门禁与 0.1.5 发布候选

**Objective:** 同步整个权威链，构建可外部验证的 0.1.5 候选。

**Files:**

- Modify: `src/agentporter/__init__.py`
- Modify: `CHANGELOG.md`
- Modify: `README.md`, `README.zh-CN.md`
- Modify: `docs/00-solution-overview.md`
- Modify: `docs/02-platform-adapters.md`
- Modify: `docs/03-installation-and-uninstall-design.md`
- Modify: `docs/04-installation-and-troubleshooting*.md`
- Modify: `docs/plan/00-index.md`
- Modify: `SECURITY.md`, `CONTRIBUTING.md`
- Modify: packaging/release contract tests and `scripts/verify_release.py`

**Steps:**

1. 将0.1.4标记为已发布历史基线，删除当前权威文档中的“未发布/未打标签”矛盾。
2. 明确0.1.5候选的安装/配置/live call/proof/dispatch分层。
3. 更新用户流程：curl安装 → `agentporter-activate` → Hermes Profile auth → 真实调用授权。
4. 更新卸载说明为三公共入口完整自清理。
5. 升版本到0.1.5并更新 wheel/sdist/entry/resource/module契约。
6. 运行完整门禁：

```bash
PYTHONPATH=src:. PYTHONDONTWRITEBYTECODE=1 \
  python -m pytest -p no:cacheprovider -q
python -m ruff format --check src tests scripts
python -m ruff check src tests scripts
python -m pyright
python -m build
```

7. 运行 Markdown链接、隐私、secret、私人路径、diff和release verifier。
8. 集中发布复审一次；closure review至多一次，只处理 blocking findings。
9. 提交并push已验证候选；只有用户明确授权后创建tag/GitHub Release。
10. 从GitHub外部下载全部assets，验证checksum、脚本digest、三个入口、版本和升级路径。

**Acceptance:** GATE-01、GATE-02；发布动作本身另行授权。

---

## Phase G：单独授权的真实模型验收

**Objective:** 在用户明确授权provider、凭据、调用次数和费用后，对两个 Worker执行真实 one-shot。

**前置条件：**

- 0.1.5候选或发布制品已安装；
- 两个 Profile 的凭据由用户通过 Hermes原生机制授权；
- 用户明确授权最多两次真实模型调用；
- 不授权 Gateway、Kanban mutation 或任务派发，除非另行说明。

**Steps:**

1. 对两个 Worker分别运行一次 `agentporter-activate` canary。
2. 读回非秘密 receipt，不展示 endpoint、credential、session或模型原始输出。
3. 验证 nonce、model、provider、api_calls和清理。
4. 预期 Hermes v0.20结果为：

```text
live-call-passed
route-proof-incomplete
restricted dispatch
```

5. 若目标 Hermes后续公开 tool/fallback遥测，再提升为严格 `runtime-ready`。
6. 真实失败按分类修复 AgentPorter适配，不修改 Hermes源码；若公共能力不足则声明兼容边界。

**Acceptance:** 两 Worker真实调用成功；严格 runtime-ready只按现有证据如实决定。

---

## 提交与交付纪律

- 每个 Phase 先确定性 RED，再最小 GREEN，再 focused tests；不得把实现前已存在的测试称为新 RED。
- 两轨每个 Phase 形成独立提交；主代理只在读回测试、diff和路径owner后集成。
- 完整 pytest、build和release verifier串行执行。
- 每阶段完成后同步设计、计划索引、项目状态和受影响文档；代码-only GREEN不是完成。
- 开源提交前扫描个人信息、token、endpoint、私人路径和运行输出。
- 阶段验收后按项目规则push到远端；tag/Release、真实模型、Gateway和Kanban仍分别需要明确授权。

## 未发布修订验收矩阵

- [x] custom Provider 激活不调用 Hermes v0.20 `auth add/status`。
- [x] 主/default Profile 中唯一且 endpoint 一致的完整 Provider 定义被复制到两个 Worker。
- [x] Hermes v0.20 keyed `providers.<id>` 与兼容 `custom_providers` 均受支持；来源 schema 保持不变，跨结构重复时 fail closed。
- [x] 来源缺失/重复/endpoint 不一致/确认后漂移时 fail closed。
- [x] 每个 receipt 发布前及全部发布后重验来源与 Worker 完整配置/身份；receipt 窗口漂移会补偿配置和已发布 receipt，无法安全恢复的并发 Worker 修改报告 residue。
- [x] Provider 定义不进入输出、repr、receipt 或 argv；目标配置继承是唯一获批的秘密复制边界。
- [x] bootstrap 安装成功后直接进入 activation，无额外 opt-in。
- [x] activation 失败保留公开重试入口并返回非零。
- [ ] 真实凭据 one-shot 仍需用户在 canary 门明确授权；本修订未执行真实模型调用。
