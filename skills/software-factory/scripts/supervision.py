"""Supervise process groups and optional command deadlines for one coordinator."""

import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import time
import tempfile

from workspace import write_json


class ProcessError(RuntimeError):
    """The process could not start, or its execution was interrupted."""


def _gone(pid, *, group=False):
    if type(pid) is not int or pid <= 0:
        return False
    try:
        (os.killpg if group else os.kill)(pid, 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OverflowError):
        pass
    return False


def turn_stopped(receipt):
    """Check an interrupted turn after acquiring its inherited workspace lock."""
    phase = receipt.get("status")
    if phase in {"success", "failed"}:
        return True
    if phase not in {"starting", "running"}:
        return False
    supervisor = receipt.get("supervisor_pid")
    if supervisor is not None and not _gone(supervisor):
        return False
    group = receipt.get("pgid", receipt.get("pid"))
    if group is not None:
        return _gone(group, group=True)
    # run_worker passes the lease to the supervisor. Even if its launcher
    # forked, execute_owned releases that launcher only after persisting its
    # group. Death before publication closes the gate without executing it.
    owner = receipt.get("coordinator_pid")
    return phase == "starting" and type(owner) is int and owner > 0


def run_worker(script, argument, timeout, *, private_fds=(), env=None):
    """Keep the workspace lease until the watchdog has stopped the process group."""
    from workspace import workspace_lock_fds

    worker = subprocess.Popen(
        [sys.executable, "-B", str(script), str(argument)],
        stdin=subprocess.PIPE,
        start_new_session=True,
        pass_fds=(*workspace_lock_fds(), *private_fds),
        env=env,
    )
    try:
        worker.wait(timeout=None if timeout is None else timeout + 12)
    except subprocess.TimeoutExpired as error:
        raise ProcessError(
            "Supervisor failed to finish. Inspect its process receipt."
        ) from error
    finally:
        # The OS closes this same pipe if the caller is killed outright.
        worker.stdin.close()
        try:
            worker.wait(timeout=3)
        except subprocess.TimeoutExpired:
            # Keep the watchdog and its lease if cleanup itself is stalled.
            # Its recorded PID and process group let an operator reconcile it.
            raise ProcessError(
                "Supervisor is still cleaning up. Inspect its process receipt."
            )
    if worker.returncode:
        raise ProcessError(
            f"Supervisor exited {worker.returncode}. Inspect its process receipt."
        )


def _owner_gone(wait=0):
    return bool(select.select([sys.stdin.buffer], [], [], wait)[0])


def _exec_after_receipt(fd, argv):
    # The provider/check never runs until its process group has a durable owner.
    with socket.socket(fileno=fd) as gate:
        gate.set_inheritable(False)
        if gate.recv(1) != b"G":
            return 126
        try:
            os.execvp(argv[0], argv)
        except (ValueError, OSError) as error:
            gate.sendall(str(error).encode(errors="replace")[:2048])
            return 126


def execute_owned(argv, *, cwd, stdin, stdout, stderr, timeout, on_start, env=None):
    """Execute from the watchdog (stdin is its coordinator-liveness pipe)."""
    if _owner_gone():
        raise ProcessError("Coordinator interrupted the command before launch")
    deadline = None if timeout is None else time.monotonic() + timeout
    parent, child = socket.socketpair()
    with parent, child:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-B",
                str(Path(__file__).resolve()),
                "--exec",
                str(child.fileno()),
                *argv,
            ],
            cwd=cwd,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            env=env,
            pass_fds=(child.fileno(),),
            start_new_session=True,
        )
        child.close()
        try:
            on_start(proc.pid)
            if _owner_gone():
                raise ProcessError("Coordinator interrupted the command before launch")
            parent.sendall(b"G")
            while proc.poll() is None:
                wait = 0.05
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ProcessError(f"Command timed out after {timeout}s")
                    wait = min(wait, remaining)
                if _owner_gone(wait):
                    raise ProcessError("Command interrupted by its coordinator")
            startup_error = parent.recv(2048)
            if startup_error:
                raise ProcessError(startup_error.decode(errors="replace"))
            return proc.returncode
        finally:
            # The leader can exit while a child in the group is still writing.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()


def _check_worker(path):
    state = json.loads(path.read_text())
    state["supervisor_pid"] = os.getpid()
    write_json(path, state)

    def started(pid):
        state.update(status="RUNNING", pgid=pid)
        write_json(path, state)

    try:
        with Path(state["log"]).open("ab") as stream:
            rc = execute_owned(
                state["argv"],
                cwd=state["cwd"],
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=state["timeout"],
                on_start=started,
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            )
        state.update(status="PASS" if rc == 0 else "FAIL", returncode=rc, reason="")
    except (ProcessError, OSError, ValueError) as exc:
        state.update(status="BLOCKED", returncode=None, reason=str(exc))
    write_json(path, state)


def captured_check(argv, cwd, artifact, timeout):
    artifact = Path(artifact).resolve()
    with artifact.open("xb"):
        pass
    path = artifact.with_name(artifact.name + ".process.json")
    state = {
        "argv": [os.fspath(x) for x in argv],
        "cwd": str(Path(cwd).resolve()),
        "log": str(artifact),
        "timeout": timeout,
        "coordinator_pid": os.getpid(),
        "status": "STARTING",
    }
    write_json(path, state)
    try:
        run_worker(Path(__file__).resolve(), path, timeout)
    except (OSError, ProcessError) as exc:
        return "BLOCKED", None, str(exc)
    result = json.loads(path.read_text())
    return result["status"], result["returncode"], result["reason"]


def _capture_worker(job_fd):
    """Perform a checkpoint command using anonymous descriptors for all private data."""
    with os.fdopen(job_fd, "r+b") as control:
        job = json.load(control)

        def publish(info):
            control.seek(0)
            control.truncate()
            control.write(json.dumps(info).encode())
            control.flush()

        try:
            rc = execute_owned(
                job["argv"],
                cwd=job["cwd"],
                stdin=job["stdin"],
                stdout=job["stdout"],
                stderr=job["stderr"],
                timeout=job["timeout"],
                on_start=lambda pid: publish({"pgid": pid}),
            )
            publish({"returncode": rc})
        except (ProcessError, OSError, ValueError) as error:
            publish({"error": str(error)})


def captured_process(argv, *, cwd, input=None, env=None, timeout):
    """subprocess.run-style capture with owner-death and process-group cleanup.

    Git may receive a credential-bearing URL or configuration in its environment.
    Only file descriptors cross the supervisor command line. No request, pathspec,
    output, or environment is left behind as a named artifact after a crash.
    """
    with (
        tempfile.TemporaryFile() as job,
        tempfile.TemporaryFile() as source,
        tempfile.TemporaryFile() as out,
        tempfile.TemporaryFile() as err,
    ):
        if input is not None:
            source.write(input)
            source.seek(0)
        job.write(
            json.dumps(
                dict(
                    argv=argv,
                    cwd=os.fspath(cwd),
                    timeout=timeout,
                    stdin=source.fileno(),
                    stdout=out.fileno(),
                    stderr=err.fileno(),
                )
            ).encode()
        )
        job.seek(0)
        run_worker(
            Path(__file__).resolve(),
            f"--capture={job.fileno()}",
            timeout,
            private_fds=(job.fileno(), source.fileno(), out.fileno(), err.fileno()),
            env=env,
        )
        job.seek(0)
        result = json.load(job)
        if "returncode" not in result:
            raise ProcessError(
                result.get("error", "Checkpoint command ended without its result")
            )
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(
            argv, result["returncode"], out.read(), err.read()
        )


if __name__ == "__main__":
    if sys.argv[1] == "--exec":
        sys.exit(_exec_after_receipt(int(sys.argv[2]), sys.argv[3:]))
    if sys.argv[1].startswith("--capture="):
        _capture_worker(int(sys.argv[1].split("=", 1)[1]))
    else:
        _check_worker(Path(sys.argv[1]))
