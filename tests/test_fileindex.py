"""FileIndex resolves loose files and members inside official IMF tarballs."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import yaml

from bib.ingest.run import DEFAULT_MANIFEST, FileIndex, _archive_needles, _needed_product_names

SED_100 = Path(__file__).resolve().parents[1] / "src" / "bib" / "ingest" / "sed-100.yaml"
SED_EXTRA = Path(__file__).resolve().parents[1] / "src" / "bib" / "ingest" / "sed-extra-imfs.yaml"


def _write_tar(path: Path, members: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return path


def test_find_loose_file(tmp_path: Path):
    target = tmp_path / "spectra-bin-imf135_100.z020.dat"
    target.write_text("ok")
    index = FileIndex(tmp_path, archive_needles=["imf135_100"])
    found = index.find("spectra-bin-imf135_100.z020.dat")
    assert found == target
    assert index.provenance(found) == target.name


def test_extracts_matching_tar_member(tmp_path: Path):
    _write_tar(
        tmp_path / "bpass_v2.2.1_imf135_100.tar.gz",
        {"spectra-bin-imf135_100.z020.dat.gz": b"gzipped-spectra"},
    )
    _write_tar(
        tmp_path / "bpass_v2.2.1_imf135_300.tar.gz",
        {"spectra-bin-imf135_300.z020.dat.gz": b"should-not-extract"},
    )
    index = FileIndex(tmp_path, archive_needles=["imf135_100"])
    found = index.find("spectra-bin-imf135_100.z020.dat")
    assert found is not None
    assert found.read_bytes() == b"gzipped-spectra"
    assert found.parent.name == ".bib-extract"
    assert index.provenance(found) == (
        "bpass_v2.2.1_imf135_100.tar.gz::spectra-bin-imf135_100.z020.dat.gz"
    )
    assert not (tmp_path / ".bib-extract" / "spectra-bin-imf135_300.z020.dat.gz").exists()


def test_prefetch_skips_unrelated_imf_tarball(tmp_path: Path):
    wanted = tmp_path / "bpass_v2.2.1_imf_chab100.tar.gz"
    other = tmp_path / "bpass_v2.2.1_imf_chab300.tar.gz"
    _write_tar(wanted, {"ionizing-bin-imf_chab100.z002.dat.gz": b"chab100"})
    _write_tar(other, {"ionizing-bin-imf_chab300.z002.dat.gz": b"chab300"})
    index = FileIndex(tmp_path, archive_needles=["imf_chab100"])
    index.prefetch(["ionizing-bin-imf_chab100.z002.dat"])
    assert index.find("ionizing-bin-imf_chab100.z002.dat").read_bytes() == b"chab100"
    assert index.find("ionizing-bin-imf_chab300.z002.dat") is None


def test_sed100_manifest_names_only_100msun_imfs():
    spec = yaml.safe_load(SED_100.read_text())
    assert spec["releases"]["2.2.1"]
    assert _archive_needles(spec) == {"imf135_100", "imf_chab100"}
    names = _needed_product_names(spec)
    assert len([n for n in names if n.startswith("spectra-")]) == 52
    assert len([n for n in names if n.startswith("numbers-")]) == 52
    assert "spectra-bin-imf135_100.z020.dat" in names
    assert "spectra-sin-imf_chab100.zem5.dat" in names
    assert "numbers-bin-imf135_100.z020.dat" in names
    assert not any("300" in n or "imf100_" in n or "imf170_" in n for n in names)
    assert DEFAULT_MANIFEST.name == "golden.yaml"


def test_extra_imf_manifest_names_the_six_variant_grids():
    spec = yaml.safe_load(SED_EXTRA.read_text())
    needles = _archive_needles(spec)
    assert needles == {
        "imf100_100",
        "imf100_300",
        "imf135_300",
        "imf170_100",
        "imf170_300",
        "imf_chab300",
    }
    # Needles are substrings of archive names. A shorter code must not
    # also match a sibling tarball (imf100_100 inside imf100_300, etc.).
    archives = [f"bpass_v2.2.1_{code}.tar.gz" for code in needles]
    for code in needles:
        hits = [name for name in archives if code in name]
        assert hits == [f"bpass_v2.2.1_{code}.tar.gz"]
    names = _needed_product_names(spec)
    assert len([n for n in names if n.startswith("spectra-")]) == 6 * 2 * 13
    assert "spectra-bin-imf135_300.z020.dat" in names
    assert "numbers-sin-imf_chab300.zem5.dat" in names
    assert not any(".a+00." in n or "imf135_100" in n or "imf_chab100" in n for n in names)


SED_V23 = Path(__file__).resolve().parents[1] / "src" / "bib" / "ingest" / "sed-v23.yaml"


def test_v23_filenames_are_official_untagged():
    from bib.ingest.run import _product_filenames

    names = _product_filenames("spectra", "bin", "imf135_300", "z020", "a+00")
    assert names[0] == "spectra-bin-imf135_300.a+00.z020.dat"
    assert "spectra-bin-imf135_300.z020.a+00.dat" in names
    assert not any(".C3K." in n or ".AP." in n for n in names)


def test_v23_manifest_opens_official_packs():
    spec = yaml.safe_load(SED_V23.read_text())
    assert spec["releases"]["2.3"]
    assert _archive_needles(spec) == {"imf135_300", "v2.3"}
    names = _needed_product_names(spec)
    assert "spectra-bin-imf135_300.a+00.z020.dat" in names
    assert "spectra-sin-imf135_300.a-02.zem5.dat" in names
    assert "colours-bin-imf135_300.a+06.z014.dat" in names
    assert "ionizing-sin-imf135_300.a+04.z040.dat" in names
    assert not any(".C3K." in n or "byrne" in n.lower() for n in names)
    assert len([n for n in names if n.startswith("spectra-")]) == 260


def test_extracts_member_from_official_v23_tarball(tmp_path: Path):
    _write_tar(
        tmp_path / "bpass_v2.3.a+00.tar.gz",
        {"spectra-bin-imf135_300.a+00.z020.dat": b"v23-flux"},
    )
    index = FileIndex(tmp_path, archive_needles=["v2.3", "imf135_300"])
    found = index.find("spectra-bin-imf135_300.a+00.z020.dat")
    assert found is not None
    assert found.read_bytes() == b"v23-flux"
    assert index.provenance(found) == (
        "bpass_v2.3.a+00.tar.gz::spectra-bin-imf135_300.a+00.z020.dat"
    )
