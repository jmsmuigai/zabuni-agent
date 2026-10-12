"""Tests run against a fresh copy of the synthetic data in a temp directory (never the repo's runs/)."""
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="zabuni-test-"))
os.environ.update({
    "ZABUNI_ROOT": str(ROOT),
    "ZABUNI_DB": str(TMP / "zabuni.sqlite"),
    "ZABUNI_WORKSPACE": str(TMP / "workspace"),
    "ZABUNI_RUNS": str(TMP / "runs"),
    "ZABUNI_GATE_SECRET": "test-secret",
    "ZABUNI_QUIET": "1",
})
shutil.copytree(ROOT / "workspace" / "inputs", TMP / "workspace" / "inputs")

import pytest  # noqa: E402

from zabuni.data import ingest, synth  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def database():
    out = TMP / "sample.jsonl.gz"
    synth.main([str(out)])
    stats = ingest.ingest([out], Path(os.environ["ZABUNI_DB"]))
    return {"path": out, "stats": stats}
