from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from creator_intelligence.services.desktop_oauth import LoopbackOAuthReceiver


def _is_loopback(uri: str | None) -> bool:
    parsed = urlparse(uri or "")
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}


def _manual_callback(parent, service, platform: str, redirect_uri: str):
    flow = service.begin_oauth(platform, redirect_uri)
    QDesktopServices.openUrl(QUrl(flow["authorization_url"]))
    dialog = QDialog(parent)
    dialog.setWindowTitle(f"Connect {platform.title()}")
    layout = QVBoxLayout(dialog)
    message = QLabel(
        "Finish approving access in your browser. Then copy the complete address from the browser's address bar and paste it below."
    )
    message.setWordWrap(True)
    callback = QPlainTextEdit()
    callback.setPlaceholderText("Paste the complete callback URL here")
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(message)
    layout.addWidget(callback)
    layout.addWidget(buttons)
    if not dialog.exec():
        return None
    parsed = urlparse(callback.toPlainText().strip())
    values = {key: entries[0] for key, entries in parse_qs(parsed.query).items() if entries}
    if not values:
        raise ValueError("Paste the complete callback URL, including its code and state values.")
    return service.complete_oauth(platform, values, flow)


def run_browser_oauth(parent, service, platform: str, redirect_uri: str | None = None):
    if redirect_uri and not _is_loopback(redirect_uri):
        return _manual_callback(parent, service, platform, redirect_uri)

    receiver = LoopbackOAuthReceiver(redirect_uri)
    flow = service.begin_oauth(platform, receiver.redirect_uri)
    receiver.start()
    QDesktopServices.openUrl(QUrl(flow["authorization_url"]))

    dialog = QDialog(parent)
    dialog.setWindowTitle(f"Connect {platform.title()}")
    layout = QVBoxLayout(dialog)
    message = QLabel(
        f"Your browser is waiting for {platform.title()} approval. Creator Intelligence will finish the connection automatically."
    )
    message.setWordWrap(True)
    layout.addWidget(message)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    timer = QTimer(dialog)
    timer.setInterval(300)
    outcome = {}

    def check_callback():
        callback = receiver.result()
        if callback is None:
            return
        timer.stop()
        try:
            outcome["result"] = service.complete_oauth(platform, callback, flow)
        except Exception as exc:
            outcome["error"] = exc
            dialog.reject()
        else:
            dialog.accept()

    timer.timeout.connect(check_callback)
    timer.start()
    try:
        accepted = dialog.exec()
    finally:
        timer.stop()
        receiver.close()
    if outcome.get("error"):
        raise outcome["error"]
    return outcome.get("result") if accepted else None


def run_twitch_device_oauth(parent, service, client_id: str):
    connection = service.begin_twitch_connection(client_id)
    verification_uri = str(connection["verification_uri"])
    user_code = str(connection["user_code"])
    QApplication.clipboard().setText(user_code)
    QDesktopServices.openUrl(QUrl(verification_uri))

    dialog = QDialog(parent)
    dialog.setWindowTitle("Connect Twitch")
    layout = QVBoxLayout(dialog)
    message = QLabel(
        "Approve Creator Intelligence in the Twitch page that just opened. "
        "If Twitch asks for a code, it has already been copied to your clipboard."
    )
    message.setWordWrap(True)
    code = QLabel(user_code)
    code.setStyleSheet("font-size: 24px; font-weight: 700; padding: 12px;")
    layout.addWidget(message)
    layout.addWidget(code)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    timer = QTimer(dialog)
    timer.setInterval(max(1, int(connection.get("interval") or 5)) * 1000)
    outcome = {}

    def poll():
        try:
            result = service.poll_twitch_connection(connection)
        except Exception as exc:
            outcome["error"] = exc
            timer.stop()
            dialog.reject()
            return
        if result:
            outcome["result"] = result
            timer.stop()
            dialog.accept()

    timer.timeout.connect(poll)
    timer.start()
    accepted = dialog.exec()
    timer.stop()
    if outcome.get("error"):
        raise outcome["error"]
    return outcome.get("result") if accepted else None


def show_connection_result(parent, platform: str, result) -> None:
    if not result:
        return
    account = result.get("account_name") or result.get("account_id") or result.get("broadcaster_id")
    suffix = f" as {account}" if account else ""
    QMessageBox.information(parent, f"{platform.title()} connected", f"Connected securely{suffix}.")
