"""Loads Infra/.env before anything reads the environment.

Without this the documented env file had no effect: the service read os.environ
directly, so forgetting to source the file by hand started a process that
reported "status": "ok" while silently running with no persistence and the stub
prospector. A misconfiguration that looks like success is worse than one that
fails, so the file is now loaded for real.

Existing environment variables win. A value exported by the shell, a container
`-e` flag or a CI secret must not be overridden by a file left on disk.
"""

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / "Infra" / ".env"
# Tests set this so an operator's local file cannot leak into assertions.
SKIP_FLAG = "AUTOGTM_LOAD_DOTENV"


def load_env(path: Path = ENV_FILE) -> bool:
    """Populate os.environ from the env file. Returns whether it was read."""
    if os.environ.get(SKIP_FLAG) == "0":
        return False
    if not path.is_file():
        return False

    from dotenv import load_dotenv

    return load_dotenv(path, override=False)
