"""Editable Mac viewing rule: pause -> save this file -> reload -> resume.

This file affects only the interactive viewer. Reproducible baseline evaluation
uses queue_action and the settings frozen in the experiment manifest.
"""

from src.traffic.corridor import queue_action


HYSTERESIS_VEHICLES = None  # None uses the scenario value (2); try 0 or 5.


def choose_action(observation, info):
    if HYSTERESIS_VEHICLES is not None:
        info = {**info, "queue_hysteresis_vehicles": HYSTERESIS_VEHICLES}
    return queue_action(observation, info)
