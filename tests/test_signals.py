import numpy as np
import pytest

from traffic_rl.signals import SafetySignal, decode_action, encode_action, joint_mask


def spec():
    return {"id": "test", "lanes": [], "greens": ["Gr", "rG"], "yellows": ["yr", "ry"], "all_red_state": "rr", "min_green": 10, "max_green": 20, "fixed_green": 15, "yellow": 3, "all_red": 2}


@pytest.mark.parametrize("count", [1, 2, 3])
def test_joint_encoding_and_asymmetric_mask(count):
    signals = [SafetySignal(spec()) for _ in range(count)]
    for action in range(2**count):
        assert encode_action(decode_action(action, count)) == action
    assert np.flatnonzero(joint_mask(signals)).tolist() == [0]
    signals[-1].elapsed = 20
    assert np.flatnonzero(joint_mask(signals)).tolist() == [2 ** (count - 1)]


def test_exact_clearance_and_minimum_green():
    s = SafetySignal(spec())
    s.request(1)
    assert s.stage == "green"
    for _ in range(10):
        assert s.before_second() == "Gr"
        s.after_second()
    s.request(1)
    states = []
    for _ in range(6):
        states.append(s.before_second())
        s.after_second()
    assert states == ["yr", "yr", "yr", "rr", "rr", "rG"]
    assert s.elapsed == 1 and s.switches == 1


def test_holding_cannot_exceed_max_green():
    s = SafetySignal(spec())
    trace = []
    for _ in range(45):
        s.request(0)
        trace.append(s.before_second())
        s.after_second()
    assert trace[:20] == ["Gr"] * 20
    assert trace[20:25] == ["yr"] * 3 + ["rr"] * 2
    assert trace[25:45] == ["rG"] * 20


def test_invalid_clearance_is_rejected():
    s = spec()
    s["yellows"] = ["ry", "ry"]
    with pytest.raises(ValueError, match="outgoing"):
        SafetySignal(s)
