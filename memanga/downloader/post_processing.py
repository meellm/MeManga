"""User post-processing hook run after a chapter is saved."""

import logging
import os
import re
import shlex
import signal
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .errors import DownloaderError

logger = logging.getLogger(__name__)

# How long a post-processing command may run before it's killed (seconds).
POST_PROCESSING_TIMEOUT = 600


def _run_post_processing(
    post_processing: Optional[Dict[str, Any]],
    output_path: Path,
    title: str,
    chapter_num: str,
    source: str,
    output_format: str,
):
    """Run the optional user post-processing command for a finished chapter.

    The command is split into argv and run directly, not through a shell.
    Useful values are passed both as ``{placeholder}`` substitutions in command
    arguments and as ``MEMANGA_*`` environment variables:

    - ``{output_path}`` / ``MEMANGA_OUTPUT_PATH`` - final file or folder path
    - ``{title}`` / ``MEMANGA_MANGA_TITLE`` - manga title
    - ``{chapter}`` / ``MEMANGA_CHAPTER`` - chapter number
    - ``{source}`` / ``MEMANGA_SOURCE`` - source the chapter came from
    - ``{format}`` / ``MEMANGA_OUTPUT_FORMAT`` - output format
    - ``{is_dir}`` / ``MEMANGA_IS_DIR`` - "1" if output is a folder, else "0"

    Placeholder values are substituted after argv parsing, so metadata cannot
    become shell syntax. For shell features such as pipes or redirects, invoke
    a shell explicitly and prefer the ``MEMANGA_*`` environment variables.

    A non-zero exit, timeout, or launch error is treated as failure: if
    ``fail_on_error`` is set the failure is re-raised as
    :class:`DownloaderError`; otherwise a warning is printed and the download
    stays successful.
    """
    if not post_processing or not post_processing.get("enabled"):
        return

    command = (post_processing.get("command") or "").strip()
    if not command:
        return

    fail_on_error = bool(post_processing.get("fail_on_error"))
    is_dir = "1" if output_path.is_dir() else "0"
    output_path_str = str(output_path)
    title = str(title)
    chapter_num = str(chapter_num)
    source = str(source)
    output_format = str(output_format)

    replacements = {
        "output_path": output_path_str,
        "title": title,
        "chapter": chapter_num,
        "source": source,
        "format": output_format,
        "is_dir": is_dir,
    }

    def _fail(message: str):
        if fail_on_error:
            raise DownloaderError(message)
        logger.warning("%s", message)

    try:
        command_args = _split_post_processing_command(command)
    except ValueError as e:
        _fail(f"Post-processing command could not be parsed: {e}")
        return
    if not command_args:
        return

    resolved_args = [
        _substitute_post_processing_placeholders(arg, replacements)
        for arg in command_args
    ]

    env = os.environ.copy()
    env.update({
        "MEMANGA_OUTPUT_PATH": output_path_str,
        "MEMANGA_MANGA_TITLE": title,
        "MEMANGA_CHAPTER": chapter_num,
        "MEMANGA_SOURCE": source,
        "MEMANGA_OUTPUT_FORMAT": output_format,
        "MEMANGA_IS_DIR": is_dir,
    })

    try:
        result = _run_post_processing_command(
            resolved_args,
            env=env,
            timeout=POST_PROCESSING_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        _fail(
            f"Post-processing command timed out after "
            f"{POST_PROCESSING_TIMEOUT}s"
        )
        return
    except Exception as e:
        _fail(f"Post-processing command failed to start: {e}")
        return

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        message = f"Post-processing command exited with code {result.returncode}"
        if detail:
            message += f": {detail}"
        _fail(message)


def _run_post_processing_command(
    args: List[str],
    env: Dict[str, str],
    timeout: int,
) -> subprocess.CompletedProcess:
    """Run a post-processing command and terminate its process tree on timeout."""
    kwargs: Dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
    else:
        kwargs["start_new_session"] = True

    process = subprocess.Popen(
        args,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **kwargs,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # The process tree is killed first, then we drain the pipes with a
        # bounded wait. If a surviving grandchild still holds the pipe handles
        # open, communicate() would block forever, so every drain here has its
        # own timeout and we ultimately abandon the output rather than hang.
        _terminate_process_tree(process)
        stdout, stderr = _drain_after_timeout(process)
        exc.output = stdout
        exc.stderr = stderr
        raise exc

    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def _drain_after_timeout(
    process: subprocess.Popen,
    drain_timeout: int = 5,
) -> tuple:
    """Read remaining output from a killed process without ever blocking.

    Returns ``(stdout, stderr)``. If the pipes cannot be drained even after a
    second kill, they are force-closed and ``(None, None)`` is returned so the
    caller never waits on a wedged child that inherited the handles.
    """
    try:
        return process.communicate(timeout=drain_timeout)
    except subprocess.TimeoutExpired:
        pass

    process.kill()
    try:
        return process.communicate(timeout=drain_timeout)
    except subprocess.TimeoutExpired:
        pass

    for stream in (process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
    return None, None


_POST_PROCESSING_PLACEHOLDER_RE = re.compile(
    r"\{(output_path|title|chapter|source|format|is_dir)\}"
)


def _substitute_post_processing_placeholders(
    arg: str,
    replacements: Dict[str, str],
) -> str:
    """Replace placeholders once, without expanding placeholder text in values."""
    return _POST_PROCESSING_PLACEHOLDER_RE.sub(
        lambda match: replacements[match.group(1)],
        arg,
    )


def _split_post_processing_command(command: str) -> List[str]:
    """Split a command string into argv without damaging Windows paths."""
    if os.name != "nt":
        return shlex.split(command)

    args: List[str] = []
    current: List[str] = []
    in_quotes = False
    quote_char = ""

    for ch in command:
        if ch in ("'", '"'):
            if in_quotes and ch == quote_char:
                in_quotes = False
                quote_char = ""
            elif not in_quotes:
                in_quotes = True
                quote_char = ch
            else:
                current.append(ch)
        elif ch.isspace() and not in_quotes:
            if current:
                args.append("".join(current))
                current = []
        else:
            current.append(ch)

    if in_quotes:
        raise ValueError("No closing quotation")
    if current:
        args.append("".join(current))
    return args


def _terminate_process_tree(process: subprocess.Popen) -> bool:
    """Terminate a process and its children where the platform supports it."""
    if process.poll() is not None:
        return True
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            return True
        except Exception:
            pass
    try:
        process.kill()
        return True
    except Exception:
        return False
