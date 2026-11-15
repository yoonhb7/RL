"""Edit this file in VS Code, save it, then type `reload` in the running console.

green_seconds is used by the original timing console. choose_action is used by
the new Gymnasium console. Both leave yellow/all-red transitions to the session.
This module must not connect to SUMO, close the connection, or run its own loop.
"""

# Change these values and use `reload`. Allowed range: 10 to 60 seconds.
NS_GREEN_SECONDS = 30.0
EW_GREEN_SECONDS = 30.0


def green_seconds(observation):
    """Choose the total duration of the current green phase.

    observation contains: time_s, phase_index, phase_elapsed_s, signal_state,
    queues (stopped vehicles by approach), and vehicles (vehicles by approach).
    Called for green phases only: 0 = north/south, 3 = east/west.
    """
    if observation["phase_index"] == 0:
        return NS_GREEN_SECONDS
    return EW_GREEN_SECONDS


def choose_action(observation, info):
    """Toy environment policy: return 0=hold or 1=request switch.

    This is a simple duration-based rule, not a trained DQN. The normalized
    observation vector is ready for a future model.predict(observation) call.
    """
    raw = info["raw_observation"]
    if raw["phase_index"] not in (0, 3):
        return 0
    return int(raw["phase_elapsed_s"] >= green_seconds(raw))
