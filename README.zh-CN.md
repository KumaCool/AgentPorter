# AgentPorter

[English](README.md) | 简体中文

AgentPorter 是一个开源的 [Hermes Agent](https://hermes-agent.nousresearch.com/) 多代理工作组部署方案：一次安装多个职责明确的 Worker Profile，并逐步接通 Hermes 原生 Kanban 的任务分解与合理路由。[职责型身份与自定义推理绑定设计](docs/06-role-identities-and-configurable-model-binding-design.md)已在 v0.2.0 正式发布。

> **当前状态：** v0.2.0 是最新正式非预发布版。tag `v0.2.0` 精确指向 `be31eb2af67660780593c716d488ca88e508f710`；GitHub Release 与 7 个托管 assets 已通过 checksum/verifier、fresh HTTPS clone、隔离 wheel import 和公开 `latest/download/install.sh` 字节回读。修正后的 fresh install 只创建 `bounded_worker` 与 `mechanical_worker` 两个 Worker Profile，并为两者显式封闭 model/provider/endpoint。主 Hermes agent 是 orchestrator；当前没有独立 orchestrator Profile。未执行真实模型 canary、Gateway 变更、Kanban mutation 或 live routing，因此不能称为 `operational`。

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

## 修正后的安装内容

一次运行现在只安装两个 Worker Profile：

- `agentporter-bounded-worker`（`bounded_worker`）：仅在主 Hermes agent 已固定目标、约束、范围、文件和验收后完成边界明确的委派；信息不足或越界时停止，不猜测、不扩张。
- `agentporter-mechanical-worker`（`mechanical_worker`）：只处理更简单的机械工作，包括极简单操作脚本、大输出读取/过滤/摘要、按精确规则批量编辑；需要更广判断时返回歧义。

主 Hermes agent 负责 orchestrate、分解、路由与集成；当前不安装独立 orchestrator Profile。v0.2.0 确实曾以第三个 `agentporter-orchestrator` 发布并安装；这是错误的 legacy 拓扑，现在仅为安全发现/卸载兼容，并通过单独确认的迁移删除。fresh install、activation 和 canary 只针对两个 binding，最多两次调用。

## 产品方向：先部署工作组，再合理分配任务

项目重点不只是复制 Profile 文件。完整产品应让用户提交任务后，由主 Hermes agent 取得分解候选、在写入任务前按职责验证，再由 Hermes 在合适的 workspace 中执行，并返回可验证的交接结果。

当前版本已完成安全安装和离线编排合同；真实编排主线仍需单独验收：

- [计划索引与当前状态](docs/plan/00-index.md)
- [多代理编排与路由实施计划](docs/plan/02-multi-agent-orchestration.md)

在该计划通过真实验收前，请使用 Hermes 原生 Kanban 手动指定任务；不要把 Profile 安装或 description 读回当作自动路由已经可用。


## 运行状态矩阵

| 维度 | 当前状态 |
|---|---|
| installation | v0.2.0 已正式发布；tag、7 个托管 assets、verifier、fresh HTTPS clone、隔离 wheel import 与 `latest` bootstrap 字节回读均通过。 |
| public entries | bootstrap 会发布 `agentporter`、`agentporter-activate` 和 `agentporter-uninstall`。 |
| binding/credential | custom Provider binding 可将封印的定义写入两个执行 Worker；凭据可用性仍由 Profile/操作者持有，必须由真实调用证明。 |
| canary/live call | v0.2.0 发布不声称已执行带凭据的真实 canary；`config check=0`仍只证明静态有效。 |
| route proof | 激活路径使用 Hermes usage 报告验证 model/provider/api_calls；v0.20 缺 tool/fallback 遥测时只到 `route-proof-incomplete`。 |
| dispatcher/route | 主 Hermes agent 是 orchestrator；当前无独立控制面 Profile。Gateway、Kanban mutation 和 live routing 未验收。 |
| continuity | `DispatchReceipt`、任务订阅（`notify-list`）、运行观察与结构性恢复仍仅有离线合同；不声称真实通知或接续。 |

当前 v0.2.0 已发布 `agentporter-activate`，可事务化写入所选 custom Provider binding，并在单独确认后执行 one-shot；不会修改 Hermes 源码。没有当前绑定的真实证据时不得把 Worker 标记为可派发；本文不声称带凭据 canary 或 Kanban live routing 已通过。

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

- `src/agentporter/resources/workers.yaml`：修正后的 bounded/mechanical 两职责定义；model/provider/endpoint 来自用户显式 sealed binding；
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
- [职责型 Worker 身份与自定义推理绑定设计](docs/06-role-identities-and-configurable-model-binding-design.md)
- [职责型 Worker 身份与自定义推理绑定计划](docs/plan/06-role-identities-and-configurable-model-binding.md)
- [变更日志](CHANGELOG.md)

这些详细设计和计划记录的是工程契约及验收历史，并不构成对所有环境的通用生产就绪声明。v0.2.0 不包含 Codex CLI 平台适配器；历史模型语义名称也不代表已经支持 Codex CLI。职责型名称实现已正式发布，但未完成 live 验收；旧模型语义名称只保留在兼容与明确历史上下文。

## 开发、安全与许可证

提交变更前，请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，并执行其中规定的离线门禁和独立真实 Hermes 验收流程。

不要提交凭据、私有运行状态、缓存、模型输出、个人路径或环境敏感数据。安全问题请按照 [SECURITY.md](SECURITY.md) 私下报告。

AgentPorter 使用 [MIT License](LICENSE) 发布。

## 当前 custom Provider 安装到激活流程

AgentPorter v0.2.0 会在 Profile 安装成功后直接串联激活，不再额外询问“是否进入激活”。针对 Hermes v0.20 的 custom Provider，激活器不再调用不受支持的裸 Provider `auth add/status`；它要求主/default Profile 中存在唯一且 endpoint 一致的完整定义，封印来源配置后，将所选 `custom_providers` 条目事务化复制到每个 Worker，再执行绑定和单独确认的真实 canary。复制范围包含用户已放入该定义的 `api_key` 或 `key_env`，但不会打印定义或写入 AgentPorter receipt。缺失、重复、endpoint 不匹配或并发变化均 fail closed。

### 真实 canary 合同（Unreleased 修正）

每个 Worker 的 canary timeout 默认 30 秒，支持显式配置为 90 秒。继承定义中的 `key_env` 未解析时必须返回 `credential-required`，除非目标 Worker Profile 自己的 `.env` 可解析。只有封印的具体 custom Provider 定义可使用 canonical provider `custom`，usage 中的 `custom` 也只能映射回该定义。即使退出码为 0，只要 usage 标记 `failed`，仍按封闭安全原因归类，绝不算成功。失败原因保持 `authentication-failed`、`model-unsupported`、`endpoint-unavailable`、`rate-limited`、`probe-timeout`、`response-contract-failed`、`usage-evidence-invalid` 与 `unexpected-runtime-route`。
