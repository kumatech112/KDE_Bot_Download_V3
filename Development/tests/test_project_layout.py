from pathlib import Path
import hashlib
import importlib.util

import pytest


def load_tool(name):
    path = Path(__file__).resolve().parents[1] / 'tools' / (name + '.py')
    spec = importlib.util.spec_from_file_location('layout_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('relative', ['Program', 'portable', 'Archive/builds/portable-20261017-120000',
                                      'Archive/releases/KDE-3.8.1-0123456789ab'])
def test_promotion_accepts_only_designated_bundle_locations(tmp_path, relative):
    tool = load_tool('promote_portable')
    tool.ROOT = tmp_path / 'project'
    bundle = tool.ROOT / relative
    bundle.mkdir(parents=True)
    payload = b'identified test executable'
    (bundle / tool.EXE).write_bytes(payload)
    (bundle / '_internal').mkdir()
    (bundle / 'Quick start.md').write_text('test guide', encoding='utf-8')
    digest = hashlib.sha256(payload).hexdigest()
    assert tool.validate_bundle(bundle, digest) == bundle.resolve()
    with pytest.raises(ValueError, match='differs'):
        tool.validate_bundle(bundle, '0' * 64)


@pytest.mark.parametrize('relative', ['business-files', '../outside', 'Archive/other/portable-20261017-120000'])
def test_promotion_rejects_unapproved_locations_before_touching_files(tmp_path, relative):
    tool = load_tool('promote_portable')
    tool.ROOT = tmp_path / 'project'
    bundle = tool.ROOT / relative
    bundle.mkdir(parents=True)
    marker = bundle / 'preserve.txt'
    marker.write_bytes(b'do not change')
    with pytest.raises(ValueError, match='contained'):
        tool.validate_bundle(bundle, '0' * 64)
    assert marker.read_bytes() == b'do not change'
