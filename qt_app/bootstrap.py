import sys

from PySide6.QtWidgets import QApplication

from qt_app.login_window import LoginWindow
from qt_app.main_window import MainWindow


def run_qt_app() -> int:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    app.setApplicationName("Gestionale")
    app.setStyleSheet(
        """
        QPushButton {
            min-height: 30px;
            padding: 5px 12px;
            font-weight: 600;
            border: 1px solid #8f9aa7;
            border-radius: 6px;
            background-color: #f2f4f7;
        }
        QPushButton:hover {
            border-color: #6f7f90;
            background-color: #e8edf3;
        }
        QPushButton:pressed {
            background-color: #dde3ea;
        }
        QPushButton:disabled {
            color: #8f8f8f;
            border-color: #c8c8c8;
            background-color: #f4f4f4;
        }
        """
    )

    login_window = LoginWindow()
    state = {"main_window": None}

    def back_to_login():
        main_window = state.get("main_window")
        if main_window is not None:
            main_window.close()
        state["main_window"] = None

        login_window.clear_password()
        login_window.show()
        login_window.activateWindow()
        login_window.raise_()

    def open_main(user_id: int, username: str):
        login_window.hide()

        main_window = MainWindow(user_id=user_id, username=username)
        state["main_window"] = main_window
        main_window.change_user_requested.connect(back_to_login)
        main_window.showMaximized()

    login_window.authenticated.connect(open_main)
    login_window.show()

    return app.exec()
