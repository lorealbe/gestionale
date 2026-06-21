import sqlite3

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app_utils import is_blank
from database import get_conn


ph = PasswordHasher()


class LoginWindow(QWidget):
    authenticated = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Login Gestionale (Qt)")
        self.setMinimumWidth(360)
        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(12)

        title = QLabel("Autenticazione")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        main_layout.addWidget(title)

        self.input_user = QLineEdit(self)
        self.input_user.setPlaceholderText("Username")
        self.input_user.returnPressed.connect(self._on_enter_pressed)
        main_layout.addWidget(self.input_user)

        self.input_password = QLineEdit(self)
        self.input_password.setPlaceholderText("Password")
        self.input_password.setEchoMode(QLineEdit.Password)
        self.input_password.returnPressed.connect(self._on_enter_pressed)
        main_layout.addWidget(self.input_password)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        self.button_login = QPushButton("Accedi", self)
        self.button_login.clicked.connect(self.login)
        button_row.addWidget(self.button_login)

        self.button_register = QPushButton("Registrati", self)
        self.button_register.clicked.connect(self.register)
        button_row.addWidget(self.button_register)

        main_layout.addLayout(button_row)
        self.input_user.setFocus()

    def _on_enter_pressed(self):
        self.login()

    def clear_password(self):
        self.input_password.clear()

    def register(self):
        user = self.input_user.text().strip()
        pwd = self.input_password.text()

        if is_blank(user) or is_blank(pwd):
            QMessageBox.warning(self, "Errore", "Inserisci Username e Password")
            return

        try:
            pwd_hash = ph.hash(pwd)
            with get_conn() as conn:
                c = conn.cursor()
                c.execute("INSERT INTO utenti (username, password_hash) VALUES (?, ?)", (user, pwd_hash))
            QMessageBox.information(self, "Successo", "Registrazione completata. Ora puoi accedere.")
            self.clear_password()
        except sqlite3.IntegrityError:
            QMessageBox.critical(self, "Errore", "Nome utente gia esistente.")
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")

    def login(self):
        user = self.input_user.text().strip()
        pwd = self.input_password.text()

        if is_blank(user) or is_blank(pwd):
            QMessageBox.warning(self, "Errore", "Inserisci Username e Password")
            return

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT id, password_hash FROM utenti WHERE username=?", (user,))
                row = c.fetchone()

            if not row:
                QMessageBox.critical(self, "Accesso Negato", "Username o Password errati.")
                return

            user_id, stored_hash = row[0], row[1]
            try:
                ph.verify(stored_hash, pwd)
            except VerifyMismatchError:
                QMessageBox.critical(self, "Accesso Negato", "Username o Password errati.")
                return

            self.clear_password()
            self.authenticated.emit(int(user_id), user)
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
