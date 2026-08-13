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
        assert "0.1.4" in text
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
    assert (
        "zero kanban mutation calls" in corpus.lower()
        or "零 kanban mutation 调用" in corpus.lower()
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
