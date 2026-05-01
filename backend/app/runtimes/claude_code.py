"""Local Claude Code CLI runtime.

Spawns the user's local `claude` CLI via a shell wrapper that captures
stdout/stderr/exit-code to files in the per-ticket workspace, then polls
for the exit-code sentinel. Bypassing every variant of asyncio's process
machinery proved necessary — see comments inline.

Why this over the API:
  - Uses the user's existing Claude Code subscription, no API key.
  - Full tool surface (bash, read, write, edit, glob, grep) — once a
    workspace is mounted, the agent can do real edits in it.

Subprocess hardening notes (each fixed a real failure mode):
  - System prompt must go via `--system-prompt-file` (>3KB on argv wedges).
  - User message must go as the positional `[prompt]` arg (stdin EOF
    detection from a Python parent is unreliable).
  - Strip `ANTHROPIC_API_KEY` from child env (else CLI tries the env key
    and 401s instead of using OAuth).
  - Spawn through a generated shell script with output redirection to
    files. asyncio.create_subprocess_exec.communicate() wedges on EOF
    because claude's hooks/MCP grandchildren keep the pipes open.
    asyncio.wait() also fails — the child watcher reaps the process from
    underneath and our wait never returns. The shell-script + sentinel
    approach is the only thing that works reliably under uvicorn.
  - Wrapper script writes `_exit.code` ATOMICALLY (write to .tmp then
    mv) — so the polling loop never reads a partial value.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile

log = logging.getLogger(__name__)


class AlreadyRunning(RuntimeError):
    """Another claude run is already in flight for this workspace.

    Raised when `_run.lock` exists and points at a live PID. Linear emits
    `ticket.created` and `ticket.updated` as separate webhooks for the same
    logical "create" event, so without this guard two concurrent claude
    processes spawn in the same per-ticket workspace and race on git/files.
    """


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user


def _acquire_lock(path: str) -> None:
    """Atomically claim `path` as our run lock.

    Raises AlreadyRunning if a live PID already owns it. Stale locks (PID
    dead) are removed and re-acquired transparently.
    """
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return
        except FileExistsError:
            try:
                with open(path) as f:
                    old_pid = int(f.read().strip() or 0)
            except (ValueError, FileNotFoundError):
                old_pid = 0
            if _pid_alive(old_pid):
                raise AlreadyRunning(
                    f"another run already in flight for {path} (pid={old_pid})"
                )
            log.warning("removing stale lock %s (pid=%s)", path, old_pid)
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            # loop and retry O_EXCL


class _ExistingDir:
    """Context manager that yields a pre-existing path (for persistent cwd)."""
    def __init__(self, path: str) -> None:
        self.path = path
    def __enter__(self) -> str:
        os.makedirs(self.path, exist_ok=True)
        return self.path
    def __exit__(self, *a: object) -> None:
        pass  # don't delete a persistent workspace


CLI_TIMEOUT_SECONDS = 600.0  # real file ops + bash can take a while
DEFAULT_MODEL = "sonnet"  # tool-using work needs Sonnet-level capability


def is_available() -> bool:
    return shutil.which("claude") is not None


async def generate_reply(
    *,
    system_prompt: str,
    user_message: str,
    workspace_dir: str | None = None,
    extra_dirs: tuple[str, ...] = (),
    enable_tools: bool = True,
    model: str = DEFAULT_MODEL,
    timeout: float = CLI_TIMEOUT_SECONDS,
) -> str:
    """Run the local Claude Code CLI and return its stdout.

    workspace_dir: cwd for the CLI. Tools that read/write the filesystem
                   default to operating here. Persistent per-ticket so
                   multi-turn work picks up where it left off. If None, a
                   throwaway tempdir is used (chat-only fallback).
    extra_dirs:    additional paths the CLI is allowed to read/write
                   (mapped to --add-dir). Use this to grant access to
                   ~/Desktop, repo clones, etc.
    enable_tools:  when True (default), use --permission-mode
                   bypassPermissions so the model can edit/bash without
                   per-call approval. When False, all tools are blocked.
    """
    log.info(
        "invoking claude CLI: model=%s tools=%s cwd=%s extra=%s system=%dch user=%dch",
        model, "on" if enable_tools else "off",
        workspace_dir or "<tmp>", list(extra_dirs),
        len(system_prompt), len(user_message),
    )

    # Strip ANTHROPIC_API_KEY so the CLI uses the local subscription/OAuth auth
    # instead of trying (and failing) to use a stale/wrong API key from env.
    child_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

    # cwd: persistent workspace if provided, else throwaway tempdir.
    cwd_ctx = (
        _ExistingDir(workspace_dir) if workspace_dir
        else tempfile.TemporaryDirectory(prefix="coii_cc_")
    )

    with cwd_ctx as cwd:
        # Per-ticket lock: prevent two concurrent claude runs in the same
        # workspace from racing on git/files. Acquired BEFORE any other I/O
        # so a duplicate webhook bails before clobbering _system.md etc.
        lock_path = os.path.join(cwd, "_run.lock")
        _acquire_lock(lock_path)
        try:
            # System prompt goes in a file — passing 3KB+ on argv wedges the CLI.
            sys_path = os.path.join(cwd, "_system.md")
            with open(sys_path, "w", encoding="utf-8") as f:
                f.write(system_prompt)

            cmd: list[str] = [
                "claude",
                "--print",
                "--no-session-persistence",
                "--model", model,
                "--system-prompt-file", sys_path,
            ]
            if enable_tools:
                cmd += ["--permission-mode", "bypassPermissions"]
            else:
                cmd += ["--tools", "default"]
            for d in extra_dirs:
                cmd += ["--add-dir", os.path.expanduser(d)]
            # Positional user message LAST — passing via stdin has been flaky from
            # a Python parent (EOF detection unreliable).
            cmd.append(user_message)

            # Drive the subprocess through a wrapper shell script and capture its
            # output via shell redirection to files. This avoids every flavor of
            # asyncio/subprocess interaction issue we hit:
            #   - No pipe handoff (no EOF wedge from claude's grandchildren).
            #   - No asyncio child-watcher race (the only direct child is `sh`,
            #     which exits as soon as claude does — quick to reap).
            #   - claude doesn't see anything unusual: it inherits the script's
            #     fds, which point at regular files.
            # Bypass asyncio's process tracking entirely. Spawn a detached shell
            # wrapper via os.posix_spawn (no parent-child relationship visible to
            # asyncio's child watcher), have it write stdout/stderr/exit-code to
            # files, and poll for the exit-code file. This proved to be the only
            # path that works reliably under uvicorn — every variant of
            # asyncio.create_subprocess_exec wedged in proc.wait() because the
            # child watcher and subprocess accounting fight over reaping.
            import shlex
            out_path = os.path.join(cwd, "_stdout.log")
            err_path = os.path.join(cwd, "_stderr.log")
            rc_path = os.path.join(cwd, "_exit.code")
            # Remove any stale sentinels.
            for p in (out_path, err_path, rc_path):
                if os.path.exists(p):
                    os.remove(p)

            quoted_cmd = " ".join(shlex.quote(a) for a in cmd)
            # Trailing `& wait $!; echo $? > rc` runs claude in the background of
            # its own sh, then writes the exit code as the last action of sh —
            # writing rc atomically signals "done" to the parent watcher.
            wrapper = (
                f"{quoted_cmd} > {shlex.quote(out_path)} "
                f"2> {shlex.quote(err_path)} < /dev/null; "
                f"echo $? > {shlex.quote(rc_path)}.tmp && "
                f"mv {shlex.quote(rc_path)}.tmp {shlex.quote(rc_path)}"
            )

            # Detach completely with setsid + nohup-style ignored signals so the
            # child does not depend on uvicorn for lifecycle.
            # Write the wrapper to a script file rather than passing on argv —
            # large user prompts in argv have caused sh to misparse.
            script_path = os.path.join(cwd, "_run.sh")
            trace_path = os.path.join(cwd, "_trace.log")
            with open(script_path, "w") as f:
                # `set -x` traces every command, redirected to _trace.log so we
                # see exactly where the wrapper got to. No `set -e` because we
                # want the `; echo $? > rc` step to ALWAYS run, even on failure.
                f.write(
                    "#!/bin/sh\n"
                    f'exec 2>{shlex.quote(trace_path)}\n'
                    "set -x\n"
                    "echo \"wrapper started at $(date) cwd=$(pwd)\"\n"
                    f"cd {shlex.quote(cwd)}\n"
                    "echo \"after cd cwd=$(pwd)\"\n"
                    "echo \"PATH=$PATH\"\n"
                    "which claude\n"
                    + wrapper + "\n"
                    "echo \"wrapper finished\"\n"
                )
            os.chmod(script_path, 0o700)

            log.info("wrapper script size=%d bytes", os.path.getsize(script_path))
            # Note: os.posix_spawn does NOT have a cwd parameter; the script
            # cd's to its workspace itself.
            pid = os.posix_spawn(
                "/bin/sh",
                ["/bin/sh", script_path],
                child_env,
            )
            log.info("sh wrapper pid=%s, polling for exit-code file", pid)
            # Refresh the lock with the wrapper PID so other activations
            # (and the startup sweep, when added) can detect liveness.
            with open(lock_path, "w") as f:
                f.write(str(pid))

            deadline = asyncio.get_running_loop().time() + timeout
            while not os.path.exists(rc_path):
                if asyncio.get_running_loop().time() > deadline:
                    # Best-effort kill the process group.
                    try:
                        os.killpg(pid, 9)
                    except (ProcessLookupError, PermissionError):
                        pass
                    raise RuntimeError(f"claude CLI timed out after {timeout}s")
                await asyncio.sleep(0.5)

            with open(rc_path, "r") as f:
                returncode = int(f.read().strip())
            log.info("claude wrapper exited rc=%s", returncode)

            with open(out_path, "rb") as f:
                stdout = f.read()
            with open(err_path, "rb") as f:
                stderr = f.read()

            out_text = stdout.decode("utf-8", errors="replace")
            err_text = stderr.decode("utf-8", errors="replace")

            if returncode != 0:
                raise RuntimeError(
                    f"claude CLI exited {returncode}; "
                    f"stderr={err_text[:1000]!r}; stdout={out_text[:1000]!r}"
                )

            return out_text.strip()
        finally:
            try:
                os.remove(lock_path)
            except FileNotFoundError:
                pass
