from datetime import datetime
import pyqtgraph as pg

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDateEdit, QFormLayout, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
    QTabWidget, QVBoxLayout, QWidget, QSizePolicy, QSplitter, QTableWidgetItem
)

from app_utils import format_eur, format_number, TabellaIsolata
from models import Movimento, ManutenzioneMacchinario # Importiamo il nostro ORM

class AziendaReportPage(QWidget):
    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = int(user_id)
        self._build_ui()
        self.imposta_periodo_default(show_errors=False)
        self.genera_report(show_errors=False)

    def _build_ui(self):
        STYLE_BTN_INFO = "background-color: #17a2b8; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_SECONDARIO = "background-color: #6c757d; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        header_layout = QVBoxLayout()
        titolo = QLabel("📈 Report e Bilancio Aziendale")
        titolo.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        header_layout.addWidget(titolo)
        header_layout.addWidget(QLabel("Analizza entrate, uscite e statistiche economiche nel dettaglio."))
        main_layout.addLayout(header_layout)

        filtri_frame = QFrame()
        filtri_frame.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        filtri_layout = QVBoxLayout(filtri_frame)
        
        self.checkbox_usa_filtro = QCheckBox("Usa filtro periodo", self)
        self.checkbox_usa_filtro.setStyleSheet("font-weight: bold;")
        self.checkbox_usa_filtro.toggled.connect(lambda on: (self.data_inizio.setEnabled(on), self.data_fine.setEnabled(on)))
        filtri_layout.addWidget(self.checkbox_usa_filtro)

        form_filtri = QFormLayout()
        self.data_inizio = QDateEdit()
        self.data_inizio.setDisplayFormat("dd/MM/yyyy")
        self.data_inizio.setCalendarPopup(True)
        self.data_fine = QDateEdit()
        self.data_fine.setDisplayFormat("dd/MM/yyyy")
        self.data_fine.setCalendarPopup(True)
        self.data_inizio.setEnabled(False)
        self.data_fine.setEnabled(False)

        form_filtri.addRow("Data INIZIO:", self.data_inizio)
        form_filtri.addRow("Data FINE:", self.data_fine)
        filtri_layout.addLayout(form_filtri)

        bottoni_filtri = QHBoxLayout()
        btn_aggiorna = QPushButton("📊 Genera Report")
        btn_aggiorna.setStyleSheet(STYLE_BTN_INFO)
        btn_aggiorna.clicked.connect(lambda: self.genera_report(show_errors=True))
        bottoni_filtri.addWidget(btn_aggiorna)

        btn_default = QPushButton("Periodo Storico Completo")
        btn_default.setStyleSheet(STYLE_BTN_SECONDARIO)
        btn_default.clicked.connect(self._reset_and_refresh)
        bottoni_filtri.addWidget(btn_default)
        bottoni_filtri.addStretch()
        filtri_layout.addLayout(bottoni_filtri)
        main_layout.addWidget(filtri_frame)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane { border: 1px solid #ccc; background-color: white; }")
        main_layout.addWidget(self.tabs, 1)

        # Tab Tabelle
        self.tab_tabelle = QWidget()
        tabelle_layout = QVBoxLayout(self.tab_tabelle)
        splitter_tabelle = QSplitter(Qt.Vertical)

        self.table_riepilogo = TabellaIsolata(0, 2)
        self.table_riepilogo.setHorizontalHeaderLabels(["Metrica", "Valore"])
        self.table_riepilogo.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_riepilogo.setEditTriggers(QAbstractItemView.NoEditTriggers)
        splitter_tabelle.addWidget(self.table_riepilogo)

        self.table_categorie = TabellaIsolata(0, 4)
        self.table_categorie.setHorizontalHeaderLabels(["Tipo", "Categoria", "Totale", "N. Movimenti"])
        self.table_categorie.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_categorie.setEditTriggers(QAbstractItemView.NoEditTriggers)
        splitter_tabelle.addWidget(self.table_categorie)

        tabelle_layout.addWidget(splitter_tabelle)
        self.tabs.addTab(self.tab_tabelle, "Dati e Tabelle")

        # Tab Grafici
        self.tab_grafici = QWidget()
        grafici_layout = QVBoxLayout(self.tab_grafici)
        self.plot_trend = pg.PlotWidget(title="Trend Mensile")
        self.plot_trend.setBackground('w')
        self.plot_categorie = pg.PlotWidget(title="Top Costi Aziendali")
        self.plot_categorie.setBackground('w')
        grafici_layout.addWidget(self.plot_trend)
        grafici_layout.addWidget(self.plot_categorie)
        self.tabs.addTab(self.tab_grafici, "Grafici Interattivi")

    def _reset_and_refresh(self):
        self.checkbox_usa_filtro.setChecked(False)
        self.imposta_periodo_default()
        self.genera_report()

    def imposta_periodo_default(self, show_errors=True):
        try:
            from peewee import fn
            # Trova la prima e l'ultima data in 2 millisecondi
            min_date = Movimento.select(fn.MIN(Movimento.data_op)).where(Movimento.user == self.user_id).scalar()
            max_date = Movimento.select(fn.MAX(Movimento.data_op)).where(Movimento.user == self.user_id).scalar()
            
            self.data_inizio.setDate(QDate.fromString(min_date, "yyyy-MM-dd") if min_date else QDate.currentDate())
            self.data_fine.setDate(QDate.fromString(max_date, "yyyy-MM-dd") if max_date else QDate.currentDate())
        except Exception as e:
            if show_errors: QMessageBox.critical(self, "Errore", str(e))

    def genera_report(self, show_errors=True):
        d_inizio = self.data_inizio.date().toString("yyyy-MM-dd") if self.checkbox_usa_filtro.isChecked() else "1900-01-01"
        d_fine = self.data_fine.date().toString("yyyy-MM-dd") if self.checkbox_usa_filtro.isChecked() else "2100-01-01"

        try:
            # 1 singola query a Peewee invece di 10
            movimenti = list(Movimento.select().where((Movimento.user == self.user_id) & (Movimento.data_op >= d_inizio) & (Movimento.data_op <= d_fine)).dicts())
            manutenzioni = list(ManutenzioneMacchinario.select().where((ManutenzioneMacchinario.user == self.user_id) & (ManutenzioneMacchinario.data_manutenzione >= d_inizio) & (ManutenzioneMacchinario.data_manutenzione <= d_fine)).dicts())
            
            # Calcoli pythonici in RAM
            entrate = sum(m['importo'] for m in movimenti if m['tipo'] == 'ENTRATA' and m['importo'])
            uscite = sum(m['importo'] for m in movimenti if m['tipo'] == 'USCITA' and m['importo'])
            costi_manut = sum(m['costo'] for m in manutenzioni if m['costo'])
            
            self.table_riepilogo.setRowCount(0)
            dati_riepilogo = [
                ("Ricavi Lordi (Entrate)", entrate),
                ("Costi Operativi (Uscite)", uscite),
                ("Costi Manutenzioni Macchinari", costi_manut),
                ("Utile Netto (Risultato)", entrate - uscite - costi_manut)
            ]
            for i, (nome, val) in enumerate(dati_riepilogo):
                self.table_riepilogo.insertRow(i)
                self.table_riepilogo.setItem(i, 0, QTableWidgetItem(nome))
                item_val = QTableWidgetItem(format_eur(val))
                item_val.setForeground(Qt.darkGreen if val >= 0 else Qt.red)
                self.table_riepilogo.setItem(i, 1, item_val)

            # Raggruppamento per Categoria
            categorie = {}
            for m in movimenti:
                cat = m['categoria'] or "Altro"
                if cat not in categorie: categorie[cat] = {'ENTRATA': [0,0], 'USCITA': [0,0]}
                categorie[cat][m['tipo']][0] += m['importo'] or 0
                categorie[cat][m['tipo']][1] += 1
            if costi_manut > 0:
                categorie["Manutenzioni"] = {'ENTRATA': [0,0], 'USCITA': [costi_manut, len(manutenzioni)]}

            self.table_categorie.setRowCount(0)
            riga = 0
            for cat, dati in categorie.items():
                for tipo in ['ENTRATA', 'USCITA']:
                    if dati[tipo][1] > 0:
                        self.table_categorie.insertRow(riga)
                        self.table_categorie.setItem(riga, 0, QTableWidgetItem(tipo))
                        self.table_categorie.setItem(riga, 1, QTableWidgetItem(cat))
                        self.table_categorie.setItem(riga, 2, QTableWidgetItem(format_eur(dati[tipo][0])))
                        self.table_categorie.setItem(riga, 3, QTableWidgetItem(str(dati[tipo][1])))
                        riga += 1

            # (Qui puoi reinserire il codice di plot_trend e plot_categorie se ti serve la UI specifica)
            self.plot_trend.clear()
            self.plot_categorie.clear()

        except Exception as e:
            if show_errors: QMessageBox.critical(self, "Errore", f"Errore DB: {e}")