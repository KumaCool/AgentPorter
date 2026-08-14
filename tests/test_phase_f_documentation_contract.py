from pathlib import Path

ROOT = Path(__file__).parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_current_user_docs_publish_truthful_phase_f_state_matrix() -> None:
    for path in (
        "README.md",
        "README.zh-CN.md",
        "docs/04-installation-and-troubleshooting.md",
        "docs/04-installation-and-troubleshooting.zh-CN.md",
    ):
        text = _text(path)
        assert "0.2.0" in text
        assert "bounded" in text.lower()
        assert "mechanical" in text.lower()
        assert "model/provider/endpoint" in text
        for state in (
            "installation",
            "binding",
            "credential",
            "canary",
            "dispatcher",
            "route",
            "continuity",
        ):
            assert state in text.lower(), f"{path} omits {state} state"


def test_current_docs_do_not_overclaim_v020_live_acceptance() -> None:
    corpus = "\n".join(
        _text(path)
        for path in (
            "README.md",
            "README.zh-CN.md",
            "docs/plan/00-index.md",
            "docs/plan/04-runtime-readiness-closure-implementation.md",
        )
    )
    assert "probe-unsupported" in corpus
    assert "mutation-unsupported" in corpus
    assert "zero model calls" in corpus.lower() or "零模型调用" in corpus
    assert "kanban mutation" in corpus.lower()
    assert (
        "unaccepted" in corpus.lower()
        or "unperformed" in corpus.lower()
        or "未执行" in corpus
        or "未验收" in corpus
    )


def test_activation_and_notify_receipt_boundaries_are_documented() -> None:
    corpus = "\n".join(
        _text(path)
        for path in (
            "README.md",
            "README.zh-CN.md",
            "docs/04-installation-and-troubleshooting.md",
            "docs/04-installation-and-troubleshooting.zh-CN.md",
        )
    )
    assert "agentporter-activate" in corpus
    assert "config check" in corpus
    assert "static" in corpus.lower() or "静态" in corpus
    assert "notify-list" in corpus
    assert "DispatchReceipt" in corpus


def test_v020_publication_and_historical_baseline_are_distinguished() -> None:
    corpus = "\n".join(path.read_text(encoding="utf-8") for path in ROOT.rglob("*.md"))
    for stale in (
        "current supported patch release",
        "当前受支持修复版本",
    ):
        assert stale not in corpus
    assert "0.2.0" in corpus
    assert "0.1.8" in corpus
    assert "latest published" in corpus.lower() or "最新正式" in corpus or "已正式发布" in corpus
    assert "be31eb2af67660780593c716d488ca88e508f710" in corpus
    assert "seven hosted assets" in corpus.lower() or "7 个托管 assets" in corpus
    assert "Plan 06" in corpus
    assert "离线实现" in corpus or "offline" in corpus.lower()


def test_install_guides_describe_two_current_workers_and_truthful_legacy_boundary() -> None:
    for path in (
        "docs/04-installation-and-troubleshooting.md",
        "docs/04-installation-and-troubleshooting.zh-CN.md",
    ):
        text = _text(path)
        assert "exactly two Worker" in text or "恰好只有" in text or "恰好处理两个" in text
        assert "main Hermes agent" in text or "主 Hermes agent" in text
        assert "erroneous" in text or "错误" in text
        assert "discovery/uninstall" in text or "发现/卸载" in text
        assert "releases/latest/download/install.sh" in text
        assert "0.2.0" in text
        assert "agentporter-bounded-worker" in text
        assert "agentporter-mechanical-worker" in text
        assert "auto decomposition" in text or "自动分解" in text
        assert "Gateway" in text
        assert "live routing" in text


def test_current_authorities_freeze_two_worker_and_canary_truth() -> None:
    paths = (
        "README.md",
        "README.zh-CN.md",
        "docs/00-solution-overview.md",
        "docs/01-portable-worker-spec.md",
        "docs/03-installation-and-uninstall-design.md",
        "docs/04-installation-and-troubleshooting.md",
        "docs/04-installation-and-troubleshooting.zh-CN.md",
        "docs/05-runtime-activation-and-live-call-design.md",
        "docs/06-role-identities-and-configurable-model-binding-design.md",
        "docs/plan/00-index.md",
        "docs/plan/02-multi-agent-orchestration.md",
        "docs/plan/02a-worker-readiness-orchestration-closure.md",
        "docs/plan/04-runtime-readiness-closure-implementation.md",
        "docs/plan/06-role-identities-and-configurable-model-binding.md",
    )
    for path in paths:
        text = _text(path)
        assert "bounded_worker" in text and "mechanical_worker" in text
        assert "main Hermes agent" in text or "主 Hermes agent" in text
        assert "agentporter-orchestrator" in text
        assert "legacy" in text.lower()
        assert "30" in text and "90" in text
        assert "key_env" in text
        assert "credential-required" in text
        assert "custom" in text.lower()
        assert "exit-zero" in text.lower() or "退出码" in text


def test_plan_authority_marks_offline_completion_and_historical_baselines() -> None:
    index = _text("docs/plan/00-index.md")
    plan02 = _text("docs/plan/02-multi-agent-orchestration.md")
    plan04 = _text("docs/plan/04-runtime-readiness-closure-implementation.md")
    assert "Phase A–F" in index
    assert "离线实现完成" in index
    assert "Plan 03" in index and "live" in index
    assert "Phase A 前历史基线" in plan02
    assert "Phase A 前历史基线" in plan04
    assert "本文是实施与收口记录" in plan04
