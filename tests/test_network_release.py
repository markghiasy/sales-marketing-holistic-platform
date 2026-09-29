from pathlib import Path

import pytest


def test_release_contains_runtime_assets_and_explicit_clis():
    from scripts.network_real import create_app
    from scripts.network_worker import main
    from scripts.network_schema import main as schema_main
    from scripts.check_network_real import check
    root=Path(__file__).resolve().parents[1]
    for name in ('scripts/onboarding/templates/inbox.html','scripts/onboarding/templates/network.html',
                 'scripts/onboarding/static/network/profiles.js','scripts/onboarding/static/vendor/cytoscape.min.js',
                 'db/network/0001_network.sql'):
        assert (root/name).is_file(),name
    assert all(callable(f) for f in (create_app,main,schema_main,check))


def test_smoke_rejects_nonlocal_target_without_contacting_it():
    from scripts.check_network_real import check
    with pytest.raises(ValueError,match='loopback'):
        check('https://example.com')
