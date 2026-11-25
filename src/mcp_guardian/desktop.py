import json
from collections import deque
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QListWidget, QListWidgetItem,
    QSystemTrayIcon, QMenu
)
from PySide6.QtGui import QAction, QIcon

class UIEvents(QObject):
    request_pending = Signal(object)
    decision = Signal(str, bool)
    status = Signal(str)

class ApprovalWindow(QMainWindow):
    def __init__(self, events: UIEvents):
        super().__init__()
        self.events = events
        self.setWindowTitle("MCP Guardian — Approval Required")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(560, 440)
        central = QWidget()
        layout = QVBoxLayout(central)
        self.heading = QLabel("MCP tool request needs your approval")
        self.heading.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.meta = QLabel("Waiting for request…")
        self.args = QTextEdit()
        self.args.setReadOnly(True)
        self.args.setPlaceholderText("Tool arguments will appear here")
        buttons = QHBoxLayout()
        self.allow_btn = QPushButton("Allow request")
        self.block_btn = QPushButton("Block request")
        self.allow_btn.setStyleSheet("background:#16803c;color:white;padding:10px;font-weight:700;")
        self.block_btn.setStyleSheet("background:#b42318;color:white;padding:10px;font-weight:700;")
        self.allow_btn.clicked.connect(lambda: self._decide(True))
        self.block_btn.clicked.connect(lambda: self._decide(False))
        buttons.addWidget(self.allow_btn)
        buttons.addWidget(self.block_btn)
        layout.addWidget(self.heading)
        layout.addWidget(self.meta)
        layout.addWidget(self.args, 1)
        layout.addLayout(buttons)
        self.setCentralWidget(central)
        self.current_id = None
        self.request_queue = deque()
        self.events.request_pending.connect(self.enqueue_request)

    def enqueue_request(self, request):
        self.request_queue.append(request)
        if self.current_id is None:
            self._show_next()

    def _show_next(self):
        if not self.request_queue:
            self.current_id = None
            self.hide()
            return
        request = self.request_queue.popleft()
        self.current_id = request.request_id
        self.meta.setText(
            f"Server: {request.server_name}    |    Tool: {request.tool_name}    |    ID: {request.request_id}"
        )
        self.args.setPlainText(request.preview)
        self.allow_btn.setEnabled(True)
        self.block_btn.setEnabled(True)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        QApplication.alert(self, 0)

    def _decide(self, allow: bool):
        if self.current_id is None:
            return
        request_id = self.current_id
        self.current_id = None
        self.allow_btn.setEnabled(False)
        self.block_btn.setEnabled(False)
        self.hide()
        self.events.decision.emit(request_id, allow)
        self._show_next()

class GuardianTray:
    def __init__(self, app: QApplication, window: ApprovalWindow):
        self.icon = QSystemTrayIcon(QIcon(), app)
        self.icon.setToolTip("MCP Guardian — protecting MCP tool calls")
        menu = QMenu()
        show_action = QAction("Show approval window", menu)
        show_action.triggered.connect(window.show)
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(app.quit)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.icon.setContextMenu(menu)
        self.icon.show()
