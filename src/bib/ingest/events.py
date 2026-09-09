"""Evolutionary-phase detection for stellar model tracks.

BPASS sneplot files contain no central abundances, so phases are inferred from
core-mass formation, surface composition and track morphology. These are
documented heuristics — good enough to guide the eye pedagogically, and each
curated golden-subset track is checked by hand. Thresholds are module
constants so they can be tuned in one place.

Event types emitted:
  zams, tams, he_exhaustion, c_burning, giant_branch, wr_onset,
  rlof_start, rlof_end, cee, thermal_pulses, endpoint
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from bib.ingest.parsers import TrackData

CORE_FORMS_MSUN = 1.0e-3  # a core "exists" above this mass
GIANT_LOG_T = 3.70  # cooler than ~5000 K counts as giant territory
WR_X_SURF = 0.4  # surface hydrogen fraction below this = stripped
WR_LOG_T = 4.45  # manual WR temperature criterion
CEE_LOG_SEP_DROP = 0.15  # in-spiral: drop in log(a) between adjacent steps
PULSE_MIN_CYCLES = 3  # L oscillation cycles to call thermal pulses
MAX_RLOF_EVENTS = 5  # cap marker spam for systems with many episodes


@dataclass
class Event:
    event_type: str
    step: int
    age_yr: float
    label: str
    note: str | None = None


def _first_index(mask: np.ndarray) -> int | None:
    hits = np.flatnonzero(mask)
    return int(hits[0]) if hits.size else None


def detect_events(track: TrackData) -> list[Event]:
    age = track["age_yr"]
    steps = track["step"].astype(int)
    events: list[Event] = []

    def add(event_type: str, i: int, label: str, note: str | None = None) -> None:
        events.append(Event(event_type, int(steps[i]), float(age[i]), label, note))

    add("zams", 0, "ZAMS — track begins", None)

    # --- core-driven phases ---------------------------------------------------
    i_tams = _first_index(track["he_core"] > CORE_FORMS_MSUN)
    if i_tams is not None and i_tams > 0:
        add(
            "tams",
            i_tams,
            "Core H exhaustion (He core forms)",
            "Inferred from He-core mass rising above zero; sneplot files carry no central abundances.",
        )

    i_he_exh = _first_index(track["co_core"] > CORE_FORMS_MSUN)
    if i_he_exh is not None and i_he_exh > 0:
        add("he_exhaustion", i_he_exh, "Core He exhaustion (CO core forms)")

    i_cburn = _first_index(track["one_core"] > CORE_FORMS_MSUN)
    if i_cburn is not None and i_cburn > 0:
        add("c_burning", i_cburn, "Carbon burning (ONe core forms)")

    # --- morphology ------------------------------------------------------------
    log_t = track["log_t1"]
    if i_tams is not None:
        after = np.zeros_like(log_t, dtype=bool)
        after[i_tams:] = True
        i_giant = _first_index(after & (log_t < GIANT_LOG_T))
        if i_giant is not None:
            add("giant_branch", i_giant, "Reaches the giant branch (Teff < 5000 K)")

    i_wr = _first_index((track["x_surf"] < WR_X_SURF) & (log_t > WR_LOG_T))
    if i_wr is not None and i_wr > 0:
        add(
            "wr_onset",
            i_wr,
            "Surface H stripped — Wolf-Rayet regime",
            f"Surface X < {WR_X_SURF} while log Teff > {WR_LOG_T}.",
        )

    # --- binary interaction -----------------------------------------------------
    dm1r = track.get("dm1r")
    log_sep = track.get("log_sep")
    if dm1r is not None and np.any(np.nan_to_num(dm1r) > 0):
        active = np.nan_to_num(dm1r) > 0
        boundaries = np.flatnonzero(np.diff(active.astype(int)))
        starts = [int(b + 1) for b in boundaries if active[b + 1]]
        ends = [int(b + 1) for b in boundaries if not active[b + 1]]
        if active[0]:
            starts.insert(0, 0)
        n_episodes = len(starts)
        for n, i_start in enumerate(starts[:MAX_RLOF_EVENTS]):
            suffix = f" (episode {n + 1}/{n_episodes})" if n_episodes > 1 else ""
            add("rlof_start", i_start, f"Roche-lobe overflow begins{suffix}")
            i_end = next((e for e in ends if e > i_start), None)
            if i_end is not None:
                add("rlof_end", i_end, f"Roche-lobe overflow ends{suffix}")

        # Common envelope: rapid in-spiral while RLOF is active.
        if log_sep is not None:
            dsep = np.diff(np.nan_to_num(log_sep, nan=0.0))
            plunge = np.flatnonzero((dsep < -CEE_LOG_SEP_DROP) & active[1:])
            if plunge.size:
                add(
                    "cee",
                    int(plunge[0] + 1),
                    "Common-envelope evolution (rapid in-spiral)",
                    f"log(a) dropped by >{CEE_LOG_SEP_DROP} in one step during mass transfer.",
                )

    # --- thermal pulses ---------------------------------------------------------
    tp_zone = (track["co_core"] > CORE_FORMS_MSUN) & (log_t < 3.8)
    if np.count_nonzero(tp_zone) > 10:
        zone = np.flatnonzero(tp_zone)
        dl = np.diff(track["log_l1"][zone])
        meaningful = np.abs(dl) > 1e-3
        signs = np.sign(dl[meaningful])
        flips = int(np.count_nonzero(np.diff(signs) != 0))
        if flips >= 2 * PULSE_MIN_CYCLES:
            add(
                "thermal_pulses",
                int(zone[0]),
                "Thermal pulses (AGB shell instabilities)",
                f"{flips} luminosity reversals on the cool, CO-core branch.",
            )

    # --- endpoint ----------------------------------------------------------------
    last = int(age.size - 1)
    final_mass = float(track["m1"][last])
    he = float(track["he_core"][last])
    co = float(track["co_core"][last])
    if co > 1.35 and final_mass > 2.0:
        hint = "massive core at the end of the calculation — supernova candidate"
    elif co > CORE_FORMS_MSUN:
        hint = "CO core formed — likely white-dwarf progenitor" if final_mass < 8 else "evolved core"
    elif he > CORE_FORMS_MSUN:
        hint = "He core formed"
    else:
        hint = "calculation ends on or near the main sequence"
    add(
        "endpoint",
        last,
        f"End of track — final mass {final_mass:.2f} Msun",
        hint,
    )

    events.sort(key=lambda e: (e.age_yr, e.step))
    return events
