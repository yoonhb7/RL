"""Explicit operational definitions; the source paper does not supply six executable formulas."""
from .common import REWARDS


def reward_value(name, *, stopped, active, mean_speed, speed_limit, arrived, weighted_arrived, departed):
    values = {
        'wtmin': -float(stopped),                  # negative additional stopped vehicle-seconds (dt=1)
        'asmax': float(mean_speed / speed_limit) if active else 0.0,
        'ttmin': -float(active),                   # negative additional in-network vehicle-seconds
        'ctmax': float(arrived),
        'wctmax': float(weighted_arrived),         # sum(shortest permitted route length / reference)
        'tmqmax': float(departed - stopped),       # paper definition: inserted vehicles minus halting vehicles
    }
    if name not in REWARDS:
        raise ValueError(name)
    return values[name]
