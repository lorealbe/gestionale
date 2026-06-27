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
from models import Utente  # Importiamo il modello Peewee

ph = PasswordHasher()

class LoginWindow(QWidget):
    authenticated = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Login Gestionale (Cloud)")
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

        # CORRETTO: il nome è self.input_password
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
        pwd = self.input_password.text() # CORRETTO: self.input_password

        if is_blank(user) or is_blank(pwd):
            QMessageBox.warning(self, "Errore", "Inserisci Username e Password")
            return

        try:
            pwd_hash = ph.hash(pwd)
            # PEEWEE ORM: Salva l'utente nel cloud
            Utente.create(username=user, password_hash=pwd_hash)
            
            QMessageBox.information(self, "Successo", "Registrazione completata. Ora puoi accedere.")
            self.clear_password()
        except Exception as exc:
            QMessageBox.critical(self, "Errore", f"Impossibile registrare l'utente: {exc}")

    def login(self):
        user = self.input_user.text().strip()
        pwd = self.input_password.text() # CORRETTO: self.input_password

        if is_blank(user) or is_blank(pwd):
            QMessageBox.warning(self, "Errore", "Inserisci Username e Password")
            return

        try:
            # PEEWEE ORM: Recupera l'utente dal cloud
            utente = Utente.get_or_none(Utente.username == user)

            if not utente:
                QMessageBox.critical(self, "Accesso Negato", "Username o Password errati.")
                return

            try:
                ph.verify(utente.password_hash, pwd)
            except VerifyMismatchError:
                QMessageBox.critical(self, "Accesso Negato", "Username o Password errati.")
                return

            self.clear_password()
            self.authenticated.emit(int(utente.id), user)
        except Exception as exc:
            print(f"DEBUG ERROR: {exc}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Errore", f"Errore durante il login: {exc}")