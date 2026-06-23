from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from qt_app.pages.azienda_fatture_page import AziendaFatturePage
from qt_app.pages.azienda_report_page import AziendaReportPage


class AziendaPage(QWidget):
    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = int(user_id)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        tabs = QTabWidget(self)
        tabs.addTab(AziendaReportPage(self.user_id, tabs), "Report Azienda")
        tabs.addTab(AziendaFatturePage(self.user_id, tabs), "Fatture")
        
        layout.addWidget(tabs)