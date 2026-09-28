import json
import threading
from copy import deepcopy
from pathlib import Path

from .model import ScenarioData
from .projection import build_snapshot
from .search import search_contacts


def load_scenario(path: Path | None = None) -> ScenarioData:
    source = path or Path(__file__).resolve().parents[2] / "tests/fixtures/network_demo.json"
    return json.loads(source.read_text(encoding="utf-8"))


class ScenarioStore:
    def __init__(self):
        self._condition = threading.Condition()
        self._data = load_scenario()
        self.version = 1

    def data(self):
        with self._condition:
            return deepcopy(self._data)

    def capture(self):
        with self._condition:
            return deepcopy(self._data), self.version

    def snapshot(self, query):
        with self._condition:
            return build_snapshot(self._data, query, self.version)

    def reply(self):
        with self._condition:
            for direction, minute in [("out", "00"), ("in", "05")]:
                self._data["messages"].append(
                    {
                        "id": f"reply:{self.version}:{direction}",
                        "contact_id": "person:maya",
                        "channel": "whatsapp",
                        "direction": direction,
                        "direct": True,
                        "at": f"2026-09-27T10:{minute}:00Z",
                        "text": "Fictional reply: Yes, I can help with the Harbour finance review this week.",
                    }
                )
            self.version += 1
            self._condition.notify_all()
            return self.version

    def search(self, query, text):
        with self._condition:
            return search_contacts(self._data, query, text, self.version)

    def reset(self):
        with self._condition:
            self._data = load_scenario()
            self.version += 1
            self._condition.notify_all()
            return self.version

    def wait_for_version(self, after, timeout):
        with self._condition:
            self._condition.wait_for(lambda: self.version > after, timeout)
            return self.version
