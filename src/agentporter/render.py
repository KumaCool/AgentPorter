from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import yaml

from .identity import COMPONENT_IDS, INITIAL_PROFILE_NAMES, PRODUCT_ID
from .models import HermesProfileName, MarkerV1, WorkersManifest

DISTRIBUTION_VERSION = "0.1.0"
DISTRIBUTION_OWNED = ("SOUL.md", "config.yaml", "agentporter-profile.json")


@dataclass(frozen=True)
class RenderedProfile:
    portable_id: str
    profile_name: str
    directory: Path


def _soul(instructions: str, mechanical: bool) -> str:
    rules = [
        instructions.rstrip(),
        "",
        "AgentPorter delegation boundaries:",
        "- Do not change the delegated objective.",
        "- Do not broaden the delegated scope or file set.",
        "- If required information is missing, stop and report the exact blocker.",
        "- Never invent results in place of real execution and verification.",
    ]
    if mechanical:
        rules.append("- Accept only work that is simpler and more mechanical than bounded work.")
    return "\n".join(rules) + "\n"


def render_staging(
    manifest: WorkersManifest, staging_root: Path, installation_id: UUID
) -> tuple[RenderedProfile, ...]:
    canonical_installation_id = str(installation_id)
    rendered: list[RenderedProfile] = []
    for portable_id, worker in manifest.workers.items():
        profile_name = str(HermesProfileName(INITIAL_PROFILE_NAMES[portable_id]))
        directory = staging_root / profile_name
        directory.mkdir(parents=True, exist_ok=False)
        distribution = {
            "name": profile_name,
            "version": DISTRIBUTION_VERSION,
            "description": worker.description,
            "license": "MIT",
            "distribution_owned": list(DISTRIBUTION_OWNED),
        }
        model_config = {"default": worker.model}
        if worker.provider is not None:
            model_config["provider"] = worker.provider
        config = {"model": model_config, "agent": {"reasoning_effort": worker.reasoning_effort}}
        marker = MarkerV1(
            schema_version=1,
            product_id=PRODUCT_ID,
            component_id=COMPONENT_IDS[portable_id],
            installation_id=canonical_installation_id,
            distribution_version=DISTRIBUTION_VERSION,
        )
        (directory / "distribution.yaml").write_text(
            yaml.safe_dump(distribution, sort_keys=False), encoding="utf-8"
        )
        (directory / "config.yaml").write_text(
            yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
        )
        (directory / "SOUL.md").write_text(
            _soul(worker.instructions, worker.tier == "mechanical"), encoding="utf-8"
        )
        (directory / "agentporter-profile.json").write_text(
            json.dumps(marker.model_dump(), indent=2) + "\n", encoding="utf-8"
        )
        rendered.append(RenderedProfile(portable_id, profile_name, directory))
    return tuple(rendered)
