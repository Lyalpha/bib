"""Age query parameter: log_age on the BPASS 0.1 dex grid."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from bib.api.v1.helpers import resolve_age_index


def test_log_age_maps_to_grid_index():
    assert resolve_age_index(None, 6.0) == 0
    assert resolve_age_index(None, 8.0) == 20
    assert resolve_age_index(None, 9.0) == 30
    assert resolve_age_index(None, 11.0) == 50
    assert resolve_age_index(20, None) == 20
    assert resolve_age_index(None, 8.12) == 21  # nearest 0.1 dex


def test_log_age_and_index_must_agree():
    assert resolve_age_index(30, 9.0) == 30
    with pytest.raises(HTTPException) as clash:
        resolve_age_index(0, 9.0)
    assert clash.value.status_code == 422
    with pytest.raises(HTTPException) as missing:
        resolve_age_index(None, None)
    assert missing.value.status_code == 422
