from unittest.mock import MagicMock

import pytest

from adapters.outlook import client, sync


def test_discovery_uses_ids_excludes_descendants_and_has_no_depth_cutoff(monkeypatch):
    monkeypatch.setattr(client, "get_access_token", lambda: "synthetic")
    visited = []

    def folder(id, name, children=0):
        return {"id": id, "displayName": name, "totalItemCount": 1, "childFolderCount": children}

    def get(url, headers):
        visited.append(url)
        response = MagicMock()
        key = url.split("/mailFolders/")[-1].split("?")[0]
        if key in ("inbox", "sentitems", "deleteditems", "junkemail", "drafts", "outbox"):
            data = {"id": "builtin-" + key}
        elif "/childFolders" in url:
            parent = key.split("/")[0]
            level = int(parent[1:]) if parent.startswith("n") else 0
            data = {"value": [folder("n" + str(level + 1), "Level", level < 7)]}
        else:
            data = {
                "value": [
                    folder("builtin-inbox", "收件箱"),
                    folder("builtin-sentitems", "已发送"),
                    folder("builtin-drafts", "草稿", 1),
                    folder("builtin-deleteditems", "垃圾桶", 1),
                    folder("custom", "Inbox"),
                    folder("n0", "Projects", 1),
                ]
            }
        response.json.return_value = data
        return response

    monkeypatch.setattr(client, "_get_with_retry", get)
    rows = client.discover_folders()
    keys = {r[0] for r in rows}
    assert {"inbox", "sentitems", "custom", "n8"} <= keys
    assert "builtin-drafts" not in keys
    assert not any(
        "/builtin-drafts/childFolders" in u or "/builtin-deleteditems/childFolders" in u
        for u in visited
    )


def test_default_scope_no_discovery_and_all_includes_empty_folders(monkeypatch):
    monkeypatch.delenv("OUTLOOK_FOLDER_SCOPE", raising=False)
    discover = MagicMock(return_value=[("custom", "Empty parent", 0)])
    monkeypatch.setattr(sync, "discover_folders", discover, raising=False)
    assert sync._folders_to_sync() == [("inbox", "inbox"), ("sentitems", "sentitems")]
    discover.assert_not_called()
    monkeypatch.setenv("OUTLOOK_FOLDER_SCOPE", "all")
    assert sync._folders_to_sync() == [("custom", "Empty parent")]
    monkeypatch.setenv("OUTLOOK_FOLDER_SCOPE", "typo")
    with pytest.raises(ValueError):
        sync._folders_to_sync()


def test_delta_paths_preserve_builtin_and_safely_hash_ids():
    assert sync._delta_link_path("inbox") == sync._DELTA_LINK_PATHS["inbox"]
    path = sync._delta_link_path("../../a/b=long")
    assert path.parent == sync._DELTA_LINK_PATHS["inbox"].parent
    assert path.name.startswith(".delta_link.id-")
    assert path != sync._delta_link_path("../../a/b=long2")


def test_folder_discovery_follows_pagination(monkeypatch):
    monkeypatch.setattr(client, "get_access_token", lambda: "synthetic")
    def get(url, headers):
        response = MagicMock()
        if "?$select=id" in url and "$top" not in url:
            data = {"id": url.split("/mailFolders/")[-1].split("?")[0]}
        elif "page2" in url:
            data = {"value": [{"id": "filed", "displayName": "Filed"}]}
        else:
            data = {"value": [], "@odata.nextLink": client.GRAPH_BASE + "/page2"}
        response.json.return_value = data
        return response
    monkeypatch.setattr(client, "_get_with_retry", get)
    assert client.discover_folders() == [("filed", "Filed", 0)]


def test_draft_outside_drafts_is_never_ingested():
    assert sync._to_envelope({"isDraft": True, "internetMessageId": "draft"}, set()) is None
    assert "isDraft" in client._SELECT_FIELDS.split(",")


def test_failed_commit_does_not_advance_delta_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTLOOK_MAILBOX", "me@example.test")
    monkeypatch.setenv("DATABASE_URL", "synthetic")
    monkeypatch.setattr(sync, "load_dotenv", lambda: None)
    monkeypatch.setattr(sync, "_migrate_legacy_inbox_delta_link", lambda: None)
    monkeypatch.setattr(sync, "_write_status", lambda *a: None)
    paths = {f: tmp_path / (f + ".txt") for f in ("inbox", "sentitems")}
    monkeypatch.setattr(sync, "_DELTA_LINK_PATHS", paths)
    monkeypatch.delenv("OUTLOOK_FOLDER_SCOPE", raising=False)

    def fetch(**kwargs):
        yield from ()
        return "next-checkpoint"

    monkeypatch.setattr(sync, "fetch_messages", fetch)
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.commit.side_effect = RuntimeError("commit failed")
    monkeypatch.setattr(sync.psycopg, "connect", lambda *a, **k: conn)
    with pytest.raises(RuntimeError, match="commit failed"):
        sync.run()
    assert not any(p.exists() for p in paths.values())
