"""
Shared test bootstrap. Runs before any test module is imported, so the module-level
DB_PATH in db.models (read once at import) resolves to a writable temp DB instead of
the production default (/app/data/...). Per-test fixtures that need an isolated DB
still monkeypatch CYBERSCREENER_DB and reload db.models.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

_tmp = tempfile.mkdtemp(prefix="cyberscreener-test-")
os.environ.setdefault("CYBERSCREENER_DB", os.path.join(_tmp, "test.db"))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-minimum-pad!")
os.environ.setdefault("CYBERSCREENER_PASSWORD", "testpassword")
