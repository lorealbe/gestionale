import sqlite3
from datetime import datetime
import pyqtgraph as pg

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton, QGridLayout, QSizePolicy
)

from database import get_conn

class DashboardPage(QWidget):
    # Segnale che avviserà il MainWindow di cambiare tab quando premiamo un'Azione Rapida
    richiesta_navigazione = Signal(str)

    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        
        self._build_ui()
        
        # Carichiamo i dati con un leggero ritardo per assicurarci che l'UI sia renderizzata
        QTimer.singleShot(100, self._carica_dati_finanziari)

    def showEvent(self, event):
        """Ogni volta che si apre la pagina Dashboard, aggiorna i numeri"""
        super().showEvent(event)
        self._carica_dati_finanziari()

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

        grid_azioni.addWidget(btn_mappa)
        grid_azioni.addWidget(btn_spesa)
        grid_azioni.addWidget(btn_macchinari)
        grid_azioni.addWidget(btn_animali)

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
        self.legend = self.plot_spese.addLegend(offset=(10, 10))
        
        # FIX IMPORTANTE: Garantisce uno spazio fisso di 50px in basso affinché le scritte non escano fuori
        self.plot_spese.getPlotItem().getAxis('bottom').setHeight(50)
        
        grafico_vbox.addWidget(self.plot_spese)

        finanza_layout.addWidget(grafico_frame, 70) # Prende il 70% dello spazio orizzontale

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

    # --- LOGICA DEI DATI ---
    def _carica_dati_finanziari(self):
        try:
            with get_conn() as conn:
                c = conn.cursor()
                
                # Calcolo Ricavi globali dalla tabella generale 'movimenti'
                c.execute("SELECT SUM(importo) FROM movimenti WHERE user_id=? AND tipo='ENTRATA'", (self.user_id,))
                ricavi = float(c.fetchone()[0] or 0.0)

                # Calcolo Spese globali dalla tabella generale 'movimenti'
                c.execute("SELECT SUM(importo) FROM movimenti WHERE user_id=? AND tipo='USCITA'", (self.user_id,))
                spese = float(c.fetchone()[0] or 0.0)

                # Classifica bilancio per categoria (calcola sia entrate che uscite per ogni categoria)
                c.execute("""
                    SELECT 
                        COALESCE(NULLIF(TRIM(categoria), ''), 'Non categorizzato') as cat, 
                        SUM(CASE WHEN tipo='ENTRATA' THEN importo ELSE 0 END) as tot_entrate,
                        SUM(CASE WHEN tipo='USCITA' THEN importo ELSE 0 END) as tot_uscite
                    FROM movimenti 
                    WHERE user_id=?
                    GROUP BY cat 
                    ORDER BY (SUM(CASE WHEN tipo='ENTRATA' THEN importo ELSE 0 END) + SUM(CASE WHEN tipo='USCITA' THEN importo ELSE 0 END)) DESC
                """, (self.user_id,))
                dati_categorie = c.fetchall()

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