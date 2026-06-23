from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget, QLabel

from qt_app.pages.azienda_animali_page import AziendaAnimaliPage
from qt_app.pages.zootecnia_carne_page import ZootecniaCarnePage
from qt_app.pages.zootecnia_latte_page import ZootecniaLattePage


class ZootecniaPage(QWidget):
    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = int(user_id)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        # HEADER
        header_layout = QVBoxLayout()
        header_layout.setSpacing(2)
        titolo = QLabel("🐄 Gestione Zootecnia e Allevamento")
        titolo.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        sottotitolo = QLabel("Gestisci i gruppi di animali, la produzione di latte e la vendita di carne.")
        sottotitolo.setStyleSheet("font-size: 14px; color: #7f8c8d;")
        header_layout.addWidget(titolo)
        header_layout.addWidget(sottotitolo)
        layout.addLayout(header_layout)

        self.tabs = QTabWidget(self)
        self.tabs.setStyleSheet("QTabWidget::pane { border: 1px solid #ccc; border-radius: 4px; background-color: white; }")
        
        self.page_animali = AziendaAnimaliPage(self.user_id, self.tabs)
        self.page_latte = ZootecniaLattePage(self.user_id, self.tabs)
        self.page_carne = ZootecniaCarnePage(self.user_id, self.tabs)

        # In Zootecnia la tabella gruppi deve essere piu leggibile rispetto al default.
        self.page_animali.table_animali.setMinimumHeight(420)

        self.tabs.addTab(self.page_animali, "Gruppi animali")
        self.tabs.addTab(self.page_latte, "Produzione Latte")
        self.tabs.addTab(self.page_carne, "Produzione Carne")

        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.page_latte.produzione_changed.connect(self._on_produzione_changed)
        self.page_carne.produzione_changed.connect(self._on_produzione_changed)

        layout.addWidget(self.tabs, 1)

    def _on_tab_changed(self, _index):
        self.page_latte.aggiorna_lista_gruppi_latte()
        self.page_carne.aggiorna_lista_gruppi_carne()

    def _on_produzione_changed(self):
        self.page_animali.carica_report_animali(show_errors=False)
        self.page_latte.aggiorna_lista_gruppi_latte()
        self.page_carne.aggiorna_lista_gruppi_carne()