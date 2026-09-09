"""Event heuristics exercised on the synthetic demo tracks.

The toy tracks are purpose-built to trigger each heuristic, so they double as
regression fixtures for the detector.
"""

from __future__ import annotations

from bib.ingest.events import detect_events
from bib.ingest.synthetic import (
    toy_cee_binary,
    toy_close_binary,
    toy_secondary,
    toy_single,
    toy_wide_binary,
)


def types(track) -> list[str]:
    return [e.event_type for e in detect_events(track)]


def test_every_track_starts_and_ends():
    for track in (toy_single(1.0), toy_close_binary(), toy_cee_binary()):
        found = types(track)
        assert found[0] == "zams"
        assert found[-1] == "endpoint"


def test_low_mass_single_star_agb():
    found = types(toy_single(1.0))
    assert "tams" in found
    assert "giant_branch" in found
    assert "he_exhaustion" in found
    assert "thermal_pulses" in found


def test_massive_single_star_wr():
    found = types(toy_single(60.0))
    assert "wr_onset" in found
    assert "c_burning" in found


def test_close_binary_rlof_and_stripping():
    found = types(toy_close_binary())
    assert "rlof_start" in found
    assert "rlof_end" in found
    assert "wr_onset" in found  # stripped to a hot helium star


def test_cee_binary_detects_common_envelope():
    found = types(toy_cee_binary())
    assert "cee" in found
    assert "rlof_start" in found


def test_wide_binary_never_interacts():
    found = types(toy_wide_binary())
    assert "rlof_start" not in found
    assert "cee" not in found


def test_secondary_track_valid():
    found = types(toy_secondary())
    assert found[0] == "zams"
    assert "endpoint" in found


def test_events_sorted_by_age():
    events = detect_events(toy_cee_binary())
    ages = [e.age_yr for e in events]
    assert ages == sorted(ages)
