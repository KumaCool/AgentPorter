# AgentPorter

[English](README.md) | 简体中文

AgentPorter 是一个开源的 [Hermes Agent](https://hermes-agent.nousresearch.com/) 多代理工作组部署方案：一次安装多个职责明确的 Worker Profile，并逐步接通 Hermes 原生 Kanban 的任务分解与合理路由。

> **当前能力：** v0.1.2 已安全交付双 Profile 安装/卸载基础，并写入 routing description；Hermes 能只读枚举两个 assignee。但 AgentPorter 尚未配置或验收自动分解、dispatcher 执行和真实 Worker 路由。这是下一阶段计划，不是当前发布能力。

## curl 一键安装（POSIX）

Linux 和 macOS 用户无需指定版本即可安装最新正式版本：

```bash
curl --fail --location --proto '=https' --tlsv1.2 \
  https://github.com/KumaCool/AgentPorter/releases/latest/download/install.sh | sh
```

`latest` 端点选择最新的非预发布 GitHub Release；下载到的引导脚本仍固定该版本及其精确制品。如需更高可信度，请先下载并检查 `install.sh` 再执行。引导脚本要求 Python 3.11+ 和真实终端，使用 `.sha256` 校验 wheel 后安装到独立虚拟环境，在 `${XDG_BIN_HOME:-$HOME/.local/bin}` 发布独立卸载入口 `agentporter-uninstall`，并通过 `/dev/tty` 启动原有交互式安装计划。它不会绕过确认，也不会代装 Hermes。

安装完成后，如需卸载，直接在真实终端运行：

```bash
agentporter-uninstall
```

如果终端提示找不到命令，请运行完整路径：

```bash
"${XDG_BIN_HOME:-$HOME/.local/bin}/agentporter-uninstall"
```

卸载会删除 AgentPorter 安装的 Worker Profile 及其中的本地数据和后续自定义；确认前请先备份。Profile 删除成功（或已不存在）后，通过发布版引导脚本安装的卸载器还会删除自身的精确公开入口和对应版本私有 Python 环境。从可信源码检出运行的 `python uninstall.py` 只删除 Profile，绝不删除源码仓库或其虚拟环境。检查后执行方式、PATH、信任边界与完整卸载说明见[安装指南](docs/04-installation-and-troubleshooting.zh-CN.md)。

## v0.1.2 安装内容

一次运行会安装仓库当前的双 Profile Worker 基础：

- `luna_worker`：在父 Agent 已明确目标、范围、约束和验收标准后，执行有边界的实现与分析任务；
- `codex-5-3-small-worker`：负责范围更窄、严格机械化的委派任务。

每个 Profile 都包含 Hermes 原生配置、指令、路由描述以及一个非秘密的所有权标记。AgentPorter 组合 Hermes 原生能力，不替代 Profile 存储、Kanban 任务库、decomposer、dispatcher、worktree 或供应商配置。

## 产品方向：先部署工作组，再合理分配任务

项目重点不只是复制 Profile 文件。完整产品应让用户提交任务后，由 AgentPorter 的专用 orchestrator 调用 Hermes 分解器取得候选、在写入任务前按职责验证，再由 Hermes 在合适的 workspace 中执行，并返回可验证的交接结果。

当前版本只完成了该流程的安全安装基础。缺失的编排主线已经正式纳入：

- [计划索引与当前状态](docs/plan/00-index.md)
- [多代理编排与路由实施计划](docs/plan/02-multi-agent-orchestration.md)

在该计划通过真实验收前，请使用 Hermes 原生 Kanban 手动指定任务；不要把 Profile 安装或 description 读回当作自动路由已经可用。

## 安全边界

安装前，AgentPorter 会对完整集合执行预检，展示一次精确计划并要求交互确认；随后通过 Hermes 原生命令安装、静态回读结果，并在失败时执行有界补偿。它不会：

- 覆盖已有或 `default` Profile；
- 复制凭据、令牌或供应商配置；
- 调用模型；
- 安装常驻服务；
- 保存任务数据库。

独立卸载器使用固定的产品、组件和安装 ID 标记识别 AgentPorter Profile，因此即使两个 Profile 都被重命名，仍可安全发现。卸载前会警告所有 Profile 本地数据及后续自定义都将被删除，要求输入与 installation ID 绑定的确认短语，并在删除前重新验证集合和每个目标。集合歧义或身份变化时一律 fail closed。

## 从源码快速开始

要求：

- Python 3.11 或更高版本；
- 已安装且可发现预期的 Hermes 可执行文件；
- 标准输入连接真实交互终端。

```bash
git clone https://github.com/KumaCool/AgentPorter.git
cd AgentPorter
python -m venv .venv
# POSIX: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e .
python install.py
```

AgentPorter 不提供面向用户的参数或子命令。请完整阅读屏幕上的安装计划，然后输入所显示的精确确认短语。

从可信源码检出卸载：

```bash
python uninstall.py
```

如果通过 wheel 安装，则使用专用控制台入口：

```bash
agentporter-uninstall
```

确认卸载前，请备份 Profile 内需要保留的凭据、记忆、会话、技能、日志及其他自定义内容。

## 安装制品与故障排查

完整的 wheel 安装方法、状态含义、恢复建议、平台证据边界和安全发布流程见：

- [安装、故障排查与安全发布 — 简体中文](docs/04-installation-and-troubleshooting.zh-CN.md)
- [Installation, troubleshooting, and safe release — English](docs/04-installation-and-troubleshooting.md)

## 平台与兼容性证据

离线 CI 在 Linux 和 macOS 的 Python 3.11–3.13 上运行完整可移植测试及打包/发布契约；Windows 运行格式、lint、以 Linux 为目标的严格类型检查和分发构建，不声称能原生执行依赖 POSIX 描述符或归档 mode 语义的契约。真实 Hermes 验收单独在 Linux 上针对固定、不可变的 Hermes 上游提交运行，因为它需要原生 Hermes 可执行文件和更强的隔离条件。

离线矩阵通过不代表已证明所有平台和 Hermes 版本的原生兼容性。Hermes v0.20.0 是当前真实验收版本，不是通用兼容范围承诺。

## 仓库结构

- `src/agentporter/resources/workers.yaml`：打包内唯一权威 Worker 定义及模型偏好；
- `install.py`、`uninstall.py` 与 `src/agentporter/`：当前一次性工作组部署基础和受保护的独立卸载实现；
- `tests/`：单元、文件系统、事务、压力和隔离真实 Hermes 验收测试；
- `scripts/verify_release.py`：fail-closed 的源码、wheel 和 sdist 发布契约验证器；
- `docs/`：架构、Worker 格式、适配器映射、生命周期设计、实施计划和用户指南。

## 设计与验收文档

- [方案总览](docs/00-solution-overview.md)
- [可移植 Worker 规范](docs/01-portable-worker-spec.md)
- [Hermes Adapter 设计](docs/02-platform-adapters.md)
- [安装、卸载与验收矩阵](docs/03-installation-and-uninstall-design.md)
- [计划索引](docs/plan/00-index.md)
- [v0.1.0 安装基础实施记录](docs/plan/01-installation-foundation.md)
- [多代理编排与路由实施计划](docs/plan/02-multi-agent-orchestration.md)
- [编排接通后的 Worker 验证与基准计划](docs/plan/03-agent-validation-and-benchmark.md)
- [变更日志](CHANGELOG.md)

这些详细设计和计划记录的是工程契约及验收历史，并不构成对所有环境的通用生产就绪声明。首个版本不包含 Codex CLI 平台适配器；Worker 名称也不代表已经支持 Codex CLI。

## 开发、安全与许可证

提交变更前，请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，并执行其中规定的离线门禁和独立真实 Hermes 验收流程。

不要提交凭据、私有运行状态、缓存、模型输出、个人路径或环境敏感数据。安全问题请按照 [SECURITY.md](SECURITY.md) 私下报告。

AgentPorter 使用 [MIT License](LICENSE) 发布。
