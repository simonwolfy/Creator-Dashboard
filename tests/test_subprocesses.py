from __future__ import annotations

import os
import subprocess

from creator_intelligence.utils.subprocesses import hidden_process_kwargs


def test_hidden_process_kwargs_are_platform_safe():
    kwargs = hidden_process_kwargs()

    if os.name == "nt":
        assert kwargs == {"creationflags": subprocess.CREATE_NO_WINDOW}
    else:
        assert kwargs == {}
