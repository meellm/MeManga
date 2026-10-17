"""Run MeManga from this checkout in the caller's working directory.

Used by scripts/run.sh and scripts\\windows\\run.bat (#406). Modules must
never load from the folder the command was typed in, or a file such as
`requests.py` there could replace a dependency.

The wrappers start this file with `python -I`, so neither that folder
nor PYTHONPATH is searched yet. It removes the entries that point at the
caller's folder (`.`, an empty entry, its absolute path or a link to it)
from PYTHONPATH and starts itself again without -I, so the remaining
PYTHONPATH and the other PYTHON* settings apply as usual. That second run
puts the checkout first on sys.path and runs `memanga` like `python -m`.
"""
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)


def _real(path):
    return os.path.normcase(os.path.realpath(path))


def _outside_caller_dir(entries):
    """Path entries that do not resolve to the working directory."""
    cwd = os.getcwd()
    return [p for p in entries if _real(os.path.join(cwd, p)) != _real(cwd)]


if sys.flags.isolated:
    env = dict(os.environ)
    if "PYTHONPATH" in env:
        kept = _outside_caller_dir(env["PYTHONPATH"].split(os.pathsep))
        if kept:
            env["PYTHONPATH"] = os.pathsep.join(kept)
        else:
            del env["PYTHONPATH"]
    command = [sys.executable, os.path.abspath(__file__), *sys.argv[1:]]
    if os.name != "nt":
        os.execve(sys.executable, command, env)
    # Windows has no real exec; wait so run.bat gets MeManga's exit code.
    import subprocess
    process = subprocess.Popen(command, env=env)
    while True:
        try:
            sys.exit(process.wait())
        except KeyboardInterrupt:
            pass  # MeManga gets Ctrl+C too and exits with its own code

sys.path[:] = [ROOT] + [p for p in _outside_caller_dir(sys.path) if _real(p) != _real(HERE)]

import runpy  # noqa: E402  (only after sys.path is safe)

runpy.run_module("memanga", run_name="__main__", alter_sys=True)
