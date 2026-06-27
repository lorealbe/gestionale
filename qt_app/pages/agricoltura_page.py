import json
import urllib.request
import threading
from datetime import datetime
from collections import defaultdict
import pyqtgraph as pg

from PySide6.QtCore import Qt, QObject, Slot, Signal, QTimer, QDate
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton, QSplitter,
    QInputDialog, QMessageBox, QListWidget, QListWidgetItem, QTabWidget,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QFormLayout,
    QLineEdit, QDateEdit, QDoubleSpinBox, QSpinBox, QAbstractItemView, QDialog, 
    QDialogButtonBox, QCheckBox, QSizePolicy, QToolTip
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel

from app_utils import TabellaIsolata
from models import CampoAgricolo, StoricoColtura, EconomiaColtura, RegistroMeteo


# ==========================================
# FINESTRE DI DIALOGO VINCOLATE E FINANZIARIE
# ==========================================

class StoricoMeteoDialog(QDialog):
    def __init__(self, user_id, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registro delle Precipitazioni")
        self.setMinimumSize(700, 450)
        self.user_id = user_id
        
        layout = QVBoxLayout(self)
        titolo = QLabel("Storico delle Piogge Rilevate (mm/giorno)")
        titolo.setStyleSheet("font-size: 16px; font-weight: bold; color: #2c3e50; margin-bottom: 10px;")
        layout.addWidget(titolo)
        
        self.plot_meteo = pg.PlotWidget()
        self.plot_meteo.setBackground('w')
        self.plot_meteo.showGrid(x=False, y=True, alpha=0.3)
        self.plot_meteo.setMouseEnabled(x=False, y=False)
        self.plot_meteo.setMenuEnabled(False)
        layout.addWidget(self.plot_meteo)
        
        self._carica_grafico()
        
    def _carica_grafico(self):
        dati = list(RegistroMeteo.select().where(RegistroMeteo.user == self.user_id).order_by(RegistroMeteo.data_rilevazione.asc()).limit(30).dicts())
            
        if not dati:
            self.plot_meteo.setTitle("Nessun dato pluviometrico registrato finora.", color='#7f8c8d', size='12pt')
            return
            
        x_labels, y_values = [], []
        for d in dati:
            try: d_fmt = datetime.strptime(d['data_rilevazione'], "%Y-%m-%d").strftime("%d/%m")
            except: d_fmt = d['data_rilevazione']
            x_labels.append(d_fmt)
            y_values.append(float(d['pioggia_mm']))
            
        x_pos = list(range(len(x_labels)))
        ticks = [list(zip(x_pos, x_labels))]
        
        ax = self.plot_meteo.getAxis('bottom')
        ax.setTicks(ticks)
        
        bar_chart = pg.BarGraphItem(x=x_pos, height=y_values, width=0.4, brush='#3498db', pen='w')
        self.plot_meteo.addItem(bar_chart)
        self.plot_meteo.setXRange(-0.5, len(x_pos) - 0.5, padding=0)
        if y_values:
            self.plot_meteo.setYRange(0, max(y_values) * 1.2 if max(y_values) > 0 else 5, padding=0)


class GestioneEconomicaDialog(QDialog):
    def __init__(self, storico_id, user_id, titolo_coltura, parent=None):
        super().__init__(parent)
        self.storico_id = storico_id
        self.user_id = user_id
        self.setWindowTitle(f"Bilancio Economico: {titolo_coltura}")
        self.setMinimumSize(750, 550)
        
        layout = QVBoxLayout(self)
        
        kpi_frame = QFrame()
        kpi_frame.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        kpi_layout = QHBoxLayout(kpi_frame)
        
        self.lbl_spese = QLabel("Spese Totali: 0.00 €")
        self.lbl_spese.setStyleSheet("color: #dc3545; font-size: 16px; font-weight: bold;")
        self.lbl_ricavi = QLabel("Ricavi Totali: 0.00 €")
        self.lbl_ricavi.setStyleSheet("color: #28a745; font-size: 16px; font-weight: bold;")
        self.lbl_utile = QLabel("Utile Netto: 0.00 €")
        self.lbl_utile.setStyleSheet("color: #007bff; font-size: 18px; font-weight: 900;")
        
        kpi_layout.addWidget(self.lbl_spese)
        kpi_layout.addWidget(self.lbl_ricavi)
        kpi_layout.addWidget(self.lbl_utile)
        layout.addWidget(kpi_frame)
        
        self.table = TabellaIsolata(0, 5)
        self.table.setHorizontalHeaderLabels(["Data", "Tipo", "Categoria", "Descrizione", "Importo"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)
        
        btn_elimina = QPushButton("Elimina Voce Selezionata")
        btn_elimina.setStyleSheet("background-color: #dc3545; color: white; padding: 5px; border-radius: 3px;")
        btn_elimina.clicked.connect(self._elimina_voce)
        layout.addWidget(btn_elimina)
        
        form_frame = QFrame()
        form_frame.setStyleSheet("background-color: white; border: 1px solid #ccc; border-radius: 5px;")
        form_layout = QFormLayout(form_frame)
        form_layout.setContentsMargins(15, 15, 15, 15)
        
        lbl_titolo_form = QLabel("Aggiungi Nuova Spesa / Ricavo")
        lbl_titolo_form.setStyleSheet("font-weight: bold; font-size: 14px;")
        form_layout.addRow(lbl_titolo_form)
        
        self.combo_tipo = QComboBox()
        self.combo_tipo.addItems(["SPESA", "RICAVO"])
        self.combo_tipo.setStyleSheet("padding: 5px; font-weight: bold;")
        self.combo_tipo.currentTextChanged.connect(self._aggiorna_categorie)
        
        self.combo_categoria = QComboBox()
        self._aggiorna_categorie("SPESA")
        
        self.input_desc = QLineEdit()
        self.input_desc.setPlaceholderText("Es: Fattura Consorzio Agrario, Lavoro contoterzista...")
        
        self.input_importo = QDoubleSpinBox()
        self.input_importo.setRange(0.01, 1000000)
        self.input_importo.setSuffix(" €")
        self.input_importo.setDecimals(2)
        
        self.input_data = QDateEdit(QDate.currentDate())
        self.input_data.setCalendarPopup(True)
        self.input_data.setDisplayFormat("dd/MM/yyyy")
        
        h_box_importo_data = QHBoxLayout()
        h_box_importo_data.addWidget(self.input_importo)
        h_box_importo_data.addWidget(self.input_data)
        
        form_layout.addRow("Tipo Movimento:", self.combo_tipo)
        form_layout.addRow("Categoria Spesa/Ricavo:", self.combo_categoria)
        form_layout.addRow("Descrizione (Opzionale):", self.input_desc)
        form_layout.addRow("Importo e Data:", h_box_importo_data)
        
        btn_aggiungi = QPushButton("Registra a Bilancio")
        btn_aggiungi.setStyleSheet("background-color: #28a745; color: white; padding: 10px; font-weight: bold; border-radius: 5px;")
        btn_aggiungi.clicked.connect(self._aggiungi_voce)
        form_layout.addRow("", btn_aggiungi)
        
        layout.addWidget(form_frame)
        self._carica_dati()
        
    def _aggiorna_categorie(self, tipo):
        self.combo_categoria.clear()
        if tipo == "SPESA":
            self.combo_tipo.setStyleSheet("color: #dc3545; font-weight: bold;")
            self.combo_categoria.addItems(["Sementi/Piantine", "Concimi/Fertilizzanti", "Fitofarmaci", "Gasolio/Energia", "Manodopera", "Lavorazioni Conto Terzi", "Irrigazione", "Noleggi", "Altro Costo"])
        else:
            self.combo_tipo.setStyleSheet("color: #28a745; font-weight: bold;")
            self.combo_categoria.addItems(["Vendita Raccolto", "Contributi/PAC", "Assicurazioni (Risarcimenti)", "Altro Ricavo"])
            
    def _carica_dati(self):
        self.table.setRowCount(0)
        tot_spese = 0.0
        tot_ricavi = 0.0
        
        movimenti = list(EconomiaColtura.select().where((EconomiaColtura.storico == self.storico_id) & (EconomiaColtura.user == self.user_id)).order_by(EconomiaColtura.data_operazione.asc()).dicts())
        
        for row_idx, mov in enumerate(movimenti):
            self.table.insertRow(row_idx)
            try: d_fmt = datetime.strptime(mov['data_operazione'], "%Y-%m-%d").strftime("%d/%m/%Y")
            except Exception: d_fmt = mov['data_operazione']
                
            item_data = QTableWidgetItem(d_fmt)
            item_data.setData(Qt.UserRole, mov['id'])
            item_tipo = QTableWidgetItem(mov['tipo'])
            item_tipo.setTextAlignment(Qt.AlignCenter)
            item_importo = QTableWidgetItem(f"{mov['importo']:,.2f} €")
            item_importo.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            
            if mov['tipo'] == "SPESA":
                item_tipo.setForeground(Qt.red)
                item_importo.setForeground(Qt.red)
                tot_spese += mov['importo']
            else:
                item_tipo.setForeground(Qt.darkGreen)
                item_importo.setForeground(Qt.darkGreen)
                tot_ricavi += mov['importo']
                
            self.table.setItem(row_idx, 0, item_data)
            self.table.setItem(row_idx, 1, item_tipo)
            self.table.setItem(row_idx, 2, QTableWidgetItem(mov['categoria']))
            self.table.setItem(row_idx, 3, QTableWidgetItem(mov['descrizione'] or ""))
            self.table.setItem(row_idx, 4, item_importo)
            
        self.lbl_spese.setText(f"Spese Totali: {tot_spese:,.2f} €")
        self.lbl_ricavi.setText(f"Ricavi Totali: {tot_ricavi:,.2f} €")
        utile = tot_ricavi - tot_spese
        colore_utile = "#28a745" if utile >= 0 else "#dc3545"
        self.lbl_utile.setText(f"Utile Netto: {utile:,.2f} €")
        self.lbl_utile.setStyleSheet(f"color: {colore_utile}; font-size: 18px; font-weight: 900;")
        
    def _aggiungi_voce(self):
        tipo = self.combo_tipo.currentText()
        cat = self.combo_categoria.currentText()
        desc = self.input_desc.text().strip()
        importo = self.input_importo.value()
        data_op = self.input_data.date().toString("yyyy-MM-dd")
        now_text = datetime.now().isoformat(timespec="seconds")
        
        try:
            EconomiaColtura.create(user=self.user_id, storico=self.storico_id, tipo=tipo, categoria=cat, descrizione=desc, importo=importo, data_operazione=data_op, created_at=now_text)
            self.input_desc.clear()
            self.input_importo.setValue(0.01)
            self._carica_dati()
        except Exception as e: QMessageBox.critical(self, "Errore", f"Impossibile salvare il movimento: {e}")
            
    def _elimina_voce(self):
        riga = self.table.currentRow()
        if riga < 0: return
        r_id = self.table.item(riga, 0).data(Qt.UserRole)
        risposta = QMessageBox.question(self, "Conferma", "Vuoi eliminare questa voce di bilancio?", QMessageBox.Yes | QMessageBox.No)
        if risposta == QMessageBox.Yes:
            try:
                EconomiaColtura.delete().where(EconomiaColtura.id == r_id, EconomiaColtura.user == self.user_id).execute()
                self._carica_dati()
            except Exception: pass


class NuovoCampoDialog(QDialog):
    def __init__(self, area_ha, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Salva Nuovo Appezzamento")
        self.setMinimumWidth(350)
        layout = QVBoxLayout(self)
        lbl_info = QLabel(f"Area misurata dal satellite: <b>{area_ha:.2f} ettari</b>")
        layout.addWidget(lbl_info)
        
        form = QFormLayout()
        self.input_nome = QLineEdit()
        self.input_nome.setPlaceholderText("Es: Campo di sotto, Uliveto Nord...")
        self.combo_tipo = QComboBox()
        self.combo_tipo.addItems(["Seminativo", "Ortaggi", "Uliveto", "Vigneto", "Frutteto"])
        self.combo_tipo.currentTextChanged.connect(self._toggle_campi_permanenti)
        self.input_varieta = QLineEdit()
        self.input_varieta.setPlaceholderText("Es: Leccino, Sangiovese, Fuji...")
        self.input_varieta.setEnabled(False)
        self.input_piante = QSpinBox()
        self.input_piante.setRange(0, 100000)
        self.input_piante.setSuffix(" piante")
        self.input_piante.setEnabled(False)
        self.input_anno = QSpinBox()
        self.input_anno.setRange(1900, QDate.currentDate().year())
        self.input_anno.setValue(QDate.currentDate().year())
        self.input_anno.setEnabled(False)
        
        form.addRow("Nome Campo:", self.input_nome)
        form.addRow("Destinazione:", self.combo_tipo)
        form.addRow("Varietà Dominante:", self.input_varieta)
        form.addRow("Numero Piante:", self.input_piante)
        form.addRow("Anno Impianto:", self.input_anno)
        layout.addLayout(form)
        
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        
    def _toggle_campi_permanenti(self, tipo):
        is_permanente = tipo in ["Uliveto", "Vigneto", "Frutteto"]
        self.input_varieta.setEnabled(is_permanente)
        self.input_anno.setEnabled(is_permanente)
        if tipo in ["Uliveto", "Frutteto"]: self.input_piante.setEnabled(True)
        else: self.input_piante.setEnabled(False); self.input_piante.setValue(0)
        if not is_permanente: self.input_varieta.clear()

    def get_dati(self):
        return (self.input_nome.text().strip(), self.combo_tipo.currentText(), self.input_varieta.text().strip(), self.input_piante.value(), self.input_anno.value())


class ModificaDettagliCampoDialog(QDialog):
    def __init__(self, nome, tipo, varieta, piante, anno, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Modifica Informazioni Appezzamento")
        self.setMinimumWidth(350)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        
        self.input_nome = QLineEdit(nome)
        self.input_varieta = QLineEdit(varieta if varieta else "")
        self.input_piante = QSpinBox()
        self.input_piante.setRange(0, 100000)
        self.input_piante.setSuffix(" piante")
        self.input_piante.setValue(piante if piante else 0)
        self.input_anno = QSpinBox()
        self.input_anno.setRange(1900, QDate.currentDate().year())
        self.input_anno.setValue(anno if anno else QDate.currentDate().year())
        
        form.addRow("Nome Campo:", self.input_nome)
        if tipo in ["Uliveto", "Vigneto", "Frutteto"]:
            form.addRow("Varietà Dominante:", self.input_varieta)
            if tipo in ["Uliveto", "Frutteto"]: form.addRow("Numero Piante:", self.input_piante)
            form.addRow("Anno Impianto:", self.input_anno)
        layout.addLayout(form)
        
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        
    def get_dati(self):
        return (self.input_nome.text().strip(), self.input_varieta.text().strip(), self.input_piante.value(), self.input_anno.value())


class RegistraRaccoltoDialog(QDialog):
    def __init__(self, spese_totali, parent=None):
        super().__init__(parent)
        self.spese_totali = spese_totali
        self.setWindowTitle("Registra Raccolto e Break-Even")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        
        info_frame = QFrame()
        info_frame.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        info_layout = QVBoxLayout(info_frame)
        
        lbl_spesa_titolo = QLabel(f"Costi di produzione sostenuti: <b>{spese_totali:,.2f} €</b>")
        lbl_spesa_titolo.setStyleSheet("font-size: 14px;")
        
        self.lbl_breakeven = QLabel("Prezzo di Pareggio: <b>---</b>")
        self.lbl_breakeven.setStyleSheet("font-size: 16px; color: #d35400;")
        
        self.lbl_consiglio = QLabel("Inserisci i quintali raccolti per calcolare il limite minimo di vendita.")
        self.lbl_consiglio.setStyleSheet("color: #7f8c8d; font-size: 12px; font-style: italic;")
        self.lbl_consiglio.setWordWrap(True)
        
        info_layout.addWidget(lbl_spesa_titolo)
        info_layout.addWidget(self.lbl_breakeven)
        info_layout.addWidget(self.lbl_consiglio)
        layout.addWidget(info_frame)
        
        form = QFormLayout()
        
        self.input_data = QDateEdit()
        self.input_data.setCalendarPopup(True)
        self.input_data.setDisplayFormat("dd/MM/yyyy")
        self.input_data.setDate(QDate.currentDate())
        
        self.input_resa = QDoubleSpinBox()
        self.input_resa.setRange(0.00, 100000.00)
        self.input_resa.setSuffix(" Quintali")
        self.input_resa.setDecimals(2)
        self.input_resa.setValue(0.00)
        
        self.input_resa.valueChanged.connect(self._calcola_breakeven)
        
        form.addRow("Data Raccolto:", self.input_data)
        form.addRow("Resa Totale:", self.input_resa)
        layout.addLayout(form)
        
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        
    def _calcola_breakeven(self, resa):
        if self.spese_totali == 0:
            self.lbl_breakeven.setText("Prezzo di Pareggio: <b>Nessuna spesa registrata</b>")
            self.lbl_consiglio.setText("Non avendo inserito spese nel Bilancio, il costo per quintale risulta 0 €.")
            return
            
        if resa > 0:
            costo_quintale = self.spese_totali / resa
            self.lbl_breakeven.setText(f"Costo di Produzione: <b style='color:#dc3545;'>{costo_quintale:,.2f} € / q.le</b>")
            self.lbl_consiglio.setText(f"Per non andare in perdita, dovrai vendere il raccolto a un prezzo superiore a <b>{costo_quintale:,.2f} €</b> al quintale.")
        else:
            self.lbl_breakeven.setText("Prezzo di Pareggio: <b>---</b>")
            self.lbl_consiglio.setText("Inserisci i quintali raccolti per calcolare il limite minimo di vendita.")
            
    def get_dati(self):
        return self.input_data.date().toString("yyyy-MM-dd"), self.input_resa.value()


class ModificaColturaDialog(QDialog):
    def __init__(self, coltura, data_sem, data_rac, resa, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Modifica Dati Coltura")
        self.setMinimumWidth(350)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        
        self.input_coltura = QComboBox()
        self.input_coltura.setEditable(True)
        self.input_coltura.addItems([
            "Grano Duro", "Grano Tenero", "Mais", "Soia", 
            "Erba Medica", "Girasole", "Orzo", "Avena", 
            "Pomodoro", "Patata", "Zucchina", "Prato Stabile", 
            "Raccolta Olive", "Vendemmia", "Raccolta Frutta"
        ])
        self.input_coltura.setCurrentText(coltura)
        
        self.input_data_sem = QDateEdit()
        self.input_data_sem.setCalendarPopup(True)
        self.input_data_sem.setDisplayFormat("dd/MM/yyyy")
        self.input_data_sem.setDate(QDate.fromString(data_sem, "yyyy-MM-dd") if data_sem else QDate.currentDate())
        
        self.chk_concluso = QCheckBox("Ciclo Concluso (Raccolto effettuato)")
        
        self.input_data_rac = QDateEdit()
        self.input_data_rac.setCalendarPopup(True)
        self.input_data_rac.setDisplayFormat("dd/MM/yyyy")
        
        self.input_resa = QDoubleSpinBox()
        self.input_resa.setRange(0, 100000)
        self.input_resa.setSuffix(" Quintali")
        self.input_resa.setDecimals(2)
        
        if data_rac:
            self.chk_concluso.setChecked(True)
            self.input_data_rac.setDate(QDate.fromString(data_rac, "yyyy-MM-dd"))
            self.input_resa.setValue(float(resa) if resa else 0.0)
            self.input_data_rac.setEnabled(True)
            self.input_resa.setEnabled(True)
        else:
            self.chk_concluso.setChecked(False)
            self.input_data_rac.setDate(QDate.currentDate())
            self.input_resa.setValue(0.0)
            self.input_data_rac.setEnabled(False)
            self.input_resa.setEnabled(False)
            
        self.chk_concluso.toggled.connect(self.input_data_rac.setEnabled)
        self.chk_concluso.toggled.connect(self.input_resa.setEnabled)
        
        form.addRow("Coltura/Annata:", self.input_coltura)
        form.addRow("Data Avvio Ciclo:", self.input_data_sem)
        form.addRow(self.chk_concluso)
        form.addRow("Data Raccolto:", self.input_data_rac)
        form.addRow("Resa:", self.input_resa)
        layout.addLayout(form)
        
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        
    def get_dati(self):
        col = self.input_coltura.currentText().strip()
        d_sem = self.input_data_sem.date().toString("yyyy-MM-dd")
        if self.chk_concluso.isChecked():
            d_rac = self.input_data_rac.date().toString("yyyy-MM-dd")
            resa = self.input_resa.value()
        else:
            d_rac = None
            resa = 0.0
        return col, d_sem, d_rac, resa


# ==========================================
# CLASSI DELLA MAPPA (Javascript Bridge)
# ==========================================
class WebBridge(QObject):
    def __init__(self, parent_page):
        super().__init__()
        self.parent_page = parent_page

    @Slot(str, float)
    def ricevi_disegno(self, geojson_str, area_ha):
        self.parent_page.gestisci_nuovo_disegno(geojson_str, area_ha)

    @Slot(int, str, float)
    def aggiorna_disegno(self, campo_id, geojson_str, area_ha):
        self.parent_page.gestisci_aggiornamento_disegno(campo_id, geojson_str, area_ha)


class AgricolturaPage(QWidget):
    
    segnale_meteo = Signal(str, float, float, float)
    
    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self._mappa_pronta = False 
        
        self.segnale_meteo.connect(self._imposta_testo_meteo)
        
        self.channel = QWebChannel()
        self.bridge = WebBridge(self)
        self.channel.registerObject("bridge", self.bridge)

        self.dizionario_colture = {
            "Cereali": ["Grano Duro", "Grano Tenero", "Mais", "Orzo", "Avena", "Sorgo"],
            "Ortaggi": ["Pomodoro", "Patata", "Cipolla", "Zucchina", "Insalata", "Carota", "Melone", "Cocomero", "Peperone", "Melanzana", "Aglio", "Finocchio"],
            "Leguminose": ["Soia", "Fava", "Cece", "Pisello", "Lenticchia", "Fagiolo"],
            "Foraggere": ["Erba Medica", "Prato Stabile", "Loietto"],
            "Oleaginose": ["Girasole", "Colza"]
        }

        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)

        header_layout = QVBoxLayout()
        titolo = QLabel("Gestione Campi, Colture e Appezzamenti")
        titolo.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        sottotitolo = QLabel("Disegna i campi, analizza le rese e consulta il meteo locale.")
        sottotitolo.setStyleSheet("font-size: 14px; color: #7f8c8d;")
        header_layout.addWidget(titolo)
        header_layout.addWidget(sottotitolo)
        main_layout.addLayout(header_layout)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane { border: 1px solid #ccc; border-radius: 4px; }")
        main_layout.addWidget(self.tabs, 1)

        self.tab_mappa = QWidget()
        self._build_tab_mappa()
        self.tabs.addTab(self.tab_mappa, "📍 Mappa Satellitare")

        self.tab_quaderno = QWidget()
        self._build_tab_quaderno()
        self.tabs.addTab(self.tab_quaderno, "📖 Quaderno di Campagna")

        self.tab_statistiche = QWidget()
        self._build_tab_statistiche()
        self.tabs.addTab(self.tab_statistiche, "📊 Statistiche e Rese")

        self.tabs.currentChanged.connect(self._on_tab_changed)


    # ==========================================
    # COSTRUZIONE INTERFACCIA MAPPA
    # ==========================================
    def _build_tab_mappa(self):
        layout = QVBoxLayout(self.tab_mappa)
        layout.setContentsMargins(10, 10, 10, 10)
        
        splitter = QSplitter(Qt.Horizontal)
        
        mappa_frame = QFrame()
        mappa_frame.setStyleSheet("background-color: white; border-radius: 8px; border: 1px solid #ccc;")
        mappa_layout = QVBoxLayout(mappa_frame)
        mappa_layout.setContentsMargins(2, 2, 2, 2)
        
        self.web_view = QWebEngineView()
        self.web_view.page().setWebChannel(self.channel)
        self.web_view.setHtml(self._get_mappa_html())
        self.web_view.loadFinished.connect(self._on_mappa_caricata)
        mappa_layout.addWidget(self.web_view)
        
        splitter.addWidget(mappa_frame)

        control_frame = QFrame()
        control_frame.setMinimumWidth(320)
        control_layout = QVBoxLayout(control_frame)
        
        self.meteo_frame = QFrame()
        self.meteo_frame.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.meteo_frame.setStyleSheet("background-color: #e0f7fa; border: 1px solid #17a2b8; border-radius: 8px; padding: 10px;")
        meteo_layout = QVBoxLayout(self.meteo_frame)
        meteo_layout.setContentsMargins(10, 10, 10, 10)
        
        self.lbl_meteo_titolo = QLabel("🌤️ Meteo a 3 Giorni")
        self.lbl_meteo_titolo.setStyleSheet("font-weight: bold; font-size: 14px; color: #006064; border: none; margin-bottom: 5px;")
        
        self.lbl_meteo_dati = QLabel("Localizzazione campi in corso...")
        self.lbl_meteo_dati.setStyleSheet("font-size: 13px; color: #006064; border: none;")
        self.lbl_meteo_dati.setWordWrap(True)
        
        self.btn_storico_meteo = QPushButton("📊 Storico Piogge")
        self.btn_storico_meteo.setStyleSheet("background-color: #008cba; color: white; border-radius: 4px; padding: 5px; font-weight: bold;")
        self.btn_storico_meteo.clicked.connect(self._apri_storico_meteo)
        
        meteo_layout.addWidget(self.lbl_meteo_titolo)
        meteo_layout.addWidget(self.lbl_meteo_dati)
        meteo_layout.addWidget(self.btn_storico_meteo)
        control_layout.addWidget(self.meteo_frame)
        
        lbl_campi = QLabel("I tuoi Appezzamenti")
        lbl_campi.setStyleSheet("font-size: 18px; font-weight: bold; margin-top: 10px; margin-bottom: 5px;")
        control_layout.addWidget(lbl_campi)
        
        self.list_campi = QListWidget()
        self.list_campi.setStyleSheet("font-size: 14px; border: 1px solid #ddd; border-radius: 5px;")
        self.list_campi.itemSelectionChanged.connect(self._centra_mappa_su_selezionato)
        control_layout.addWidget(self.list_campi)
        
        btn_layout_mappa = QHBoxLayout()
        
        self.btn_modifica_info = QPushButton("Modifica Info")
        self.btn_modifica_info.setStyleSheet("background-color: #ffc107; color: black; padding: 10px; font-weight: bold; border-radius: 5px;")
        self.btn_modifica_info.clicked.connect(self._modifica_info_campo_selezionato)
        btn_layout_mappa.addWidget(self.btn_modifica_info)
        
        self.btn_elimina = QPushButton("Elimina")
        self.btn_elimina.setStyleSheet("background-color: #dc3545; color: white; padding: 10px; font-weight: bold; border-radius: 5px;")
        self.btn_elimina.clicked.connect(self._elimina_campo_selezionato)
        btn_layout_mappa.addWidget(self.btn_elimina)
        
        control_layout.addLayout(btn_layout_mappa)
        
        splitter.addWidget(control_frame)
        splitter.setSizes([700, 320])
        layout.addWidget(splitter)


    # ==========================================
    # COSTRUZIONE INTERFACCIA QUADERNO E BILANCIO
    # ==========================================
    def _build_tab_quaderno(self):
        layout = QVBoxLayout(self.tab_quaderno)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(20)

        selezione_layout = QHBoxLayout()
        lbl_sel = QLabel("Seleziona Appezzamento:")
        lbl_sel.setStyleSheet("font-weight: bold; font-size: 16px;")
        self.combo_campi = QComboBox()
        self.combo_campi.setStyleSheet("padding: 5px; font-size: 14px;")
        self.combo_campi.currentIndexChanged.connect(self._on_campo_quaderno_selezionato)
        
        selezione_layout.addWidget(lbl_sel)
        selezione_layout.addWidget(self.combo_campi, 1)
        layout.addLayout(selezione_layout)

        h_layout = QHBoxLayout()
        
        form_frame = QFrame()
        form_frame.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(15, 15, 15, 15)
        
        lbl_nuova = QLabel("Registra Nuovo Ciclo / Annata")
        lbl_nuova.setStyleSheet("font-weight: bold; font-size: 16px; margin-bottom: 10px;")
        form_layout.addWidget(lbl_nuova)
        
        f_layout = QFormLayout()
        
        self.combo_categoria = QComboBox()
        self.combo_categoria.currentIndexChanged.connect(self._aggiorna_colture_da_categoria)
        
        self.input_coltura = QComboBox()
        self.input_coltura.setEditable(True)
        
        self.input_data_semina = QDateEdit()
        self.input_data_semina.setCalendarPopup(True)
        self.input_data_semina.setDisplayFormat("dd/MM/yyyy")
        self.input_data_semina.setDate(QDate.currentDate())
        
        f_layout.addRow("Categoria Famiglia:", self.combo_categoria)
        f_layout.addRow("Coltura/Annata:", self.input_coltura)
        f_layout.addRow("Data Inizio:", self.input_data_semina)
        form_layout.addLayout(f_layout)
        
        btn_aggiungi = QPushButton("Avvia Ciclo")
        btn_aggiungi.setStyleSheet("background-color: #28a745; color: white; padding: 10px; font-weight: bold; border-radius: 5px; margin-top: 10px;")
        btn_aggiungi.clicked.connect(self._aggiungi_coltura)
        form_layout.addWidget(btn_aggiungi)
        form_layout.addStretch()
        
        h_layout.addWidget(form_frame, 1)

        tabella_frame = QVBoxLayout()
        self.table_colture = TabellaIsolata(0, 5)
        self.table_colture.setHorizontalHeaderLabels(["Ciclo/Coltura", "Data Inizio", "Data Raccolto", "Resa", "Stato"])
        self.table_colture.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_colture.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_colture.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_colture.setAlternatingRowColors(True)
        self.table_colture.setEditTriggers(QAbstractItemView.NoEditTriggers)
        
        tabella_frame.addWidget(self.table_colture)
        
        btn_layout = QHBoxLayout()
        
        self.btn_economia = QPushButton("Gestisci Bilancio (€)")
        self.btn_economia.setStyleSheet("background-color: #17a2b8; color: white; padding: 10px; font-weight: bold; border-radius: 5px;")
        self.btn_economia.clicked.connect(self._apri_gestione_economica)
        btn_layout.addWidget(self.btn_economia)
        
        btn_modifica = QPushButton("Modifica Base")
        btn_modifica.setStyleSheet("background-color: #ffc107; color: black; padding: 10px; font-weight: bold; border-radius: 5px;")
        btn_modifica.clicked.connect(self._modifica_coltura)
        btn_layout.addWidget(btn_modifica)
        
        btn_raccolto = QPushButton("Registra Raccolto")
        btn_raccolto.setStyleSheet("background-color: #007bff; color: white; padding: 10px; font-weight: bold; border-radius: 5px;")
        btn_raccolto.clicked.connect(self._registra_raccolto)
        btn_layout.addWidget(btn_raccolto)
        
        tabella_frame.addLayout(btn_layout)
        
        h_layout.addLayout(tabella_frame, 2)
        layout.addLayout(h_layout)

    # ==========================================
    # COSTRUZIONE INTERFACCIA STATISTICHE E REDDITIVITA'
    # ==========================================
    def _build_tab_statistiche(self):
        layout = QVBoxLayout(self.tab_statistiche)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(20)

        top_layout = QHBoxLayout()
        top_layout.setSpacing(20)
        
        self.card_area = QFrame()
        self.card_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.card_area.setStyleSheet("""
            QFrame { background-color: white; border-radius: 10px; border: 1px solid #e1e8ed; border-bottom: 4px solid #007bff; }
        """)
        card_layout = QVBoxLayout(self.card_area)
        card_layout.setContentsMargins(20, 20, 20, 20)
        
        self.lbl_kpi_titolo = QLabel("TOTALE TERRENO GESTITO")
        self.lbl_kpi_titolo.setStyleSheet("font-size: 12px; font-weight: bold; color: #7f8c8d; border: none;")
        self.lbl_kpi_valore = QLabel("0.00 ha")
        self.lbl_kpi_valore.setStyleSheet("font-size: 24px; font-weight: 800; color: #2c3e50; border: none;")
        
        card_layout.addWidget(self.lbl_kpi_titolo)
        card_layout.addWidget(self.lbl_kpi_valore)
        
        filtro_frame = QFrame()
        filtro_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        filtro_frame.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px; padding: 10px;")
        filtro_layout = QVBoxLayout(filtro_frame)
        filtro_layout.setContentsMargins(15, 15, 15, 15)
        
        lbl_filtro = QLabel("Seleziona Analisi:")
        lbl_filtro.setStyleSheet("font-weight: bold; font-size: 14px; border: none;")
        
        self.combo_stat_campi = QComboBox()
        self.combo_stat_campi.setStyleSheet("padding: 8px; font-size: 14px;")
        self.combo_stat_campi.currentIndexChanged.connect(self._aggiorna_grafico_agricoltura)
        
        self.combo_metrica = QComboBox()
        self.combo_metrica.setStyleSheet("padding: 8px; font-size: 14px; font-weight: bold; color: #2c3e50;")
        self.combo_metrica.addItems(["🌾 Resa Produttiva (Quintali)", "💶 Redditività Finanziaria (€ / ha)"])
        self.combo_metrica.currentIndexChanged.connect(self._aggiorna_grafico_agricoltura)
        
        filtro_layout.addWidget(lbl_filtro)
        filtro_layout.addWidget(self.combo_stat_campi)
        filtro_layout.addWidget(self.combo_metrica)
        
        top_layout.addWidget(self.card_area, 35)
        top_layout.addWidget(filtro_frame, 65)
        layout.addLayout(top_layout)

        self.plot_agri = pg.PlotWidget()
        self.plot_agri.setBackground('w')
        self.plot_agri.showGrid(x=False, y=True, alpha=0.3)
        self.plot_agri.setMouseEnabled(x=False, y=False)
        self.plot_agri.setMenuEnabled(False)
        self.plot_agri.hideButtons()
        
        layout.addWidget(self.plot_agri, 1)

        self.plot_agri.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.dati_barre = [] 
        self.hovered_bar_index = -1 
        
        self.custom_tooltip = pg.TextItem(color='w')
        self.custom_tooltip.setAnchor((0.5, 1.2)) 
        self.custom_tooltip.setZValue(100) 
        self.custom_tooltip.hide()
        self.plot_agri.addItem(self.custom_tooltip)

    def _get_colore_coltura(self, nome_coltura):
        if not nome_coltura: return "#2c3e50"
        name = nome_coltura.lower()
        if any(x in name for x in ["grano", "orzo", "avena", "sorgo"]): return "#f39c12"  
        elif "mais" in name: return "#d35400"  
        elif any(x in name for x in ["soia", "medica", "prato", "fava", "cece", "pisello", "lenticchia", "fagiolo"]): return "#27ae60"  
        elif any(x in name for x in ["girasole", "colza"]): return "#f1c40f"  
        elif any(x in name for x in ["pomodoro", "patata", "cipolla", "zucchina", "insalata", "carota", "peperone", "melanzana", "melone", "cocomero", "aglio", "finocchio"]): return "#e67e22" 
        elif "oliv" in name: return "#556b2f" 
        elif any(x in name for x in ["vendemmia", "uva", "vign"]): return "#8e44ad" 
        elif any(x in name for x in ["frutta", "frutteto", "mel", "per"]): return "#c0392b" 
        return "#2c3e50"     

    def _aggiorna_dati_statistiche(self):
        self.combo_stat_campi.blockSignals(True)
        self.combo_stat_campi.clear()
        self.combo_stat_campi.addItem("📊 Tutti i Campi", None)
        
        for c in CampoAgricolo.select().where(CampoAgricolo.user == self.user_id).order_by(CampoAgricolo.nome).dicts():
            icona = "🌳" if c['tipo_campo'] == "Uliveto" else "🍇" if c['tipo_campo'] == "Vigneto" else "🍎" if c['tipo_campo'] == "Frutteto" else "🥕" if c['tipo_campo'] == "Ortaggi" else "🌾"
            self.combo_stat_campi.addItem(f"{icona} {c['nome']}", c['id'])
            
        self.combo_stat_campi.blockSignals(False)
        self._aggiorna_grafico_agricoltura()

    def _aggiorna_grafico_agricoltura(self):
        campo_id = self.combo_stat_campi.currentData()
        is_finanziaria = (self.combo_metrica.currentIndex() == 1)
        
        self.plot_agri.clear()
        self.dati_barre.clear()
        self.hovered_bar_index = -1
        self.custom_tooltip.hide()
        self.plot_agri.addItem(self.custom_tooltip)

        campi = {c['id']: c for c in CampoAgricolo.select().where(CampoAgricolo.user == self.user_id).dicts()}
        if not campi: return
        
        storico = list(StoricoColtura.select().where((StoricoColtura.user == self.user_id) & (StoricoColtura.data_raccolto.is_null(False)) & (StoricoColtura.data_raccolto != '')).dicts())
        economia = list(EconomiaColtura.select().where(EconomiaColtura.user == self.user_id).dicts())

        if campo_id is None:
            if not is_finanziaria:
                tot_ettari = sum(c['area_ettari'] for c in campi.values())
                self.lbl_kpi_titolo.setText("TOTALE TERRENO GESTITO")
                self.lbl_kpi_valore.setText(f"{tot_ettari:.2f} ha")
                self.lbl_kpi_valore.setStyleSheet("font-size: 24px; font-weight: 800; color: #2c3e50; border: none;")
                
                rese = defaultdict(float)
                for s in storico: rese[s['coltura']] += float(s['resa_quintali'] or 0)
                dati = sorted(rese.items(), key=lambda x: x[1], reverse=True)[:10]
                titolo_grafico = "Classifica Globale Resa per Coltura (Quintali)"
            else:
                ricavi = sum(e['importo'] for e in economia if e['tipo'] == 'RICAVO')
                spese = sum(e['importo'] for e in economia if e['tipo'] == 'SPESA')
                utile_totale = ricavi - spese
                colore_utile = "#28a745" if utile_totale >= 0 else "#dc3545"
                self.lbl_kpi_titolo.setText("UTILE NETTO GLOBALE GENERATO")
                self.lbl_kpi_valore.setText(f"{utile_totale:,.2f} €")
                self.lbl_kpi_valore.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {colore_utile}; border: none;")
                
                eco_storico = defaultdict(lambda: {'ric': 0.0, 'spe': 0.0})
                for e in economia:
                    if e['tipo'] == 'RICAVO': eco_storico[e['storico_id']]['ric'] += e['importo']
                    else: eco_storico[e['storico_id']]['spe'] += e['importo']
                
                utile_coltura = defaultdict(float)
                ha_coltura = defaultdict(float)
                for s in storico:
                    utile = eco_storico[s['id']]['ric'] - eco_storico[s['id']]['spe']
                    utile_coltura[s['coltura']] += utile
                    ha_coltura[s['coltura']] += campi[s['campo_id']]['area_ettari']
                
                dati = sorted([(c, u / ha_coltura[c]) for c, u in utile_coltura.items() if ha_coltura[c] > 0], key=lambda x: x[1], reverse=True)[:10]
                titolo_grafico = "Redditività Globale per Ettaro (Euro / ha)"
        else:
            nome_campo = campi[campo_id]['nome']
            area = campi[campo_id]['area_ettari']
            storico_campo = [s for s in storico if s['campo_id'] == campo_id]
            storico_campo.sort(key=lambda x: x['data_raccolto'])
            
            if not is_finanziaria:
                self.lbl_kpi_titolo.setText(f"DIMENSIONE CAMPO: {nome_campo.upper()}")
                self.lbl_kpi_valore.setText(f"{area:.2f} ha")
                self.lbl_kpi_valore.setStyleSheet("font-size: 24px; font-weight: 800; color: #2c3e50; border: none;")
                
                dati = [(f"{s['coltura']} ({str(s['data_raccolto'])[:4]})", float(s['resa_quintali'] or 0)) for s in storico_campo]
                titolo_grafico = "Storico Temporale Rese dell'Appezzamento (Quintali)"
            else:
                eco_campo = [e for e in economia if any(s['id'] == e['storico_id'] for s in storico_campo)]
                ricavi = sum(e['importo'] for e in eco_campo if e['tipo'] == 'RICAVO')
                spese = sum(e['importo'] for e in eco_campo if e['tipo'] == 'SPESA')
                utile_totale = ricavi - spese
                colore_utile = "#28a745" if utile_totale >= 0 else "#dc3545"
                self.lbl_kpi_titolo.setText(f"UTILE NETTO CAMPO: {nome_campo.upper()}")
                self.lbl_kpi_valore.setText(f"{utile_totale:,.2f} €")
                self.lbl_kpi_valore.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {colore_utile}; border: none;")
                
                eco_storico = defaultdict(lambda: {'ric': 0.0, 'spe': 0.0})
                for e in eco_campo:
                    if e['tipo'] == 'RICAVO': eco_storico[e['storico_id']]['ric'] += e['importo']
                    else: eco_storico[e['storico_id']]['spe'] += e['importo']
                
                dati = [(f"{s['coltura']} ({str(s['data_raccolto'])[:4]})", (eco_storico[s['id']]['ric'] - eco_storico[s['id']]['spe']) / area) for s in storico_campo]
                titolo_grafico = "Storico Redditività per Ettaro (Euro / ha)"

        self.plot_agri.setTitle(titolo_grafico, color='#2c3e50', size='14pt')
        if not dati: return

        x_labels = [str(d[0]) for d in dati]
        y_values = [float(d[1] or 0) for d in dati]
        x_pos = list(range(len(x_labels)))
        ticks = [list(zip(x_pos, x_labels))]

        if y_values:
            massimo = max(y_values)
            minimo = min(y_values)
            min_y = min(0, minimo * 1.2) if minimo < 0 else 0
            self.plot_agri.setYRange(min_y, massimo * 1.2, padding=0)

        ax = self.plot_agri.getAxis('bottom')
        ax.setTicks(ticks)

        bar_width = 0.25
        colori_hex = [self._get_colore_coltura(label) for label in x_labels]
        brushes = [pg.mkBrush(colore) for colore in colori_hex]
        
        bar_chart = pg.BarGraphItem(x=x_pos, height=y_values, width=bar_width, brushes=brushes, pen='w')
        self.plot_agri.addItem(bar_chart)
        
        margine_destro = max(5.5, len(x_pos) - 0.5)
        self.plot_agri.setXRange(-0.5, margine_destro, padding=0)
        
        unita_misura = "€ / ha" if is_finanziaria else "q.li"
        
        for i, (label, val, colore) in enumerate(zip(x_labels, y_values, colori_hex)):
            x_min = x_pos[i] - bar_width / 2
            x_max = x_pos[i] + bar_width / 2
            self.dati_barre.append((x_min, x_max, val, label, colore, unita_misura))

    def _on_mouse_moved(self, pos):
        if self.plot_agri.sceneBoundingRect().contains(pos):
            mousePoint = self.plot_agri.plotItem.vb.mapSceneToView(pos)
            x, y = mousePoint.x(), mousePoint.y()
            
            indice_barra_hover = -1
            for i, (x_min, x_max, val_resa, label, colore, unita) in enumerate(self.dati_barre):
                if x_min <= x <= x_max and (0 <= y <= val_resa or val_resa <= y <= 0):
                    indice_barra_hover = i
                    break
            
            if indice_barra_hover != getattr(self, 'hovered_bar_index', -1):
                self.hovered_bar_index = indice_barra_hover
                
                if indice_barra_hover != -1:
                    x_min, x_max, val_resa, label, colore, unita = self.dati_barre[indice_barra_hover]
                    x_center = (x_min + x_max) / 2 
                    
                    html_testo = f"<div style='text-align: center;'><b style='font-size: 14px;'>{label}</b><br><span style='font-size: 13px;'>Valore: {val_resa:,.2f} {unita}</span></div>"
                    self.custom_tooltip.setHtml(html_testo)
                    self.custom_tooltip.fill = pg.mkBrush(colore)
                    self.custom_tooltip.border = pg.mkPen('w', width=1) 
                    self.custom_tooltip.setPos(x_center, val_resa)
                    self.custom_tooltip.show()
                else:
                    self.custom_tooltip.hide()
        else:
            if getattr(self, 'hovered_bar_index', -1) != -1:
                self.hovered_bar_index = -1
                self.custom_tooltip.hide()

    # ==========================================
    # LOGICA MAPPA E DB E INTEGRAZIONE METEO
    # ==========================================
    
    @Slot(str, float, float, float)
    def _imposta_testo_meteo(self, testo_html, pioggia_oggi, tmax_oggi, tmin_oggi):
        self.lbl_meteo_dati.setText(testo_html)
        oggi = QDate.currentDate().toString("yyyy-MM-dd")
        
        m = RegistroMeteo.get_or_none((RegistroMeteo.user == self.user_id) & (RegistroMeteo.data_rilevazione == oggi))
        if m:
            m.pioggia_mm, m.temperatura_max, m.temperatura_min = pioggia_oggi, tmax_oggi, tmin_oggi
            m.save()
        else:
            RegistroMeteo.create(user=self.user_id, data_rilevazione=oggi, pioggia_mm=pioggia_oggi, temperatura_max=tmax_oggi, temperatura_min=tmin_oggi)

    def _aggiorna_meteo_async(self):
        def task():
            lat, lon = 41.9028, 12.4964 
            campo = CampoAgricolo.select(CampoAgricolo.geojson).where(CampoAgricolo.user == self.user_id).first()
            if campo and campo.geojson:
                try:
                    dati = json.loads(campo.geojson)
                    coords = dati['geometry']['coordinates'][0][0] if dati.get('type') == 'Feature' else dati['coordinates'][0][0]
                    lon, lat = coords[0], coords[1]
                except Exception: pass
                
            try:
                url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=weathercode,precipitation_sum,temperature_2m_max,temperature_2m_min&timezone=Europe%2FRome"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = json.loads(response.read().decode())
                    daily = data['daily']
                    
                    icone = {0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️", 45: "🌫️", 48: "🌫️", 51: "🌦️", 53: "🌧️", 55: "🌧️", 61: "🌧️", 63: "🌧️", 65: "🌧️", 71: "❄️", 73: "❄️", 75: "❄️", 95: "⛈️", 96: "⛈️", 99: "⛈️"}
                    giorni = ["Oggi", "Domani", "Dopodomani"]
                    html_blocchi = "<table width='100%' style='text-align:center;'><tr>"
                    
                    for i in range(3):
                        codice = daily['weathercode'][i]
                        pioggia = daily['precipitation_sum'][i]
                        colore_pioggia = '#d35400' if pioggia > 0 else '#27ae60'
                        testo_pioggia = f"💧 {pioggia} mm" if pioggia > 0 else "💧 0 mm"
                        html_blocchi += f"<td style='padding: 5px; {'border-right: 1px solid #b2ebf2;' if i < 2 else ''}'><b>{giorni[i]}</b><br><span style='font-size: 26px;'>{icone.get(codice, '☁️')}</span><br><span style='font-size: 11px;'>{daily['temperature_2m_max'][i]}° / {daily['temperature_2m_min'][i]}°</span><br><span style='font-size: 12px; font-weight:bold; color: {colore_pioggia};'>{testo_pioggia}</span></td>"
                        
                    html_blocchi += "</tr></table>"
                    self.segnale_meteo.emit(html_blocchi, daily['precipitation_sum'][0], daily['temperature_2m_max'][0], daily['temperature_2m_min'][0])
            except Exception:
                self.segnale_meteo.emit("<div style='text-align:center;'>Impossibile scaricare le previsioni meteo.</div>", 0.0, 0.0, 0.0)

        threading.Thread(target=task, daemon=True).start()
        
    def _apri_storico_meteo(self):
        dialog = StoricoMeteoDialog(self.user_id, self)
        dialog.exec_()

    def _on_mappa_caricata(self):
        self._mappa_pronta = True
        if self.isVisible() and self.tabs.currentIndex() == 0:
            QTimer.singleShot(200, lambda: self._carica_campi_salvati(centra_mappa=True))
        else:
            self._carica_campi_salvati(centra_mappa=False)

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, '_mappa_pronta', False) and self.tabs.currentIndex() == 0:
            QTimer.singleShot(200, lambda: self._carica_campi_salvati(centra_mappa=True))
        self._aggiorna_combo_campi()
        self.lbl_meteo_dati.setText("Localizzazione campi in corso...")
        self._aggiorna_meteo_async()

    def _on_tab_changed(self, index):
        if index == 1: self._aggiorna_combo_campi()
        elif index == 2: self._aggiorna_dati_statistiche()
        elif index == 0 and getattr(self, '_mappa_pronta', False):
            QTimer.singleShot(200, lambda: self._carica_campi_salvati(centra_mappa=False))

    def _aggiorna_combo_campi(self):
        self.combo_campi.blockSignals(True)
        self.combo_campi.clear()
        for c in CampoAgricolo.select().where(CampoAgricolo.user == self.user_id).order_by(CampoAgricolo.nome).dicts():
            self.combo_campi.addItem(c['nome'], (c['id'], c['tipo_campo']))
        self.combo_campi.blockSignals(False)
        self._on_campo_quaderno_selezionato()

    def _on_campo_quaderno_selezionato(self):
        data = self.combo_campi.currentData()
        if data:
            c_id, tipo = data
            self.combo_categoria.blockSignals(True)
            self.combo_categoria.clear()
            
            if tipo in ["Uliveto", "Vigneto", "Frutteto"]:
                self.combo_categoria.addItem("Colture Permanenti")
                self.combo_categoria.setEnabled(False)
                self.input_coltura.clear()
                if tipo == "Uliveto": self.input_coltura.addItems([f"Raccolta Olive {QDate.currentDate().year()}"])
                elif tipo == "Vigneto": self.input_coltura.addItems([f"Vendemmia {QDate.currentDate().year()}"])
                elif tipo == "Frutteto": self.input_coltura.addItems([f"Raccolta Frutta {QDate.currentDate().year()}"])
            else:
                self.combo_categoria.addItems(list(self.dizionario_colture.keys()))
                self.combo_categoria.setEnabled(True)
                self.combo_categoria.setCurrentText("Ortaggi" if tipo == "Ortaggi" else "Cereali")
                self._aggiorna_colture_da_categoria()
                
            self.combo_categoria.blockSignals(False)
        self._carica_storico_colture()

    def _aggiorna_colture_da_categoria(self):
        categoria = self.combo_categoria.currentText()
        self.input_coltura.clear()
        if categoria in self.dizionario_colture:
            self.input_coltura.addItems(self.dizionario_colture[categoria])

    def _aggiungi_coltura(self):
        data = self.combo_campi.currentData()
        if not data: return
        campo_id, _ = data
        coltura = self.input_coltura.currentText().strip()
        if not coltura: return
        
        d_sem = self.input_data_semina.date().toString("yyyy-MM-dd")
        now_text = datetime.now().isoformat(timespec="seconds")
        StoricoColtura.create(user=self.user_id, campo=campo_id, coltura=coltura, data_semina=d_sem, created_at=now_text, updated_at=now_text)
        self._carica_storico_colture()

    def _apri_gestione_economica(self):
        riga = self.table_colture.currentRow()
        if riga < 0: return QMessageBox.warning(self, "Attenzione", "Seleziona un ciclo colturale.")
        dialog = GestioneEconomicaDialog(self.table_colture.item(riga, 0).data(Qt.UserRole), self.user_id, self.table_colture.item(riga, 0).text(), self)
        dialog.exec_()

    def _modifica_coltura(self):
        riga = self.table_colture.currentRow()
        if riga < 0: return
        coltura_id = self.table_colture.item(riga, 0).data(Qt.UserRole)
        
        c = StoricoColtura.get_or_none(StoricoColtura.id == coltura_id, StoricoColtura.user == self.user_id)
        if not c: return
            
        dialog = ModificaColturaDialog(c.coltura, c.data_semina, c.data_raccolto, c.resa_quintali, self)
        if dialog.exec_():
            new_col, new_sem, new_rac, new_resa = dialog.get_dati()
            c.coltura, c.data_semina, c.data_raccolto, c.resa_quintali, c.updated_at = new_col, new_sem, new_rac, new_resa, datetime.now().isoformat(timespec="seconds")
            c.save()
            self._carica_storico_colture()

    def _registra_raccolto(self):
        riga = self.table_colture.currentRow()
        if riga < 0: return QMessageBox.warning(self, "Attenzione", "Seleziona una coltura 'In Corso'.")
            
        coltura_id = self.table_colture.item(riga, 0).data(Qt.UserRole)
        if "Concluso" in self.table_colture.item(riga, 4).text(): return QMessageBox.information(self, "Info", "Questa coltura è già chiusa.")
            
        spese_totali = sum(e.importo for e in EconomiaColtura.select().where((EconomiaColtura.storico == coltura_id) & (EconomiaColtura.user == self.user_id) & (EconomiaColtura.tipo == 'SPESA')))
            
        dialog = RegistraRaccoltoDialog(spese_totali, self)
        if dialog.exec_():
            d_rac, resa = dialog.get_dati()
            StoricoColtura.update(data_raccolto=d_rac, resa_quintali=resa, updated_at=datetime.now().isoformat(timespec="seconds")).where(StoricoColtura.id == coltura_id).execute()
            self._carica_storico_colture()

    def _carica_storico_colture(self):
        self.table_colture.setRowCount(0)
        data = self.combo_campi.currentData()
        if not data: return
        
        storico = list(StoricoColtura.select().where((StoricoColtura.campo == data[0]) & (StoricoColtura.user == self.user_id)).order_by(StoricoColtura.data_semina.desc()).dicts())
        for row_idx, s in enumerate(storico):
            self.table_colture.insertRow(row_idx)
            try: sem_fmt = datetime.strptime(s['data_semina'], "%Y-%m-%d").strftime("%d/%m/%Y") if "-" in s['data_semina'] else s['data_semina']
            except: sem_fmt = s['data_semina']
            
            item_col = QTableWidgetItem(s['coltura'])
            item_col.setData(Qt.UserRole, s['id']) 
            self.table_colture.setItem(row_idx, 0, item_col)
            self.table_colture.setItem(row_idx, 1, QTableWidgetItem(sem_fmt))
            
            if not s['data_raccolto']:
                self.table_colture.setItem(row_idx, 2, QTableWidgetItem("---"))
                self.table_colture.setItem(row_idx, 3, QTableWidgetItem("---"))
                item_stato = QTableWidgetItem("🌱 In Corso")
                item_stato.setForeground(Qt.darkGreen)
                self.table_colture.setItem(row_idx, 4, item_stato)
            else:
                try: rac_fmt = datetime.strptime(s['data_raccolto'], "%Y-%m-%d").strftime("%d/%m/%Y") if "-" in s['data_raccolto'] else s['data_raccolto']
                except: rac_fmt = s['data_raccolto']
                self.table_colture.setItem(row_idx, 2, QTableWidgetItem(rac_fmt))
                self.table_colture.setItem(row_idx, 3, QTableWidgetItem(f"{s['resa_quintali']} q.li"))
                item_stato = QTableWidgetItem("🌾 Concluso")
                item_stato.setForeground(Qt.darkGray)
                self.table_colture.setItem(row_idx, 4, item_stato)

    def gestisci_nuovo_disegno(self, geojson_str, area_ha):
        dialog = NuovoCampoDialog(area_ha, self)
        if dialog.exec_():
            nome, tipo, varieta, piante, anno = dialog.get_dati()
            if nome:
                CampoAgricolo.create(user=self.user_id, nome=nome, area_ettari=area_ha, geojson=geojson_str, tipo_campo=tipo, varieta=varieta, num_piante=piante, anno_impianto=anno, created_at=datetime.now().isoformat(timespec="seconds"), updated_at=datetime.now().isoformat(timespec="seconds"))
                self._carica_campi_salvati(centra_mappa=False) 
                self._aggiorna_meteo_async() 
        else:
            self.web_view.page().runJavaScript("rimuoviUltimoDisegno();")

    def gestisci_aggiornamento_disegno(self, campo_id, geojson_str, area_ha):
        CampoAgricolo.update(area_ettari=area_ha, geojson=geojson_str, updated_at=datetime.now().isoformat(timespec="seconds")).where(CampoAgricolo.id == campo_id, CampoAgricolo.user == self.user_id).execute()
        self._carica_campi_salvati(centra_mappa=False) 

    def _modifica_info_campo_selezionato(self):
        items = self.list_campi.selectedItems()
        if not items: return QMessageBox.warning(self, "Attenzione", "Seleziona un appezzamento dalla lista per modificarlo.")
        campo_id = items[0].data(Qt.UserRole)
        
        c = CampoAgricolo.get_or_none(CampoAgricolo.id == campo_id, CampoAgricolo.user == self.user_id)
        if not c: return
            
        dialog = ModificaDettagliCampoDialog(c.nome, c.tipo_campo, c.varieta, c.num_piante, c.anno_impianto, self)
        if dialog.exec_():
            new_nome, new_varieta, new_piante, new_anno = dialog.get_dati()
            if new_nome:
                c.nome, c.varieta, c.num_piante, c.anno_impianto, c.updated_at = new_nome, new_varieta, new_piante, new_anno, datetime.now().isoformat(timespec="seconds")
                c.save()
                self._carica_campi_salvati(centra_mappa=False)
                self._aggiorna_combo_campi()
                self._aggiorna_dati_statistiche()

    def _elimina_campo_selezionato(self):
        items = self.list_campi.selectedItems()
        if not items: return
        if QMessageBox.question(self, "Conferma", "Sei sicuro di voler eliminare questo appezzamento?\n(Verrà eliminato anche lo storico nel quaderno di campagna)", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            CampoAgricolo.delete().where(CampoAgricolo.id == items[0].data(Qt.UserRole), CampoAgricolo.user == self.user_id).execute()
            self._carica_campi_salvati(centra_mappa=False)
            self._aggiorna_combo_campi()

    def _centra_mappa_su_selezionato(self):
        items = self.list_campi.selectedItems()
        if items: self.web_view.page().runJavaScript(f"centraSuCampo({items[0].data(Qt.UserRole)});")

    def _carica_campi_salvati(self, centra_mappa=False):
        self.list_campi.clear()
        
        campi = list(CampoAgricolo.select().where(CampoAgricolo.user == self.user_id).order_by(CampoAgricolo.id.asc()).dicts())
        storico_attivo = list(StoricoColtura.select().where((StoricoColtura.user == self.user_id) & ((StoricoColtura.data_raccolto.is_null()) | (StoricoColtura.data_raccolto == ''))).order_by(StoricoColtura.data_semina.desc()).dicts())
        
        active_crops = {}
        for s in storico_attivo:
            if s['campo_id'] not in active_crops: active_crops[s['campo_id']] = s['coltura']

        campi_dati = []
        for c in campi:
            coltura_attiva = active_crops.get(c['id'], None)
            icona = "🌳" if c['tipo_campo'] == "Uliveto" else "🍇" if c['tipo_campo'] == "Vigneto" else "🍎" if c['tipo_campo'] == "Frutteto" else "🥕" if c['tipo_campo'] == "Ortaggi" else "🌾"
            testo_lista = f"{icona} {c['nome']} ({c['area_ettari']:.2f} ha)"
            if coltura_attiva: testo_lista += f" - 🌱 {coltura_attiva}"
                
            item = QListWidgetItem(testo_lista)
            item.setData(Qt.UserRole, c['id'])
            self.list_campi.addItem(item)
            
            c['coltura_attiva'] = coltura_attiva
            c['area'] = f"{c['area_ettari']:.2f}"
            campi_dati.append(c)

        self.web_view.page().runJavaScript(f"caricaCampi({json.dumps(campi_dati)}, {'true' if centra_mappa else 'false'});")

    def _get_mappa_html(self):
        # MANTENUTO INTATTO IL TUO CODICE HTML JAVASCRIPT DELLA MAPPA
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.css"/>
            <link rel="stylesheet" href="https://unpkg.com/leaflet-control-geocoder/dist/Control.Geocoder.css" />
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
            
            <style>
                html, body { padding: 0; margin: 0; width: 100%; height: 100%; overflow: hidden; }
                #map { width: 100%; height: 100%; }
                .crop-icon-wrapper { background: transparent; border: none; }
                .crop-icon { width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; font-size: 16px; border: 2px solid white; box-shadow: 0 3px 6px rgba(0,0,0,0.5); }
            </style>
        </head>
        <body>
            <div id="map"></div>
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.js"></script>
            <script src="https://unpkg.com/leaflet-control-geocoder/dist/Control.Geocoder.js"></script>
            <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
            
            <script>
                window.typeWarningFix = true;
                if (L.LineUtil && !L.LineUtil._flat) { L.LineUtil._flat = L.LineUtil.isFlat; }
                if (L.Polyline && !L.Polyline._flat) { L.Polyline._flat = L.LineUtil.isFlat; }
            
                var map = L.map('map', {attributionControl: false}).setView([41.9028, 12.4964], 6);
                L.tileLayer('http://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',{maxZoom: 20, subdomains:['mt0','mt1','mt2','mt3']}).addTo(map);
                const resizeObserver = new ResizeObserver(() => { map.invalidateSize(); });
                resizeObserver.observe(document.getElementById('map'));
                var geocoder = L.Control.geocoder({defaultMarkGeocode: false, position: 'topright', placeholder: 'Cerca...'}).on('markgeocode', function(e) { map.fitBounds(e.geocode.bbox); }).addTo(map);

                var backendBridge = null;
                new QWebChannel(qt.webChannelTransport, function (channel) { backendBridge = channel.objects.bridge; });

                var campiLayer = new L.FeatureGroup();
                map.addLayer(campiLayer);
                var tempLayer = null;

                var drawControl = new L.Control.Draw({ position: 'topleft', edit: { featureGroup: campiLayer, remove: false }, draw: { polygon: { allowIntersection: false, showArea: true, shapeOptions: { color: '#28a745', weight: 3 } }, polyline: false, circle: false, rectangle: false, marker: false, circlemarker: false } });
                map.addControl(drawControl);

                map.on(L.Draw.Event.CREATED, function (event) { tempLayer = event.layer; var area_m2 = L.GeometryUtil.geodesicArea(tempLayer.getLatLngs()[0]); if (backendBridge) backendBridge.ricevi_disegno(JSON.stringify(tempLayer.toGeoJSON()), area_m2 / 10000); });
                map.on(L.Draw.Event.EDITED, function (e) { e.layers.eachLayer(function (layer) { if (layer.campo_id && backendBridge) { var area_m2 = L.GeometryUtil.geodesicArea(layer.getLatLngs()[0]); backendBridge.aggiorna_disegno(layer.campo_id, JSON.stringify(layer.toGeoJSON()), area_m2 / 10000); } }); });

                function rimuoviUltimoDisegno() { if (tempLayer) { map.removeLayer(tempLayer); tempLayer = null; } }
                function centraSuCampo(campoId) { campiLayer.eachLayer(function(layer) { if (layer.campo_id === campoId && typeof layer.getBounds === 'function') { map.fitBounds(layer.getBounds(), {maxZoom: 18}); layer.openPopup(); } }); }

                function getCropStyle(campo) {
                    if (campo.tipo_campo === "Uliveto") return { icon: "fa-tree", color: "#556b2f", fill: "#8f9779" };
                    if (campo.tipo_campo === "Vigneto") return { icon: "fa-wine-glass", color: "#8e44ad", fill: "#af7ac5" };
                    if (campo.tipo_campo === "Frutteto") return { icon: "fa-apple-whole", color: "#c0392b", fill: "#ec7063" };
                    let name = (campo.coltura_attiva || "").toLowerCase();
                    if (name.includes("grano") || name.includes("orzo") || name.includes("avena") || name.includes("sorgo")) return { icon: "fa-wheat-awn", color: "#f39c12", fill: "#f8c471" };
                    if (name.includes("mais")) return { icon: "fa-leaf", color: "#d35400", fill: "#e59866" };
                    if (name.includes("soia") || name.includes("medica") || name.includes("prato") || name.includes("fava") || name.includes("cece") || name.includes("pisello") || name.includes("lenticchia")) return { icon: "fa-seedling", color: "#27ae60", fill: "#58d68d" };
                    if (name.includes("girasole") || name.includes("colza")) return { icon: "fa-sun", color: "#f1c40f", fill: "#f7dc6f" };
                    if (name.includes("pomodoro") || name.includes("patata") || name.includes("cipolla") || name.includes("zucchina") || name.includes("insalata") || name.includes("carota") || name.includes("peperone") || name.includes("melanzana") || name.includes("melone") || name.includes("cocomero") || name.includes("aglio") || name.includes("finocchio")) return { icon: "fa-carrot", color: "#e67e22", fill: "#f0b27a" };
                    return { icon: "fa-seedling", color: "#2c3e50", fill: "#5d6d7e" };
                }

                function caricaCampi(campi, centra) {
                    campiLayer.clearLayers();
                    rimuoviUltimoDisegno();
                    var firstBounds = null; 
                    campi.forEach(function(campo, index) {
                        var geojson = JSON.parse(campo.geojson);
                        var borderColor = campo.colore; var fillColor = campo.colore;
                        var haColtura = (campo.tipo_campo !== "Seminativo" && campo.tipo_campo !== "Ortaggi") || campo.coltura_attiva;
                        if (haColtura) { let style = getCropStyle(campo); borderColor = style.color; fillColor = style.fill; }
                        
                        var layerGroup = L.geoJSON(geojson, { style: { color: borderColor, fillColor: fillColor, weight: 3, fillOpacity: 0.45 } });
                        layerGroup.eachLayer(function(layer) {
                            layer.campo_id = campo.id; 
                            let popupHtml = "<div style='text-align:center;'><b>" + campo.nome + "</b><br>Estensione: " + campo.area + " ha";
                            if (campo.tipo_campo !== "Seminativo" && campo.tipo_campo !== "Ortaggi") { popupHtml += `<br><b>${campo.tipo_campo}</b>`; if(campo.varieta) popupHtml += ` - Var. ${campo.varieta}`; if(campo.num_piante > 0 && campo.tipo_campo !== "Vigneto") popupHtml += `<br>Piante: ${campo.num_piante}`; }
                            if (campo.coltura_attiva) popupHtml += "<br><span style='color:#27ae60; font-weight:bold;'>🌱 " + campo.coltura_attiva + " (In Corso)</span>";
                            popupHtml += "</div>";
                            layer.bindPopup(popupHtml);
                            campiLayer.addLayer(layer);
                            
                            if (haColtura && typeof layer.getBounds === 'function') {
                                let style = getCropStyle(campo); let center = layer.getBounds().getCenter(); 
                                let customIcon = L.divIcon({ className: 'crop-icon-wrapper', html: `<div class="crop-icon" style="background-color: ${style.color};"><i class="fa-solid ${style.icon}"></i></div>`, iconSize: [34, 34], iconAnchor: [17, 17] });
                                let marker = L.marker(center, {icon: customIcon}); marker.bindPopup(popupHtml); campiLayer.addLayer(marker);
                            }
                            if (index === 0 && !firstBounds) firstBounds = layer.getBounds();
                        });
                    });
                    if (centra) { setTimeout(function() { map.invalidateSize(); if (firstBounds) map.fitBounds(firstBounds, {maxZoom: 18}); else map.setView([41.9028, 12.4964], 6); }, 100); }
                }
            </script>
        </body>
        </html>
        """