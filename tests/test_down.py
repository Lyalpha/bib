"""Finding and classifying bib serve processes."""

from __future__ import annotations

from pathlib import Path

from bib.down import is_bib_server_cmd, listening_socket_inodes, pids_holding_sockets, with_server_parents


def test_is_bib_server_cmd_matches_serve_not_down():
    assert is_bib_server_cmd("uv run bib serve")
    assert is_bib_server_cmd("/home/jdl/code/bib/.venv/bin/bib serve")
    assert is_bib_server_cmd("uvicorn bib.app:create_app --factory")
    assert not is_bib_server_cmd("uv run bib down")
    assert not is_bib_server_cmd("postgres -D /var/lib/postgresql/data")
    assert not is_bib_server_cmd("uv run pytest")


def test_listening_socket_inodes(tmp_path: Path):
    tcp = tmp_path / "net"
    tcp.mkdir()
    (tcp / "tcp").write_text(
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        "   0: 00000000:1F40 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 4242 1\n"
        "   1: 00000000:1538 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 99 1\n"
    )
    (tcp / "tcp6").write_text(
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
    )
    assert listening_socket_inodes(8000, tmp_path) == {4242}
    assert listening_socket_inodes(5432, tmp_path) == {99}


def test_pids_holding_sockets(tmp_path: Path):
    proc = tmp_path / "1"
    fd = proc / "fd"
    fd.mkdir(parents=True)
    (fd / "5").symlink_to("socket:[4242]")
    (fd / "6").symlink_to("socket:[7]")
    assert pids_holding_sockets({4242}, tmp_path) == {1}
    assert pids_holding_sockets({99}, tmp_path) == set()


def test_with_server_parents(tmp_path: Path):
    child = tmp_path / "20"
    parent = tmp_path / "10"
    child.mkdir()
    parent.mkdir()
    (child / "status").write_text("Name:\tbib\nPPid:\t10\n")
    (parent / "status").write_text("Name:\tuv\nPPid:\t1\n")
    (child / "cmdline").write_bytes(b"python\x00bib\x00serve")
    (parent / "cmdline").write_bytes(b"uv\x00run\x00bib\x00serve")
    assert with_server_parents({20}, tmp_path) == {20, 10}
