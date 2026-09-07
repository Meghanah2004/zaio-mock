from __future__ import annotations

import pytest

from src.config import load_qualification_config


def test_load_qualification_config_rejects_out_of_scope():
    with pytest.raises(ValueError, match="out of scope"):
        load_qualification_config("cybersecurity")


def test_load_qualification_config_rejects_unknown_data_science():
    with pytest.raises(ValueError, match="out of scope"):
        load_qualification_config("data_science")


def test_load_qualification_config_loads_software_developer():
    config = load_qualification_config("software_developer")
    assert config["qualification_key"] == "software_developer"
    assert sum(s["marks"] for s in config["sections"]) == config["total_marks"]
