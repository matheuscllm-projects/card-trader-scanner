"""Isola a suíte: SKIP_LIST_FILE aponta pra tmp_path, nunca pra a skip-list real da raiz."""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def _isolate_skip_list(tmp_path, monkeypatch):
    import cardtrader_scanner as sc

    monkeypatch.setattr(sc, "SKIP_LIST_FILE", tmp_path / "scanner_skip_list.json")
