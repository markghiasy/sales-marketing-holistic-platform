import json
from pathlib import Path

from .model import ScenarioData


def load_scenario(path: Path | None = None) -> ScenarioData:
    source = path or Path(__file__).resolve().parents[2] / "tests/fixtures/network_demo.json"
    return json.loads(source.read_text(encoding="utf-8"))
