"""Find and stop a running ``bib serve`` process. Does not touch PostgreSQL."""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

_LISTEN = "0A"


def is_bib_server_cmd(cmd: str) -> bool:
    """True for a ``bib serve`` / uvicorn factory process, not ``bib down``."""
    if "bib down" in cmd:
        return False
    return (
        "bib serve" in cmd or "bib.app:create_app" in cmd or ("uvicorn" in cmd and "bib.app" in cmd)
    )


def listening_socket_inodes(port: int, proc: Path = Path("/proc")) -> set[int]:
    inodes: set[int] = set()
    needle = f"{port:04X}"
    for name in ("net/tcp", "net/tcp6"):
        path = proc / name
        try:
            lines = path.read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) < 10 or parts[3] != _LISTEN:
                continue
            local = parts[1]
            if local.rsplit(":", 1)[-1].upper() == needle:
                inodes.add(int(parts[9]))
    return inodes


def pids_holding_sockets(inodes: set[int], proc: Path = Path("/proc")) -> set[int]:
    found: set[int] = set()
    if not inodes:
        return found
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        fd_dir = entry / "fd"
        try:
            fds = list(fd_dir.iterdir())
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            if (
                target.startswith("socket:[")
                and target.endswith("]")
                and int(target[8:-1]) in inodes
            ):
                found.add(int(entry.name))
                break
    return found


def pids_by_cmdline(proc: Path = Path("/proc"), *, skip: set[int] | None = None) -> set[int]:
    skip = skip or set()
    found: set[int] = set()
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in skip:
            continue
        cmd = _cmdline(entry)
        if cmd and is_bib_server_cmd(cmd):
            found.add(pid)
    return found


def with_server_parents(pids: set[int], proc: Path = Path("/proc")) -> set[int]:
    extra = set(pids)
    for pid in list(pids):
        ppid = _ppid(proc / str(pid))
        while ppid and ppid > 1:
            cmd = _cmdline(proc / str(ppid))
            if cmd and is_bib_server_cmd(cmd):
                extra.add(ppid)
                ppid = _ppid(proc / str(ppid))
            else:
                break
    return extra


def find_server_pids(port: int, proc: Path = Path("/proc")) -> set[int]:
    me = {os.getpid(), os.getppid()}
    pids = pids_holding_sockets(listening_socket_inodes(port, proc), proc)
    pids |= pids_by_cmdline(proc, skip=me)
    pids = with_server_parents(pids, proc)
    return pids - me


def stop_pids(pids: set[int], timeout: float = 8.0) -> tuple[set[int], set[int]]:
    """SIGTERM, wait, then SIGKILL leftovers. Returns (signaled, still_alive)."""
    signaled: set[int] = set()
    for pid in sorted(pids):
        try:
            os.kill(pid, signal.SIGTERM)
            signaled.add(pid)
        except ProcessLookupError:
            continue
        except PermissionError:
            continue
    deadline = time.monotonic() + timeout
    remaining = set(signaled)
    while remaining and time.monotonic() < deadline:
        remaining = {pid for pid in remaining if _alive(pid)}
        if remaining:
            time.sleep(0.1)
    for pid in list(remaining):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            remaining.discard(pid)
    remaining = {pid for pid in remaining if _alive(pid)}
    return signaled, remaining


def _cmdline(proc_dir: Path) -> str:
    try:
        return (proc_dir / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace")
    except OSError:
        return ""


def _ppid(proc_dir: Path) -> int | None:
    try:
        for line in (proc_dir / "status").read_text().splitlines():
            if line.startswith("PPid:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
