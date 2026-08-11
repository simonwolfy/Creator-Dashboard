"""Child-process helpers that never flash a console from the desktop app."""

from __future__ import annotations

import os
import subprocess
from typing import Any


def windowless_kwargs(kwargs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return subprocess options that hide console programs on Windows."""

    options = dict(kwargs or {})
    if os.name != "nt":
        return options

    creationflags = int(options.get("creationflags", 0) or 0)
    options["creationflags"] = creationflags | int(
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    if options.get("startupinfo") is None and hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
        startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
        options["startupinfo"] = startupinfo
    return options


def windowless_run(*popenargs: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(*popenargs, **windowless_kwargs(kwargs))


def windowless_popen(*popenargs: Any, **kwargs: Any) -> subprocess.Popen[Any]:
    return subprocess.Popen(*popenargs, **windowless_kwargs(kwargs))
