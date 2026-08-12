from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from pathlib import Path
from typing import TextIO

import pytest
import yaml

import agentporter.activation_application as activation
from agentporter.activation_application import (
    ActivationBindingInput,
    ActivationStatus,
    ActivationTargetPlan,
    ConfigSnapshot,
    apply_activation,
    build_activation_plan,
)
from agentporter.hermes import HermesCapabilities, HermesDetection
from agentporter.identity import COMPONENT_IDS, PRODUCT_ID
from agentporter.runtime_binding import RuntimeBindingPlan
from agentporter.uninstall_discovery import DiscoveryResult, DiscoveryStatus, discover_installation

INSTALLATION_ID = "12345678-1234-4abc-8def-1234567890ab"
SECRET_ENDPOINT = "https://activation-endpoint.invalid/v1"


class _StopActivation(BaseException):
    pass


def _detection(tmp_path: Path) -> HermesDetection:
    executable = tmp_path / "bin" / "hermes"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    home = tmp_path / "home" / ".hermes"
    profiles = home / "profiles"
    profiles.mkdir(parents=True)
    commands = frozenset({"install", "delete", "describe", "list", "info"})
    return HermesDetection(
        executable, "0.20.0", home, profiles, HermesCapabilities(commands, frozenset()), ()
    )


def _installation(tmp_path: Path) -> tuple[HermesDetection, DiscoveryResult]:
    found = _detection(tmp_path)
    models = {
        "luna_worker": "gpt-5.6-luna",
        "codex_5_3_small_worker": "gpt-5.3-codex-spark",
    }
    names = ("renamed-luna", "renamed-codex")
    for (portable_id, component_id), name in zip(COMPONENT_IDS.items(), names, strict=True):
        profile = found.profiles_root / name
        profile.mkdir(mode=0o700)
        (profile / "config.yaml").write_text(
            yaml.safe_dump(
                {"model": {"default": models[portable_id]}, "agent": {"reasoning_effort": "max"}}
            ),
            encoding="utf-8",
        )
        (profile / "config.yaml").chmod(0o600)
        marker = {
            "schema_version": 1,
            "product_id": PRODUCT_ID,
            "component_id": component_id,
            "installation_id": INSTALLATION_ID,
            "distribution_version": "0.1.3",
        }
        (profile / "agentporter-profile.json").write_text(json.dumps(marker), encoding="utf-8")
    discovery = discover_installation(found.profiles_root)
    assert discovery.status is DiscoveryStatus.READY
    return found, discovery


def _inputs() -> dict[str, ActivationBindingInput]:
    return {
        component_id: ActivationBindingInput(
            provider_id="custom-provider",
            endpoint_value=SECRET_ENDPOINT,
            credential_grant_kind="profile-auth",
            credential_state="operator-authorized",
        )
        for component_id in COMPONENT_IDS.values()
    }


def test_build_plan_uses_only_complete_discovered_installation_and_typed_snapshots(
    tmp_path: Path,
) -> None:
    found, discovery = _installation(tmp_path)

    plan = build_activation_plan(discovery, found, _inputs())

    assert plan.installation_id == INSTALLATION_ID
    assert {item.profile_name for item in plan.bindings} == {"renamed-luna", "renamed-codex"}
    assert {item.expected_model for item in plan.bindings} == {
        "gpt-5.6-luna",
        "gpt-5.3-codex-spark",
    }
    assert all(item.original_config.provider is None for item in plan.bindings)
    assert SECRET_ENDPOINT not in repr(plan)


def test_apply_activation_confirms_once_then_writes_and_reads_back_without_cli(
    tmp_path: Path,
) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    prompts: list[str] = []
    output: list[str] = []
    argv_calls: list[object] = []

    result = apply_activation(
        plan,
        input_fn=lambda prompt: prompts.append(prompt) or plan.confirmation_phrase,
        output=_Writer(output),
        command_observer=argv_calls.append,
    )

    assert result.status is ActivationStatus.ACTIVATED
    assert len(prompts) == 1
    assert argv_calls == []
    assert all(item.readback_passed for item in result.items)
    assert SECRET_ENDPOINT not in "".join(prompts + output)
    for binding in plan.bindings:
        loaded = yaml.safe_load((binding.profile_path / "config.yaml").read_text(encoding="utf-8"))
        assert loaded["model"] == {
            "default": binding.expected_model,
            "provider": "custom-provider",
            "base_url": SECRET_ENDPOINT,
        }


def test_stale_snapshot_causes_zero_writes(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    first = plan.bindings[0]
    path = first.profile_path / "config.yaml"
    changed = yaml.safe_load(path.read_text(encoding="utf-8"))
    changed["agent"]["reasoning_effort"] = "high"
    path.write_text(yaml.safe_dump(changed), encoding="utf-8")
    before = {
        item.profile_name: (item.profile_path / "config.yaml").read_bytes()
        for item in plan.bindings
    }

    result = apply_activation(plan, input_fn=lambda _: plan.confirmation_phrase)

    assert result.status is ActivationStatus.STALE
    assert {
        item.profile_name: (item.profile_path / "config.yaml").read_bytes()
        for item in plan.bindings
    } == before


def test_compare_is_repeated_immediately_before_each_write(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    second = plan.bindings[1]
    second_path = second.profile_path / "config.yaml"

    def drift_next_target(binding: ActivationTargetPlan, index: int) -> None:
        if index == 0:
            loaded = yaml.safe_load(second_path.read_text(encoding="utf-8"))
            loaded["agent"]["reasoning_effort"] = "high"
            second_path.write_text(yaml.safe_dump(loaded), encoding="utf-8")

    result = apply_activation(
        plan,
        input_fn=lambda _: plan.confirmation_phrase,
        after_write=drift_next_target,
    )

    assert result.status is ActivationStatus.FAILED
    second_loaded = yaml.safe_load(second_path.read_text(encoding="utf-8"))
    assert second_loaded["agent"]["reasoning_effort"] == "high"
    assert "provider" not in second_loaded["model"]
    first_loaded = yaml.safe_load(
        (plan.bindings[0].profile_path / "config.yaml").read_text(encoding="utf-8")
    )
    assert "provider" not in first_loaded["model"]
    assert "base_url" not in first_loaded["model"]


def test_drift_at_final_config_publication_is_preserved_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    target = plan.bindings[0]
    config = target.profile_path / "config.yaml"
    exchange = activation._exchange_names
    injected = False

    def drift_then_exchange(directory_fd: int, left: str, right: str) -> None:
        nonlocal injected
        if not injected and right == "config.yaml":
            injected = True
            loaded = yaml.safe_load(config.read_text(encoding="utf-8"))
            loaded["concurrent"] = "KEEP"
            config.write_text(yaml.safe_dump(loaded), encoding="utf-8")
        exchange(directory_fd, left, right)

    monkeypatch.setattr(activation, "_exchange_names", drift_then_exchange)
    result = apply_activation(plan, input_fn=lambda _: plan.confirmation_phrase)

    assert result.status is ActivationStatus.COMPENSATION_INCOMPLETE
    assert result.residue_count == 1
    loaded = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert loaded["concurrent"] == "KEEP"
    assert "provider" not in loaded["model"]


def test_profile_replacement_with_identical_config_is_stale_and_untouched(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    target = plan.bindings[0]
    original = target.profile_path
    replacement = original.with_name(original.name + "-replacement")
    replacement.mkdir(mode=0o700)
    (replacement / "config.yaml").write_bytes(target.original_config.content)
    original.rename(original.with_name(original.name + "-old"))
    replacement.rename(original)

    result = apply_activation(plan, input_fn=lambda _: plan.confirmation_phrase)

    assert result.status is ActivationStatus.STALE
    loaded = yaml.safe_load((original / "config.yaml").read_text(encoding="utf-8"))
    assert "provider" not in loaded["model"]
    assert "base_url" not in loaded["model"]


def test_failure_restores_only_undrifted_values_and_reports_residue(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    second = plan.bindings[1]

    def after_write(binding: RuntimeBindingPlan, index: int) -> None:
        if index == 0:
            path = plan.bindings[0].profile_path / "config.yaml"
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            loaded["model"]["provider"] = "operator-drift"
            path.write_text(yaml.safe_dump(loaded), encoding="utf-8")
        if index == 1:
            raise RuntimeError("sensitive failure " + SECRET_ENDPOINT)

    result = apply_activation(
        plan,
        input_fn=lambda _: plan.confirmation_phrase,
        after_write=after_write,
    )

    assert result.status is ActivationStatus.COMPENSATION_INCOMPLETE
    assert result.residue_count == 1
    assert SECRET_ENDPOINT not in repr(result)
    first_config = yaml.safe_load(
        (plan.bindings[0].profile_path / "config.yaml").read_text(encoding="utf-8")
    )
    second_config = yaml.safe_load(
        (second.profile_path / "config.yaml").read_text(encoding="utf-8")
    )
    assert first_config["model"]["provider"] == "operator-drift"
    assert "base_url" not in second_config["model"]
    assert "provider" not in second_config["model"]


def test_unresolved_credential_writes_binding_but_runs_zero_probe(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    inputs = _inputs()
    component = next(iter(inputs))
    inputs[component] = replace(inputs[component], credential_state="unresolved")
    plan = build_activation_plan(discovery, found, inputs)
    probes: list[str] = []

    result = apply_activation(
        plan,
        input_fn=lambda _: plan.confirmation_phrase,
        probe_runner=lambda binding: probes.append(binding.component_id),
    )

    assert result.status is ActivationStatus.CREDENTIAL_REQUIRED
    assert probes == []


def test_safe_receipt_is_private_atomic_and_inside_user_owned_local(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())

    result = apply_activation(plan, input_fn=lambda _: plan.confirmation_phrase)

    assert result.status is ActivationStatus.ACTIVATED
    for binding in plan.bindings:
        receipt = binding.profile_path / "local" / "agentporter" / "runtime-binding.json"
        assert receipt.is_file()
        assert receipt.stat().st_mode & 0o777 == 0o600
        assert receipt.parent.stat().st_mode & 0o777 == 0o700
        payload = receipt.read_text(encoding="utf-8")
        assert SECRET_ENDPOINT not in payload
        assert not (binding.profile_path / ".env").exists()
        assert not (binding.profile_path / "auth.json").exists()


def test_symlink_config_is_rejected_without_read_or_write(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    target = discovery.targets[0]
    config = target.path / "config.yaml"
    outside = tmp_path / "outside.yaml"
    outside.write_text("sentinel: unchanged\n", encoding="utf-8")
    config.unlink()
    config.symlink_to(outside)

    with pytest.raises(ValueError, match="safe regular"):
        build_activation_plan(discovery, found, _inputs())

    assert outside.read_text(encoding="utf-8") == "sentinel: unchanged\n"


@pytest.mark.parametrize(
    "interrupt", [KeyboardInterrupt("sentinel"), SystemExit(23), _StopActivation("sentinel")]
)
def test_control_flow_exception_is_compensated_then_propagated_with_identity(
    tmp_path: Path, interrupt: BaseException
) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())

    with pytest.raises(type(interrupt)) as caught:
        apply_activation(
            plan,
            input_fn=lambda _: plan.confirmation_phrase,
            after_write=lambda _target, index: (
                (_ for _ in ()).throw(interrupt) if index == 0 else None
            ),
        )

    assert caught.value is interrupt
    assert all(
        "provider" not in yaml.safe_load((item.profile_path / "config.yaml").read_text())["model"]
        for item in plan.bindings
    )


def test_marker_content_change_after_plan_is_stale_with_zero_writes(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    marker = plan.bindings[0].profile_path / "agentporter-profile.json"
    marker.write_text("{}", encoding="utf-8")

    result = apply_activation(plan, input_fn=lambda _: plan.confirmation_phrase)

    assert result.status is ActivationStatus.STALE
    assert all(
        "provider" not in yaml.safe_load((item.profile_path / "config.yaml").read_text())["model"]
        for item in plan.bindings
    )


def test_config_replacement_with_identical_content_is_stale(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    config = plan.bindings[0].profile_path / "config.yaml"
    content = config.read_bytes()
    replacement = config.with_suffix(".replacement")
    replacement.write_bytes(content)
    replacement.replace(config)

    assert (
        apply_activation(plan, input_fn=lambda _: plan.confirmation_phrase).status
        is ActivationStatus.STALE
    )
    assert "provider" not in yaml.safe_load(config.read_text())["model"]


def test_preexisting_fixed_temp_names_are_never_unlinked(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    sentinels: list[Path] = []
    for target in plan.bindings:
        config_temp = target.profile_path / ".agentporter-config.tmp"
        config_temp.write_text("owned elsewhere", encoding="utf-8")
        receipt_dir = target.profile_path / "local" / "agentporter"
        receipt_dir.mkdir(parents=True)
        receipt_temp = receipt_dir / ".runtime-binding.tmp"
        receipt_temp.write_text("owned elsewhere", encoding="utf-8")
        sentinels.extend((config_temp, receipt_temp))

    assert (
        apply_activation(plan, input_fn=lambda _: plan.confirmation_phrase).status
        is ActivationStatus.ACTIVATED
    )
    assert [path.read_text() for path in sentinels] == ["owned elsewhere"] * len(sentinels)


def test_second_receipt_failure_restores_both_existing_receipts_and_configs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found, discovery = _installation(tmp_path)
    first_plan = build_activation_plan(discovery, found, _inputs())
    assert (
        apply_activation(first_plan, input_fn=lambda _: first_plan.confirmation_phrase).status
        is ActivationStatus.ACTIVATED
    )
    before_configs = [
        item.profile_path.joinpath("config.yaml").read_bytes() for item in first_plan.bindings
    ]
    receipts = [
        item.profile_path / "local/agentporter/runtime-binding.json" for item in first_plan.bindings
    ]
    before_receipts = [path.read_bytes() for path in receipts]
    changed = {
        key: replace(value, provider_id="replacement-provider") for key, value in _inputs().items()
    }
    plan = build_activation_plan(discover_installation(found.profiles_root), found, changed)
    original = activation._write_receipt
    calls = 0

    def fail_second(
        target: ActivationTargetPlan, readback: ConfigSnapshot
    ) -> activation._ReceiptSnapshot:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("receipt fault")
        return original(target, readback)

    monkeypatch.setattr(activation, "_write_receipt", fail_second)
    result = apply_activation(plan, input_fn=lambda _: plan.confirmation_phrase)

    assert result.status is ActivationStatus.FAILED
    assert [
        item.profile_path.joinpath("config.yaml").read_bytes() for item in plan.bindings
    ] == before_configs
    assert [path.read_bytes() for path in receipts] == before_receipts


def test_absent_receipt_restore_preserves_concurrent_replacement_and_reports_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    receipt = plan.bindings[0].profile_path / "local/agentporter/runtime-binding.json"
    original = activation._write_receipt
    calls = 0
    concurrent = b'{"concurrent":"KEEP"}\n'

    def replace_first_then_fail_second(
        target: ActivationTargetPlan, readback: ConfigSnapshot
    ) -> activation._ReceiptSnapshot:
        nonlocal calls
        calls += 1
        if calls == 1:
            published = original(target, readback)
            replacement = receipt.with_suffix(".replacement")
            replacement.write_bytes(concurrent)
            replacement.replace(receipt)
            return published
        raise OSError("receipt fault")

    monkeypatch.setattr(activation, "_write_receipt", replace_first_then_fail_second)
    result = apply_activation(plan, input_fn=lambda _: plan.confirmation_phrase)

    assert result.status is ActivationStatus.COMPENSATION_INCOMPLETE
    assert result.residue_count == 1
    assert receipt.read_bytes() == concurrent


def test_restore_refuses_whole_file_drift_and_preserves_unrelated_key(
    tmp_path: Path,
) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())

    def drift_then_fail(target: ActivationTargetPlan, index: int) -> None:
        if index == 0:
            path = target.profile_path / "config.yaml"
            loaded = yaml.safe_load(path.read_text())
            loaded["concurrent"] = "KEEP"
            path.write_text(yaml.safe_dump(loaded), encoding="utf-8")
            raise RuntimeError("fault")

    result = apply_activation(
        plan, input_fn=lambda _: plan.confirmation_phrase, after_write=drift_then_fail
    )

    assert result.status is ActivationStatus.COMPENSATION_INCOMPLETE
    assert result.residue_count >= 1
    loaded = yaml.safe_load((plan.bindings[0].profile_path / "config.yaml").read_text())
    assert loaded["concurrent"] == "KEEP"
    assert loaded["model"]["provider"] == "custom-provider"


def test_atomic_config_replacement_preserves_owner_and_private_mode(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    config = plan.bindings[0].profile_path / "config.yaml"
    os.chown(config, 65534, 65534)
    plan = build_activation_plan(discover_installation(found.profiles_root), found, _inputs())

    assert (
        apply_activation(plan, input_fn=lambda _: plan.confirmation_phrase).status
        is ActivationStatus.ACTIVATED
    )
    info = config.stat()
    assert (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (65534, 65534, 0o600)


def test_receipt_directory_fchmod_failure_closes_opened_directory_fd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    target = plan.bindings[0]
    real_fchmod = activation.os.fchmod
    calls = 0
    receipt_fd: int | None = None

    def fail_receipt_fchmod(descriptor: int, mode: int) -> None:
        nonlocal calls, receipt_fd
        calls += 1
        if calls == 2:
            receipt_fd = descriptor
            raise OSError("fchmod fault")
        real_fchmod(descriptor, mode)

    monkeypatch.setattr(activation.os, "fchmod", fail_receipt_fchmod)
    with pytest.raises(OSError, match="fchmod fault"):
        activation._receipt_directory_fd(target)

    assert receipt_fd is not None
    with pytest.raises(OSError):
        os.fstat(receipt_fd)


class _Writer(TextIO):
    def __init__(self, values: list[str]) -> None:
        self.values = values

    def write(self, value: str) -> int:
        self.values.append(value)
        return len(value)
