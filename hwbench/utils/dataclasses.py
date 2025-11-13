from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _typeshed import DataclassInstance


def iterate_dataclass(obj: DataclassInstance | dict):
    """Useful to not convert a whole dataclass recursively to keep instances"""

    if isinstance(obj, dict):
        yield from obj.items()
    else:
        for field in dataclasses.fields(obj):
            yield (field.name, getattr(obj, field.name))
