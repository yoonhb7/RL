"""Start one SUMO process and report its real failure instead of changing ports."""
from pathlib import Path
import subprocess

from sumolib.miscutils import getFreeSocketPort
import traci


def start_sumo(command, label, output=None):
    log_path = Path(output) / "sumo-startup.log" if output else None
    log = log_path.open("w", encoding="utf-8") if log_path else subprocess.DEVNULL
    process = None
    try:
        port = getFreeSocketPort()
        process = subprocess.Popen(command + ["--remote-port", str(port)], stdout=log, stderr=subprocess.STDOUT)
        conn = traci.connect(port, numRetries=40, host="127.0.0.1", proc=process, waitBetweenRetries=0.25, label=label)
        conn.getVersion()
        return conn
    except Exception as error:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        code = process.returncode if process is not None else None
        if log_path:
            log.close()
        details = log_path.read_text(encoding="utf-8", errors="replace")[-5000:] if log_path and log_path.exists() else ""
        status = f"0x{code & 0xffffffff:08X}" if code is not None else "not launched"
        raise RuntimeError(f"SUMO startup failed ({status}): {command[0]}\nStartup log: {log_path}\n{details or str(error)}") from error
    finally:
        if log_path and not log.closed:
            log.close()
