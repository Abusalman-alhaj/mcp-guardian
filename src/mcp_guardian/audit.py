import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

class AuditLog:
    def __init__(self, path: str):
        self.path = Path(path)

    def write(self, event: str, request_id: str, tool: str, details: Any = None):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "request_id": request_id,
            "tool": tool,
            "details": details,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
