# AgentPorter

[English](README.md) | 简体中文

AgentPorter 是一个预发布、开源、一次性运行的安装器，用于安装可复用的 [Hermes Agent](https://hermes-agent.nousresearch.com/) Worker Profile。

> **证据状态：** Phase 1–6 已通过本地实现、对抗性测试、打包、制品检查及隔离 Hermes v0.20.0 验收，全程未调用模型。发布流程仍未完成：远程 CI、版本标签、GitHub Release 与托管制品下载回验尚未全部关闭，因此目前没有受支持的正式版本。Hermes v0.20.0 是已经实际验收的目标，不代表承诺的最低版本。

## curl 一键安装（POSIX）

受支持版本正式发布后，Linux 和 macOS 用户可运行：

```bash
curl --fail --location --proto '=https' --tlsv1.2 \
  https://raw.githubusercontent.com/KumaCool/AgentPorter/v0.1.0/install.sh | sh
```

如需更高可信度，请先从不可变版本标签下载并检查 `install.sh`，再用 `sh` 执行。该引导脚本要求 Python 3.11+ 和真实终端，从 GitHub Releases 下载同版本 wheel 与 `.sha256` 文件，校验 wheel 后安装到独立虚拟环境，只在 `${XDG_BIN_HOME:-$HOME/.local/bin}` 发布独立卸载入口 `agentporter-uninstall`，最后通过 `/dev/tty` 启动 AgentPorter 原有的交互式安装计划。它不会绕过确认，也不会代装 Hermes。

匹配的 GitHub Release 制品发布前，这条命令不会成功。PATH 与恢复方法见[安装指南](docs/04-installation-and-troubleshooting.zh-CN.md)。

## 安装内容

一次运行会安装仓库定义的完整双 Profile Worker 集：

- `luna_worker`：在父 Agent 已明确目标、范围、约束和验收标准后，执行有边界的实现与分析任务；
- `codex-5-3-small-worker`：负责范围更窄、严格机械化的委派任务。

每个 Profile 都包含 Hermes 原生配置、指令、路由描述以及一个非秘密的所有权标记。AgentPorter 只编排 Hermes Profile 原生能力，不替代 Hermes 的存储、队列、worktree 或供应商配置。

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

离线 CI 面向 Linux、macOS 和 Windows，并覆盖 Python 3.11–3.13。真实 Hermes 验收单独在 Linux 上针对固定、不可变的 Hermes 上游提交运行，因为它需要原生 Hermes 可执行文件和更强的隔离条件。

离线矩阵通过不代表已证明所有平台和 Hermes 版本的原生兼容性。Hermes v0.20.0 是当前真实验收版本，不是通用兼容范围承诺。

## 仓库结构

- `src/agentporter/resources/workers.yaml`：打包内唯一权威 Worker 定义及模型偏好；
- `install.py`、`uninstall.py` 与 `src/agentporter/`：一次性安装和受保护的独立卸载实现；
- `tests/`：单元、文件系统、事务、压力和隔离真实 Hermes 验收测试；
- `scripts/verify_release.py`：fail-closed 的源码、wheel 和 sdist 发布契约验证器；
- `docs/`：架构、Worker 格式、适配器映射、生命周期设计、实施计划和用户指南。

## 设计与验收文档

- [方案总览](docs/00-solution-overview.md)
- [可移植 Worker 规范](docs/01-portable-worker-spec.md)
- [Hermes Adapter 设计](docs/02-platform-adapters.md)
- [安装、卸载与验收矩阵](docs/03-installation-and-uninstall-design.md)
- [实施计划](docs/plan/01-implementation-plan.md)
- [安装后 Worker 验证与基准计划](docs/plan/02-agent-validation-and-benchmark.md)
- [变更日志](CHANGELOG.md)

这些详细设计和计划记录的是工程契约及验收历史，并不构成对所有环境的通用生产就绪声明。首个版本不包含 Codex CLI 平台适配器；Worker 名称也不代表已经支持 Codex CLI。

## 开发、安全与许可证

提交变更前，请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，并执行其中规定的离线门禁和独立真实 Hermes 验收流程。

不要提交凭据、私有运行状态、缓存、模型输出、个人路径或环境敏感数据。安全问题请按照 [SECURITY.md](SECURITY.md) 私下报告。

AgentPorter 使用 [MIT License](LICENSE) 发布。
