from dataclasses import dataclass
from typing import Any

@dataclass
class PendingRequest:
    request_id: str
    server_name: str
    tool_name: str
    arguments: Any
    preview: str
