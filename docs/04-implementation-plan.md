# AgentPorter Hermes 一键安装实施计划

## 状态

- **产品方向：** 已确认，Hermes-first；
- **设计：** Hermes-first 方向已批准；实现候选仍需按本文门禁复审；
- **代码：** 未实现；
- **离线测试：** 未建立；
- **Hermes 真实安装验收：** 未执行；
- **Codex：** 仅保留未来接口位置，不在当前计划内；
- **发布：** 未开始。

## 第一版完成定义

用户在已安装受支持 Hermes 的机器上启动一次 AgentPorter 安装器，即可完成两个 Worker Profile 的集合级预检、计划、确认、原生安装、description 写入、静态读回和失败补偿。默认不复制凭证、不覆盖 Profile、不发起模型调用。

## Phase 1：Schema、Hermes 检测与纯渲染

### RED/GREEN 交付

1. 建立 Python 包、单一安装入口和测试骨架；
2. 为 `workers.yaml` 建立 schema 与领域模型；
3. 锁定 portable ID、Hermes Profile 名和保留名校验；
4. 定义 `HermesAdapter` 与最小 `unsupported platform` 边界；
5. 检测 `hermes` 路径、版本、`HERMES_HOME` 和现有 Profile；
6. 渲染每个 Worker 的 `distribution.yaml`、`config.yaml`、`SOUL.md`；
7. 对 staging 执行 schema、symlink、秘密和私人路径扫描。

### 验收

- 每个行为先有预期失败的测试，再做最小实现；
- 非法 tier、reasoning、ID、空 instructions 和 Hermes 保留名被拒绝；
- 除必需的 `distribution.yaml` 外，可安装 payload 只包含显式 `distribution_owned` 文件；
- provider 未指定时不会猜测 `custom` 或复制当前 Profile；
- 所有测试使用临时 HOME/HERMES_HOME；
- Codex 名称可存在于未来接口测试，但不产生文件或安装路径。

## Phase 2：集合计划与禁止副作用

### RED/GREEN 交付

1. 聚合两个 Worker 的单次安装计划；
2. 在写入前完成全部冲突和版本检查；
3. 输出模型/provider readiness 与五级验证状态；
4. 实现一次交互确认；第一版不提供静默确认参数；
5. 对命令执行器使用参数数组，禁止 shell 拼接；
6. 添加“调用即失败”守卫，证明 dry-run、冲突和 unsupported 路径不写任何 Profile。

### 验收

- 任一目标 Profile 已存在时，两个 Profile 均零写入；
- Hermes 缺失、版本不满足、staging 非法时零写入；
- 确认步骤不绕过预检和验证；
- 输出不包含凭证值、私有 base URL 或个人路径；
- default Profile 的文件哈希在所有失败路径保持不变。

## Phase 3：Hermes 原生安装与补偿

### RED/GREEN 交付

1. 通过 Hermes 原生 `profile install <local-staging> --name ... --yes` 安装；
2. 使用 `profile describe --text` 设置路由描述；
3. 使用原生命令枚举并读回 Profile、distribution 和 config；
4. 区分“安装命令确认创建”“身份已验证可自动删除”“创建或身份不确定”三类状态；
5. 第二个安装、description 或静态验证失败时，只对身份已验证的本次新建 Profile 逆序补偿；
6. 读回失败或身份不一致时 fail closed，不删除未知 Profile，并以补偿不完整退出。

### 验收

- 临时 Hermes 根中两个 Profile 均安装且字段一致；
- 不使用 `--force`，不覆盖同名 Profile；
- 人为注入第二个安装失败后，第一个本次新建 Profile 被安全删除；
- 预先存在 Profile 和 default Profile 从不被删除；
- 人为篡改第一个 Profile 身份后，补偿停止并明确报告残留；
- 模拟安装命令成功但首次 info/readback 失败时，Profile 被列为不确定残留且不会被误删；
- 安装器结果区分成功、配置待完成、冲突、安装失败和补偿不完整。

## Phase 4：调用指引、Kanban 与真实 Hermes 验收

### 交付

1. 输出直接调用命令；
2. 输出 Kanban assignee + scratch/worktree 示例；
3. 明确 Profile、workspace 和 sandbox 的差异；
4. 在干净临时 Hermes 根执行正式安装入口；
5. 对已验证 Hermes 版本执行 `profile list/show/info`、description 和 config readback；
6. 第一版不提供 live check，并以调用即失败 guard 证明安装路径不发起模型请求。

### 验收

- 同一配置根下从不同项目目录读到同一 Profile；
- worktree 不触发重复安装；
- Kanban 可接受两个 Profile 名作为 assignee；
- 静态验收不声称模型运行成功；
- 安装、静态读回和补偿路径对模型调用均为零；
- 当前开发机证据与最低支持版本声明分开记录。

## Phase 5：开源产品化与首发

### 交付

- `pyproject.toml`、版本策略、变更日志和单一安装启动入口；
- Linux/macOS/Windows CI；
- 经验证的 Hermes 兼容矩阵；
- 干净环境包安装和一次性安装演练；
- 中英文用户安装/故障排查文档；
- 发布前复核 `LICENSE`、`CONTRIBUTING.md`、`SECURITY.md`；
- sdist/wheel 内容和隐私扫描；
- 版本标签、GitHub Release 和下载后产物验证。

### 完整门禁

1. schema 与策略测试；
2. HermesAdapter 单元测试；
3. 临时 HOME/HERMES_HOME 集成测试；
4. 禁止副作用 guard 测试；
5. 集合补偿与身份变化测试；
6. 支持版本 Hermes 原生接口静态验收；
7. 证明第一版安装路径不发起模型请求；
8. lint、format、type、Markdown 链接与隐私扫描；
9. sdist/wheel 构建、内容检查和干净安装；
10. 新鲜克隆对发布标签与一次性安装产物复验。

## 一次性产品边界

AgentPorter 只负责首次安装并退出，不提供子命令体系、后台服务、升级、修复或卸载能力。临时 staging source 也不支持可靠的原生 `profile update`。任何后续生命周期需求均不属于当前产品，不能以预留命令或未验收入口进入实现。

## Codex 延后条件

Codex 不占用以上任何 Phase。未来只有在用户另行批准且取得真实 Codex CLI 证据后，才创建独立设计和实施计划。保留接口不得演变成猜测性配置生成器。

## 提交与交付纪律

- 每个 Phase 在 focused tests 和完整门禁通过后提交；
- 提交前扫描 staged/index 树中的秘密、个人路径和环境专属值；
- 使用公开仓库认可的 GitHub noreply 身份；
- Phase 完成后推送并验证本地与远程 SHA 一致；
- 文档状态、实现状态和真实验收状态必须在同一交付切片同步。
