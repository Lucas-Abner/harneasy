import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJETO = Path.cwd().resolve()

PROFILE = f"""(version 1)
(deny default)
(allow process-exec process-fork signal)
(allow file-read*)
(allow sysctl-read)
(deny network*)
(allow file-write* (subpath "{PROJETO}") (literal "/dev/null"))
(deny file-write* (subpath "{PROJETO}/.git"))
"""

def wrap(command):
    if sys.platform == 'darwin':
        profile = Path(tempfile.gettempdir())/ 'agent_harness.sb'
        profile.write_text(PROFILE)
        return ['sandbox-exec', '-f', str(profile)], '/bin/sh', '-c', command

    if sys.platform.startswith('linux') and shutil.which('bwrap'):
        return [
            "bwrap",
            "--ro-bind", "/", "/",
            "--bind", str(PROJETO), str(PROJETO),
            "--dev", "/dev", "--proc", "/proc",
            "--unshare-net", "--die-with-parent",
            "/bin/sh", "-c", command,
        ]

    return None

def name():
    if sys.platform == 'darwin':
        return 'seatbelt'
    if sys.platform.startswith('linux') and shutil.which('bwrap'):
        return 'bubblewrap'
    return 'none'

def run(command, timeout=60):
    sandbox = wrap(command)
    return subprocess.run(
        sandbox or command,
        shell=sandbox is None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )