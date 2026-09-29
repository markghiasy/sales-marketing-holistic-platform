from pathlib import Path

import pytest


def test_release_contains_runtime_assets_and_explicit_clis():
    from scripts.check_network_real import check
    from scripts.network_real import create_app
    from scripts.network_schema import main as schema_main
    from scripts.network_worker import main
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


def test_declared_flask_versions_enforce_trusted_hosts():
    import tomllib

    from packaging.requirements import Requirement
    root=Path(__file__).resolve().parents[1]
    dependencies=tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))['project']['dependencies']
    requirement=next(Requirement(d) for d in dependencies if Requirement(d).name.casefold()=='flask')
    assert '3.0.3' not in requirement.specifier
    assert '3.1.0' in requirement.specifier
