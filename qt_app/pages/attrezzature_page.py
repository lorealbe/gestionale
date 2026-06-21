from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class AttrezzaturePage(QWidget):
    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = int(user_id)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Area Attrezzature")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        title.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        subtitle = QLabel(
            "Sezione pronta per inventario, manutenzione e scadenze delle attrezzature. "
            "La migrazione funzionale verra completata nei prossimi step."
        )
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)
