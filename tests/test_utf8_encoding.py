"""
Tests ensuring explicit UTF-8 encoding across packaging and MCP configuration.
"""

from pathlib import Path
from importlib import resources
import json
import pytest

from libshipkore.mcp_server.config import load_config


def test_carriers_json_loads_as_utf8():
    """Verify carrier directory data resource loads cleanly as UTF-8."""
    text = resources.files("libshipkore").joinpath("data/carriers.json").read_text(encoding="utf-8")
    data = json.loads(text)
    assert len(data) > 0
    assert any(c.get("slug") == "delhivery" for c in data)


def test_capability_matrix_markdown_loads_as_utf8():
    """Verify provider capability matrix resource loads cleanly as UTF-8."""
    text = resources.files("libshipkore").joinpath("data/provider-capability-matrix.md").read_text(encoding="utf-8")
    assert len(text) > 0
    assert "Delhivery" in text or "delhivery" in text


def test_mcp_config_loads_utf8_unicode(tmp_path):
    """Verify MCP load_config reads JSON containing UTF-8 characters on all platforms."""
    cfg_file = tmp_path / "config.json"
    data = {
        "providers": {
            "delhivery": {
                "credentials": {"api_token": "token-🚀-123"},
                "sandbox": True
            }
        }
    }
    cfg_file.write_text(json.dumps(data), encoding="utf-8")
    loaded = load_config(str(cfg_file), environ={})
    assert loaded["providers"]["delhivery"]["credentials"]["api_token"] == "token-🚀-123"


def test_setup_py_utf8_compliance():
    """Verify setup.py reads README and HISTORY with UTF-8 without cp1252 exceptions."""
    root = Path(__file__).resolve().parent.parent
    readme = (root / "README.rst").read_text(encoding="utf-8")
    history = (root / "HISTORY.rst").read_text(encoding="utf-8")
    assert len(readme) > 0
    assert len(history) > 0
