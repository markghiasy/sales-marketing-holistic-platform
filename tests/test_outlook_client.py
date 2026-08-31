from __future__ import annotations

from unittest.mock import MagicMock, patch

from adapters.outlook import client


def test_get_access_token_calls_on_device_code_before_polling(monkeypatch, tmp_path):
    monkeypatch.setattr(client, "TOKEN_CACHE_PATH", tmp_path / ".token_cache.bin")

    device_code_response = MagicMock()
    device_code_response.json.return_value = {
        "message": "go to https://microsoft.com/devicelogin and enter ABC-123",
        "user_code": "ABC-123",
        "verification_uri": "https://microsoft.com/devicelogin",
        "device_code": "raw-device-code",
        "interval": 0,
        "expires_in": 900,
    }
    device_code_response.raise_for_status = MagicMock()

    token_response = MagicMock()
    token_response.json.return_value = {"access_token": "tok", "expires_in": 3600}

    seen = []
    with patch.object(client.requests, "post", side_effect=[device_code_response, token_response]):
        result = client.get_access_token(on_device_code=lambda flow: seen.append(flow))

    assert result == "tok"
    assert seen == [device_code_response.json.return_value]
