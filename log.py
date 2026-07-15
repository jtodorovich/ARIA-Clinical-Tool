import json
import os
from datetime import datetime, timezone

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "interactions.jsonl")


def log_interaction(record: dict) -> None:
    """
    Appends one interaction record as a line of JSON to a local log file.
    This is the seed data for future tier-calibration learning.
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    record["timestamp"] = datetime.now(timezone.utc).isoformat()

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
