"""Learning plots must separate demand, preserve warmup gaps and retain real zero loss."""

import copy
import math
import unittest

from src.agents.fourphase_learning import reward_series, update_series


def episodes_for(values):
    return [{"episode": i, "level": level, "global_decisions": i * 240,
             "raw_reward_sum": reward, "mean_R1": reward / 240, "epsilon": .5,
             "replay_size": i * 240, "optimizer_updates": max(0, i * 240 - 1000),
             "checks": {"valid": True}} for i, (level, reward) in enumerate(values, 1)]


def updates_for(losses):
    rows, count = [], 0
    for i, loss in enumerate(losses, 1):
        count += loss is not None
        rows.append({"decision": i, "epsilon": 1. - i / 10, "loss": loss,
                     "mean_q": -i, "mean_target": -2 * i, "replay_size": i, "optimizer_updates": count})
    return rows


class LearningCurveTests(unittest.TestCase):
    def test_rolling_returns_use_only_the_same_demand_and_need_a_full_SD_window(self):
        values = episodes_for((("low", -10), ("high", -1000), ("low", -30),
                               ("high", -2000), ("medium", -400), ("low", -50)))
        rows = reward_series(values, window=2)
        self.assertIsNone(rows[0]["return_sd"])
        self.assertIsNone(rows[4]["return_sd"])
        self.assertEqual(rows[2]["return_ma"], -20)
        self.assertAlmostEqual(rows[2]["return_sd"], math.sqrt(200))
        self.assertEqual(rows[5]["return_ma"], -40)
        self.assertEqual(rows[5]["window_episodes"], 2)

    def test_no_learning_is_missing_loss_but_zero_loss_is_a_real_update(self):
        bins, epsilon = update_series(updates_for((None, None, 0., 8., 2.)), learning_starts=2, bin_size=2)
        self.assertIsNone(bins[0]["loss_mean"])
        self.assertEqual(bins[0]["updates_in_bin"], 0)
        self.assertEqual(bins[1]["loss_mean"], 4.)
        self.assertAlmostEqual(bins[1]["loss_p90"], 7.2)
        self.assertEqual(bins[2]["updates_in_bin"], 1)
        self.assertEqual(bins[2]["optimizer_updates"], 3)
        self.assertEqual(bins[2]["decision_last"], 5)
        self.assertEqual(epsilon[1]["behavior_epsilon"], 1.)
        self.assertAlmostEqual(epsilon[2]["behavior_epsilon"], .8)
        self.assertAlmostEqual(epsilon[-1]["behavior_epsilon"], .6)

    def test_missing_decisions_and_nonfinite_values_are_rejected(self):
        original = updates_for((None, None, 1.))
        with self.assertRaises(ValueError):
            update_series([original[0], original[2]], learning_starts=2)
        for key in ("loss", "mean_q", "mean_target"):
            rows = copy.deepcopy(original)
            rows[-1][key] = math.nan
            with self.subTest(key=key), self.assertRaises(ValueError):
                update_series(rows, learning_starts=2)


if __name__ == "__main__":
    unittest.main()
