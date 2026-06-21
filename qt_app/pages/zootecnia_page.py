from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

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
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.tabs = QTabWidget(self)
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
