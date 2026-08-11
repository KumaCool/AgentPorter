# AgentPorter 实施计划

## 1. 状态与权威来源

- **产品方向：** Hermes-first 已确认；
- **设计与计划：** Plan 01、合并设计与独立 Plan 02 均已确认；
- **代码与测试：** Phase 1–5 已完成：原生分发契约、集合预检与确认、正式安装/静态读回/有限补偿、名称无关独立卸载，以及临时根 Hermes v0.20 正式入口/资源/规模/故障验收均已通过对应阶段集中复审；Phase 6 开源产品化与最终 GATE 尚未完成；
- **真实 Hermes 验收与发布：** 已完成隔离临时根下正式安装、跨目录读回、批量 rename、正式卸载、冷/热资源基线和 120 次故障循环；Kanban 证据限于 parser 与只读 assignee 枚举，未运行 Worker/模型；尚未构建发布产物、执行跨平台 CI、打标签或发布 GitHub Release；
- **Codex CLI Adapter：** 仅保留未来边界，不在当前计划内；Hermes Profile `codex-5-3-small-worker` 仍属于第一版 Worker 集。

实施只解释阶段顺序，不重新定义产品语义。文档职责和权威关系见 [合并设计的文档分工](../03-installation-and-uninstall-design.md#1-文档职责与当前状态)；本计划的 Phase 只提供或关闭对应验收证据，其中所有 GATE 仅由 Phase 6 最终关闭。

## 2. 第一版完成定义

在受支持 Hermes 环境中：

主安装器、独立 `uninstall.py`、Hermes 集成验收和开源产物全部满足 [INS/UN/GATE 权威矩阵](../03-installation-and-uninstall-design.md#7-验收矩阵)。安装完成后的真实 Worker 行为与性能评测由 [Plan 02](02-agent-validation-and-benchmark.md) 独立执行，不阻止本计划交付，也不能改写安装结果。

## 3. Phase 1：领域模型、检测与纯渲染

**当前状态：** 已通过最终 closure review；该状态只说明本阶段证据已验收，不关闭任何最终 GATE。

### RED/GREEN

1. 建立 Python 包、单一安装入口、独立卸载入口和测试骨架；
2. 为 `workers.yaml`、安装标记和结果状态建立 schema/领域模型；
3. 冻结 product ID 与两个 component ID 协议常量；
4. 实现 Portable ID、Hermes 初始名和保留名校验；
5. 检测 Hermes 路径、版本、`HERMES_HOME`、Profile 根和现有 Profile；
6. 渲染每个 Worker 的 distribution、config、SOUL 和名称无关标记；
7. 对 staging 执行 schema、symlink、秘密和私人路径扫描。

### 验收映射

为 `INS-03`、`INS-07`、`GATE-01`、`GATE-03`、`GATE-06` 提供 schema、渲染、临时根和隐私检查基础；所有 GATE 均只在 Phase 6 统一关闭。

## 4. Phase 2：集合预检、计划与确认

**当前状态：** 已通过本阶段集中语义复审。`configuration-required` 仍可静态安装和确认，但不代表运行配置完成；Phase 2 不执行原生安装。

### RED/GREEN

1. 聚合两个 Worker 的单次安装计划；
2. 在任何写入前完成版本、目标初始名和 staging 检查；
3. 输出 provider/model 准备状态和静态验证边界；
4. 实现对当前计划的一次交互确认；
5. 命令执行器使用参数数组和 `shell=False`；
6. 添加调用即失败 guard，证明失败/取消路径零写入、零模型调用。

### 验收映射

完成 `INS-01`–`INS-04` 的 focused 覆盖，并为 `GATE-05` 提供统一命令执行器证据；GATE 不在本阶段关闭。

## 5. Phase 3：原生安装、读回与补偿

**当前状态：** 实现、完整机械门禁及临时根真实 Hermes v0.20 安装/读回/补偿演练已完成并通过本阶段集中语义复审。该状态关闭 Phase 3 实现项，不提前关闭 Phase 6 的最终 GATE。

### RED/GREEN

1. 调用 Hermes 原生 Profile distribution 安装；
2. 设置并读回 description；
3. 读回 distribution、config、SOUL 和完整安装标记；
4. 按权威设计维护 `confirmed-created`、`verified-compensable`、`uncertain-remnant`；
5. 后续失败时按反向安装顺序逐项重验对象快照，仅删除仍匹配的可补偿目标；rename/replace/占名必须降级为不确定残留；
6. 输出确定的安装和补偿结果状态。

### 验收映射

关闭 `INS-01`–`INS-07`。额外故障注入必须覆盖：第一项在第二项安装前即可进入 `verified-compensable`；“先创建后非零退出/超时/中断”会经 post-attempt 枚举转入 `uncertain-remnant`；进入可补偿状态后发生 rename/replace/原名占用时，补偿重验阻止误删并报告 `compensation-incomplete`。

## 6. Phase 4：名称无关独立卸载

**当前状态：** 名称无关发现、封印计划、完整警告、绑定确认、集合/逐项重验、原生删除、双重读回、独立入口及临时根 Hermes v0.20 批量改名卸载演练已完成并通过本阶段集中语义复审。Phase 5–6 最终 GATE 仍保持开放。

### RED/GREEN

1. 只读扫描实际 Profile 根中的 AgentPorter 标记；
2. 归并唯一完整 installation set，拒绝全部异常组合；
3. 展示当前名称、路径、component 和完整数据损失警告；
4. 实现绑定 installation ID 的确认短语；
5. 对两个目标执行集合级最终重验；
6. 每项原生删除前立即重验，并执行枚举/路径双重读回；
7. 直接采用权威设计的精确词汇，不另造简称：发现 finding/主状态、逐项结果和集合结果分层输出；例如第二项原生删除失败时，逐项为 `delete-failed`，集合为 `partial-delete`。

### 验收映射

关闭 `UN-01`–`UN-09`；为 `GATE-02`–`GATE-05` 提供卸载路径证据。测试必须覆盖批量改名、所有异常集合、路径/inode 变化、非规范 basename 和原生删除后的结果分层。

## 7. Phase 5：Hermes 集成验收

**当前状态：** 正式安装/卸载入口的临时根 Hermes v0.20 冷热周期、跨目录读回、批量改名、资源基线，2/10/100/1000 合成根扫描和 120 次故障循环已实现并通过机械门禁及本阶段集中语义复审。Phase 6 最终 GATE 仍保持开放。Kanban 证据限于真实 CLI parser 与只读 assignee 枚举，未创建卡片或触发 Worker/模型运行。

1. 在干净临时 Hermes 根执行正式安装入口；
2. 使用原生命令读回 Profile、description、config、SOUL 和标记；
3. 从不同项目目录证明同一配置根可见；
4. 验证 Kanban assignee 和 worktree 示例；
5. 原生 rename 两个 Profile 后运行独立卸载；
6. 验证枚举与路径均不存在；
7. 证明所有路径不发起模型请求；
8. 记录冷/热安装总时延、单 Profile 时延、Hermes 子进程次数、峰值 RSS、CPU 时间、staging 峰值和最终磁盘增量；
9. 对 2、10、100、1000 个合成 Profile 根分别记录卸载发现扫描耗时；扫描/歧义归类零写入。删除、集合/逐项重验和双重读回时延只在唯一完整两组件安装集合上测量，不能删除合成背景 Profile；
10. 执行至少 100 次安装/卸载与 rename、replace、占名、symlink、inode 替换、根切换、超时和中断故障循环，分别记录安全残留与不安全删除；无关/default Profile 误删必须为 `0`。

这些性能数据在第一版建立可重复基线，不在没有基线时虚构绝对时延阈值；安全语义仍按权威 `INS/UN/GATE` 判定。当前开发机证据与最低支持版本声明必须分开记录。静态验收不得声称模型运行成功。

本 Phase 不运行 [Plan 02](02-agent-validation-and-benchmark.md) 的真实模型任务；后者只能在本计划全部关闭后独立启动。

### 验收映射

为 `GATE-01`、`GATE-02`、`GATE-05`、`GATE-07`、`GATE-08` 提供真实 Hermes/正式入口证据；这些 GATE 只在 Phase 6 完整门禁通过后统一关闭。

## 8. Phase 6：开源产品化

**当前状态：** 打包资源、双 console 入口、版本/元数据、离线跨平台 CI、固定上游提交的真实 Hermes Linux workflow、fail-closed 发布验证器、中英文文档、sdist/wheel 构建及仓库外干净环境安装均已实现并通过集中 closure review。`GATE-01`–`GATE-08` 已由本地候选证据关闭；`GATE-09` 仍等待用户明确授权后执行 push、远程 CI、版本标签、GitHub Release 和托管产物下载回验。

- `pyproject.toml`、版本策略、变更日志、主安装器入口和独立 `uninstall.py`；
- Linux/macOS/Windows CI 与 Hermes 兼容矩阵；
- 中英文安装、卸载和故障排查文档；
- `LICENSE`、`CONTRIBUTING.md`、`SECURITY.md` 复核；
- sdist/wheel 构建、内容与隐私扫描；
- 干净环境安装演练；
- 版本标签、GitHub Release 和下载后产物验证。

## 9. 完整门禁

Phase 6 对 [权威矩阵中的 `GATE-01`–`GATE-09`](../03-installation-and-uninstall-design.md#73-边界和交付) 执行唯一最终关闭；前序 Phase 只提供证据，不得宣称关闭同一 GATE。执行命令、CI job 和产物检查表在实现时维护于单一验证入口，不在本文复制第二份验收清单。

## 10. 提交与交付纪律

- 每个 Phase 通过 focused tests 和适用完整门禁后形成可提交候选；
- 文档状态、实现状态和验收状态必须同步；
- 提交前扫描 staged/index 中的秘密、个人路径和环境值，并验证公开 Git 身份；
- 通过交付门禁后可直接 commit，不再要求逐次用户确认；push 仍需用户明确授权；
- 获批 push 后验证本地与远程 SHA 一致；
- Codex CLI Adapter、升级、修复、后台服务和其它生命周期能力不得进入当前实现。
