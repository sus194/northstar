from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from northstar.config import load_parameter_version


@pytest.fixture
def params():
    return load_parameter_version("p1")
