"""Parameter-version loading.

Per spec section 9.1: a parameter version is a frozen, versioned JSON blob.
Changing a default requires minting a new version id (p2, p3, ...) rather
than mutating p1 in place. This module only *loads* versions; it never
writes them except via ledger.store.freeze_parameter_version.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ParameterVersion:
    version: str
    setup_name: str
    frozen_at: str
    holdout_start: str
    in_sample_start: str
    in_sample_end: str
    parameters: dict[str, Any]
    news_keyword_list_version: str
    news_keywords: tuple[str, ...]

    def get(self, key: str) -> Any:
        return self.parameters[key]

    @property
    def raw(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "setup_name": self.setup_name,
            "frozen_at": self.frozen_at,
            "holdout_start": self.holdout_start,
            "in_sample_start": self.in_sample_start,
            "in_sample_end": self.in_sample_end,
            "parameters": self.parameters,
            "news_keyword_list_version": self.news_keyword_list_version,
            "news_keywords": list(self.news_keywords),
        }


def _params_dir() -> Path:
    return Path(str(resources.files("northstar") / "params"))


@cache
def load_parameter_version(version: str = "p1") -> ParameterVersion:
    path = _params_dir() / f"{version}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No parameter version file at {path}. Known versions live in "
            "src/northstar/params/*.json and must never be edited after "
            "freezing -- create a new version instead."
        )
    data = json.loads(path.read_text())
    return ParameterVersion(
        version=data["version"],
        setup_name=data["setup_name"],
        frozen_at=data["frozen_at"],
        holdout_start=data["holdout_start"],
        in_sample_start=data["in_sample_start"],
        in_sample_end=data["in_sample_end"],
        parameters=data["parameters"],
        news_keyword_list_version=data["news_keyword_list_version"],
        news_keywords=tuple(data["news_keywords"]),
    )
