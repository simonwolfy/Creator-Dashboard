from PySide6.QtWidgets import QMessageBox

def show_error(parent, title, message, details=None):
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Critical)
    box.setWindowTitle(title)
    box.setText(message)
    if details:
        box.setDetailedText(details)
    box.exec()
