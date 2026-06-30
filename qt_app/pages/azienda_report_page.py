from datetime import datetime
import pyqtgraph as pg

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDateEdit, QFormLayout, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
    QTabWidget, QVBoxLayout, QWidget, QSizePolicy, QScrollArea, QTableWidgetItem
)

from app_utils import format_eur, format_number, TabellaIsolata
from models import Movimento, ManutenzioneMacchinario, CapoAnimale, AziendaAnimaliDettaglio 

class AziendaReportPage(QWidget):
    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = int(user_id)
        self._build_ui()
        self.imposta_periodo_default(show_errors=False)
        self.genera_report(show_errors=False)

    def _setup_tabella_dinamica(self, table: TabellaIsolata):
        """Forza la tabella a non avere spazi bianchi e ad aderire al contenuto"""
        table.setMinimumHeight(0)
        table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def _build_ui(self):
        STYLE_BTN_INFO = "background-color: #17a2b8; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_SECONDARIO = "background-color: #6c757d; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"

        # ==========================================
        # RADICE DELLA PAGINA: SCROLL GLOBALE
        # ==========================================
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        
        # Contenitore principale (Quello che effettivamente scorrerà)
        main_content = QWidget()
        main_content.setStyleSheet("background-color: transparent;")
        main_layout = QVBoxLayout(main_content)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # HEADER
        header_layout = QVBoxLayout()
        titolo = QLabel("📈 Report e Bilancio Aziendale")
        titolo.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        header_layout.addWidget(titolo)
        header_layout.addWidget(QLabel("Analizza entrate, uscite e statistiche economiche nel dettaglio."))
        main_layout.addLayout(header_layout)

        # FILTRI
        filtri_frame = QFrame()
        filtri_frame.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        filtri_layout = QVBoxLayout(filtri_frame)
        
        self.checkbox_usa_filtro = QCheckBox("Usa filtro periodo (Applica a Bilancio e Movimenti)", self)
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

        # ==========================================
        # SCHEDE (TABS)
        # ==========================================
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane { border: 1px solid #ccc; background-color: white; }")
        
        # --- TAB 1: DATI E TABELLE (Senza Scroll interno) ---
        self.tab_tabelle = QWidget()
        tabelle_layout = QVBoxLayout(self.tab_tabelle)
        tabelle_layout.setContentsMargins(15, 15, 15, 15)
        tabelle_layout.setSpacing(20)

        # 1. Tabella Riepilogo
        lbl_riepilogo = QLabel("Bilancio Globale")
        lbl_riepilogo.setStyleSheet("font-size: 16px; font-weight: bold; color: #34495e;")
        tabelle_layout.addWidget(lbl_riepilogo)
        
        self.table_riepilogo = TabellaIsolata(0, 2)
        self.table_riepilogo.setHorizontalHeaderLabels(["Metrica", "Valore"])
        self.table_riepilogo.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_riepilogo.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._setup_tabella_dinamica(self.table_riepilogo)
        tabelle_layout.addWidget(self.table_riepilogo)

        # 2. Tabella Statistiche Zootecniche
        lbl_zoo = QLabel("Statistiche Zootecniche")
        lbl_zoo.setStyleSheet("font-size: 16px; font-weight: bold; color: #34495e;")
        tabelle_layout.addWidget(lbl_zoo)
        
        self.table_zootecnia = TabellaIsolata(0, 8)
        self.table_zootecnia.setHorizontalHeaderLabels([
            "Tipo Animale", "Settore", "Capi Att.", "Costi Tot.", "Ricavi Tot.", 
            "Produzione Tot.", "Costo / Unità", "Margine %"
        ])
        self.table_zootecnia.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for i in [2, 6, 7]: self.table_zootecnia.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.table_zootecnia.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._setup_tabella_dinamica(self.table_zootecnia)
        tabelle_layout.addWidget(self.table_zootecnia)

        # 3. Tabella Categorie Movimenti
        lbl_cat = QLabel("Categorie Movimenti")
        lbl_cat.setStyleSheet("font-size: 16px; font-weight: bold; color: #34495e;")
        tabelle_layout.addWidget(lbl_cat)
        
        self.table_categorie = TabellaIsolata(0, 4)
        self.table_categorie.setHorizontalHeaderLabels(["Tipo", "Categoria Movimenti", "Totale", "N. Mov."])
        self.table_categorie.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_categorie.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._setup_tabella_dinamica(self.table_categorie)
        tabelle_layout.addWidget(self.table_categorie)

        # Molla per spingere le tabelle verso l'alto se lo schermo è enorme
        tabelle_layout.addStretch(1) 
        self.tabs.addTab(self.tab_tabelle, "Dati e Tabelle")

        # --- TAB 2: GRAFICI ---
        self.tab_grafici = QWidget()
        grafici_layout = QVBoxLayout(self.tab_grafici)
        
        self.plot_trend = pg.PlotWidget(title="Trend Mensile")
        self.plot_trend.setBackground('w')
        self.plot_trend.setMinimumHeight(350) # Obbligatorio in una scroll area per non collassare
        
        self.plot_categorie = pg.PlotWidget(title="Top Costi Aziendali")
        self.plot_categorie.setBackground('w')
        self.plot_categorie.setMinimumHeight(350)
        
        grafici_layout.addWidget(self.plot_trend)
        grafici_layout.addWidget(self.plot_categorie)
        self.tabs.addTab(self.tab_grafici, "Grafici Interattivi")

        main_layout.addWidget(self.tabs)

        # Aggiungiamo tutto al contenitore scrollabile
        self.scroll_area.setWidget(main_content)
        root_layout.addWidget(self.scroll_area)

    def _reset_and_refresh(self):
        self.checkbox_usa_filtro.setChecked(False)
        self.imposta_periodo_default()
        self.genera_report()

    def imposta_periodo_default(self, show_errors=True):
        try:
            from peewee import fn
            min_date = Movimento.select(fn.MIN(Movimento.data_op)).where(Movimento.user == self.user_id).scalar()
            max_date = Movimento.select(fn.MAX(Movimento.data_op)).where(Movimento.user == self.user_id).scalar()
            
            self.data_inizio.setDate(QDate.fromString(min_date, "yyyy-MM-dd") if min_date else QDate.currentDate())
            self.data_fine.setDate(QDate.fromString(max_date, "yyyy-MM-dd") if max_date else QDate.currentDate())
        except Exception as e:
            if show_errors: QMessageBox.critical(self, "Errore", str(e))

    def _adatta_altezza_tabelle(self):
        def _resize():
            for table in [self.table_riepilogo, self.table_zootecnia, self.table_categorie]:
                try:
                    header_h = table.horizontalHeader().height()
                    if header_h < 20: header_h = 32
                    
                    rows_h = 0
                    for i in range(table.rowCount()):
                        h = table.rowHeight(i)
                        rows_h += h if h > 0 else 35
                        
                    table.setFixedHeight(header_h + rows_h + 2)
                except Exception:
                    pass
        QTimer.singleShot(10, _resize)

    def genera_report(self, show_errors=True):
        d_inizio = self.data_inizio.date().toString("yyyy-MM-dd") if self.checkbox_usa_filtro.isChecked() else "1900-01-01"
        d_fine = self.data_fine.date().toString("yyyy-MM-dd") if self.checkbox_usa_filtro.isChecked() else "2100-01-01"

        try:
            movimenti = list(Movimento.select().where((Movimento.user == self.user_id) & (Movimento.data_op >= d_inizio) & (Movimento.data_op <= d_fine)).dicts())
            manutenzioni = list(ManutenzioneMacchinario.select().where((ManutenzioneMacchinario.user == self.user_id) & (ManutenzioneMacchinario.data_manutenzione >= d_inizio) & (ManutenzioneMacchinario.data_manutenzione <= d_fine)).dicts())
            
            entrate = sum(m['importo'] for m in movimenti if m['tipo'] == 'ENTRATA' and m['importo'])
            uscite = sum(m['importo'] for m in movimenti if m['tipo'] == 'USCITA' and m['importo'])
            costi_manut = sum(m['costo'] for m in manutenzioni if m['costo'])
            
            # --- TABELLA 1: BILANCIO ---
            self.table_riepilogo.setRowCount(0)
            dati_riepilogo = [
                ("Ricavi Lordi (Entrate)", entrate),
                ("Costi Operativi (Uscite)", uscite),
                ("Costi Manutenzioni Macchinari", costi_manut),
                ("Utile Netto (Risultato)", entrate - uscite - costi_manut)
            ]
            for i, (nome, val) in enumerate(dati_riepilogo):
                self.table_riepilogo.insertRow(i)
                self.table_riepilogo.setRowHeight(i, 35) 
                self.table_riepilogo.setItem(i, 0, QTableWidgetItem(nome))
                item_val = QTableWidgetItem(format_eur(val))
                item_val.setForeground(Qt.darkGreen if val >= 0 else Qt.red)
                self.table_riepilogo.setItem(i, 1, item_val)

            # --- TABELLA 2: ZOOTECNIA ---
            capi = list(CapoAnimale.select(CapoAnimale, AziendaAnimaliDettaglio).join(AziendaAnimaliDettaglio).where(CapoAnimale.user == self.user_id))
            stats_zootecnia = {}
            for capo in capi:
                if not hasattr(capo, 'gruppo') or not capo.gruppo: continue
                tipo = capo.gruppo.tipo_animale
                finalita = capo.gruppo.finalita
                if not tipo or finalita not in ['LATTE', 'CARNE']: continue

                chiave = (tipo, finalita)
                if chiave not in stats_zootecnia:
                    stats_zootecnia[chiave] = {'capi_attivi': 0, 'costi': 0.0, 'ricavi': 0.0, 'produzione': 0.0}

                if capo.stato == 'ATTIVO': stats_zootecnia[chiave]['capi_attivi'] += 1
                stats_zootecnia[chiave]['costi'] += getattr(capo, 'costi_accumulati', 0.0) or 0.0
                stats_zootecnia[chiave]['ricavi'] += getattr(capo, 'ricavi_accumulati', 0.0) or 0.0

                if finalita == 'LATTE':
                    media = getattr(capo, 'media_litri_latte', 0.0) or 0.0
                    giorni = getattr(capo, 'giorni_produzione_latte', 0) or 0
                    stats_zootecnia[chiave]['produzione'] += (media * giorni)
                elif finalita == 'CARNE':
                    stats_zootecnia[chiave]['produzione'] += getattr(capo, 'kg_carne_prodotti', 0.0) or 0.0

            self.table_zootecnia.setRowCount(0)
            riga_z = 0
            for (tipo, finalita), dati in stats_zootecnia.items():
                costi, ricavi, produzione = dati['costi'], dati['ricavi'], dati['produzione']
                
                costo_unitario = (costi / produzione) if produzione > 0 else 0.0
                str_unita = "L" if finalita == 'LATTE' else "Kg"
                str_costo_unit = f"€ {costo_unitario:.2f} / {str_unita}" if produzione > 0 else "-"

                utile = ricavi - costi
                margine_pct = (utile / ricavi * 100) if ricavi > 0 else 0.0
                str_margine = f"{margine_pct:.1f} %" if ricavi > 0 else "-"

                self.table_zootecnia.insertRow(riga_z)
                self.table_zootecnia.setRowHeight(riga_z, 35) 
                self.table_zootecnia.setItem(riga_z, 0, QTableWidgetItem(tipo))
                self.table_zootecnia.setItem(riga_z, 1, QTableWidgetItem(finalita))
                self.table_zootecnia.setItem(riga_z, 2, QTableWidgetItem(str(dati['capi_attivi'])))
                self.table_zootecnia.setItem(riga_z, 3, QTableWidgetItem(format_eur(costi)))
                self.table_zootecnia.setItem(riga_z, 4, QTableWidgetItem(format_eur(ricavi)))
                self.table_zootecnia.setItem(riga_z, 5, QTableWidgetItem(f"{produzione:.0f} {str_unita}"))
                self.table_zootecnia.setItem(riga_z, 6, QTableWidgetItem(str_costo_unit))
                
                item_margine = QTableWidgetItem(str_margine)
                if ricavi > 0: item_margine.setForeground(Qt.darkGreen if margine_pct >= 0 else Qt.red)
                self.table_zootecnia.setItem(riga_z, 7, item_margine)
                riga_z += 1

            # --- TABELLA 3: CATEGORIE ---
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
                        self.table_categorie.setRowHeight(riga, 35) 
                        self.table_categorie.setItem(riga, 0, QTableWidgetItem(tipo))
                        self.table_categorie.setItem(riga, 1, QTableWidgetItem(cat))
                        item_tot = QTableWidgetItem(format_eur(dati[tipo][0]))
                        item_tot.setForeground(Qt.darkGreen if tipo == 'ENTRATA' else Qt.red)
                        self.table_categorie.setItem(riga, 2, item_tot)
                        self.table_categorie.setItem(riga, 3, QTableWidgetItem(str(dati[tipo][1])))
                        riga += 1

            self.plot_trend.clear()
            self.plot_categorie.clear()
            
            # --- Ricalcolo visivo finale ---
            self._adatta_altezza_tabelle()

        except Exception as e:
            if show_errors: QMessageBox.critical(self, "Errore", f"Errore DB: {e}")