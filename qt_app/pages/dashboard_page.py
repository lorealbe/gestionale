import pyqtgraph as pg
import csv

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton, QSizePolicy, QTableWidget, QHeaderView, QTableWidgetItem, 
    QAbstractItemView, QMessageBox, QFileDialog
)

# IMPORT PEEWEE
from app_utils import ImpostazioniAziendaDialog
from models import Movimento, db
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
        layout.setSpacing(15)

        # ==========================================
        # 1. HEADER (Titolo)
        # ==========================================
        header_layout = QVBoxLayout()
        header_layout.setSpacing(2)
        titolo = QLabel("Cruscotto Aziendale")
        titolo.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        sottotitolo = QLabel("Panoramica finanziaria e azioni rapide per la gestione quotidiana.")
        sottotitolo.setStyleSheet("font-size: 13px; color: #7f8c8d;")
        header_layout.addWidget(titolo)
        header_layout.addWidget(sottotitolo)
        layout.addLayout(header_layout)

        # ==========================================
        # 2. SEZIONE AZIONI RAPIDE
        # ==========================================
        azioni_frame = QFrame()
        # QSizePolicy.Fixed in verticale garantisce che i bottoni non rubino spazio al grafico
        azioni_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        azioni_frame.setStyleSheet("background-color: #f8f9fa; border: 1px solid #e1e8ed; border-radius: 8px;")
        azioni_layout = QVBoxLayout(azioni_frame)
        azioni_layout.setContentsMargins(15, 10, 15, 15)

        lbl_azioni = QLabel("⚡ Azioni Rapide")
        lbl_azioni.setStyleSheet("font-size: 14px; font-weight: bold; color: #34495e; border: none;")
        azioni_layout.addWidget(lbl_azioni)

        grid_azioni = QHBoxLayout()
        grid_azioni.setSpacing(10)

        # Creazione dei bottoni (Testi brevi su una singola riga per evitare tagli verticali)
        btn_mappa = self._crea_bottone_azione("📍 Campi", "#27ae60")
        btn_mappa.clicked.connect(lambda: self.richiesta_navigazione.emit("agricoltura"))

        btn_spesa = self._crea_bottone_azione("💶 Fatture", "#e74c3c")
        btn_spesa.clicked.connect(lambda: self.richiesta_navigazione.emit("fatture"))

        btn_macchinari = self._crea_bottone_azione("🚜 Mezzi", "#f39c12")
        btn_macchinari.clicked.connect(lambda: self.richiesta_navigazione.emit("macchinari"))

        btn_animali = self._crea_bottone_azione("🐄 Stalla", "#8e44ad")
        btn_animali.clicked.connect(lambda: self.richiesta_navigazione.emit("zootecnia"))

        btn_esporta = self._crea_bottone_azione("📤 Esporta (Excel)", "#34495e")
        btn_esporta.clicked.connect(self._esporta_commercialista_csv)

        btn_impostazioni = self._crea_bottone_azione("👤 Profilo Azienda", "#7f8489")
        btn_impostazioni.clicked.connect(self.apri_impostazioni)
        # Lo aggiungi al layout in alto a destra...


        grid_azioni.addWidget(btn_mappa)
        grid_azioni.addWidget(btn_spesa)
        grid_azioni.addWidget(btn_macchinari)
        grid_azioni.addWidget(btn_animali)
        grid_azioni.addWidget(btn_esporta)
        grid_azioni.addWidget(btn_impostazioni)

        azioni_layout.addLayout(grid_azioni)
        layout.addWidget(azioni_frame)

        # ==========================================
        # 3. SEZIONE STATO ECONOMICO
        # ==========================================
        # Contenitore elastico per la zona finanziaria
        finanza_container = QWidget()
        finanza_layout = QHBoxLayout(finanza_container)
        finanza_layout.setContentsMargins(0, 0, 0, 0)
        finanza_layout.setSpacing(15)

        # --- PANNELLO KPI (A Sinistra) ---
        kpi_frame = QFrame()
        kpi_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        kpi_frame.setStyleSheet("background-color: white; border: 1px solid #e1e8ed; border-radius: 8px;")
        kpi_vbox = QVBoxLayout(kpi_frame)
        kpi_vbox.setContentsMargins(15, 15, 15, 15)
        kpi_vbox.setSpacing(10)

        lbl_finanza = QLabel("📊 Bilancio Totale")
        lbl_finanza.setStyleSheet("font-size: 14px; font-weight: bold; color: #34495e; border: none;")
        kpi_vbox.addWidget(lbl_finanza)

        # Contenitori modificabili dinamicamente
        self.lbl_ricavi = self._crea_kpi_label("Ricavi Totali", "0.00 €", "#28a745")
        self.lbl_spese = self._crea_kpi_label("Spese Totali", "0.00 €", "#dc3545")
        self.lbl_utile = self._crea_kpi_label("Utile Netto", "0.00 €", "#007bff", font_size="22px")

        kpi_vbox.addWidget(self.lbl_ricavi)
        kpi_vbox.addWidget(self.lbl_spese)
        kpi_vbox.addWidget(self.lbl_utile)
        kpi_vbox.addStretch()

        finanza_layout.addWidget(kpi_frame, 30) # Prende il 30% dello spazio orizzontale

        # --- GRAFICO RIPARTIZIONE SPESE (A Destra) ---
        grafico_frame = QFrame()
        grafico_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        grafico_frame.setStyleSheet("background-color: white; border: 1px solid #e1e8ed; border-radius: 8px; padding: 10px;")
        grafico_vbox = QVBoxLayout(grafico_frame)

        lbl_grafico = QLabel("📉 Entrate e Uscite")
        lbl_grafico.setStyleSheet("font-size: 14px; font-weight: bold; color: #7f8c8d; border: none;")
        grafico_vbox.addWidget(lbl_grafico)

        self.plot_spese = pg.PlotWidget()
        self.plot_spese.setBackground('w')
        self.plot_spese.showGrid(x=False, y=True, alpha=0.3)
        self.plot_spese.setMouseEnabled(x=False, y=False)
        self.plot_spese.setMenuEnabled(False)
        self.plot_spese.hideButtons()
        self.legend = self.plot_spese.addLegend(offset=(-10, 10))
        
        self.plot_spese.getPlotItem().getAxis('bottom').setHeight(50)

        font_assi = QFont()
        font_assi.setPointSize(9) # Impostiamo un point-size esplicito > 0
        self.plot_spese.getPlotItem().getAxis('bottom').setTickFont(font_assi)
        self.plot_spese.getPlotItem().getAxis('left').setTickFont(font_assi)
        
        grafico_vbox.addWidget(self.plot_spese)


        # ==========================================
        # NUOVO ASSEGNO DEGLI SPAZI (20% KPI, 45% Grafico, 35% Scadenze)
        # ==========================================
        finanza_layout.addWidget(kpi_frame, 20) 
        finanza_layout.addWidget(grafico_frame, 45)

        # --- PANNELLO SCADENZIARIO (A Destra) ---
        self.scadenze_frame = QFrame()
        self.scadenze_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.scadenze_frame.setStyleSheet("background-color: white; border: 1px solid #e1e8ed; border-radius: 8px; padding: 5px;")
        scadenze_vbox = QVBoxLayout(self.scadenze_frame)
        scadenze_vbox.setContentsMargins(10, 10, 10, 10)
        
        lbl_scadenze = QLabel("🚨 Da Pagare")
        lbl_scadenze.setStyleSheet("font-size: 14px; font-weight: bold; color: #c0392b; border: none;")
        scadenze_vbox.addWidget(lbl_scadenze)
        
        # Creazione della tabella delle scadenze
        self.table_scadenze = QTableWidget()
        self.table_scadenze.setColumnCount(4)
        self.table_scadenze.setHorizontalHeaderLabels(["Data", "Descrizione", "Importo", ""])
        self.table_scadenze.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_scadenze.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_scadenze.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_scadenze.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_scadenze.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_scadenze.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_scadenze.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_scadenze.verticalHeader().setVisible(False)
        self.table_scadenze.setStyleSheet("""
            QTableWidget { border: none; }
            QHeaderView::section { font-weight: bold; border: none; border-bottom: 1px solid #ddd; background-color: white; }
        """)
        
        scadenze_vbox.addWidget(self.table_scadenze)
        
        # Aggiungiamo il pannello scadenze al contenitore orizzontale
        finanza_layout.addWidget(self.scadenze_frame, 35)

        # Stretch=1 indica al contenitore finanziario di espandersi verticalmente prendendosi tutto lo spazio rimasto
        layout.addWidget(finanza_container, 1)

    # --- FUNZIONI DI SUPPORTO GRAFICO ---
    def _crea_bottone_azione(self, testo, colore):
        btn = QPushButton(testo)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.setMinimumHeight(60) # Altezza ideale per testi a singola riga
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: white;
                color: {colore};
                border: 2px solid {colore};
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
                padding: 5px;
            }}
            QPushButton:hover {{
                background-color: {colore};
                color: white;
            }}
        """)
        return btn

    def _crea_kpi_label(self, titolo, valore, colore, font_size="18px"):
        container = QFrame()
        container.setStyleSheet(f"border-left: 5px solid {colore}; background-color: #f8f9fa; padding: 8px; border-radius: 5px;")
        lay = QVBoxLayout(container)
        lay.setContentsMargins(10, 5, 10, 5)

        lbl_tit = QLabel(titolo)
        lbl_tit.setStyleSheet("color: #7f8c8d; font-size: 12px; font-weight: bold; border: none; background: transparent;")

        lbl_val = QLabel(valore)
        lbl_val.setStyleSheet(f"color: {colore}; font-size: {font_size}; font-weight: 900; border: none; background: transparent;")

        lay.addWidget(lbl_tit)
        lay.addWidget(lbl_val)
        return container

    # --- LOGICA DEI DATI (ORA IN PEEWEE) ---
    def _carica_dati_finanziari(self):
        try:
            # 1. Ricavi globali
            ricavi = Movimento.select(fn.SUM(Movimento.importo)).where((Movimento.user == self.user_id) & (Movimento.tipo == 'ENTRATA')).scalar() or 0.0
            
            # 2. Spese globali
            spese = Movimento.select(fn.SUM(Movimento.importo)).where((Movimento.user == self.user_id) & (Movimento.tipo == 'USCITA')).scalar() or 0.0

            # 3. Classifica bilancio per categoria
            movimenti = Movimento.select(Movimento.categoria, Movimento.tipo, Movimento.importo).where(Movimento.user == self.user_id).dicts()
            
            categorie_dict = {}
            for m in movimenti:
                cat_raw = m.get('categoria')
                cat = cat_raw.strip() if cat_raw and cat_raw.strip() else 'Non categorizzato'
                
                if cat not in categorie_dict:
                    categorie_dict[cat] = {'entrate': 0.0, 'uscite': 0.0}
                    
                importo_val = float(m.get('importo') or 0.0)
                if m.get('tipo') == 'ENTRATA':
                    categorie_dict[cat]['entrate'] += importo_val
                elif m.get('tipo') == 'USCITA':
                    categorie_dict[cat]['uscite'] += importo_val
            
            dati_categorie = []
            for cat, vals in categorie_dict.items():
                dati_categorie.append((cat, vals['entrate'], vals['uscite']))
            
            # Ordina per volume totale (entrate + uscite) decrescente
            dati_categorie.sort(key=lambda x: x[1] + x[2], reverse=True)

        except Exception as e:
            print("Errore caricamento dati dashboard:", e)
            return

        utile = ricavi - spese

        # 1. Aggiornamento Testi KPI
        self.lbl_ricavi.findChildren(QLabel)[1].setText(f"{ricavi:,.2f} €")
        self.lbl_spese.findChildren(QLabel)[1].setText(f"{spese:,.2f} €")
        self.lbl_utile.findChildren(QLabel)[1].setText(f"{utile:,.2f} €")
        
        # Colore dinamico per l'utile
        if utile < 0:
            self.lbl_utile.setStyleSheet("border-left: 5px solid #dc3545; background-color: #f8f9fa; padding: 8px; border-radius: 5px;")
            self.lbl_utile.findChildren(QLabel)[1].setStyleSheet("color: #dc3545; font-size: 22px; font-weight: 900; border: none; background: transparent;")
        else:
            self.lbl_utile.setStyleSheet("border-left: 5px solid #007bff; background-color: #f8f9fa; padding: 8px; border-radius: 5px;")
            self.lbl_utile.findChildren(QLabel)[1].setStyleSheet("color: #007bff; font-size: 22px; font-weight: 900; border: none; background: transparent;")

        # 2. Aggiornamento Grafico a Barre Doppie
        self.plot_spese.clear()
        if not dati_categorie:
            self.plot_spese.setTitle("Nessun movimento registrato.", color='#7f8c8d', size="11pt")
            return

        self.plot_spese.setTitle("")
        
        # Abbreviazioni per far entrare i testi sotto le barre
        abbreviazioni = {
            "Sementi/Piantine": "Sementi",
            "Concimi/Fertilizzanti": "Concimi",
            "Fitofarmaci": "Fito",
            "Gasolio/Energia": "Energia",
            "Lavorazioni Conto Terzi": "Terzisti",
            "Manodopera": "Lavoro",
            "Assicurazioni (Risarcimenti)": "Assicuraz.",
            "Irrigazione": "Acqua",
            "Non categorizzato": "Varie"
        }
        
        x_labels = []
        y_entrate = []
        y_uscite = []
        
        # Prepariamo le liste separate per entrate e uscite
        for row in dati_categorie:
            cat_nome = str(row[0])
            x_labels.append(abbreviazioni.get(cat_nome, cat_nome))
            y_entrate.append(float(row[1]))
            y_uscite.append(float(row[2]))

        # Creiamo le posizioni sfalsate sull'asse X (larghezza barra = 0.35)
        # Offset di -0.2 per le entrate e +0.2 per le uscite
        x_pos_entrate = [i - 0.2 for i in range(len(x_labels))]
        x_pos_uscite = [i + 0.2 for i in range(len(x_labels))]
        
        # Posizioniamo le etichette di testo esattamente al centro (su i)
        ticks = [list(zip(range(len(x_labels)), x_labels))]
        ax = self.plot_spese.getAxis('bottom')
        ax.setTicks(ticks)

        bar_width = 0.35
        
        # Creazione delle due serie di barre
        bar_chart_entrate = pg.BarGraphItem(x=x_pos_entrate, height=y_entrate, width=bar_width, brush='#28a745', pen='w', name="Entrate")
        bar_chart_uscite = pg.BarGraphItem(x=x_pos_uscite, height=y_uscite, width=bar_width, brush='#dc3545', pen='w', name="Uscite")

        self.plot_spese.addItem(bar_chart_entrate)
        self.plot_spese.addItem(bar_chart_uscite)

        # Regolazione dinamica della vista
        margine_destro = max(5.5, len(x_labels) - 0.5)
        self.plot_spese.setXRange(-0.5, margine_destro, padding=0)
        
        max_y = max(max(y_entrate + [0]), max(y_uscite + [0]))
        self.plot_spese.setYRange(0, max_y * 1.2 if max_y > 0 else 100, padding=0)
    
    def _carica_fatture_da_pagare(self):
        try:
            da_pagare_raw = list(Movimento.select().where(
                (Movimento.user == self.user_id) & (Movimento.stato_pagamento == 'DA PAGARE')
            ).dicts())
            
            # Ordina le fatture (Data scadenza se presente, altrimenti data operazione)
            def get_sort_date(m):
                due = str(m.get('parser_due_date') or '').strip()
                op = str(m.get('data_op') or '').strip()
                return due if due else op
                
            da_pagare_raw.sort(key=get_sort_date)
            righe = da_pagare_raw

        except Exception as e:
            print("Errore caricamento scadenze:", e)
            return

        self.table_scadenze.clearSpans()
        self.table_scadenze.setRowCount(0)
        
        # Se non c'è nulla da pagare, mostriamo un messaggio di rassicurazione
        if not righe:
            self.table_scadenze.setRowCount(1)
            item_ok = QTableWidgetItem("🎉 Tutto in regola! Nessun sospeso.")
            item_ok.setTextAlignment(Qt.AlignCenter)
            item_ok.setForeground(QColor("#7f8c8d"))
            self.table_scadenze.setSpan(0, 0, 1, 4)
            self.table_scadenze.setItem(0, 0, item_ok)
            return
            
        self.table_scadenze.setRowCount(len(righe))
        
        for idx, m in enumerate(righe):
            mov_id = m.get('id')
            data_op = str(m.get('data_op') or '')
            descrizione = str(m.get('descrizione') or "Senza descrizione").strip()
            importo = float(m.get('importo') or 0.0)
            iva = float(m.get('iva_importo') or 0.0)
            due_date = str(m.get('parser_due_date') or "").strip()
            tipo = str(m.get('tipo') or "").strip()
            
            totale = importo + iva
            data_mostrata = due_date if due_date else data_op
            
            # Formattazione grafica in base al fatto che noi dobbiamo pagare (Rosso) o incassare (Verde)
            if tipo == "USCITA":
                colore_testo = "#c0392b"
                icona = "📉 "
            else:
                colore_testo = "#27ae60"
                icona = "📈 "
                
            item_data = QTableWidgetItem(data_mostrata)
            item_desc = QTableWidgetItem(icona + descrizione)
            item_imp = QTableWidgetItem(f"{totale:,.2f} €")
            item_imp.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            
            for item in (item_data, item_desc, item_imp):
                item.setForeground(QColor(colore_testo))
            
            self.table_scadenze.setItem(idx, 0, item_data)
            self.table_scadenze.setItem(idx, 1, item_desc)
            self.table_scadenze.setItem(idx, 2, item_imp)
            
            # Creiamo dinamicamente il bottone per ogni riga
            btn_paga = QPushButton("Saldato ✔")
            btn_paga.setStyleSheet("background-color: #27ae60; color: white; border-radius: 4px; font-weight: bold; padding: 4px 8px;")
            btn_paga.setCursor(Qt.PointingHandCursor)
            
            # Utilizziamo una closure per intrappolare il valore di 'mov_id' in questo ciclo
            btn_paga.clicked.connect(lambda checked=False, m_id=mov_id: self._segna_come_pagato(m_id))
            
            widget_btn = QWidget()
            layout_btn = QHBoxLayout(widget_btn)
            layout_btn.setContentsMargins(5, 2, 5, 2)
            layout_btn.addWidget(btn_paga)
            
            self.table_scadenze.setCellWidget(idx, 3, widget_btn)

    def _segna_come_pagato(self, movimento_id):
        risposta = QMessageBox.question(
            self, "Conferma Pagamento", 
            "Vuoi segnare questo movimento come SALDATO?", 
            QMessageBox.Yes | QMessageBox.No
        )
        
        if risposta == QMessageBox.Yes:
            try:
                # PEEWEE: aggiorniamo il record
                Movimento.update(stato_pagamento='PAGATO').where(
                    (Movimento.id == movimento_id) & (Movimento.user == self.user_id)
                ).execute()
            except Exception as e:
                QMessageBox.critical(self, "Errore", f"Impossibile aggiornare lo stato: {e}")
                return
            
            # Ricarichiamo la tabella: la fattura scomparirà automaticamente dalle pendenze!
            self._carica_fatture_da_pagare()
    
    def _esporta_commercialista_csv(self):
        percorso, _ = QFileDialog.getSaveFileName(
            self, "Esporta Movimenti per Commercialista", "movimenti_agricoli.csv", "CSV Excel (*.csv)"
        )
        if not percorso:
            return
            
        try:
            # PEEWEE ORM: Preleviamo tutti i dati per l'export ordinati per data
            movimenti = list(Movimento.select().where(Movimento.user == self.user_id).order_by(Movimento.data_op.asc()).dicts())
                
            # Usiamo utf-8-sig per garantire che Excel legga correttamente accenti e valute
            with open(percorso, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';') # Il punto e virgola divide le colonne per l'Excel italiano
                writer.writerow(["Data", "Tipo", "Categoria", "Descrizione", "Fornitore/Cliente", "Num. Fattura", "Imponibile", "IVA", "Totale", "Stato"])
                
                for m in movimenti:
                    data = m.get('data_op', '')
                    tipo = m.get('tipo', '')
                    cat = m.get('categoria') or ''
                    desc = m.get('descrizione') or ''
                    imp_val = float(m.get('importo') or 0.0)
                    iva_val = float(m.get('iva_importo') or 0.0)
                    stato = m.get('stato_pagamento') or ''
                    
                    fornitore = m.get('parser_supplier_name') or m.get('parser_customer_name') or ''
                    num_fat = m.get('parser_invoice_number') or ''
                    
                    tot_val = imp_val + iva_val
                    
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
        
        
    def apri_impostazioni(self):
        dialog = ImpostazioniAziendaDialog(self.user_id, self)
        dialog.exec()