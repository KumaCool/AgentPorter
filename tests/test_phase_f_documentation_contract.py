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
        assert "0.1.8" in text
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


def test_released_baseline_and_next_candidate_are_distinguished() -> None:
    corpus = "\n".join(path.read_text(encoding="utf-8") for path in ROOT.rglob("*.md"))
    for stale in (
        "current supported patch release",
        "当前受支持修复版本",
    ):
        assert stale not in corpus
    assert "0.1.8 is released" in corpus or "0.1.8 已正式发布" in corpus
    assert "Plan 06" in corpus
    assert "离线实现" in corpus or "offline" in corpus.lower()


def test_install_guides_describe_three_entries_three_profiles_and_candidate_boundary() -> None:
    for path in (
        "docs/04-installation-and-troubleshooting.md",
        "docs/04-installation-and-troubleshooting.zh-CN.md",
    ):
        text = _text(path)
        assert "three generated entry" in text or "三个生成入口" in text
        assert "two dedicated Worker Profiles and one dedicated orchestrator" in text or (
            "两个专用 Worker Profile 和一个专用 orchestrator" in text
        )
        assert "releases/latest/download/install.sh" in text
        assert "0.1.8" in text
        assert "agentporter-bounded-worker" in text
        assert "agentporter-mechanical-worker" in text
        assert "auto decomposition" in text or "自动分解" in text
        assert "Gateway" in text
        assert "live routing" in text


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
