# Tests for config.py: the first tests that have to control the environment.
#
# config.py does its work at import time (load_dotenv, then read os.environ into
# constants), and Python only imports a module once per process. So to test it
# under different environments, each test changes the environment and then
# re-runs the module with importlib.reload().
#
# Two traps, both handled by the reload_config fixture below:
# 1. Your real .env. load_dotenv() would read it on every reload, so a test
#    expecting "no bucket set" would pass in CI (no .env) and fail on your laptop.
# 2. Leaking state. The reloaded constants stay changed after the test unless
#    the module is reloaded again in a clean environment afterwards.

import importlib

import dotenv
import pytest

from tfl_ttl import config

# Keep a reference to the real function before any test replaces it.
REAL_LOAD_DOTENV = dotenv.load_dotenv

CONFIG_VARS = ("S3_BUCKET", "S3_PREFIX", "AWS_REGION", "TFL_APP_KEY")


@pytest.fixture
def reload_config(monkeypatch):
    """Clear the config env vars, disable .env loading, and hand back a reload function."""
    for name in CONFIG_VARS:
        # monkeypatch remembers each variable's original value (or absence) and
        # puts it back after the test, even if the test fails.
        monkeypatch.delenv(name, raising=False)

    # Patch dotenv.load_dotenv, not tfl_ttl.config.load_dotenv. Reloading re-runs
    # `from dotenv import load_dotenv`, which fetches the name from the dotenv
    # module afresh and would overwrite a patch made on config.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)

    # A fixture can return a function: here the test decides when to reload,
    # after setting up the environment it wants.
    def _reload():
        return importlib.reload(config)

    # Everything after yield is teardown, run once the test finishes.
    yield _reload

    # Fixture teardowns run in reverse order of setup, so monkeypatch hasn't
    # restored anything yet at this point. Undo it now, then reload in the real
    # environment, so other test files see config exactly as it was.
    monkeypatch.undo()
    importlib.reload(config)


def test_defaults_when_nothing_is_set(reload_config):
    cfg = reload_config()
    assert cfg.S3_PREFIX == "raw/tfl"
    assert cfg.AWS_REGION == "eu-west-2"
    # No defaults on purpose: guessing a bucket would be worse than failing, and
    # a missing app key means unauthenticated requests rather than an error.
    assert cfg.S3_BUCKET is None
    assert cfg.TFL_APP_KEY is None


def test_values_come_from_the_environment(reload_config, monkeypatch):
    monkeypatch.setenv("S3_BUCKET", "my-bucket")
    monkeypatch.setenv("S3_PREFIX", "raw/test")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("TFL_APP_KEY", "abc123")

    cfg = reload_config()

    assert cfg.S3_BUCKET == "my-bucket"
    assert cfg.S3_PREFIX == "raw/test"
    assert cfg.AWS_REGION == "us-east-1"
    assert cfg.TFL_APP_KEY == "abc123"


def test_real_environment_beats_dotenv_file(reload_config, monkeypatch, tmp_path):
    # tmp_path is a built-in fixture: a fresh empty folder for this test only.
    env_file = tmp_path / ".env"
    env_file.write_text("S3_BUCKET=from-dotenv\nTFL_APP_KEY=from-dotenv\n")

    # Swap the no-op back for the real load_dotenv, pointed at the temp file.
    # Everything else about it (including override=False) is the real behaviour.
    monkeypatch.setattr(
        dotenv, "load_dotenv", lambda *args, **kwargs: REAL_LOAD_DOTENV(dotenv_path=env_file)
    )
    # Set in the "terminal", as GitHub Actions secrets would be.
    monkeypatch.setenv("S3_BUCKET", "from-environment")

    cfg = reload_config()

    # Already set, so .env is ignored: a stray .env can't redirect a real run.
    assert cfg.S3_BUCKET == "from-environment"
    # Not set, so .env fills the gap.
    assert cfg.TFL_APP_KEY == "from-dotenv"
