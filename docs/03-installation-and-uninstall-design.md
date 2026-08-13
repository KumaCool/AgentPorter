# AgentPorter 安装、卸载与验收设计

## 0. 0.1.4 发布候选状态（Phase F）

| 维度 | 当前证据状态 |
|---|---|
| installation | fresh 三 Profile 与 legacy 双 Worker → 三 Profile 的安装、升级、读回、改名、卸载已通过离线及隔离 Hermes v0.20 验证。 |
| binding | `agentporter-activate` 的 snapshot/确认/精确写入读回/compare-before-restore 事务已离线通过；只作用两个 Worker。 |
| credential | 由操作者授权并由 Hermes/用户持有；AgentPorter 不读取、复制或持久化秘密。 |
| canary | v0.20 为 `probe-unsupported`，在模型适配调用前关闭，零模型调用；未达到 runtime-ready。 |
| dispatcher | 专用 orchestrator 配置静态读回通过；未启动 Gateway，未验收 live dispatcher。 |
| route | v0.20 为 `mutation-unsupported`，在 Kanban adapter 调用前关闭，零 Kanban mutation 调用。 |
| continuity | DispatchReceipt、任务级订阅、运行观察、结构性恢复合同仅离线通过；未验收真实投递/接续。 |

`hermes config check` 仅证明静态配置可解析。无任务时 `notify-list == []` 正常；只有正式任务创建后，精确 task/subscription 读回与安全 `DispatchReceipt` 才是解锁 dispatch 的必要条件。本候选未发布、未 tag、未 push，不声称 `operational`、真实 canary 或 live routing passed。

## 1. 文档职责与当前状态

本文是 AgentPorter **Profile 工作组安装事务、名称无关身份、独立卸载和安装基础验收语义的唯一权威设计**。它是多代理产品的生命周期基础，不再承担完整产品定位或任务编排设计。

- **设计/代码/验收状态：** v0.1.0 的安装、静态读回、有限补偿、名称无关独立卸载及完整 INS/UN/GATE 已实现、验收并发布；
- **安装入口：** 一次启动，无子命令、平台参数、静默模式或后台服务；
- **卸载入口：** 独立 `uninstall.py`，不是命令体系或长期管理界面；
- **能力边界：** 现有证据只证明两个 Worker Profile 可安全安装、读回和卸载；Kanban 仅验证 parser 与只读 assignee 枚举，未创建任务、运行 dispatcher 或调用 Worker/模型；
- **后续产品主线：** 自动分解、按职责路由和多 Worker 执行由 [Plan 02](plan/02-multi-agent-orchestration.md) 定义。

文档分工：

- [方案总览](00-solution-overview.md)：工作组部署与任务路由的产品定位；
- [Worker 规范](01-portable-worker-spec.md)：打包内 `workers.yaml` 与派生文件格式；
- [Hermes Adapter](02-platform-adapters.md)：Hermes Profile 与原生编排能力映射；
- **本文：** 安装、补偿、卸载、验证及安全边界；
- [安装基础实施记录](plan/01-installation-foundation.md)：v0.1.0 安装器、卸载器、测试和发布证据；
- [多代理编排与路由计划](plan/02-multi-agent-orchestration.md)：当前产品主线；
- [Worker 验证与基准计划](plan/03-agent-validation-and-benchmark.md)：编排接通后的真实代理质量与性能评测。

## 2. 共同不变量

1. 主安装器一次运行完成预检、计划、确认、安装、读回、有限补偿并退出；安装器和独立卸载器均不提供子命令或静默模式。
2. 不覆盖任一预先存在的 Profile，不修改 `default`。
3. 不复制或发布 `.env`、`auth.json`、API key、私有 base URL、记忆、会话、日志或状态数据库。
4. 第一版安装器、静态读回、补偿、卸载及 Plan 01 集成验收不发起模型请求；静态安装成功不代表模型运行成功。Plan 01 完成后另行显式运行的 [Worker 基准](plan/03-agent-validation-and-benchmark.md) 不属于这些路径。
5. **安装失败补偿和日后主动卸载是两种删除语义。** 补偿只处理当前安装事务中可证明新建的目标；卸载会删除后来产生的 Profile-local 数据，必须重新发现、警告并确认。发布版引导脚本安装的软件包属于第二层收尾：只有 Profile 集合已确认删除或原本不存在后，才可清理精确发布入口和对应版本私有环境。
6. 原始/当前 Profile 名、Portable ID、Display name 和 description 均不构成所有权身份。
7. 名称无关 marker 是唯一组件/安装身份；Hermes distribution info 中的 source 只可作为当前安装期的辅助事务证据，不能单独建立身份，也永不参与日后卸载资格。
8. 通过对应交付门禁的修改可直接 commit；push 仍需用户明确授权。

## 3. 名称无关安装标记

安装器在每个 Profile 中写入 `agentporter-profile.json`。文件名是 AgentPorter 协议保留名：其它产品不得使用它；用户若自行创建同名文件，卸载扫描会按本节规则校验，损坏或冲突时宁可阻断也不猜测。

```json
{
  "schema_version": 1,
  "product_id": "<固定 AgentPorter 产品 UUID>",
  "component_id": "<固定组件 UUID>",
  "installation_id": "<本次安装随机 UUID>",
  "distribution_version": "0.1.0"
}
```

### 3.1 字段契约

| 字段 | 生命周期 | 身份作用 |
|---|---|---|
| `schema_version` | schema 固定 | 解析和兼容校验 |
| `product_id` | 项目永久固定 | 声明标记采用 AgentPorter 协议，不提供密码学来源证明 |
| `component_id` | 每个逻辑组件永久固定 | 区分两个组件，且与任何名称无关 |
| `installation_id` | 每次安装随机生成 | 把两个组件绑定为同一次安装集合 |
| `distribution_version` | 随发布变化 | 诊断和兼容判断，不参与名称定位 |

`product_id` 与两个 `component_id` 是代码和测试中的协议常量。唯一权威注册表是 `src/agentporter/identity.py`；测试和文档只能引用该注册表，不能各自复制另一组值。实际 UUID 已在 Phase 1 生成并冻结，不能因 Profile、Worker、模型或显示名称变化而变化；本文示例仍使用占位符，避免复制第二份协议值。

schema v1 只允许示例中的五个字段且全部必填；三个 ID 必须是规范化 UUID 字符串，`installation_id` 在任何 Profile 写入前生成一次并由两个目标共享。未知字段、错误类型、非规范 UUID 或不受支持的 schema version 均为 `invalid-marker`，不能降级猜测。

标记是本地非秘密协议声明，不是用户认证、签名或防篡改凭据。卸载器只能验证声明结构、协议常量、安装集合与对象快照的一致性；标记损坏、被复制或产生歧义时必须停止，不能把“字段匹配”描述为密码学来源证明。

标记不得包含或依赖：

- 原始或当前 Profile 名；
- Portable ID、Display name、description；
- 用户名、主机名、绝对路径或 `HERMES_HOME`；
- provider、base URL、API key、token；
- 账号或机器专属标识。

Profile 当前目录名只在完成身份发现后用于展示、调用 Hermes 原生删除和删除后读回。

## 4. 一次性安装

### 4.1 预检与计划

```text
只读检测 Hermes、版本、HERMES_HOME 和现有 Profiles
→ 校验 workers.yaml、初始名称映射和 Hermes 名称约束
→ 任一目标初始名存在则整组冲突、零写入
→ 生成一次 installation_id
→ 为两个 Worker 渲染独立 staging
→ 校验 distribution/config/SOUL/标记及隐私边界
→ 展示完整集合计划和静态能力状态
→ 用户对该计划一次确认
```

计划必须显示：

- Hermes 可执行文件、版本和实际配置根；
- Worker 到初始 Profile 名的映射；
- 将创建的 Profile 和 `distribution_owned` 文件；
- provider/model 准备状态；
- 不会复制或修改的数据；
- 冲突和版本限制；
- 默认不调用模型；
- 失败时哪些目标可能被补偿。

计划准备状态：

- `ready`：非秘密配置完整，凭证由目标 Hermes 环境提供；
- `configuration-required`：Profile 可安装，但需要用户在安装界面选择非秘密 provider ID，或安装后通过 Hermes 原生配置补齐；
- `unsupported`：Hermes 版本不支持所需能力；
- `conflict`：任一目标初始名已存在；
- `invalid`：Worker 或 staging 不合法。

无凭证或尚未完成运行配置不阻止生成并静态安装 Profile，但必须显示 `configuration-required`，不能升级为 `ready` 或运行有效；安装器不得读取、验证、复制或回显凭证值。

### 4.2 原生安装与静态读回

确认后，内部依次：

1. 调用 Hermes 原生 `profile install` 尝试安装一个 staging；
2. 无论命令成功、非零退出、超时还是被中断，都立即只读重新枚举，并与安装前快照比较；
3. 命令明确成功且可靠枚举证明目标新出现时记入 `confirmed-created`；命令未明确成功但目标新出现、或枚举/创建结果不确定时记入 `uncertain-remnant`；一旦某次 install 已被调用，后续任何失败都必须先完成本次 post-attempt 归类，再决定补偿或退出；
4. 对命令明确成功的目标设置并读回 Profile description；
5. 枚举并读回 distribution、config、`SOUL.md` 和完整标记；
6. 逐项校验安装前不存在证据、正确 product/component ID、当前 marker 的 installation ID 等于本事务预先生成的 ID，以及该 Profile 的 Hermes distribution info 指向本事务 staging source；source 只用于当前安装事务相关性，不构成日后所有权身份；
7. 当前项证据全部满足即记入 `verified-compensable`；第一个 Profile 不依赖第二个 Profile 已存在，必须在尝试安装第二个之前即可进入该状态；
8. 两项完成后再执行集合成功校验：两个实际 Profile 的 installation ID 均等于本事务 ID、component 集合完整且互不重复；集合失败则整次安装失败并进入补偿；
9. 集合校验通过后输出静态结果并退出。

本事务 staging source 必须比较 Hermes 回写后的规范绝对路径与安装器持有的规范 staging 路径；不接受 basename、相对路径、字符串前缀或名称近似匹配。staging 在整次安装、静态读回和可能的补偿全部结束后才清理。

安装顺序固定按 `workers.yaml` 读取后保留的声明顺序，补偿顺序严格反向；排序不得依赖可变 Profile 名。若两个 Profile 已完成静态读回，但任一 shared installation ID/集合不变量失败，整次安装仍失败，并只补偿 `verified-compensable` 目标。

名称和 manifest 不作为所有权身份。安装报告区分：

1. manifest/staging 有效；
2. Profile 已安装；
3. 配置静态有效；
4. description/路由字段可读回；
5. 运行有效——第一版不执行，也不得声称通过。

### 4.3 安装失败补偿

安装事务维护三类状态：

- `confirmed-created`：Hermes 安装命令已明确成功，且可靠 post-attempt 枚举证明目标相对安装前快照为新出现；
- `verified-compensable`：当前项完整标记及本事务创建/source 证据读回一致，并已保存用于删除前重验的对象快照；
- `uncertain-remnant`：创建结果或身份读回不确定。

`confirmed-created` 的定义已经同时包含命令成功与可靠 post-attempt 新出现证据，不能只凭退出码。若命令未成功且可靠枚举证明目标仍不存在，则报告安装失败但不产生残留集合；若枚举本身失败、结果矛盾或发现新目标但身份未完整读回，则进入 `uncertain-remnant`。

目标进入 `verified-compensable` 时保存：实际 Hermes home/Profile 根、当前规范路径、当前 basename、目录与 marker 的 `st_dev`/`st_ino`/类型、marker 内容哈希以及 product/component/installation ID。

后续步骤失败时：

1. 只按反向安装顺序处理 `verified-compensable` 目标；
2. 每个补偿删除前立即重验已保存的 Hermes 根未切换，且已保存路径本身仍存在，并且根、路径、basename、目录/marker inode 与类型、marker 哈希及三个 ID 均与快照一致；不得沿 rename 后的新路径追踪目标，也不得重新按名称搜索替代对象；最后再次执行 Hermes 原生名称规范化和校验；
3. 任一字段变化、目标被 rename/replace、原名被其它 Profile 占用或当前名称不再指向同一对象时，禁止调用删除，将该目标降级为 `uncertain-remnant`；
4. 只有重验完全一致时才用参数数组、`shell=False` 调用 Hermes 原生删除；执行参数使用快照中已重验的 basename，而不是初始 Worker 映射、rename 后路径或重新搜索结果；随后确认 Hermes 枚举和快照原路径均不存在；
5. `uncertain-remnant` 不自动删除，预先存在 Profile 永不进入删除集合；
6. 删除失败、删除后读回失败或存在不确定残留时，以 `compensation-incomplete` 退出并报告人工处理路径。

Hermes 补偿同样只有按名称删除接口，立即重验无法消除重验与原生命令解析之间的最后竞态；文档不宣称原子补偿或完全 TOCTOU 防护。

这是有限补偿，不是跨进程原子事务。

## 5. 独立卸载

### 5.1 发现与批量重命名

Hermes rename 会移动整个 Profile 目录，标记随目录移动。因此卸载器不搜索初始名称，而是：

```text
解析实际 HERMES_HOME/Profile 根
→ 只读扫描直属 Profile 目录中的 agentporter-profile.json
→ 以 product_id 过滤
→ 以两个固定 component_id + 共享 installation_id 归并
→ 使用标记当前所在目录作为当前 Profile 名
```

即使两个 Profile 同时批量改名，固定 product/component ID 与 installation ID 不变，仍能准确发现。

扫描顺序固定如下：

1. 只扫描 Profile 根直属目录，寻找文件名恰为 `agentporter-profile.json` 的候选；
2. 候选目录或标记存在符号链接/路径逃逸时记录 `unsafe-path`；
3. 候选不是普通文件、超过大小上限、不是合法 UTF-8、JSON 解析失败、缺字段或 schema/type 不合法时，立即记录 `invalid-marker` 并全局阻断；此时不得因为无法读取 `product_id` 而忽略；
4. 只有完整解析且 schema 合法后，`product_id` 不匹配的 marker 才视为无关 Profile 并忽略；
5. product ID 匹配但 component/installation 值不受支持时记录协议异常；
6. manifest 最多用于诊断，不参与发现或日后删除资格。

完全没有任何候选 marker 时为 `already-absent`；存在一个合法预期组件而缺少另一个时记录 `incomplete` finding，并以发现主状态 `ambiguous` 阻断。

只有以下唯一集合可进入确认：

- 恰好一个 Luna component；
- 恰好一个 Small Worker component；
- product ID 正确；
- installation ID 相同；
- 没有未知或重复 component；
- 没有其它完整、残缺或损坏的 AgentPorter 安装集合。

任何 AgentPorter 协议异常都会让整个扫描结果零删除，即使同时存在一个表面完整的集合。卸载器报告全部 finding，并按以下优先级给出主状态：

```text
unsafe-path / invalid-marker
→ unknown-component
→ duplicate-component
→ multiple-installations / installation-conflict
→ incomplete
```

### 5.2 删除计划和确认

进入确认前重新读取两个标记，并为每个目标记录：

- 当前 Profile 名和规范绝对路径；
- product/component/installation ID；
- Profile 目录与标记普通文件的 `lstat` 身份（至少 `st_dev`、`st_ino`、类型）；
- 标记内容哈希。

界面显示当前名称、完整路径、component 和 installation ID 摘要，并警告整个 Profile 会被永久删除，包括用户后来加入的：

- config、SOUL；
- `.env`、`auth.json`；
- memories、sessions；
- skills、cron、MCP；
- logs、state databases 及其它 Profile-local 文件。

用户必须输入固定格式且绑定当前 installation ID 的短语：

```text
DELETE AGENTPORTER <installation_id 前 8 位>
```

取消或不匹配时零删除。卸载器没有静默参数。

### 5.3 集合级最终重验

用户确认后、任何删除发生前，对两个目标全部重验。集合快照绑定确认时解析出的实际 Hermes home/Profile 根；若环境、配置或解析结果切换到另一根，即按 `unsafe-path` 失败，不能在新根重新发现替代目标：

1. 仍位于同一实际 Profile 根直属层级；
2. 不是 `default`，没有符号链接或路径越界；
3. product/component/installation ID 和内容哈希未变；
4. 目录和标记文件的 `st_dev`、`st_ino`、类型未变；
5. 当前 basename 通过目标 Hermes 版本的原生名称规范化与校验，规范化结果与 basename 完全一致，且不会被解析成命令选项。

任一失败：整组零删除。集合级重验全部通过后才进入删除阶段；每个目标调用 Hermes 前仍立即重复同一重验。

### 5.4 删除执行、验证与平台限制

内部用参数数组、`shell=False` 调用 Hermes 原生删除；当前名称仅是执行参数。Hermes v0.20 的 Profile 名校验只接受以字母或数字开头的 `[a-z0-9][a-z0-9_-]{0,63}`；实现仍须执行“原生 normalize 后与 basename 完全一致 + 原生 validate”，并可同时使用 argparse 支持的标准 `--` 参数终止符。`--` 只是附加防御，不能替代名称校验或对象重验。禁止 AgentPorter 自己使用 `rm -rf` 兜底。

这里的“原生删除”不是“底层不递归删除目录”：Hermes 自身会停止该 Profile 的服务/后端、清理 wrapper，并递归移除整个 Profile。AgentPorter 的边界是只调用已重验目标的 Hermes 删除接口，不在原生命令失败后自行扩大范围或直接强删目录。

每个删除成功后双重验证：

1. Hermes Profile 枚举中已不存在；
2. 确认时记录的目标路径已不存在。

结果状态：

| 层级 | 状态 | 含义 |
|---|---|---|
| 发现主状态 | `already-absent` | 没有任何 marker 候选，成功退出 |
| 发现主状态 | `ambiguous` | 存在 `invalid-marker` / `unknown-component` / `duplicate-component` / `installation-conflict` / `multiple-installations` / `incomplete` 等 finding，确认前整组零删除 |
| 交互结果 | `cancelled` | 用户取消或确认不匹配，整组零删除 |
| 集合重验结果 | `marker-changed` / `unsafe-path` | 删除前集合重验失败，整组零删除 |
| 逐项目结果 | `deleted` | 原生删除和双重读回成功 |
| 逐项目结果 | `delete-failed` | Hermes 原生删除未成功 |
| 逐项目结果 | `verification-failed` | 原生命令成功但枚举或路径读回未证明删除完成 |
| 集合结果 | `partial-delete` | 至少一个目标已删除后，后续目标变化、删除失败或验证失败，剩余操作停止 |

### 5.5 发布版软件包自清理

`agentporter-uninstall` 从 POSIX 发布版引导脚本的固定布局运行时，在 Profile 集合结果为 `deleted` 或 `already-absent` 后继续完整卸载：

1. 发布版引导脚本在原子发布前写入受限权限的 `bootstrap-install.json` ownership receipt；卸载时从当前 Python 解释器反推固定 `agentporter/<version>/venv` 布局，再以 receipt 读取并验证精确公开入口，不以卸载时可变的 HOME/XDG 环境作为授权；
2. receipt 使用固定 schema/product/version/public-entry 字段；计划封印 receipt 内容与身份、版本安装目录、解释器、私有卸载入口及公开 symlink 的设备/inode/type，并要求 symlink 精确指向该私有入口；
3. 清理前整体重验；任一对象变化、非普通类型、非 symlink、目标不匹配或隔离名冲突时停止，报告 Profile 已删除但软件包清理不安全；
4. 先把精确版本目录原子改名到同一产品根内的事务隔离名并重新验证被移动对象及内部 receipt/解释器/入口身份；公开 symlink 也先原子改名到同目录隔离名并重验 inode/type/target，只有隔离对象仍匹配才删除；最后删除版本隔离目录，产品根仅在为空时删除；
5. 不删除其它版本、不删除源码 checkout 或源码虚拟环境，也不因 Profile 删除失败/部分删除而清理软件包；
6. `python uninstall.py` 这类非发布布局只执行 Profile 卸载，返回 `not-bootstrap-install`，绝不推测可删除路径。

自清理使用已封印的产品专属目录删除，而不是 Hermes Profile 删除失败后的目录强删兜底；两者权限边界不同。进程已装载的 Python 代码允许在 POSIX 上删除其隔离后的环境，但任何清理异常必须以非成功退出并保留可诊断残留。

Hermes v0.20 的 `profile delete` 仅按名称执行，没有原子 identity-conditioned delete。最终重验和 Hermes 再次解析名称之间存在无法完全消除的竞态。因此：

- 不宣称完全 TOCTOU 防护或原子卸载；
- 最终重验必须紧邻子进程启动；
- 确认界面提示卸载期间不要并发 rename/replace；
- 集合级重验失败保证整组零删除；
- 第一个删除后才发生变化或失败时，只能停止剩余操作并如实报告 `partial-delete`。

## 6. 安装后的职责边界

临时 staging 会被删除，而 Hermes 记录的本地 source 随后失效，因此 v0.1.0 不承诺原生 `profile update`。现有代码只提供工作组 Profile 的一次性安装入口和独立卸载脚本；它没有创建 Kanban 任务、配置自动分解、运行 dispatcher 或启动 gateway。

这不再是 AgentPorter 的完整产品边界。后续 [Plan 02](plan/02-multi-agent-orchestration.md) 将在不回退本安装/卸载合同的前提下，复用 Hermes 原生 Kanban/decomposer/dispatcher 接通任务分解与路由。Plan 02 新增 orchestrator 时不得回写 v0.1.0 两个 Worker 的 marker schema 或 distribution version；新组件继续使用当前可解析的 `MarkerV1`，并记录包含它的新产品发布版本。安装/升级/卸载必须兼容两种完整集合：legacy 双组件，以及按同一 installation ID 附加 orchestrator 的三组件；任何 partial、未知 component、重复、旧组件 drift 或无法解释的版本组合继续 fail closed。三组件卸载默认保留共享 Kanban boards/tasks，运行中的 orchestrator gateway/dispatcher 或 running tasks 会阻断删除。

## 7. 验收矩阵

### 7.1 安装语义与禁止副作用

| ID | 验收项 |
|---|---|
| INS-01 | Hermes 缺失、版本不支持、staging 非法或任一初始名冲突时零写入 |
| INS-02 | 不修改 default 或预先存在的 Profile |
| INS-03 | 不复制凭证、记忆、会话、日志、私有路径或私有 base URL |
| INS-04 | 安装、静态读回和补偿路径对模型调用均为零 |
| INS-05 | 单项 marker 的 installation ID 等于本事务 ID，且该项创建、marker、source 证据完整时即可进入 verified-compensable；集合成功另验两个实际 Profile |
| INS-06 | 每个补偿删除前重验 Hermes 根未切换、快照路径仍存在，且路径、inode/type、marker 哈希、三个 ID 与 basename 均匹配快照；不得追踪 rename 或重新搜索，replace/占名/身份不确定时不误删，并报告 compensation-incomplete |
| INS-07 | description、config、SOUL 和标记读回与 Worker 计划一致；两项完成后的集合校验要求两个实际 Profile 均绑定本事务 ID 且 component 集合完整唯一 |

### 7.2 卸载语义与禁止副作用

| ID | 验收项 |
|---|---|
| UN-01 | 原名、现名、Portable ID、Display name、description 均不参与身份比较 |
| UN-02 | 两个 Profile 同时批量重命名后仍可发现 |
| UN-03 | 缺失、损坏、重复、未知、冲突或多个安装集合时整组零删除 |
| UN-04 | 用户取消、确认错误或集合级最终重验失败时整组零删除 |
| UN-05 | 不删除 default、无关 Profile 或使用目录强删 |
| UN-06 | 删除前完整警告 Profile-local 数据损失，确认短语绑定 installation ID |
| UN-07 | 每项调用前重验；原生删除后枚举与路径双重读回 |
| UN-08 | 首次删除后的并发变化或失败停止剩余操作；逐项给出 delete-failed/verification-failed 等原因，集合报告 partial-delete |
| UN-09 | 文档和报告如实披露 Hermes 非原子按名称删除竞态 |
| UN-10 | 发布版入口仅在 Profile 全部删除或已不存在后清理精确 symlink、当前版本私有环境及空产品目录；源码运行、其它版本、身份漂移和失败/部分删除路径均不被清理 |

### 7.3 边界和交付

| ID | 验收项 |
|---|---|
| GATE-01 | 所有测试使用临时 HOME/HERMES_HOME |
| GATE-02 | 覆盖 Profile 单个改名、两个批量改名及同时修改显示信息 |
| GATE-03 | 覆盖单组件、重复/未知组件、ID 冲突、多个完整集合、损坏/超大标记 |
| GATE-04 | 覆盖 symlink/path escape、inode 替换、非法/非规范 basename 和 TOCTOU 状态 |
| GATE-05 | 命令执行使用参数数组与 shell=False |
| GATE-06 | lint、type、测试、Markdown 链接、git diff 和隐私扫描通过 |
| GATE-07 | 临时 Hermes 根真实演练原生安装、补偿 TOCTOU（rename/replace/占名）、批量 rename、独立卸载及双重读回，并按 Plan 01 保存安装/扫描/删除性能与资源基线；安全语义不得被性能平均值抵消 |
| GATE-08 | 不把代码存在、离线测试、正式入口接通和真实 Hermes 验收混为完成 |
| GATE-09 | 提交前通过交付门禁并核验公开 Git 身份；push 前取得用户明确授权 |
