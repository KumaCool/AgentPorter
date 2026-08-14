from __future__ import annotations

import json
import os
import stat
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import TextIO

import pytest
import yaml

import agentporter.activation_application as activation
from agentporter.activation_application import (
    ActivationBindingInput,
    ActivationResult,
    ActivationStatus,
    ActivationTargetPlan,
    ConfigSnapshot,
    apply_activation,
    build_activation_plan,
)
from agentporter.hermes import HermesCapabilities, HermesDetection
from agentporter.identity import INSTALL_COMPONENT_IDS, PRODUCT_ID
from agentporter.planning import RuntimeBindingSelection
from agentporter.runtime_binding import RuntimeBindingPlan
from agentporter.runtime_probe import ProbeObservation, ProbeResult
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
    (found.hermes_home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "model": {"default": "parent-model"},
                "custom_providers": [
                    {
                        "name": "custom-provider",
                        "base_url": SECRET_ENDPOINT,
                        "api_key": "PRIVATE-CUSTOM-PROVIDER-KEY",
                        "model": "parent-model",
                        "models": [
                            "bounded-test-model",
                            "mechanical-test-model",
                        ],
                        "extra_headers": {"X-Provider-Mode": "private"},
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (found.hermes_home / "config.yaml").chmod(0o600)
    models = {
        "bounded_worker": "bounded-current-model",
        "mechanical_worker": "mechanical-current-model",
    }
    names = ("renamed-bounded", "renamed-mechanical")
    for (portable_id, component_id), name in zip(INSTALL_COMPONENT_IDS.items(), names, strict=True):
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
            model=f"{portable_id.removesuffix('_worker')}-test-model",
            provider_id="custom-provider",
            endpoint_value=SECRET_ENDPOINT,
            credential_grant_kind="custom-provider-config",
            credential_state="operator-authorized",
        )
        for portable_id, component_id in INSTALL_COMPONENT_IDS.items()
    }


def test_build_plan_uses_only_complete_discovered_installation_and_typed_snapshots(
    tmp_path: Path,
) -> None:
    found, discovery = _installation(tmp_path)

    plan = build_activation_plan(discovery, found, _inputs())

    assert plan.installation_id == INSTALLATION_ID
    assert {item.profile_name for item in plan.bindings} == {
        "renamed-bounded",
        "renamed-mechanical",
    }
    assert {item.expected_model for item in plan.bindings} == {
        "bounded-test-model",
        "mechanical-test-model",
    }
    assert all(item.original_config.provider is None for item in plan.bindings)
    assert all(
        item.provider_definition["api_key"] == "PRIVATE-CUSTOM-PROVIDER-KEY"
        for item in plan.bindings
    )
    assert SECRET_ENDPOINT not in repr(plan)
    assert "PRIVATE-CUSTOM-PROVIDER-KEY" not in repr(plan)


def test_explicit_inheritance_copies_only_selected_source_key_into_worker_envs(
    tmp_path: Path,
) -> None:
    found, discovery = _installation(tmp_path)
    source = yaml.safe_load((found.hermes_home / "config.yaml").read_text(encoding="utf-8"))
    definition = source["custom_providers"][0]
    definition.pop("api_key")
    definition["key_env"] = "HERMES_CUSTOM_10_88_0_3_API_KEY"
    (found.hermes_home / "config.yaml").write_text(yaml.safe_dump(source), encoding="utf-8")
    source_secret = "source-secret-never-rendered"
    (found.hermes_home / ".env").write_text(
        f"UNRELATED_SOURCE=leave-behind\nHERMES_CUSTOM_10_88_0_3_API_KEY={source_secret}\n",
        encoding="utf-8",
    )
    (found.hermes_home / ".env").chmod(0o600)

    plan = build_activation_plan(discovery, found, _inputs())
    assert source_secret not in repr(plan)
    rendered: list[str] = []
    result = apply_activation(
        plan,
        input_fn=lambda _prompt: plan.confirmation_phrase,
        output=_Writer(rendered),
    )

    assert result.status is ActivationStatus.CANARY_REQUIRED
    assert source_secret not in "".join(rendered)
    for target in plan.bindings:
        assert (target.profile_path / ".env").read_text(encoding="utf-8") == (
            f"HERMES_CUSTOM_10_88_0_3_API_KEY={source_secret}\n"
        )
        assert stat.S_IMODE((target.profile_path / ".env").stat().st_mode) == 0o600
        config = yaml.safe_load((target.profile_path / "config.yaml").read_text(encoding="utf-8"))
        assert config["custom_providers"][0] == definition


def test_explicit_inheritance_missing_source_key_fails_before_prompt_or_write(
    tmp_path: Path,
) -> None:
    found, discovery = _installation(tmp_path)
    source = yaml.safe_load((found.hermes_home / "config.yaml").read_text(encoding="utf-8"))
    definition = source["custom_providers"][0]
    definition.pop("api_key")
    definition["key_env"] = "MISSING_SELECTED_KEY"
    (found.hermes_home / "config.yaml").write_text(yaml.safe_dump(source), encoding="utf-8")

    plan = build_activation_plan(discovery, found, _inputs())
    result = apply_activation(plan, input_fn=lambda _prompt: pytest.fail("must fail before prompt"))

    assert result.status is ActivationStatus.CREDENTIAL_REQUIRED
    assert all(not (target.path / ".env").exists() for target in discovery.targets)
    assert all(
        "custom_providers" not in yaml.safe_load((target.path / "config.yaml").read_text())
        for target in discovery.targets
    )


@pytest.mark.skipif(
    not Path("/usr/local/bin/hermes").is_file(), reason="system Hermes CLI is not installed"
)
def test_activated_key_env_provider_is_recognized_by_real_hermes_without_model_call(
    tmp_path: Path,
) -> None:
    found, discovery = _installation(tmp_path)
    source = yaml.safe_load((found.hermes_home / "config.yaml").read_text(encoding="utf-8"))
    definition = source["custom_providers"][0]
    definition.pop("api_key")
    definition["key_env"] = "ISOLATED_ACTIVATION_TEST_KEY"
    (found.hermes_home / "config.yaml").write_text(yaml.safe_dump(source), encoding="utf-8")
    (found.hermes_home / ".env").write_text(
        "ISOLATED_ACTIVATION_TEST_KEY=dummy-no-network-value\n", encoding="utf-8"
    )
    (found.hermes_home / ".env").chmod(0o600)

    plan = build_activation_plan(discovery, found, _inputs())
    assert apply_activation(
        plan, input_fn=lambda _prompt: plan.confirmation_phrase
    ).status is ActivationStatus.CANARY_REQUIRED

    env = {
        "HOME": str(found.hermes_home.parent.parent),
        "HERMES_HOME": str(found.hermes_home),
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
    }
    for target in plan.bindings:
        completed = subprocess.run(
            ("/usr/local/bin/hermes", "--profile", target.profile_name, "config"),
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0
        assert "unknown provider" not in (completed.stdout + completed.stderr).lower()
    assert not (found.hermes_home / "state.db").exists()


def test_key_env_and_provider_definition_roll_back_together_on_write_failure(
    tmp_path: Path,
) -> None:
    found, discovery = _installation(tmp_path)
    source = yaml.safe_load((found.hermes_home / "config.yaml").read_text(encoding="utf-8"))
    definition = source["custom_providers"][0]
    definition.pop("api_key")
    definition["key_env"] = "ROLLBACK_TEST_KEY"
    (found.hermes_home / "config.yaml").write_text(yaml.safe_dump(source), encoding="utf-8")
    (found.hermes_home / ".env").write_text(
        "ROLLBACK_TEST_KEY=rollback-test-value\n", encoding="utf-8"
    )
    originals = {
        target.current_name: (target.path / "config.yaml").read_bytes()
        for target in discovery.targets
    }

    plan = build_activation_plan(discovery, found, _inputs())
    result = apply_activation(
        plan,
        input_fn=lambda _prompt: plan.confirmation_phrase,
        after_write=lambda _target, _index: (_ for _ in ()).throw(OSError("injected")),
    )

    assert result.status is ActivationStatus.FAILED
    for target in discovery.targets:
        assert (target.path / "config.yaml").read_bytes() == originals[target.current_name]
        assert not (target.path / ".env").exists()


def test_inherited_key_env_is_usable_only_from_target_profile_owned_env(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    source = yaml.safe_load((found.hermes_home / "config.yaml").read_text(encoding="utf-8"))
    definition = source["custom_providers"][0]
    definition.pop("api_key")
    definition["key_env"] = "PROFILE_OWNED_KEY"
    (found.hermes_home / "config.yaml").write_text(yaml.safe_dump(source), encoding="utf-8")
    for target in discovery.targets:
        (target.path / ".env").write_text("PROFILE_OWNED_KEY=not-exposed\n", encoding="utf-8")
        (target.path / ".env").chmod(0o600)

    plan = build_activation_plan(discovery, found, _inputs())
    assert all(target.binding.credential_state == "operator-authorized" for target in plan.bindings)


def test_activation_forwards_explicit_ninety_second_canary_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    observed: list[float] = []

    def fake_probe(**kwargs: object) -> ProbeResult:
        observed.append(kwargs["timeout_seconds"])  # type: ignore[arg-type]
        return ProbeResult("response-contract-failed")

    monkeypatch.setattr(activation, "run_runtime_probe", fake_probe)
    answers = iter((plan.confirmation_phrase, "RUN 2 WORKER CALLS"))
    apply_activation(
        plan,
        input_fn=lambda _prompt: next(answers),
        probe_runner=lambda _binding, _nonce, _directory: ProbeObservation(),
        require_runtime_confirmations=True,
        canary_timeout_seconds=90,
    )
    assert observed == [90, 90]


def test_runtime_entry_wires_timeout_and_canonical_custom_usage_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agentporter.activation_entry as entry  # pyright: ignore[reportPrivateUsage]

    found, _ = _installation(tmp_path)
    captured: dict[str, object] = {}
    answers = iter(
        (
            "m1",
            "custom-provider",
            "explicit-source-inheritance",
            "m2",
            "custom-provider",
            "explicit-source-inheritance",
            "m3",
            "custom-provider",
            "explicit-source-inheritance",
        )
    )

    class Runtime:
        def oneshot(self, *args: object, **kwargs: object) -> ProbeObservation:
            captured.update(kwargs)
            return ProbeObservation()

    def apply(plan: object, **kwargs: object) -> ActivationResult:
        captured.update(kwargs)
        probe = kwargs["probe_runner"]
        binding = plan.bindings[0]  # type: ignore[attr-defined]
        probe(binding.binding, "nonce", tmp_path)  # type: ignore[operator]
        return ActivationResult(ActivationStatus.CANARY_REQUIRED)

    monkeypatch.setattr(entry, "apply_activation", apply)
    result = entry._run_binding_activation(  # pyright: ignore[reportPrivateUsage]
        {},
        detector=lambda **_kwargs: found,
        input_fn=lambda _prompt: next(answers),
        endpoint_reader=lambda _prompt: SECRET_ENDPOINT,
        runtime_factory=lambda _path: Runtime(),
        canary_timeout_seconds=90,  # type: ignore[arg-type,return-value]
    )
    assert result.status is ActivationStatus.CANARY_REQUIRED
    assert captured["canary_timeout_seconds"] == 90
    assert captured["expected_usage_provider"] == "custom"


def test_build_plan_and_apply_support_current_keyed_provider_schema(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    source = yaml.safe_load((found.hermes_home / "config.yaml").read_text(encoding="utf-8"))
    legacy = source.pop("custom_providers")[0]
    source["providers"] = {
        "custom-provider": {
            "api": legacy.pop("base_url"),
            "api_key": legacy.pop("api_key"),
            "default_model": legacy.pop("model"),
            "models": legacy.pop("models"),
            "extra_headers": legacy.pop("extra_headers"),
            "transport": "openai",
        }
    }
    (found.hermes_home / "config.yaml").write_text(
        yaml.safe_dump(source, sort_keys=False), encoding="utf-8"
    )
    discovery = discover_installation(found.profiles_root)

    plan = build_activation_plan(discovery, found, _inputs())
    result = apply_activation(plan, input_fn=lambda _prompt: plan.confirmation_phrase)

    assert result.status is ActivationStatus.CANARY_REQUIRED
    assert all(target.provider_container == "providers" for target in plan.bindings)
    for target in plan.bindings:
        loaded = yaml.safe_load((target.profile_path / "config.yaml").read_text(encoding="utf-8"))
        assert loaded["providers"]["custom-provider"] == source["providers"]["custom-provider"]
        assert "custom_providers" not in loaded


def test_duplicate_provider_across_legacy_and_current_schema_is_rejected(tmp_path: Path) -> None:
    found, _ = _installation(tmp_path)
    source = yaml.safe_load((found.hermes_home / "config.yaml").read_text(encoding="utf-8"))
    legacy = source["custom_providers"][0]
    source["providers"] = {
        "custom-provider": {
            "api": legacy["base_url"],
            "api_key": "SECOND-PRIVATE-KEY",
        }
    }
    (found.hermes_home / "config.yaml").write_text(
        yaml.safe_dump(source, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="exactly one"):
        build_activation_plan(discover_installation(found.profiles_root), found, _inputs())


def test_current_keyed_provider_preserves_unrelated_worker_providers(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    source = yaml.safe_load((found.hermes_home / "config.yaml").read_text(encoding="utf-8"))
    legacy = source.pop("custom_providers")[0]
    source["providers"] = {
        "custom-provider": {"api": legacy["base_url"], "api_key": legacy["api_key"]}
    }
    (found.hermes_home / "config.yaml").write_text(
        yaml.safe_dump(source, sort_keys=False), encoding="utf-8"
    )
    for target in discovery.targets:
        worker = yaml.safe_load((target.path / "config.yaml").read_text(encoding="utf-8"))
        worker["providers"] = {"keep-provider": {"api": "https://keep.invalid/v1"}}
        (target.path / "config.yaml").write_text(
            yaml.safe_dump(worker, sort_keys=False), encoding="utf-8"
        )
    plan = build_activation_plan(discover_installation(found.profiles_root), found, _inputs())

    result = apply_activation(plan, input_fn=lambda _prompt: plan.confirmation_phrase)

    assert result.status is ActivationStatus.CANARY_REQUIRED
    for target in plan.bindings:
        loaded = yaml.safe_load((target.profile_path / "config.yaml").read_text(encoding="utf-8"))
        assert list(loaded["providers"]) == ["keep-provider", "custom-provider"]


def test_build_plan_accepts_and_reads_complete_two_worker_discovery(
    tmp_path: Path,
) -> None:
    found, _ = _installation(tmp_path)
    discovery = discover_installation(found.profiles_root)

    plan = build_activation_plan(discovery, found, _inputs())

    assert [binding.component_id for binding in plan.bindings] == list(
        INSTALL_COMPONENT_IDS.values()
    )


def test_formal_activation_entry_prompts_for_all_profiles_in_component_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agentporter.activation_entry as entry

    found, _ = _installation(tmp_path)
    prompts: list[str] = []
    captured: dict[str, ActivationBindingInput] = {}
    answers = iter(
        (
            "bounded-test-model",
            "custom-provider",
            "explicit-source-inheritance",
            "mechanical-test-model",
            "custom-provider",
            "explicit-source-inheritance",
        )
    )
    sentinel_plan = object()
    sentinel_result = object()

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    def endpoint(prompt: str) -> str:
        prompts.append(prompt)
        return "https://worker.invalid/v1"

    def capture_plan(
        discovery: DiscoveryResult,
        detection: HermesDetection,
        inputs: dict[str, ActivationBindingInput],
    ) -> object:
        assert detection is found
        captured.update(inputs)
        return sentinel_plan

    monkeypatch.setattr(entry, "build_activation_plan", capture_plan)

    monkeypatch.setattr(
        entry,
        "apply_activation",
        lambda plan, **kwargs: sentinel_result if plan is sentinel_plan else pytest.fail(),
    )

    result = entry.run_activator(
        {},
        detector=lambda **kwargs: found,
        input_fn=answer,
        endpoint_reader=endpoint,
        runtime_factory=lambda _path: object(),  # type: ignore[arg-type,return-value]
    )

    assert result is sentinel_result
    assert list(captured) == list(INSTALL_COMPONENT_IDS.values())
    assert [prompt for prompt in prompts if prompt.startswith("Provider ID")] == [
        "Provider ID for renamed-bounded: ",
        "Provider ID for renamed-mechanical: ",
    ]
    assert [prompt for prompt in prompts if prompt.startswith("Model ID")] == [
        "Model ID for renamed-bounded: ",
        "Model ID for renamed-mechanical: ",
    ]
    assert len([prompt for prompt in prompts if prompt.startswith("Credential grant")]) == 2


def test_formal_activation_entry_reuses_install_binding_authority_without_reprompting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agentporter.activation_entry as entry

    found, _ = _installation(tmp_path)
    prompts: list[str] = []
    captured: dict[str, ActivationBindingInput] = {}
    selected = {
        portable_id: RuntimeBindingSelection(
            f"{portable_id}-selected-model",
            "custom-provider",
            SECRET_ENDPOINT,
        )
        for portable_id in INSTALL_COMPONENT_IDS
    }
    grants = iter(("explicit-source-inheritance", "explicit-source-inheritance"))

    def capture_plan(
        discovery: DiscoveryResult,
        detection: HermesDetection,
        inputs: dict[str, ActivationBindingInput],
    ) -> object:
        captured.update(inputs)
        return object()

    monkeypatch.setattr(entry, "build_activation_plan", capture_plan)
    monkeypatch.setattr(entry, "apply_activation", lambda plan, **kwargs: object())

    entry._run_binding_activation(  # pyright: ignore[reportPrivateUsage]
        {},
        detector=lambda **kwargs: found,
        input_fn=lambda prompt: prompts.append(prompt) or next(grants),
        endpoint_reader=lambda _prompt: pytest.fail("endpoint must not be prompted twice"),
        runtime_factory=lambda _path: object(),  # type: ignore[arg-type,return-value]
        binding_selection=selected,
    )

    assert not any(prompt.startswith(("Model ID", "Provider ID")) for prompt in prompts)
    assert [value.model for value in captured.values()] == [
        selected[portable_id].model for portable_id in INSTALL_COMPONENT_IDS
    ]
    assert all(value.endpoint_value == SECRET_ENDPOINT for value in captured.values())


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

    assert result.status is ActivationStatus.CANARY_REQUIRED
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
        assert loaded["custom_providers"] == [
            {
                "name": "custom-provider",
                "base_url": SECRET_ENDPOINT,
                "api_key": "PRIVATE-CUSTOM-PROVIDER-KEY",
                "model": "parent-model",
                "models": [
                    "bounded-test-model",
                    "mechanical-test-model",
                ],
                "extra_headers": {"X-Provider-Mode": "private"},
            }
        ]


def test_missing_parent_custom_provider_fails_before_worker_write(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    inputs = {
        component: replace(value, provider_id="missing-provider")
        for component, value in _inputs().items()
    }
    before = {
        item.current_name: (item.path / "config.yaml").read_bytes() for item in discovery.targets
    }

    with pytest.raises(ValueError, match="custom Provider"):
        build_activation_plan(discovery, found, inputs)

    assert {
        item.current_name: (item.path / "config.yaml").read_bytes() for item in discovery.targets
    } == before


def test_activation_preserves_unrelated_worker_provider_and_never_renders_copied_secret(
    tmp_path: Path,
) -> None:
    found, discovery = _installation(tmp_path)
    for target in discovery.targets:
        config = yaml.safe_load((target.path / "config.yaml").read_text())
        config["custom_providers"] = [
            {"name": "keep-provider", "base_url": "https://keep.invalid/v1", "key_env": "KEEP"}
        ]
        (target.path / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    plan = build_activation_plan(discover_installation(found.profiles_root), found, _inputs())
    rendered: list[str] = []

    result = apply_activation(
        plan,
        input_fn=lambda _prompt: plan.confirmation_phrase,
        output=_Writer(rendered),
    )

    assert result.status is ActivationStatus.CANARY_REQUIRED
    assert "PRIVATE-CUSTOM-PROVIDER-KEY" not in "".join(rendered)
    for target in plan.bindings:
        config = yaml.safe_load((target.profile_path / "config.yaml").read_text())
        assert [item["name"] for item in config["custom_providers"]] == [
            "keep-provider",
            "custom-provider",
        ]


def test_existing_profile_definition_never_reads_main_or_rewrites_definition(
    tmp_path: Path,
) -> None:
    found, discovery = _installation(tmp_path)
    (found.hermes_home / "config.yaml").unlink()
    inputs = _inputs()
    before_definitions: dict[str, object] = {}
    for target in discovery.targets:
        config_path = target.path / "config.yaml"
        config = yaml.safe_load(config_path.read_text())
        definition = {
            "name": "custom-provider",
            "base_url": SECRET_ENDPOINT,
            "api_key": f"OWN-{target.current_name}",
        }
        config["custom_providers"] = [definition]
        config_path.write_text(yaml.safe_dump(config, sort_keys=False))
        before_definitions[target.current_name] = definition
        inputs[target.component_id] = replace(
            inputs[target.component_id],
            credential_grant_kind="existing-profile-definition",
        )

    plan = build_activation_plan(discover_installation(found.profiles_root), found, inputs)
    result = apply_activation(plan, input_fn=lambda _: plan.confirmation_phrase)

    assert result.status is ActivationStatus.CANARY_REQUIRED
    for target in plan.bindings:
        config = yaml.safe_load((target.profile_path / "config.yaml").read_text())
        assert config["custom_providers"] == [before_definitions[target.profile_name]]


def test_unresolved_grant_stops_before_confirmation_and_first_write(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    inputs = _inputs()
    first = discovery.targets[0]
    inputs[first.component_id] = replace(
        inputs[first.component_id],
        credential_grant_kind="configuration-required",
        credential_state="unresolved",
    )
    before = {
        target.current_name: (target.path / "config.yaml").read_bytes()
        for target in discovery.targets
    }
    plan = build_activation_plan(discovery, found, inputs)

    result = apply_activation(plan, input_fn=lambda _: pytest.fail("must stop before confirmation"))

    assert result.status is ActivationStatus.CREDENTIAL_REQUIRED
    assert {
        target.current_name: (target.path / "config.yaml").read_bytes()
        for target in discovery.targets
    } == before


def test_source_provider_drift_after_confirmation_compensates_worker_writes(
    tmp_path: Path,
) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())

    def drift_source(_target: ActivationTargetPlan, index: int) -> None:
        if index == len(plan.bindings) - 1:
            source = yaml.safe_load((found.hermes_home / "config.yaml").read_text())
            source["custom_providers"][0]["api_key"] = "CONCURRENT-PRIVATE-KEY"
            (found.hermes_home / "config.yaml").write_text(yaml.safe_dump(source, sort_keys=False))

    result = apply_activation(
        plan,
        input_fn=lambda _prompt: plan.confirmation_phrase,
        after_write=drift_source,
    )

    assert result.status is ActivationStatus.FAILED
    for target in plan.bindings:
        config = yaml.safe_load((target.profile_path / "config.yaml").read_text())
        assert "provider" not in config["model"]
        assert "custom_providers" not in config


def test_source_drift_during_receipt_publication_compensates_configs_and_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    original = activation._write_receipt  # pyright: ignore[reportPrivateUsage]
    injected = False

    def drift_then_write(
        target: ActivationTargetPlan, readback: activation.ConfigSnapshot
    ) -> object:
        nonlocal injected
        if not injected:
            injected = True
            source = yaml.safe_load((found.hermes_home / "config.yaml").read_text())
            source["custom_providers"][0]["api_key"] = "RECEIPT-WINDOW-PRIVATE-KEY"
            (found.hermes_home / "config.yaml").write_text(yaml.safe_dump(source, sort_keys=False))
        return original(target, readback)

    monkeypatch.setattr(activation, "_write_receipt", drift_then_write)

    result = apply_activation(plan, input_fn=lambda _prompt: plan.confirmation_phrase)

    assert result.status is ActivationStatus.FAILED
    for target in plan.bindings:
        loaded = yaml.safe_load((target.profile_path / "config.yaml").read_text())
        assert "provider" not in loaded["model"]
        assert "custom_providers" not in loaded
        assert not (target.profile_path / "local/agentporter/runtime-binding.json").exists()


def test_worker_provider_drift_before_receipt_is_not_certified(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    last = plan.bindings[-1]

    def drift_last_worker(_target: ActivationTargetPlan, index: int) -> None:
        if index == len(plan.bindings) - 1:
            config = yaml.safe_load((last.profile_path / "config.yaml").read_text())
            config["custom_providers"][0]["api_key"] = "DRIFTED-WORKER-PRIVATE-KEY"
            (last.profile_path / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))

    result = apply_activation(
        plan,
        input_fn=lambda _prompt: plan.confirmation_phrase,
        after_write=drift_last_worker,
    )

    assert result.status is ActivationStatus.COMPENSATION_INCOMPLETE
    assert result.residue_count == 1
    for target in plan.bindings:
        assert not (target.profile_path / "local/agentporter/runtime-binding.json").exists()
    first = yaml.safe_load((plan.bindings[0].profile_path / "config.yaml").read_text())
    assert "provider" not in first["model"]
    drifted = yaml.safe_load((last.profile_path / "config.yaml").read_text())
    assert drifted["custom_providers"][0]["api_key"] == "DRIFTED-WORKER-PRIVATE-KEY"


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
        probe_runner=lambda binding, _nonce, _directory: probes.append(binding.component_id),
    )

    assert result.status is ActivationStatus.CREDENTIAL_REQUIRED
    assert probes == []


def test_authorized_activation_probes_each_worker_without_cross_fallback_and_updates_receipts(
    tmp_path: Path,
) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    calls: list[str] = []

    def probe(binding: RuntimeBindingPlan, nonce: str, _directory: Path) -> ProbeObservation:
        calls.append(binding.component_id)
        if binding.component_id == plan.bindings[0].component_id:
            return ProbeObservation(http_status=401)
        return ProbeObservation(
            output=f"AGENTPORTER_READY:{nonce}",
            actual_model=binding.expected_model,
            actual_provider=binding.provider_id,
            api_calls=1,
            tool_calls=0,
        )

    result = apply_activation(
        plan,
        input_fn=lambda _: plan.confirmation_phrase,
        probe_runner=probe,
    )

    assert result.status is ActivationStatus.CANARY_FAILED
    payloads = [
        json.loads((item.profile_path / "local/agentporter/runtime-binding.json").read_text())
        for item in plan.bindings
    ]
    assert [item["canary_status"] for item in payloads] == ["failed", "passed"]
    assert [item["canary_reason_code"] for item in payloads] == [
        "authentication-failed",
        "runtime-ready",
    ]
    assert all("error" not in item for item in payloads)
    successful = payloads[1]
    assert successful["actual_model"] == plan.bindings[1].binding.expected_model
    assert successful["actual_provider"] == "custom-provider"
    assert successful["api_calls"] == 1
    assert successful["tool_calls_observed"] == 0
    assert successful["fallback_used"] is False
    assert successful["response_contract_passed"] is True
    assert successful["hermes_version"] == "0.20.0"
    assert successful["config_digest"]
    assert successful["binding_fingerprint"]
    assert successful["probe_started_at"]
    assert successful["probe_finished_at"]
    assert successful["fresh_until"]
    assert SECRET_ENDPOINT not in json.dumps(successful)


def test_probe_exceptions_are_safe_per_worker_failures_without_raw_text(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    calls: list[str] = []

    def probe(binding: RuntimeBindingPlan, _nonce: str, _directory: Path) -> ProbeObservation:
        calls.append(binding.component_id)
        if len(calls) == 1:
            raise RuntimeError("RAW_PROVIDER_SECRET " + SECRET_ENDPOINT)
        return ProbeObservation(http_status=401)

    result = apply_activation(plan, input_fn=lambda _: plan.confirmation_phrase, probe_runner=probe)
    assert result.status is ActivationStatus.CANARY_FAILED
    receipts = [
        (item.profile_path / "local/agentporter/runtime-binding.json").read_text()
        for item in plan.bindings
    ]
    assert all(
        "RAW_PROVIDER_SECRET" not in value and SECRET_ENDPOINT not in value for value in receipts
    )


@pytest.mark.parametrize(
    "interrupt", [KeyboardInterrupt("probe"), SystemExit(9), _StopActivation("probe")]
)
def test_probe_control_flow_preserves_identity_and_publishes_no_fake_terminal_receipt(
    tmp_path: Path, interrupt: BaseException, monkeypatch: pytest.MonkeyPatch
) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    monkeypatch.setattr(
        activation,
        "run_runtime_probe",
        lambda **_kwargs: (_ for _ in ()).throw(interrupt),
    )

    with pytest.raises(type(interrupt)) as caught:
        apply_activation(
            plan,
            input_fn=lambda _: plan.confirmation_phrase,
            probe_runner=lambda _binding, _nonce, _directory: ProbeObservation(),
        )
    assert caught.value is interrupt
    for item in plan.bindings:
        receipt = json.loads(
            (item.profile_path / "local/agentporter/runtime-binding.json").read_text()
        )
        assert receipt["canary_status"] == "required"


def test_canary_receipt_cas_preserves_concurrent_drift_and_reports_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    receipt = plan.bindings[0].profile_path / "local/agentporter/runtime-binding.json"
    original = activation._write_canary_receipt
    injected = False

    def drift(
        target: ActivationTargetPlan,
        result: ProbeResult,
        expected: activation._ReceiptSnapshot,
    ) -> activation._ReceiptSnapshot:
        nonlocal injected
        if not injected:
            injected = True
            receipt.write_text('{"concurrent":"KEEP"}\n', encoding="utf-8")
        return original(target, result, expected)

    monkeypatch.setattr(activation, "_write_canary_receipt", drift)
    result = apply_activation(
        plan,
        input_fn=lambda _: plan.confirmation_phrase,
        probe_runner=lambda _binding, _nonce, _directory: ProbeObservation(http_status=401),
    )
    assert result.status is ActivationStatus.COMPENSATION_INCOMPLETE
    assert result.residue_count >= 1
    assert json.loads(receipt.read_text()) == {"concurrent": "KEEP"}


def test_safe_receipt_is_private_atomic_and_inside_user_owned_local(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())

    result = apply_activation(plan, input_fn=lambda _: plan.confirmation_phrase)

    assert result.status is ActivationStatus.CANARY_REQUIRED
    for binding in plan.bindings:
        receipt = binding.profile_path / "local" / "agentporter" / "runtime-binding.json"
        assert receipt.is_file()
        assert receipt.stat().st_mode & 0o777 == 0o600
        assert receipt.parent.stat().st_mode & 0o777 == 0o700
        payload = receipt.read_text(encoding="utf-8")
        assert SECRET_ENDPOINT not in payload
        assert not (binding.profile_path / ".env").exists()
        assert not (binding.profile_path / "auth.json").exists()


def test_first_receipt_publication_refuses_preexisting_external_file(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    receipt = plan.bindings[0].profile_path / "local/agentporter/runtime-binding.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"external":"KEEP"}\n', encoding="utf-8")

    result = apply_activation(plan, input_fn=lambda _: plan.confirmation_phrase)

    assert result.status is ActivationStatus.FAILED
    assert json.loads(receipt.read_text()) == {"external": "KEEP"}


def test_identical_receipt_replay_preserves_identity(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    first = build_activation_plan(discovery, found, _inputs())
    assert (
        apply_activation(first, input_fn=lambda _: first.confirmation_phrase).status
        is ActivationStatus.CANARY_REQUIRED
    )
    receipts = [
        item.profile_path / "local/agentporter/runtime-binding.json" for item in first.bindings
    ]
    identities = [(path.stat().st_dev, path.stat().st_ino, path.read_bytes()) for path in receipts]

    replay = build_activation_plan(discover_installation(found.profiles_root), found, _inputs())
    assert (
        apply_activation(replay, input_fn=lambda _: replay.confirmation_phrase).status
        is ActivationStatus.CANARY_REQUIRED
    )
    assert [
        (path.stat().st_dev, path.stat().st_ino, path.read_bytes()) for path in receipts
    ] == identities


def test_receipt_update_rejects_unknown_external_schema(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    first = build_activation_plan(discovery, found, _inputs())
    assert (
        apply_activation(first, input_fn=lambda _: first.confirmation_phrase).status
        is ActivationStatus.CANARY_REQUIRED
    )
    receipt = first.bindings[0].profile_path / "local/agentporter/runtime-binding.json"
    receipt.write_text('{"schema_version":1,"foreign":true}\n', encoding="utf-8")
    source = yaml.safe_load((found.hermes_home / "config.yaml").read_text())
    replacement = dict(source["custom_providers"][0])
    replacement["name"] = "replacement-provider"
    source["custom_providers"].append(replacement)
    (found.hermes_home / "config.yaml").write_text(yaml.safe_dump(source, sort_keys=False))
    changed = {
        key: replace(value, provider_id="replacement-provider") for key, value in _inputs().items()
    }
    update = build_activation_plan(discover_installation(found.profiles_root), found, changed)

    result = apply_activation(update, input_fn=lambda _: update.confirmation_phrase)

    assert result.status is ActivationStatus.FAILED
    assert json.loads(receipt.read_text()) == {"schema_version": 1, "foreign": True}


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
        is ActivationStatus.CANARY_REQUIRED
    )
    assert [path.read_text() for path in sentinels] == ["owned elsewhere"] * len(sentinels)


def test_second_receipt_failure_restores_both_existing_receipts_and_configs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found, discovery = _installation(tmp_path)
    first_plan = build_activation_plan(discovery, found, _inputs())
    assert (
        apply_activation(first_plan, input_fn=lambda _: first_plan.confirmation_phrase).status
        is ActivationStatus.CANARY_REQUIRED
    )
    before_configs = [
        item.profile_path.joinpath("config.yaml").read_bytes() for item in first_plan.bindings
    ]
    receipts = [
        item.profile_path / "local/agentporter/runtime-binding.json" for item in first_plan.bindings
    ]
    before_receipts = [path.read_bytes() for path in receipts]
    source = yaml.safe_load((found.hermes_home / "config.yaml").read_text())
    replacement = dict(source["custom_providers"][0])
    replacement["name"] = "replacement-provider"
    source["custom_providers"].append(replacement)
    (found.hermes_home / "config.yaml").write_text(yaml.safe_dump(source, sort_keys=False))
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


@pytest.mark.skipif(os.geteuid() != 0, reason="changing file ownership requires root")
def test_atomic_config_replacement_preserves_owner_and_private_mode(tmp_path: Path) -> None:
    found, discovery = _installation(tmp_path)
    plan = build_activation_plan(discovery, found, _inputs())
    config = plan.bindings[0].profile_path / "config.yaml"
    os.chown(config, 65534, 65534)
    plan = build_activation_plan(discover_installation(found.profiles_root), found, _inputs())

    assert (
        apply_activation(plan, input_fn=lambda _: plan.confirmation_phrase).status
        is ActivationStatus.CANARY_REQUIRED
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
