"""Config wiring sanity checks.

Guards against values that used to be hard-coded in the source drifting away
from the environment-driven config.
"""

from __future__ import annotations

from backend import config, simulation


def test_simulation_interval_comes_from_config():
    assert simulation.SIM_INTERVAL_SECONDS == config.SIM_INTERVAL_SECONDS
    assert simulation.SIM_INTERVAL_SECONDS > 0


def test_production_flag_matches_environment():
    assert config.IS_PRODUCTION is (config.ENVIRONMENT == "production")
