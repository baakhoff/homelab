"""Tests for the extra sources pipelines/dags/ingest.py reads from
/opt/airflow/extra/sources.json. Airflow, pendulum and requests are stood in
for. Run from the repo root:

    uv run --with pytest pytest pipelines/tests
"""

import importlib
import json
import sys
import types
from pathlib import Path

import pytest


class _Task:
    """A task that is never run: only expanded when the DAG is defined."""

    def __init__(self, f):
        self.f = f

    def expand(self, **kw):
        return None


_sdk = types.ModuleType("airflow.sdk")
_sdk.dag = lambda **kw: (lambda f: (lambda *a, **k: f()))
_sdk.task = lambda *a, **kw: (lambda f: _Task(f))
sys.modules.setdefault("airflow", types.ModuleType("airflow"))
sys.modules.setdefault("airflow.sdk", _sdk)
_pendulum = types.ModuleType("pendulum")
_pendulum.datetime = lambda *a, **kw: None
_pendulum.duration = lambda **kw: None
sys.modules.setdefault("pendulum", _pendulum)
try:
    import requests  # noqa: F401
except ImportError:
    _requests = types.ModuleType("requests")
    _requests.Session = object
    _requests.Response = object
    sys.modules["requests"] = _requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))


def load(monkeypatch, tmp_path, content):
    if content is not None:
        (tmp_path / "sources.json").write_text(content)
    monkeypatch.setenv("AIRFLOW_EXTRA", str(tmp_path))
    sys.modules.pop("ingest", None)
    return importlib.import_module("ingest")


def test_no_extra_folder_means_no_extra_sources(monkeypatch, tmp_path):
    ingest = load(monkeypatch, tmp_path, None)
    assert "films" not in ingest.SOURCES and "vikunja" in ingest.SOURCES


def test_extra_sources_join_and_replace(monkeypatch, tmp_path):
    extra = {
        "films": {"base": "http://films.example:1/api", "auth": ["X-Api-Key:", "FILMS_KEY"],
                  "pages": "records", "endpoints": ["list", "history"], "schedule": "5 */6 * * *"},
        "vikunja": {"base": "http://elsewhere/api", "auth": None, "pages": "records",
                    "endpoints": ["tasks"], "schedule": "0 * * * *"},
    }
    ingest = load(monkeypatch, tmp_path, json.dumps(extra))
    films = ingest.SOURCES["films"]
    assert films["pages"] is ingest._records_pages and films["auth"] == ("X-Api-Key:", "FILMS_KEY")
    assert ingest.SOURCES["vikunja"]["base"] == "http://elsewhere/api"
    assert "ingest_films" in vars(ingest)


@pytest.mark.parametrize("content", ["{not json", json.dumps({"x": {"pages": "nonesuch"}}), "[]"])
def test_a_bad_file_is_left_out_not_fatal(monkeypatch, tmp_path, content, capsys):
    ingest = load(monkeypatch, tmp_path, content)
    assert "vikunja" in ingest.SOURCES
    assert "left out" in capsys.readouterr().out
