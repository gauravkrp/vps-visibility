import json
import os
import re
import subprocess

_UNITS = {"b": 1, "kb": 1000, "kib": 1024, "mb": 1000**2, "mib": 1024**2,
          "gb": 1000**3, "gib": 1024**3, "tb": 1000**4, "tib": 1024**4}


def run_command(cmd, timeout=10):
    """Returns (returncode, stdout). rc -1 means the binary is missing or it timed out."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1, ""


def parse_size(text):
    match = re.match(r"\s*([\d.]+)\s*([a-zA-Z]+)?", text or "")
    if not match:
        return 0
    unit = (match.group(2) or "b").lower()
    return int(float(match.group(1)) * _UNITS.get(unit, 1))


def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)


def ok(data):
    return {"status": "ok", "data": data}


def absent(message):
    return {"status": "absent", "message": message}


def error(message):
    return {"status": "error", "message": message}
