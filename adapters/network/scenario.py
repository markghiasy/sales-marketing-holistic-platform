import json
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from .model import ScenarioData
from .projection import build_snapshot
from .search import search_contacts


def load_scenario(path: Path | None = None) -> ScenarioData:
    source = path or Path(__file__).resolve().parents[2] / "tests/fixtures/network_demo.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    if path is None:
        strategy = json.loads(source.with_name("network_strategy.json").read_text(encoding="utf-8"))
        data["strategic_assertions"] = strategy["strategic_assertions"]
        data["evidence"].extend(strategy["evidence"])
    return data


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

    def review_profile(self, assertion_id, status, subject_id, version):
        from .profiles import validate_assertion

        with self._condition:
            if version != self.version:
                raise RuntimeError("The scenario changed. Reload the profile before reviewing.")
            row = next((a for a in self._data.get("strategic_assertions", []) if a["id"] == assertion_id), None)
            if row is None:
                raise KeyError(assertion_id)
            candidate = {**row, "subject_id": subject_id, "status": status}
            validate_assertion(self._data, candidate)
            now = datetime.now(UTC).isoformat()
            self._data.setdefault("strategic_reviews", []).append(
                {"id": assertion_id, "at": now, "status": status, "subject_id": subject_id}
            )
            self.version += 1
            self._condition.notify_all()
            return {"version": self.version, "as_of": now}

    def add_profile_proposals(self, rows, version):
        with self._condition:
            if version != self.version:
                raise RuntimeError("The scenario changed during extraction. Retry from the updated profile.")
            now = datetime.now(UTC).isoformat()
            existing = self._data.setdefault("strategic_assertions", [])

            def fingerprint(row):
                return (row["subject_id"], row["facet"], row["quote"], tuple(sorted(row["evidence_ids"])))

            seen = {fingerprint(row) for row in existing}
            added = 0
            for row in rows:
                if fingerprint(row) not in seen:
                    existing.append({**row, "observed_at": now, "status": "pending"})
                    seen.add(fingerprint(row))
                    added += 1
            self.version += 1
            self._condition.notify_all()
            return {"version": self.version, "as_of": now, "added": added}

    def wait_for_version(self, after, timeout):
        with self._condition:
            self._condition.wait_for(lambda: self.version > after, timeout)
            return self.version
