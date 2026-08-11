from __future__ import annotations

import hashlib
import stat
from dataclasses import FrozenInstanceError, dataclass, replace
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest

from agentporter.identity import COMPONENT_IDS, PRODUCT_ID
from agentporter.uninstall_planning import (
    InteractionStatus,
    PlanStatus,
    build_uninstall_plan,
    render_uninstall_plan,
    run_uninstall_confirmation,
)


@dataclass(frozen=True)
class Candidate:
    current_name: str
    path: Path
    product_id: str
    component_id: str
    installation_id: str
    profile_device: int
    profile_inode: int
    profile_type: int
    marker_device: int
    marker_inode: int
    marker_type: int
    marker_sha256: str
    hermes_home: Path
    profiles_root: Path


def executable_at(tmp_path: Path) -> Path:
    executable = tmp_path / "hermes"
    executable.write_bytes(b"hermes")
    return executable.resolve(strict=True)


def candidates(tmp_path: Path) -> tuple[Candidate, Candidate]:
    home = tmp_path / ".hermes"
    root = home / "profiles"
    installation_id = str(uuid4())
    result = []
    for index, (portable_id, component_id) in enumerate(COMPONENT_IDS.items(), start=1):
        name = f"renamed-{portable_id.replace('_', '-')}"
        result.append(
            Candidate(
                current_name=name,
                path=root / name,
                product_id=PRODUCT_ID,
                component_id=component_id,
                installation_id=installation_id,
                profile_device=10,
                profile_inode=100 + index,
                profile_type=stat.S_IFDIR,
                marker_device=10,
                marker_inode=200 + index,
                marker_type=stat.S_IFREG,
                marker_sha256=hashlib.sha256(portable_id.encode()).hexdigest(),
                hermes_home=home,
                profiles_root=root,
            )
        )
    return tuple(result)  # type: ignore[return-value]


def test_builds_immutable_sealed_plan_in_registry_order_independent_of_input(
    tmp_path: Path,
) -> None:
    first, second = candidates(tmp_path)

    plan = build_uninstall_plan((second, first), executable=executable_at(tmp_path))

    assert plan.status is PlanStatus.READY
    assert tuple(target.component_id for target in plan.targets) == tuple(COMPONENT_IDS.values())
    assert plan.installation_id == first.installation_id
    assert plan.confirmation_phrase == f"DELETE AGENTPORTER {first.installation_id[:8]}"
    assert len(plan.fingerprint) == 64
    assert (
        plan.fingerprint
        == build_uninstall_plan((first, second), executable=executable_at(tmp_path)).fingerprint
    )
    with pytest.raises(FrozenInstanceError):
        plan.status = PlanStatus.INVALID  # type: ignore[misc]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a, b: (a,),
        lambda a, b: (a, a),
        lambda a, b: (a, replace(b, component_id=a.component_id)),
        lambda a, b: (a, replace(b, component_id=str(uuid4()))),
        lambda a, b: (replace(a, product_id=str(uuid4())), b),
        lambda a, b: (a, replace(b, installation_id=str(uuid4()))),
        lambda a, b: (a, replace(b, hermes_home=a.hermes_home / "other")),
        lambda a, b: (a, replace(b, profiles_root=a.profiles_root / "other")),
        lambda a, b: (a, replace(b, path=b.path / "nested")),
        lambda a, b: (a, replace(b, current_name="default", path=b.profiles_root / "default")),
        lambda a, b: (a, replace(b, current_name="Bad Name", path=b.profiles_root / "Bad Name")),
        lambda a, b: (a, replace(b, path=b.profiles_root / "different")),
        lambda a, b: (a, replace(b, profile_type=stat.S_IFREG)),
        lambda a, b: (a, replace(b, marker_type=stat.S_IFLNK)),
        lambda a, b: (a, replace(b, marker_sha256="secret")),
    ],
)
def test_rejects_non_exact_or_unsafe_collection(tmp_path: Path, mutate: object) -> None:
    first, second = candidates(tmp_path)
    changed = mutate(first, second)  # type: ignore[operator]

    plan = build_uninstall_plan(changed, executable=executable_at(tmp_path))

    assert plan.status is PlanStatus.INVALID
    assert plan.targets == ()
    assert plan.installation_id is None
    assert plan.confirmation_phrase is None


def test_noncanonical_roots_are_invalid(tmp_path: Path) -> None:
    first, second = candidates(tmp_path)
    noncanonical_home = first.hermes_home / ".." / first.hermes_home.name
    changed = tuple(
        replace(item, hermes_home=noncanonical_home, profiles_root=noncanonical_home / "profiles")
        for item in (first, second)
    )
    assert (
        build_uninstall_plan(changed, executable=executable_at(tmp_path)).status
        is PlanStatus.INVALID
    )


def test_every_snapshot_field_and_bound_root_affect_fingerprint(tmp_path: Path) -> None:
    baseline = candidates(tmp_path)
    original = build_uninstall_plan(baseline, executable=executable_at(tmp_path))
    mutations = {
        "current_name": "another-name",
        "profile_device": 99,
        "profile_inode": 999,
        "profile_type": stat.S_IFDIR | 0o700,
        "marker_device": 99,
        "marker_inode": 999,
        "marker_type": stat.S_IFREG | 0o600,
        "marker_sha256": "f" * 64,
    }
    for field, value in mutations.items():
        changed = replace(baseline[0], **{field: value})
        if field == "current_name":
            changed = replace(changed, path=changed.profiles_root / str(value))
        plan = build_uninstall_plan((changed, baseline[1]), executable=executable_at(tmp_path))
        assert plan.status is PlanStatus.READY
        assert plan.fingerprint != original.fingerprint, field

    other = tmp_path / "other" / ".hermes"
    moved = tuple(
        replace(
            item,
            hermes_home=other,
            profiles_root=other / "profiles",
            path=other / "profiles" / item.current_name,
        )
        for item in baseline
    )
    assert (
        build_uninstall_plan(moved, executable=executable_at(tmp_path)).fingerprint
        != original.fingerprint
    )


def test_render_has_explicit_allowlist_and_complete_permanent_deletion_warning(
    tmp_path: Path,
) -> None:
    plan = build_uninstall_plan(candidates(tmp_path), executable=executable_at(tmp_path))

    rendered = render_uninstall_plan(plan)

    for target in plan.targets:
        assert target.current_name in rendered
        assert str(target.path) in rendered
        assert target.component_id in rendered
    assert plan.installation_id in rendered
    for item in (
        "config",
        "SOUL",
        ".env",
        "auth.json",
        "memories",
        "sessions",
        "skills",
        "cron",
        "MCP",
        "logs",
        "state databases",
        "other Profile-local files",
    ):
        assert item in rendered
    assert "permanently" in rendered
    assert "rename/replace" in rendered
    assert "marker_sha256" not in rendered
    assert all(target.marker_sha256 not in rendered for target in plan.targets)
    assert "reason" not in rendered.lower()


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("exact", InteractionStatus.CONFIRMED),
        ("", InteractionStatus.REJECTED),
        ("lower", InteractionStatus.REJECTED),
        ("space", InteractionStatus.REJECTED),
    ],
)
def test_confirmation_is_exact_single_input_and_continues_only_when_fresh(
    tmp_path: Path, answer: str, expected: InteractionStatus
) -> None:
    plan = build_uninstall_plan(candidates(tmp_path), executable=executable_at(tmp_path))
    inputs = 0
    validations = 0
    continuations = 0

    def read(_: str) -> str:
        nonlocal inputs
        inputs += 1
        choices = {
            "exact": plan.confirmation_phrase,
            "lower": plan.confirmation_phrase.lower(),
            "space": plan.confirmation_phrase + " ",
            "": "",
        }
        return choices[answer]  # type: ignore[return-value]

    def revalidate(bound_plan: object) -> bool:
        nonlocal validations
        validations += 1
        assert bound_plan is plan
        return True

    def continue_once() -> str:
        nonlocal continuations
        continuations += 1
        return "delete-stage"

    outcome = run_uninstall_confirmation(
        plan,
        revalidate_collection=revalidate,
        continuation=continue_once,
        input_fn=read,
        output=StringIO(),
    )

    assert outcome.status is expected
    assert inputs == 1
    assert validations == (1 if expected is InteractionStatus.CONFIRMED else 0)
    assert continuations == (1 if expected is InteractionStatus.CONFIRMED else 0)
    assert outcome.continuation_result == (
        "delete-stage" if expected is InteractionStatus.CONFIRMED else None
    )


@pytest.mark.parametrize("error", [EOFError(), KeyboardInterrupt()])
def test_input_termination_cancels_with_zero_revalidation_or_continuation(
    tmp_path: Path, error: BaseException
) -> None:
    plan = build_uninstall_plan(candidates(tmp_path), executable=executable_at(tmp_path))

    def terminate(_: str) -> str:
        raise error

    outcome = run_uninstall_confirmation(
        plan,
        revalidate_collection=lambda _: pytest.fail("must not revalidate"),
        continuation=lambda: pytest.fail("must not continue"),
        input_fn=terminate,
        output=StringIO(),
    )
    assert outcome.status is InteractionStatus.CANCELLED


def test_failed_collection_revalidation_is_stale_and_zero_continuation(tmp_path: Path) -> None:
    plan = build_uninstall_plan(candidates(tmp_path), executable=executable_at(tmp_path))
    calls = 0

    def stale(_: object) -> bool:
        nonlocal calls
        calls += 1
        return False

    outcome = run_uninstall_confirmation(
        plan,
        revalidate_collection=stale,
        continuation=lambda: pytest.fail("zero deletion on stale collection"),
        input_fn=lambda _: plan.confirmation_phrase,
        output=StringIO(),
    )
    assert outcome.status is InteractionStatus.STALE
    assert outcome.detail == "marker-changed/unsafe-path"
    assert calls == 1


def test_invalid_plan_is_rejected_without_interaction(tmp_path: Path) -> None:
    plan = build_uninstall_plan(candidates(tmp_path)[:1], executable=executable_at(tmp_path))
    outcome = run_uninstall_confirmation(
        plan,
        revalidate_collection=lambda _: pytest.fail("must not revalidate"),
        continuation=lambda: pytest.fail("must not continue"),
        input_fn=lambda _: pytest.fail("must not input"),
        output=StringIO(),
    )
    assert outcome.status is InteractionStatus.REJECTED


def test_output_and_injected_exceptions_propagate(tmp_path: Path) -> None:
    plan = build_uninstall_plan(candidates(tmp_path), executable=executable_at(tmp_path))

    class BrokenOutput(StringIO):
        def write(self, _: str) -> int:
            raise SystemExit("output failed")

    with pytest.raises(SystemExit, match="output failed"):
        run_uninstall_confirmation(
            plan,
            revalidate_collection=lambda _: True,
            continuation=lambda: None,
            input_fn=lambda _: plan.confirmation_phrase,
            output=BrokenOutput(),
        )
    with pytest.raises(RuntimeError, match="revalidation failed"):
        run_uninstall_confirmation(
            plan,
            revalidate_collection=lambda _: (_ for _ in ()).throw(
                RuntimeError("revalidation failed")
            ),
            continuation=lambda: None,
            input_fn=lambda _: plan.confirmation_phrase,
            output=StringIO(),
        )
    with pytest.raises(SystemExit, match="continuation failed"):
        run_uninstall_confirmation(
            plan,
            revalidate_collection=lambda _: True,
            continuation=lambda: (_ for _ in ()).throw(SystemExit("continuation failed")),
            input_fn=lambda _: plan.confirmation_phrase,
            output=StringIO(),
        )


def test_repr_hides_snapshot_hashes_and_fingerprint(tmp_path: Path) -> None:
    plan = build_uninstall_plan(candidates(tmp_path), executable=executable_at(tmp_path))
    representation = repr(plan)
    assert plan.fingerprint not in representation
    assert all(target.marker_sha256 not in representation for target in plan.targets)
