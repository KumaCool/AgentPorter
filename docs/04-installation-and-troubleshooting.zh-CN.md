# 安装、故障排查与安全发布

[English](04-installation-and-troubleshooting.md) | 简体中文

AgentPorter v0.1.4 已正式发布。它可以安装并读回三个 Profile，但当前发布版只公开 `agentporter-uninstall`；公共 `agentporter-activate` 缺失，正式 probe也固定为 unsupported，因此安装后两个 Worker仍需要后续 AgentPorter修复才能自动完成 provider/endpoint/Profile-local凭据和真实调用接续。Hermes v0.20.0 是**已观察版本**，不是承诺的最低版本或通用兼容范围。

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

如需手动安装已下载的 v0.1.4 wheel，请先验证发布校验和并建立隔离环境：

```bash
python -m venv .venv
# POSIX: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install agentporter-0.1.4-py3-none-any.whl
agentporter
```

`agentporter` 没有面向用户的参数或子命令。它会检测 Hermes、完整校验清单和目标集合、建立私有暂存区、一次性展示精确计划，并要求输入屏幕显示的确认短语。请逐项审核目标；取消或短语错误不会开始原生安装写入。

## 发布候选引导脚本边界

在托管的 v0.1.4 wheel、校验和与 `install.sh` assets 发布前，源码树中的 `install.sh` **不能作为用户安装入口执行**：它为正式发布预先固定到不可变的 `https://github.com/KumaCool/AgentPorter/releases/download/v0.1.4` assets。当前用户必须继续使用 `https://github.com/KumaCool/AgentPorter/releases/latest/download/install.sh`。发布时必须先上传不可变 assets，再从外部回读 v0.1.4 URL 和 `latest` alias，比较字节与校验和并重跑 verifier。

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

AgentPorter v0.1.4 安装两个专用 Worker Profile 和一个专用 orchestrator Profile；静态 orchestrator 配置已经安装并读回。它不会覆盖现有 Profile、复制供应商凭据、调用模型、安装常驻服务或创建任务数据库。Profile 内凭据和其他运行数据仍由 Hermes 与用户管理。

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
| installation | 0.1.4 已正式发布；fresh/legacy三 Profile生命周期合同和实际安装读回通过。 |
| public entries | 当前公开 `agentporter-uninstall`；`agentporter-activate`只在私有环境，待0.1.5发布。 |
| binding/credential | 两 Worker仍缺 provider/endpoint/Profile-local凭据，保持 `configuration-required`。 |
| canary/live call | 真实调用以 `No inference provider configured`失败；`config check`仍只证明静态有效，不是canary证据。 |
| route proof | Hermes v0.20 usage可提供 model/provider/api_calls，但缺 tool/fallback字段；0.1.5成功调用先标为 incomplete proof。 |
| dispatcher/route | Gateway未由AgentPorter启动；Kanban mutation和live routing未验收。 |
| continuity | `DispatchReceipt`、任务订阅（`notify-list`）、运行观察和结构性恢复仍仅有离线合同；不声称真实通知或接续。 |

当前0.1.4不能通过公共命令完成 activation。后续[0.1.5设计](05-runtime-activation-and-live-call-design.md)将只修改 AgentPorter，发布三公共入口、编排 Hermes原生Profile auth并执行单独授权的真实 one-shot；不会修改 Hermes源码。

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
     --version 0.1.4 \
     --dependency 'pydantic<3,>=2' \
     --dependency 'PyYAML<7,>=6' \
     --entry-point 'agentporter=agentporter:main' \
     --entry-point 'agentporter-activate=agentporter.activation_entry:main' \
     --entry-point 'agentporter-uninstall=agentporter.uninstall_entry:main' \
     --resource 'resources/workers.yaml' \
     --required-module activation_application.py \
     --required-module activation_entry.py \
     --required-module dispatch_application.py \
     --required-module dispatch_planning.py \
     --required-module kanban_runtime.py \
     --required-module runtime_observation.py \
     --required-module runtime_probe.py \
     --bootstrap-checksum <wheel>.sha256 \
     --bootstrap-source-sha256 566e07f77f3f7867b27fdb98e21c2d17f78929c203bd9500431fe82707fa84b6 \
     <wheel> <sdist>
   ```

6. 上传前检查校验和、提交身份、标签、变更日志、许可证、README 与验证器输出；只发布已经验证的同一字节序列。
7. 下载托管制品，重新计算校验和并重跑验证。仅有标签或上传成功不构成验收。

示例资源路径是 v0.1.4 发布契约。托管发布验收还会下载全部公开制品、重新计算校验和、重跑验证器，并检查公开的 `latest/download/install.sh` 端点。
