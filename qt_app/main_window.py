from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from qt_app.pages import (
    AgricolturaPage,
    AttrezzaturePage,
    AziendaPage,
    MacchinariPage,
    ZootecniaPage,
)


class MainWindow(QMainWindow):
    change_user_requested = Signal()

    CATEGORIA_AZIENDA = "Azienda"
    CATEGORIA_AGRICOLTURA = "Agricoltura"
    CATEGORIA_ATTREZZATURE = "Attrezzature"
    CATEGORIA_MACCHINARI = "Macchinari"
    CATEGORIA_ZOOTECNIA = "Zootecnia"

    CATEGORIES = (
        CATEGORIA_AZIENDA,
        CATEGORIA_AGRICOLTURA,
        CATEGORIA_ATTREZZATURE,
        CATEGORIA_MACCHINARI,
        CATEGORIA_ZOOTECNIA,
    )

    def __init__(self, user_id: int, username: str):
        super().__init__()
        self.user_id = int(user_id)
        self.username = username

        self.setWindowTitle(f"Gestione Fatture - {self.username}")
        self.resize(1200, 800)

        self.stack = QStackedWidget(self)
        self.pages = {}
        self.page_containers = {}

        for category in self.CATEGORIES:
            page = self._create_category_page(category)
            self.pages[category] = page
            container = self._create_scrollable_container(page)
            self.page_containers[category] = container
            self.stack.addWidget(container)

        self.setCentralWidget(self.stack)
        self._build_menu()
        self.statusBar().showMessage(f"Accesso effettuato come: {self.username}")
        self.show_category(self.CATEGORIA_AZIENDA)

    def _build_menu(self):
        menu_bar = self.menuBar()

        for category in self.CATEGORIES:
            action = QAction(category, self)
            action.triggered.connect(lambda _checked=False, name=category: self.show_category(name))
            menu_bar.addAction(action)

        account_menu = menu_bar.addMenu("Account")
        change_user_action = QAction("Cambia utente", self)
        change_user_action.triggered.connect(self._request_change_user)
        account_menu.addAction(change_user_action)

    def _create_category_page(self, category: str) -> QWidget:
        if category == self.CATEGORIA_AZIENDA:
            return AziendaPage(user_id=self.user_id, parent=self)
        if category == self.CATEGORIA_AGRICOLTURA:
            return AgricolturaPage(user_id=self.user_id, parent=self)
        if category == self.CATEGORIA_ATTREZZATURE:
            return AttrezzaturePage(user_id=self.user_id, parent=self)
        if category == self.CATEGORIA_MACCHINARI:
            return MacchinariPage(user_id=self.user_id, parent=self)
        if category == self.CATEGORIA_ZOOTECNIA:
            return ZootecniaPage(user_id=self.user_id, parent=self)
        return self._create_placeholder_page(category)

    def _create_placeholder_page(self, category: str) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel(f"Area {category}")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        title.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        subtitle = QLabel(
            "Migrazione in corso: questa pagina verra portata da Tkinter a PySide6 passo passo."
        )
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)
        return page

    def _create_scrollable_container(self, page: QWidget) -> QScrollArea:
        container = QScrollArea(self)
        container.setWidgetResizable(True)
        container.setFrameShape(QFrame.NoFrame)
        container.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        container.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        container.setWidget(page)
        return container

    def show_category(self, category: str):
        page_container = self.page_containers.get(category)
        if page_container is None:
            return
        self.stack.setCurrentWidget(page_container)
        self.statusBar().showMessage(f"Categoria attiva: {category}")

    def _request_change_user(self):
        conferma = QMessageBox.question(
            self,
            "Conferma",
            "Vuoi uscire e cambiare utente?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if conferma == QMessageBox.Yes:
            self.change_user_requested.emit()
