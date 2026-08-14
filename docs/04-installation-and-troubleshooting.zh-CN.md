# 安装、故障排查与安全发布

> **v0.2.1 本地 release candidate（当前权威；尚未 push、tag 或发布）：** 当前产品恰好只有 `bounded_worker` 与 `mechanical_worker` 两个 Worker Profile；主 Hermes agent 是 orchestrator，不再有独立 orchestrator Profile。v0.2.0 确实发布了错误的第三个 `agentporter-orchestrator`；下文三 Profile 叙述仅是历史发布/阶段证据。legacy 组件现在仅支持发现/卸载，以及单独确认的迁移删除。fresh install、activation、canary 均闭合为两个 binding/call。


[English](04-installation-and-troubleshooting.md) | 简体中文

AgentPorter v0.2.0 是最新正式非预发布版；tag、7 个托管 assets、verifier、fresh HTTPS clone、隔离 wheel import 与公开 `latest` bootstrap 回读均通过。该发布版历史上确实使用三个 Profile（含 `agentporter-orchestrator`），但这是错误拓扑。修正后的 fresh install 只使用 `agentporter-bounded-worker` 与 `agentporter-mechanical-worker`，并为两者显式封闭 model/provider/endpoint。精确旧默认名只能经 `agentporter-activate` 独立确认的 Hermes-native journaled rename 迁移；用户改名保留。Hermes v0.20.0 是**已观察版本**，不是承诺的最低版本或通用兼容范围。

## curl 一键安装（POSIX）

无需指定版本即可安装最新非预发布版本：

```bash
curl --fail --location --proto '=https' --tlsv1.2 \
  https://github.com/KumaCool/AgentPorter/releases/latest/download/install.sh | sh
```

GitHub 的 `latest` 端点选择发布版引导脚本；该脚本再固定并下载自身版本的 wheel 与 `.sha256` 文件，在私有同级暂存目录中完成校验、安装和版本回读，验证并将三个生成入口的 shebang 改写为最终虚拟环境路径，然后才原子发布版本化安装目录。之后在 `${XDG_BIN_HOME:-$HOME/.local/bin}` 建立 `agentporter-uninstall` 链接，并通过 `/dev/tty` 启动原有交互式安装器。已有安装目录或卸载入口时会拒绝覆盖。若用户取消或产品安装失败，已校验的软件包和卸载入口会保留，便于诊断或清理。日后成功卸载 Profile 后，该发布版卸载入口也会清除自身链接和对应版本私有 Python 环境。

校验和能防止意外损坏或托管错配，但它与 GitHub Release 账户并非独立信任源。wheel 声明的依赖仍由 pip 解析下载（仅允许二进制分发），Release 校验和不会独立认证这些依赖下载。如需更强来源保证，请先检查脚本，并核对发布证明与校验和。必要时将 `${XDG_BIN_HOME:-$HOME/.local/bin}` 加入 `PATH`。

## 前置条件

- Python 3.11 或更高版本；
- 已安装 Hermes Agent，并能发现预期的 `hermes` 可执行文件；
- 标准输入连接真实终端，因为安装和卸载都必须交互确认；
- 对重要 Hermes 配置先做干净备份。

Linux 的真实 Hermes 验收证据最强。macOS 和 Windows 纳入离线 CI 矩阵；这能证明可移植契约，不代表已在这些主机上完成 Hermes 原生验收。

## 从发布制品安装

如需测试本地生成的 v0.2.1 candidate wheel，请先验证校验和并建立隔离环境：

```bash
python -m venv .venv
# POSIX: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install agentporter-0.2.1-py3-none-any.whl
agentporter
```

`agentporter` 没有面向用户的参数或子命令。它会检测 Hermes、完整校验清单和目标集合、建立私有暂存区、一次性展示精确计划，并要求输入屏幕显示的确认短语。请逐项审核目标；取消或短语错误不会开始原生安装写入。

## 已发布引导脚本边界

源码树中的 candidate `install.sh` 固定到未来不可变的 `https://github.com/KumaCool/AgentPorter/releases/download/v0.2.1` assets；由于该 candidate 仅存在于本地，这些 assets 尚不存在。已发布 v0.2.0 及其不可变 URL 保持不变，公开 `latest` alias 仍选择 v0.2.0。7 个托管 assets 全部下载并通过字节/校验和比较与 release verifier；fresh HTTPS clone、隔离 wheel import 和公开 `latest/download/install.sh` 字节比较也已通过。

## 从源码运行

```bash
git clone <已验证的仓库地址>
cd AgentPorter
python -m venv .venv
# 按上文激活环境
python -m pip install -e .
python install.py
```

源码和制品都必须来自可信提交。不要运行脏工作树或下载不完整的代码。

## 结果与边界

终端状态会区分：成功、取消、预检失败、安装失败且补偿完成、补偿不完整、回读失败。只有明确成功结果才表示安装成功；不能根据部分 Profile 目录存在就推断成功。

v0.2.0 发布版以上述三个职责名安装两个专用 Worker Profile 和一个专用 orchestrator Profile。安装、rename 与静态读回不会覆盖用户改名、调用模型、安装常驻服务或创建任务数据库；binding 配置和 provider definition 继承仍属于独立确认的 activation。Profile 内凭据和其他运行数据仍由 Hermes 与用户管理。

静态 orchestrator 配置已经安装并读回，但自动分解仍关闭；AgentPorter **不会**启动 Gateway、创建 Kanban 任务、启用 live routing 或证明真实任务路由。上述能力由[多代理编排与路由计划](plan/02-multi-agent-orchestration.md)负责。

## 独立卸载

安装 wheel 后，请运行其专用卸载控制台入口：

```bash
agentporter-uninstall
```

卸载器没有静默参数。它先只读扫描一套完整、标记绑定的安装，展示当前名称（即使已经重命名）与路径，并明确警告：所有 Profile 本地数据及后续自定义都将删除；随后要求输入绑定安装 ID 的精确短语。确认后，它会重新验证完整集合，并在每次 Hermes 原生删除前再次验证目标。所有目标确认不存在后，通过发布版引导脚本安装的入口会验证安装器写入的 ownership receipt 和自身精确版本布局，分别原子隔离并重验版本目录与公开链接，再删除私有环境；只有产品目录为空时才删除它。入口、解释器、链接或安装目录身份变化会阻断软件包清理，且绝不删除其它已安装版本。

如明确从可信源码检出运行，则改用 `python uninstall.py`。源码运行只删除 Profile，不删除源码仓库或其虚拟环境。

如果发现缺失、不完整、重复、冲突、标记损坏、确认后变化、符号链接或路径逃逸，卸载器会停止且不会扩大范围。单项删除失败可能造成部分完成；不要手工递归删除未知目录。确认前先备份需要的 Profile 本地数据。

## Runtime readiness 与编排状态

| 维度 | 当前状态 |
|---|---|
| installation | v0.2.0 已正式发布；tag、7 个托管 assets、verifier、fresh HTTPS clone、隔离 wheel import 与 `latest` bootstrap 字节回读均通过。 |
| public entries | v0.2.0 打包三个入口；旧名迁移只能经独立确认的 `agentporter-activate` 到达。 |
| binding/credential | v0.2.0 fresh install 在 staging 前要求三个 Profile 显式 model/provider/endpoint；凭据仍由 Profile/操作者持有。 |
| canary/live call | 真实调用以 `No inference provider configured`失败；`config check`仍只证明静态有效，不是canary证据。 |
| route proof | Hermes v0.20 usage可提供 model/provider/api_calls，但缺 tool/fallback字段；0.1.5成功调用先标为 incomplete proof。 |
| dispatcher/route | Gateway未由AgentPorter启动；Kanban mutation和live routing未验收。 |
| continuity | `DispatchReceipt`、任务订阅（`notify-list`）、运行观察和结构性恢复仍仅有离线合同；不声称真实通知或接续。 |

Plan 06 代码/离线、tag、release 与托管制品读回门禁均已闭合，但未执行真实模型 canary、Gateway 变更或 Kanban mutation/live routing；这些 live 行为分别需要授权。v0.2.0 不能称为 `operational`，也不修改 Hermes 源码。

## 故障排查

| 现象 | 含义与恢复 |
| --- | --- |
| 找不到 Hermes 或命令面不兼容 | 安装/修复 Hermes，确保预期可执行文件位于 `PATH`，再启动 AgentPorter。不要手工创建目标目录。 |
| 目标 Profile 已存在 | AgentPorter 不会覆盖。确认所有权后通过 Hermes 保留、重命名或删除，也可取消。 |
| 非交互输入被拒绝 | 在真实终端运行；系统有意不提供 `--yes` 或自动化绕过。 |
| 预检/暂存失败 | 原生安装通常尚未开始。修复权限、空间或源码/清单完整性后重试。 |
| 安装失败且补偿完成 | 本次事务创建的 Profile 已移除；修复报告原因后可重试。 |
| 补偿不完整或回读失败 | 立即停止，保存脱敏输出，并使用 Hermes 原生列表检查。不要盲目重跑或递归删目录。 |
| 卸载报告 absent | 未找到完整 AgentPorter 标记集合；核对 Hermes 配置根与发布源。 |
| 卸载报告 ambiguous/conflicting/changed | 不继续删除最安全。仅在来源确定时从备份恢复标记，否则私下报告。 |
| 原生删除或验证失败 | 可能残留部分 Profile。用 Hermes 原生列表/回读确认，保留数据，查明原因后再重试。 |

不要在公开 issue 中粘贴原始配置、标记路径、凭据、会话、记忆或私有主机名。请遵守 [SECURITY.md](../SECURITY.md)。

## 维护者安全发布流程

1. 从干净且已审查的提交开始，使用空的临时构建目录。
2. 运行 [CONTRIBUTING.md](../CONTRIBUTING.md) 中精确的离线门禁。
3. 对明确选择的已观察 Hermes 版本运行手动真实 Hermes workflow；不得注入供应商密钥。
4. 使用 `python -m build --outdir <空目录>` 构建且只生成一个 wheel 和一个 sdist。
5. 对齐最终打包契约后，运行 fail-closed 验证器：

   ```bash
   python scripts/verify_release.py \
     --version 0.2.1 \
     --dependency 'pydantic<3,>=2' \
     --dependency 'PyYAML<7,>=6' \
     --entry-point 'agentporter=agentporter:main' \
     --entry-point 'agentporter-activate=agentporter.activation_entry:main' \
     --entry-point 'agentporter-uninstall=agentporter.uninstall_entry:main' \
     --resource 'resources/workers.yaml' \
     --required-module activation_application.py \
     --required-module activation_entry.py \
     --required-module bootstrap_txn.py \
     --required-module dispatch_application.py \
     --required-module dispatch_planning.py \
     --required-module hermes_runtime.py \
     --required-module legacy_migration.py \
     --required-module kanban_runtime.py \
     --required-module readiness.py \
     --required-module runtime_authority.py \
     --required-module runtime_binding.py \
     --required-module runtime_observation.py \
     --required-module runtime_probe.py \
     --required-module plan06_role_bindings.py \
     --required-module role_identity_compat.py \
     --required-module role_name_migration.py \
     --required-module role_name_migration_application.py \
     --bootstrap-checksum <wheel>.sha256 \
     --bootstrap-source-sha256 4b0ae3ca6204181201df1654a1c310e7f764db02183cb527345ae3d82f3928fa \
     <wheel> <sdist>
   ```

6. 上传前检查校验和、提交身份、标签、变更日志、许可证、README 与验证器输出；只发布已经验证的同一字节序列。
7. 下载托管制品，重新计算校验和并重跑验证。仅有标签或上传成功不构成验收。

示例资源路径是 v0.2.0 发布契约。托管发布验收已下载全部公开制品、重新计算校验和、重跑验证器，并字节比较公开的 `latest/download/install.sh` 端点；全部通过。

## 历史 0.1.7 串联激活修订

当 `/dev/tty` 不能被实际打开并验证为终端时，bootstrap 现在会在下载或创建安装路径之前失败；仅“路径可读”不再视为交互终端授权。

交互安装计划成功后，bootstrap 会通过同一个真实终端直接启动 `agentporter-activate`，不再增加是否进入激活的选择。激活仍保留绑定确认，并对真实模型调用单独披露和确认。Hermes v0.20 的 custom Provider 跳过不支持的裸 Provider 认证命令，在既有 descriptor-bound 配置事务中把主/default Profile 的完整所选 Provider 定义复制到各 Worker。当前 keyed `providers.<id>` 与兼容的 list-shaped `custom_providers` 两种 schema 均受支持，且不会相互转换或重复物化。激活失败时保留已安装 Profiles 和公开重试命令，并返回非零状态。

## 修正后的双 Worker activation 与 canary

当前 activation 恰好处理两个 Worker binding，live 授权最多覆盖两次 Worker 调用。canary timeout 默认 30 秒，可配置为 90 秒。继承定义的 `key_env` 未解析时返回 `credential-required`，除非目标 Profile 自己的 `.env` 可解析。封印的具体 custom Provider 通过 canonical `custom` 调用；exit-zero 但 usage 标记 `failed` 仍按封闭安全原因失败。
