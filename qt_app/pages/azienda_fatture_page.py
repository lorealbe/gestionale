from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from qt_app.pages.azienda_movimenti_page import AziendaMovimentiPage
from qt_app.pages.azienda_nuovo_movimento_page import AziendaNuovoMovimentoPage
from qt_app.pages.azienda_prodotti_page import AziendaProdottiPage


class AziendaFatturePage(QWidget):
    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = int(user_id)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        tabs = QTabWidget(self)
        self.tabs = tabs

        self.page_storico_movimenti = AziendaMovimentiPage(self.user_id, tabs)
        self.page_storico_prodotti = AziendaProdottiPage(self.user_id, tabs)
        self.page_nuovo_movimento = AziendaNuovoMovimentoPage(self.user_id, tabs)

        tabs.addTab(self.page_storico_movimenti, "Storico movimenti")
        tabs.addTab(self.page_storico_prodotti, "Storico prodotti")
        tabs.addTab(self.page_nuovo_movimento, "Nuovo movimento")

        self.page_storico_movimenti.edit_movimento_requested.connect(self._apri_modifica_movimento)
        self.page_storico_movimenti.movimenti_changed.connect(self._ricarica_tabelle_fatture)
        self.page_nuovo_movimento.movimento_saved.connect(self._on_movimento_salvato)

        layout.addWidget(tabs)

    def _apri_modifica_movimento(self, movimento_id: int):
        self.tabs.setCurrentWidget(self.page_nuovo_movimento)
        self.page_nuovo_movimento.carica_movimento_in_modifica(int(movimento_id))

    def _ricarica_tabelle_fatture(self):
        self.page_storico_movimenti.carica_movimenti(show_errors=False)
        self.page_storico_prodotti.carica_storico_prodotti(show_errors=False)

    def _on_movimento_salvato(self, _movimento_id: int):
        self._ricarica_tabelle_fatture()
        self.tabs.setCurrentWidget(self.page_storico_movimenti)
