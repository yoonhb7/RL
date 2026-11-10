import subprocess
import sys
from unittest.mock import patch

import pytest

from traffic_rl.launch import start_sumo


def test_failed_server_reports_exit_and_log_without_relaunching(tmp_path):
    def failed_connect(*args, **kwargs):
        kwargs["proc"].wait(timeout=5)
        raise RuntimeError("server finished")

    original_popen = subprocess.Popen
    with patch("traffic_rl.launch.traci.connect", side_effect=failed_connect), patch("traffic_rl.launch.subprocess.Popen", wraps=original_popen) as spawn:
        with pytest.raises(RuntimeError, match="0x00000007") as raised:
            start_sumo([sys.executable, "-c", "print('bad SUMO option', flush=True); raise SystemExit(7)"], "test", tmp_path)
        assert spawn.call_count == 1
    assert "bad SUMO option" in str(raised.value)
    assert (tmp_path / "sumo-startup.log").read_text().strip() == "bad SUMO option"
