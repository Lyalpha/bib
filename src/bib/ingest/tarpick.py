"""Selective extraction of stellar models from BPASS tar archives.

``NEWSINMODS.tar`` / ``NEWBINMODS.<z>.tar`` unpack to hundreds of thousands of
files; we stream the archive and pull only the members the manifest selects,
never touching the disk with the rest.
"""

from __future__ import annotations

import tarfile
from collections.abc import Callable, Iterator
from pathlib import Path

from bib.ingest.parsers import ModelName, ParseError, parse_model_filename

Selector = Callable[[ModelName], bool]


def iter_selected_models(
    tar_path: Path, selector: Selector, limit: int | None = None
) -> Iterator[tuple[ModelName, bytes]]:
    """Yield (parsed name, raw bytes) for members matching ``selector``."""
    found = 0
    with tarfile.open(tar_path, "r:*") as archive:
        for member in archive:
            if not member.isfile():
                continue
            base = member.name.rsplit("/", 1)[-1]
            if not base.startswith("sneplot"):
                continue
            try:
                name = parse_model_filename(base)
            except ParseError:
                continue
            if not selector(name):
                continue
            fh = archive.extractfile(member)
            if fh is None:
                continue
            yield name, fh.read()
            found += 1
            if limit is not None and found >= limit:
                return


def iter_models_in_dir(
    root: Path, selector: Selector, limit: int | None = None
) -> Iterator[tuple[ModelName, Path]]:
    """Same selection logic over an already-unpacked directory tree."""
    found = 0
    for path in sorted(root.rglob("sneplot*")):
        if not path.is_file():
            continue
        try:
            name = parse_model_filename(path.name)
        except ParseError:
            continue
        if not selector(name):
            continue
        yield name, path
        found += 1
        if limit is not None and found >= limit:
            return


def make_selector(
    kind: str | None = None,
    z_label: str | None = None,
    m1: list[float] | None = None,
    q: list[float] | None = None,
    logp: list[float] | None = None,
    m1_range: tuple[float, float] | None = None,
    tolerance: float = 0.051,
) -> Selector:
    """Build a selector from manifest criteria (values matched within tolerance)."""

    def close_to_any(value: float | None, targets: list[float] | None) -> bool:
        if targets is None:
            return True
        if value is None:
            return False
        return any(abs(value - t) <= tolerance for t in targets)

    def select(name: ModelName) -> bool:
        if kind is not None and name.kind != kind:
            return False
        if z_label is not None and name.z_label != z_label:
            return False
        if not close_to_any(name.m1, m1):
            return False
        if not close_to_any(name.q, q):
            return False
        if not close_to_any(name.logp, logp):
            return False
        if m1_range is not None and (
            name.m1 is None or not (m1_range[0] <= name.m1 <= m1_range[1])
        ):
            return False
        return True

    return select
