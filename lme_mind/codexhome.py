"""A throwaway CODEX_HOME that shares the user's Codex sign-in without losing a refresh."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
from pathlib import Path


@contextlib.contextmanager
def codex_home(prefix: str):
    """Yield an empty Codex home whose auth.json is the user's own.

    It is a symlink where the system allows one, so a token refresh during the run lands in the
    real file. Otherwise it is a copy that is written back if Codex refreshed it, then removed.
    """
    real = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "auth.json"
    home = Path(tempfile.mkdtemp(prefix=prefix))
    link = home / "auth.json"
    copied = None
    try:
        if real.exists():
            try:
                os.symlink(real, link)
            except OSError:
                shutil.copy2(real, link)
                copied = link.read_bytes()
        (home / "config.toml").write_text("", encoding="utf-8")
        yield home
    finally:
        # Write back a refresh: from a copy, or from a symlink Codex replaced with a new file.
        if link.exists() and not link.is_symlink() and real.exists()                 and link.read_bytes() != (copied if copied is not None else real.read_bytes()):
            try:
                json.loads(link.read_text(encoding="utf-8"))
                shutil.copy2(link, real)
            except ValueError:
                print(f"warning: Codex left an unreadable sign-in in {link}; kept your original")
        shutil.rmtree(home, ignore_errors=True)
        if home.exists():
            print(f"warning: could not remove {home}; it holds a copy of your Codex sign-in")
