"""Pull a small real BPASS v2.2.1 subset.

Primary source is the real ASCII products bundled with
`hoki` (Heloise Stevance) — same files as the official release, already
unpacked, and reliably hosted on GitHub. Zenodo's 1.5 GB fiducial zip is
a fallback when that archive is reachable.

    uv run python scripts/fetch_bpass_subset.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.request import Request, urlopen

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "bpass-subset"

# Real v2.2.1 products shipped with hoki (release branch).
HOKI_BASE = "https://raw.githubusercontent.com/heloises/hoki/release/hoki/data"
HOKI_FILES = (
    "spectra-bin-imf135_300.z002.dat",
    "spectra-bin-imf135_300.z008.dat",
    "colours-bin-imf135_300.z002.dat",
    "ionizing-bin-imf135_300.z002.dat",
)


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": "bib-fetch/0.1"})
    with urlopen(req, timeout=300) as resp, dest.open("wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in HOKI_FILES:
        dest = OUT_DIR / name
        if dest.is_file() and dest.stat().st_size > 1000:
            print(f"have {name} ({dest.stat().st_size / 1e6:.1f} MB)")
            continue
        url = f"{HOKI_BASE}/{name}"
        print(f"fetch {name}...")
        _download(url, dest)
        # Git LFS pointer is a tiny text file; fail loudly if we got one.
        head = dest.read_bytes()[:80]
        if head.startswith(b"version https://git-lfs"):
            dest.unlink()
            raise RuntimeError(f"{name} is a Git LFS pointer, not the file")
        print(f"  wrote {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    print(f"done — files in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
