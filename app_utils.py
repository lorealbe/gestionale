import re
from PySide6.QtWidgets import QAbstractScrollArea, QTableWidget

def is_blank(value: str | None) -> bool:
    return not str(value or "").strip()

def format_number(value, decimals: int = 2, thousands_sep: str = "'", decimal_sep: str = ",") -> str:
    try: num = float(value)
    except (TypeError, ValueError): num = 0.0
    return f"{num:,.{decimals}f}".replace(",", "_T_").replace(".", decimal_sep).replace("_T_", thousands_sep)

def format_eur(value, decimals: int = 2) -> str:
    return f"EUR {format_number(value, decimals)}"

def parse_decimal(raw_value, *, allow_zero: bool = True, allow_negative: bool = False) -> float | None:
    if isinstance(raw_value, (int, float)):
        num = float(raw_value)
    else:
        # Espressione regolare: mantiene solo numeri (\d), punti, virgole e il segno meno. Rimuove tutto il resto (spazi, €, ecc.)
        s = re.sub(r'[^\d\.,\-]', '', str(raw_value or ''))
        if not s: return None
        
        # Gestisce i conflitti tra formati europei (1.000,50) e americani (1,000.50) in una riga
        s = s.replace('.', '').replace(',', '.') if s.rfind(',') > s.rfind('.') else s.replace(',', '')
        
        try: num = float(s)
        except ValueError: return None
        
    if (num < 0 and not allow_negative) or (num == 0 and not allow_zero): 
        return None
    return num

def clear_treeview(tree) -> None:
    # Walrus operator (:=) esegue controllo e assegnazione in un solo colpo
    if children := tree.get_children(): tree.delete(*children)

class TabellaIsolata(QTableWidget):
    """
    QTableWidget che blocca la propagazione dello scroll alla pagina principale.
    Se il mouse è sopra la tabella, scorre solo la tabella.
    """
    def wheelEvent(self, event):
        super().wheelEvent(event)
        self.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        event.accept()  # Blocca la propagazione dello scroll alla QScrollArea genitore
    
from PySide6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QLineEdit, QPushButton, QMessageBox
from models import AziendaInfo, db

class ImpostazioniAziendaDialog(QDialog):
    def __init__(self, user_id, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.setWindowTitle("Impostazioni Azienda")
        self.resize(400, 250)
        self._build_ui()
        self.carica_dati()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        
        self.input_ragione_sociale = QLineEdit()
        self.input_partita_iva = QLineEdit()
        self.input_indirizzo = QLineEdit()
        
        form.addRow("Ragione Sociale:", self.input_ragione_sociale)
        form.addRow("Partita IVA:", self.input_partita_iva)
        form.addRow("Indirizzo Sede:", self.input_indirizzo)
        
        layout.addLayout(form)
        
        btn_salva = QPushButton("💾 Salva Impostazioni")
        btn_salva.setStyleSheet("background-color: #2c3e50; color: white; font-weight: bold; padding: 8px;")
        btn_salva.clicked.connect(self.salva_dati)
        layout.addWidget(btn_salva)

    def carica_dati(self):
        info = AziendaInfo.get_or_none(user=self.user_id)
        if info:
            self.input_ragione_sociale.setText(info.ragione_sociale or "")
            self.input_partita_iva.setText(info.partita_iva or "")
            self.input_indirizzo.setText(info.indirizzo or "")

    def salva_dati(self):
        with db.atomic():
            info, created = AziendaInfo.get_or_create(user=self.user_id)
            info.ragione_sociale = self.input_ragione_sociale.text().strip()
            info.partita_iva = self.input_partita_iva.text().strip()
            info.indirizzo = self.input_indirizzo.text().strip()
            info.save()
            
        QMessageBox.information(self, "Successo", "Dati aziendali salvati correttamente!")
        self.accept()