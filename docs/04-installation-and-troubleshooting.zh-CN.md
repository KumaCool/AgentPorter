# 安装、故障排查与安全发布

[English](04-installation-and-troubleshooting.md) | 简体中文

AgentPorter v0.1.4 是 Hermes 多代理工作组一次性安装基础的当前受支持修复版本。仓库已经具备离线契约测试，并在隔离环境中对 Hermes v0.20.0 做过真实验收；这个版本只是**已观察版本**，不是承诺的最低版本或通用兼容范围。

## curl 一键安装（POSIX）

无需指定版本即可安装最新非预发布版本：

```bash
curl --fail --location --proto '=https' --tlsv1.2 \
  https://github.com/KumaCool/AgentPorter/releases/latest/download/install.sh | sh
```

GitHub 的 `latest` 端点选择发布版引导脚本；该脚本再固定并下载自身版本的 wheel 与 `.sha256` 文件，在私有同级暂存目录中完成校验、安装和版本回读，验证并将两个生成入口的 shebang 改写为最终虚拟环境路径，然后才原子发布版本化安装目录。之后在 `${XDG_BIN_HOME:-$HOME/.local/bin}` 建立 `agentporter-uninstall` 链接，并通过 `/dev/tty` 启动原有交互式安装器。已有安装目录或卸载入口时会拒绝覆盖。若用户取消或产品安装失败，已校验的软件包和卸载入口会保留，便于诊断或清理。日后成功卸载 Profile 后，该发布版卸载入口也会清除自身链接和对应版本私有 Python 环境。

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

AgentPorter v0.1.4 安装两个专用 Worker Profile。它不会覆盖现有 Profile、复制供应商凭据、调用模型、安装常驻服务或创建任务数据库。Profile 内凭据和其他运行数据仍由 Hermes 与用户管理。

当前版本**不会**配置自动分解、启动 gateway dispatcher、创建 Kanban 任务或证明真实任务路由。上述能力由[多代理编排与路由计划](plan/02-multi-agent-orchestration.md)负责。

## 独立卸载

安装 wheel 后，请运行其专用卸载控制台入口：

```bash
agentporter-uninstall
```

卸载器没有静默参数。它先只读扫描一套完整、标记绑定的安装，展示当前名称（即使已经重命名）与路径，并明确警告：所有 Profile 本地数据及后续自定义都将删除；随后要求输入绑定安装 ID 的精确短语。确认后，它会重新验证完整集合，并在每次 Hermes 原生删除前再次验证目标。所有目标确认不存在后，通过发布版引导脚本安装的入口会验证安装器写入的 ownership receipt 和自身精确版本布局，分别原子隔离并重验版本目录与公开链接，再删除私有环境；只有产品目录为空时才删除它。入口、解释器、链接或安装目录身份变化会阻断软件包清理，且绝不删除其它已安装版本。

如明确从可信源码检出运行，则改用 `python uninstall.py`。源码运行只删除 Profile，不删除源码仓库或其虚拟环境。

如果发现缺失、不完整、重复、冲突、标记损坏、确认后变化、符号链接或路径逃逸，卸载器会停止且不会扩大范围。单项删除失败可能造成部分完成；不要手工递归删除未知目录。确认前先备份需要的 Profile 本地数据。

## Runtime readiness 与编排状态

| 维度 | 0.1.4 候选状态 |
|---|---|
| installation | fresh 三 Profile 与 legacy 双→三升级/读回/改名/卸载已通过离线和隔离 Hermes v0.20 fixture。 |
| binding | 运行 `agentporter-activate`；事务会 snapshot、确认、写入、读回，并只 compare-before-restore 本事务所有值。 |
| credential | 由操作者授权、Hermes/用户持有；AgentPorter 不读取或复制秘密值。 |
| canary | v0.20 为 `probe-unsupported`，零模型调用；`config check` 仍仅是静态检查。 |
| dispatcher | 专用 orchestrator 配置通过静态读回；不启动 Gateway。 |
| route | 适配器调用前 `mutation-unsupported`，零 Kanban mutation 调用。 |
| continuity | DispatchReceipt/订阅/观察/结构性恢复仅通过离线合同，未做真实验收。 |

激活失败会保留 Profile 与凭据所有权；未漂移的事务写入被恢复，并发漂移保留并以有界 residue 报告。无任务时 `notify-list` 为空正常；正式任务创建后，必须先精确读回任务级订阅并生成安全 `DispatchReceipt` 才能解锁 dispatch，当前 v0.20 尚无所需 mutation seam。

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
     <wheel> <sdist>
   ```

6. 上传前检查校验和、提交身份、标签、变更日志、许可证、README 与验证器输出；只发布已经验证的同一字节序列。
7. 下载托管制品，重新计算校验和并重跑验证。仅有标签或上传成功不构成验收。

示例资源路径是 v0.1.4 发布契约。托管发布验收还会下载全部公开制品、重新计算校验和、重跑验证器，并检查公开的 `latest/download/install.sh` 端点。
