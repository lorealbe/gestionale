from PySide6.QtCore import Qt, Signal, QTimer
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
    QSizePolicy
)

from qt_app.pages import (
    AgricolturaPage,
    AttrezzaturePage,
    AziendaPage,
    MacchinariPage,
    ZootecniaPage,
)
from qt_app.pages.dashboard_page import DashboardPage


class MainWindow(QMainWindow):
    change_user_requested = Signal()

    CATEGORIA_DASHBOARD = "Dashboard"
    CATEGORIA_AZIENDA = "Azienda"
    CATEGORIA_AGRICOLTURA = "Agricoltura"
    CATEGORIA_ATTREZZATURE = "Attrezzature"
    CATEGORIA_MACCHINARI = "Macchinari"
    CATEGORIA_ZOOTECNIA = "Zootecnia"

    CATEGORIES = (
        CATEGORIA_DASHBOARD,
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
        self.stack.currentChanged.connect(self._adatta_altezza_dinamica)
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
        
        self.show_category(self.CATEGORIA_DASHBOARD)

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
        if category == self.CATEGORIA_DASHBOARD:         
            page = DashboardPage(self.user_id, self)
            # --- FIX: Connettiamo la Dashboard alla MainWindow ---
            page.richiesta_navigazione.connect(self._gestisci_navigazione_dashboard)
            return page
        elif category == self.CATEGORIA_AZIENDA:
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

    # --- NUOVO METODO: Fa da vigile urbano per le richieste della Dashboard ---
    def _gestisci_navigazione_dashboard(self, destinazione: str):
        mappa_destinazioni = {
            "agricoltura": self.CATEGORIA_AGRICOLTURA,
            "fatture": self.CATEGORIA_AZIENDA, # Mandiamo Fatture nella sezione Azienda
            "macchinari": self.CATEGORIA_MACCHINARI,
            "zootecnia": self.CATEGORIA_ZOOTECNIA
        }
        categoria_target = mappa_destinazioni.get(destinazione)
        if categoria_target:
            self.show_category(categoria_target)
    # -------------------------------------------------------------------------

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
        container.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # La barra verticale ora apparirà SOLO quando realmente necessario
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
            
    def _adatta_altezza_dinamica(self, index):
        current_widget = self.stack.widget(index)
        if not current_widget:
            return

        # Impostiamo le policy senza forzare il layout immediatamente
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            # Usiamo Expanding per assicurare che prendano tutto lo spazio
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Usiamo un timer a 0ms: questo forza il ricalcolo nel ciclo di eventi successivo
        # dando tempo a Qt di completare la transizione del cambio pagina
        QTimer.singleShot(0, lambda: self._finalize_layout(current_widget))

    def _finalize_layout(self, widget):
        """Metodo di supporto per finalizzare il layout dopo il cambio pagina"""
        if not widget:
            return
        
        widget.updateGeometry()
        if widget.layout():
            widget.layout().activate()
            # Questo forza il ridisegno dei figli
            widget.layout().update()
        
        self.stack.adjustSize()
        self.update()