from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import monitor


def test_check_all_returns_three_channel_statuses(monkeypatch):
    cur = MagicMock()
    cur.fetchone.return_value = (None,)  # "no messages ever ingested" for outlook/linkedin
    monkeypatch.setattr(monitor, "_check_whatsapp_liveness", lambda: monitor.ChannelStatus("whatsapp", True, "ok"))

    statuses = monitor.check_all(cur)

    assert [s.channel for s in statuses] == ["outlook", "linkedin", "whatsapp"]
    assert statuses[0].healthy is False  # no messages ever ingested
    assert statuses[2].healthy is True
