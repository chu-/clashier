"""Exercise real macOS process launch and restart without touching the user's client."""

import os
import shutil
import subprocess
import sys
import uuid

import pytest

from clashier import platforms


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS process-launch regression")
def test_repeated_start_and_restart_create_one_real_process(tmp_path, monkeypatch):
    compiler = shutil.which("clang")
    if not compiler:
        pytest.skip("Building the disposable process fixture requires clang")
    source = tmp_path / "worker.c"
    source.write_text("#include <unistd.h>\nint main(void) { for (;;) pause(); }\n", encoding="utf-8")
    # macOS process names have a limited length; use a unique short name.
    executable = tmp_path / ("clshi" + uuid.uuid4().hex[:8])
    subprocess.run([compiler, str(source), "-o", str(executable)], check=True, capture_output=True, timeout=30)
    monkeypatch.setattr(platforms, "find_verge_executable", lambda: str(executable))
    app = platforms.VergeApp()
    query = ["pgrep", "-u", str(os.getuid()), "-x", executable.name]
    try:
        for _ in range(2):
            app.start()
            app.start()
            running = subprocess.run(query, capture_output=True, text=True, timeout=3)
            assert running.returncode == 0
            assert len(running.stdout.split()) == 1
            app.stop(5)
            assert subprocess.run(query, capture_output=True, timeout=3).returncode == 1
    finally:
        # This unique name belongs only to the disposable test worker.
        subprocess.run(["pkill", "-TERM", "-u", str(os.getuid()), "-x", executable.name],
                       capture_output=True, timeout=3, check=False)
