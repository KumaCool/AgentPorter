from __future__ import annotations

from pathlib import Path

import yaml

from .models import WorkersManifest


def load_manifest(path: Path) -> WorkersManifest:
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    return WorkersManifest.model_validate(data)
