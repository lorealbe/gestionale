import csv
from datetime import datetime
import pyqtgraph as pg

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton, 
    QGridLayout, QSizePolicy, QTableWidget, QHeaderView, QTableWidgetItem, 
    QAbstractItemView, QMessageBox, QFileDialog
)

from models import Movimento
from peewee import fn

class DashboardPage(QWidget):
    # Segnale che avviserà il MainWindow di cambiare tab quando premiamo un'Azione Rapida
    richiesta_navigazione = Signal(str)

    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        
        self._build_ui()

        def init_dashboard():
            self._carica_dati_finanziari()
            self._carica_fatture_da_pagare()

        QTimer.singleShot(100, init_dashboard)  

    def showEvent(self, event):
        """Ogni volta che si apre la pagina Dashboard, aggiorna i numeri"""
        super().showEvent(event)
        self._carica_dati_finanziari()
        self._carica_fatture_da_pagare()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(20)

        # --- HEADER ---
        header_layout = QHBoxLayout()
        titolo = QLabel("📊 Cruscotto Aziendale")
        titolo.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        header_layout.addWidget(titolo)
        
        btn_esporta = QPushButton("📥 Esporta tutto in Excel (CSV)")
        btn_esporta.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 8px; border-radius: 5px;")
        btn_esporta.clicked.connect(self.esporta_csv)
        header_layout.addStretch()
        header_layout.addWidget(btn_esporta)
        
        layout.addLayout(header_layout)

        # --- KPI CARDS (Valori Finanziari) ---
        kpi_layout = QHBoxLayout()
        kpi_layout.setSpacing(15)

        self.val_entrate = self._crea_card(kpi_layout, "Entrate Totali", "€ 0,00", "#27ae60")
        self.val_uscite = self._crea_card(kpi_layout, "Uscite Totali", "€ 0,00", "#e74c3c")
        
        # Card dell'utile un po' più grande
        card_utile = QFrame()
        card_utile.setStyleSheet("background-color: white; border-radius: 10px; border: 1px solid #ddd; border-bottom: 4px solid #3498db;")
        l_utile = QVBoxLayout(card_utile)
        l_utile.setContentsMargins(20, 20, 20, 20)
        titolo_utile = QLabel("UTILE NETTO")
        titolo_utile.setStyleSheet("font-size: 12px; font-weight: bold; color: #7f8c8d;")
        self.val_utile = QLabel("€ 0,00")
        self.val_utile.setStyleSheet("font-size: 26px; font-weight: bold; color: #2c3e50;")
        
        self.val_diff_utile = QLabel("Rispetto al mese scorso: -")
        self.val_diff_utile.setStyleSheet("font-size: 11px; color: #7f8c8d; margin-top: 5px;")
        
        l_utile.addWidget(titolo_utile)
        l_utile.addWidget(self.val_utile)
        l_utile.addWidget(self.val_diff_utile)
        kpi_layout.addWidget(card_utile)

        layout.addLayout(kpi_layout)

        # --- SEZIONE CENTRALE (Grafico + Scadenze) ---
        middle_layout = QHBoxLayout()
        middle_layout.setSpacing(15)

        # --- GRAFICO ---
        grafico_frame = QFrame()
        grafico_frame.setStyleSheet("background-color: white; border-radius: 10px; border: 1px solid #ddd;")
        grafico_vbox = QVBoxLayout(grafico_frame)
        
        titolo_grafico = QLabel("Costi e Ricavi per Mese (Ultimi 6 mesi)")
        titolo_grafico.setStyleSheet("font-weight: bold; font-size: 14px; color: #2c3e50; margin-bottom: 10px;")
        grafico_vbox.addWidget(titolo_grafico)

        self.plot_spese = pg.PlotWidget()
        self.plot_spese.setBackground('w')
        self.plot_spese.showGrid(x=False, y=True, alpha=0.3)
        self.plot_spese.setMouseEnabled(x=False, y=False)
        self.plot_spese.hideButtons()
        self.plot_spese.getPlotItem().getAxis('bottom').setHeight(50)

        font_assi = QFont()
        font_assi.setPointSize(9)
        self.plot_spese.getPlotItem().getAxis('bottom').setTickFont(font_assi)
        self.plot_spese.getPlotItem().getAxis('left').setTickFont(font_assi)

        grafico_vbox.addWidget(self.plot_spese)
        middle_layout.addWidget(grafico_frame, stretch=2)

        # --- SCADENZE (Da Pagare) ---
        scadenze_frame = QFrame()
        scadenze_frame.setStyleSheet("background-color: white; border-radius: 10px; border: 1px solid #ddd;")
        scadenze_vbox = QVBoxLayout(scadenze_frame)
        
        titolo_scadenze = QLabel("🚨 Scadenze e Fatture Da Pagare")
        titolo_scadenze.setStyleSheet("font-weight: bold; font-size: 14px; color: #e74c3c; margin-bottom: 10px;")
        scadenze_vbox.addWidget(titolo_scadenze)

        self.table_scadenze = QTableWidget(0, 3)
        self.table_scadenze.setHorizontalHeaderLabels(["Scadenza", "Descrizione", "Importo"])
        self.table_scadenze.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_scadenze.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_scadenze.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_scadenze.verticalHeader().setVisible(False)
        self.table_scadenze.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_scadenze.setSelectionMode(QAbstractItemView.NoSelection)
        self.table_scadenze.setStyleSheet("border: none;")
        scadenze_vbox.addWidget(self.table_scadenze)
        
        middle_layout.addWidget(scadenze_frame, stretch=1)
        layout.addLayout(middle_layout)

        # --- AZIONI RAPIDE ---
        azioni_layout = QHBoxLayout()
        azioni_layout.setSpacing(10)
        
        lbl_azioni = QLabel("Azioni Rapide:")
        lbl_azioni.setStyleSheet("font-weight: bold; color: #7f8c8d;")
        azioni_layout.addWidget(lbl_azioni)
        
        btn_nuova_fattura = QPushButton("➕ Registra Nuova Fattura")
        btn_nuova_fattura.setStyleSheet("background-color: #f39c12; color: white; font-weight: bold; padding: 8px; border-radius: 5px;")
        btn_nuova_fattura.clicked.connect(lambda: self.richiesta_navigazione.emit("Fatture"))
        
        btn_nuovo_latte = QPushButton("🥛 Produzione Latte")
        btn_nuovo_latte.setStyleSheet("background-color: #3498db; color: white; font-weight: bold; padding: 8px; border-radius: 5px;")
        btn_nuovo_latte.clicked.connect(lambda: self.richiesta_navigazione.emit("Stalla"))
        
        azioni_layout.addWidget(btn_nuova_fattura)
        azioni_layout.addWidget(btn_nuovo_latte)
        azioni_layout.addStretch()
        
        layout.addLayout(azioni_layout)

    def _crea_card(self, layout, titolo, val_iniziale, colore_bordo):
        frame = QFrame()
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        frame.setStyleSheet(f"background-color: white; border-radius: 10px; border: 1px solid #ddd; border-bottom: 4px solid {colore_bordo};")
        vbox = QVBoxLayout(frame)
        vbox.setContentsMargins(20, 20, 20, 20)
        
        lbl_titolo = QLabel(titolo.upper())
        lbl_titolo.setStyleSheet("font-size: 12px; font-weight: bold; color: #7f8c8d;")
        
        lbl_valore = QLabel(val_iniziale)
        lbl_valore.setStyleSheet("font-size: 22px; font-weight: bold; color: #2c3e50;")
        
        vbox.addWidget(lbl_titolo)
        vbox.addWidget(lbl_valore)
        layout.addWidget(frame)
        return lbl_valore

    def _carica_dati_finanziari(self):
        try:
            # 1. ORM: Calcola Entrate e Uscite totali 
            entrate = Movimento.select(fn.SUM(Movimento.importo)).where((Movimento.tipo == 'ENTRATA') & (Movimento.user == self.user_id)).scalar() or 0.0
            uscite = Movimento.select(fn.SUM(Movimento.importo)).where((Movimento.tipo == 'USCITA') & (Movimento.user == self.user_id)).scalar() or 0.0
            utile = entrate - uscite
            
            # 2. ORM: Calcolo Mese Corrente vs Mese Precedente
            now = datetime.now()
            mese_corrente = now.strftime("%Y-%m")
            if now.month == 1:
                mese_prec = f"{now.year - 1}-12"
            else:
                mese_prec = f"{now.year}-{now.month - 1:02d}"

            # Entrate/Uscite Mese Corrente (Gestione sicura date formato YYYY-MM-DD)
            ent_corrente = Movimento.select(fn.SUM(Movimento.importo)).where(
                (Movimento.tipo == 'ENTRATA') & (Movimento.user == self.user_id) & 
                (Movimento.data_op >= f"{mese_corrente}-01") & (Movimento.data_op <= f"{mese_corrente}-31")
            ).scalar() or 0.0
            usc_corrente = Movimento.select(fn.SUM(Movimento.importo)).where(
                (Movimento.tipo == 'USCITA') & (Movimento.user == self.user_id) & 
                (Movimento.data_op >= f"{mese_corrente}-01") & (Movimento.data_op <= f"{mese_corrente}-31")
            ).scalar() or 0.0
            utile_corrente = ent_corrente - usc_corrente
            
            # Entrate/Uscite Mese Precedente
            ent_prec = Movimento.select(fn.SUM(Movimento.importo)).where(
                (Movimento.tipo == 'ENTRATA') & (Movimento.user == self.user_id) & 
                (Movimento.data_op >= f"{mese_prec}-01") & (Movimento.data_op <= f"{mese_prec}-31")
            ).scalar() or 0.0
            usc_prec = Movimento.select(fn.SUM(Movimento.importo)).where(
                (Movimento.tipo == 'USCITA') & (Movimento.user == self.user_id) & 
                (Movimento.data_op >= f"{mese_prec}-01") & (Movimento.data_op <= f"{mese_prec}-31")
            ).scalar() or 0.0
            utile_prec = ent_prec - usc_prec
            
            # Calcolo differenza e aggiornamento UI
            differenza_utile = utile_corrente - utile_prec
            segno_diff = "+" if differenza_utile >= 0 else ""
            colore_diff = "#27ae60" if differenza_utile >= 0 else "#e74c3c"
            
            self.val_entrate.setText(f"€ {entrate:,.2f}")
            self.val_uscite.setText(f"€ {uscite:,.2f}")
            
            colore_utile = "#27ae60" if utile >= 0 else "#e74c3c"
            self.val_utile.setText(f"€ {utile:,.2f}")
            self.val_utile.setStyleSheet(f"font-size: 26px; font-weight: bold; color: {colore_utile};")
            
            self.val_diff_utile.setText(f"Rispetto al mese scorso: <span style='color:{colore_diff}; font-weight:bold;'>{segno_diff}€ {differenza_utile:,.2f}</span>")
            
        except Exception as e:
            print(f"Errore caricamento dati finanziari: {e}")

    def _carica_fatture_da_pagare(self):
        try:
            # PEEWEE ORM
            da_pagare = list(Movimento.select().where(
                (Movimento.user == self.user_id) & (Movimento.stato_pagamento == 'DA PAGARE')
            ).order_by(Movimento.data_op.asc()).dicts())
            
            self.table_scadenze.setRowCount(0)
            for r_idx, mov in enumerate(da_pagare):
                self.table_scadenze.insertRow(r_idx)
                
                try: data_fmt = datetime.strptime(mov['data_op'], "%Y-%m-%d").strftime("%d/%m/%Y")
                except: data_fmt = mov['data_op']
                
                item_data = QTableWidgetItem(data_fmt)
                item_data.setForeground(QColor("#e74c3c"))
                self.table_scadenze.setItem(r_idx, 0, item_data)
                
                self.table_scadenze.setItem(r_idx, 1, QTableWidgetItem(mov['descrizione'] or ""))
                
                item_imp = QTableWidgetItem(f"€ {mov['importo']:.2f}")
                item_imp.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item_imp.setForeground(QColor("#e74c3c"))
                self.table_scadenze.setItem(r_idx, 2, item_imp)
                
        except Exception as e:
            print(f"Errore caricamento fatture da pagare: {e}")

    def esporta_csv(self):
        percorso, _ = QFileDialog.getSaveFileName(self, "Esporta Movimenti", "", "CSV Files (*.csv)")
        if not percorso:
            return
            
        try:
            # PEEWEE ORM: Preleviamo tutti i dati per l'export in 1 riga
            movimenti = list(Movimento.select().where(Movimento.user == self.user_id).order_by(Movimento.data_op.desc()).dicts())
                
            # Usiamo utf-8-sig per garantire che Excel legga correttamente accenti e valute
            with open(percorso, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';') # Il punto e virgola divide le colonne per l'Excel italiano
                writer.writerow(["Data", "Tipo", "Categoria", "Descrizione", "Fornitore/Cliente", "Num. Fattura", "Imponibile", "IVA", "Totale", "Stato"])
                
                for mov in movimenti:
                    data = mov['data_op']
                    tipo = mov['tipo']
                    cat = mov['categoria'] or ""
                    desc = mov['descrizione'] or ""
                    
                    # Logica del COALESCE tradotta in Python
                    fornitore = mov['parser_supplier_name'] or mov['parser_customer_name'] or ""
                    num_fat = mov['parser_invoice_number'] or ""
                    
                    imp_val = float(mov['importo'] or 0)
                    iva_val = float(mov['iva_importo'] or 0)
                    tot_val = imp_val + iva_val
                    stato = mov['stato_pagamento'] or ""
                    
                    # Convertiamo i numeri in formato italiano (virgola invece del punto)
                    writer.writerow([
                        data, tipo, cat, desc, fornitore, num_fat, 
                        f"{imp_val:.2f}".replace('.', ','), 
                        f"{iva_val:.2f}".replace('.', ','), 
                        f"{tot_val:.2f}".replace('.', ','), 
                        stato
                    ])
                    
            QMessageBox.information(self, "Successo", f"Dati esportati correttamente in:\n{percorso}")
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile esportare i dati: {e}")