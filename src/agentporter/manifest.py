from __future__ import annotations

from pathlib import Path
from typing import cast

import yaml

from .models import WorkersManifest


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = cast(object, loader.construct_object(key_node, deep=deep))  # pyright: ignore[reportUnknownMemberType]
        try:
            duplicate = key in mapping
        except TypeError as error:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found unhashable key",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = cast(
            object,
            loader.construct_object(value_node, deep=deep),  # pyright: ignore[reportUnknownMemberType]
        )
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def load_manifest(path: Path) -> WorkersManifest:
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.load(stream, Loader=_UniqueKeySafeLoader)
    return WorkersManifest.model_validate(data)
