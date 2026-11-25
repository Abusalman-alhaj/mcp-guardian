import argparse
import asyncio
import json
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from .desktop import UIEvents, ApprovalWindow, GuardianTray
from .proxy import MCPProxy

def main():
    parser = argparse.ArgumentParser(description="MCP Guardian approval proxy")
    parser.add_argument("--config", default="config.json", help="Path to JSON configuration")
    args = parser.parse_args()
    config_path = Path(args.config).expanduser().resolve()
    if not config_path.exists():
        print(f"Config not found: {config_path}. Copy config.example.json to config.json and edit it.", file=sys.stderr)
        raise SystemExit(2)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(config.get("server"), dict) or not config["server"].get("command"):
            raise ValueError("Config must define server.command")
    except Exception as exc:
        print(f"Invalid configuration: {exc}", file=sys.stderr)
        raise SystemExit(2)

    qt_app = QApplication(sys.argv[:1])
    qt_app.setQuitOnLastWindowClosed(False)
    events = UIEvents()
    window = ApprovalWindow(events)
    tray = GuardianTray(qt_app, window)

    loop_holder = {}
    proxy_holder = {}

    def worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        proxy = MCPProxy(config, events)
        loop_holder["loop"] = loop
        proxy_holder["proxy"] = proxy
        events.decision.connect(
            lambda request_id, allow: loop.call_soon_threadsafe(
                lambda: asyncio.create_task(proxy.decide(request_id, allow))
            )
        )
        try:
            loop.run_until_complete(proxy.run())
        except Exception as exc:
            print(f"MCP Guardian stopped: {exc}", file=sys.stderr)
            events.status.emit(str(exc))
        finally:
            loop.close()
            QTimer.singleShot(0, qt_app.quit)

    thread = threading.Thread(target=worker, name="mcp-proxy", daemon=True)
    thread.start()
    try:
        return qt_app.exec()
    finally:
        # The proxy notices client stdin closure and shuts down its child.
        thread.join(timeout=4)

if __name__ == "__main__":
    main()
