import sqlite3
from datetime import datetime
import pyqtgraph as pg
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDateEdit,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QSplitter
)

from app_utils import format_eur, format_number, TabellaIsolata
from database import get_conn


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

        # ==========================================
        # HEADER (Titolo)
        # ==========================================
        header_layout = QVBoxLayout()
        header_layout.setSpacing(2)
        titolo = QLabel("📈 Report e Bilancio Aziendale")
        titolo.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        sottotitolo = QLabel("Analizza entrate, uscite e le statistiche economiche nel dettaglio.")
        sottotitolo.setStyleSheet("font-size: 14px; color: #7f8c8d;")
        header_layout.addWidget(titolo)
        header_layout.addWidget(sottotitolo)
        main_layout.addLayout(header_layout)

        # ==========================================
        # FILTRI (Card)
        # ==========================================
        filtri_frame = QFrame(self)
        filtri_frame.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        filtri_layout = QVBoxLayout(filtri_frame)
        filtri_layout.setContentsMargins(15, 15, 15, 15)
        filtri_layout.setSpacing(10)

        self.checkbox_usa_filtro = QCheckBox("Usa filtro periodo", self)
        self.checkbox_usa_filtro.setStyleSheet("font-weight: bold; color: #2c3e50; border: none;")
        self.checkbox_usa_filtro.setChecked(False)
        self.checkbox_usa_filtro.toggled.connect(self._on_toggle_filtro_periodo)
        filtri_layout.addWidget(self.checkbox_usa_filtro)

        form_filtri = QFormLayout()
        form_filtri.setLabelAlignment(Qt.AlignLeft)
        form_filtri.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.data_inizio = QDateEdit(self)
        self.data_inizio.setStyleSheet("padding: 5px; background-color: white; border: 1px solid #ccc; border-radius: 3px;")
        self.data_inizio.setDisplayFormat("dd/MM/yyyy")
        self.data_inizio.setCalendarPopup(True)

        self.data_fine = QDateEdit(self)
        self.data_fine.setStyleSheet("padding: 5px; background-color: white; border: 1px solid #ccc; border-radius: 3px;")
        self.data_fine.setDisplayFormat("dd/MM/yyyy")
        self.data_fine.setCalendarPopup(True)

        form_filtri.addRow("<b>Data INIZIO:</b>", self.data_inizio)
        form_filtri.addRow("<b>Data FINE:</b>", self.data_fine)
        filtri_layout.addLayout(form_filtri)

        bottoni_filtri = QHBoxLayout()
        bottoni_filtri.setSpacing(10)

        button_aggiorna = QPushButton("📊 Genera Report")
        button_aggiorna.setStyleSheet(STYLE_BTN_INFO)
        button_aggiorna.setCursor(Qt.PointingHandCursor)
        button_aggiorna.clicked.connect(lambda: self.genera_report(show_errors=True))
        bottoni_filtri.addWidget(button_aggiorna)

        button_default = QPushButton("Periodo Storico Completo")
        button_default.setStyleSheet(STYLE_BTN_SECONDARIO)
        button_default.setCursor(Qt.PointingHandCursor)
        button_default.clicked.connect(lambda: self._reset_and_refresh(show_errors=True))
        bottoni_filtri.addWidget(button_default)

        bottoni_filtri.addStretch(1)
        filtri_layout.addLayout(bottoni_filtri)

        main_layout.addWidget(filtri_frame)

        # ==========================================
        # SISTEMA A SCHEDE (TABS)
        # ==========================================
        self.tabs = QTabWidget(self)
        self.tabs.setStyleSheet("QTabWidget::pane { border: 1px solid #ccc; border-radius: 4px; background-color: white; }")
        main_layout.addWidget(self.tabs, 1)

        # ------------------------------------------
        # SCHEDA 1: TABELLE (Splitter con proporzioni forzate)
        # ------------------------------------------
        self.tab_tabelle = QWidget()
        tabelle_layout = QVBoxLayout(self.tab_tabelle)
        tabelle_layout.setContentsMargins(15, 15, 15, 15)

        splitter_tabelle = QSplitter(Qt.Vertical)

        # -- Widget Riepilogo (Sopra)
        widget_riepilogo = QWidget()
        layout_riepilogo = QVBoxLayout(widget_riepilogo)
        layout_riepilogo.setContentsMargins(0, 0, 0, 0)
        
        riepilogo_label = QLabel("Riepilogo Aziendale")
        riepilogo_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #34495e;")
        layout_riepilogo.addWidget(riepilogo_label)

        self.table_riepilogo = TabellaIsolata(0, 2, self)
        self.table_riepilogo.setHorizontalHeaderLabels(["Metrica", "Valore"])
        self.table_riepilogo.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_riepilogo.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_riepilogo.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_riepilogo.setAlternatingRowColors(True)
        self.table_riepilogo.verticalHeader().setVisible(False)
        self.table_riepilogo.setStyleSheet("QTableWidget { border: 1px solid #ccc; border-radius: 5px; } QHeaderView::section { background-color: #f8f9fa; font-weight: bold; border: 1px solid #ddd; padding: 4px; }")
        
        # FIX: Forziamo l'espansione e un'altezza minima garantita
        self.table_riepilogo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table_riepilogo.setMinimumHeight(240) # Misura esatta per ospitare le 7 righe + header

        riepilogo_header = self.table_riepilogo.horizontalHeader()
        riepilogo_header.setSectionResizeMode(0, QHeaderView.Stretch)
        riepilogo_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        layout_riepilogo.addWidget(self.table_riepilogo)
        
        splitter_tabelle.addWidget(widget_riepilogo)

        # -- Widget Categorie (Sotto)
        widget_categorie = QWidget()
        layout_categorie = QVBoxLayout(widget_categorie)
        layout_categorie.setContentsMargins(0, 0, 0, 0)

        dettaglio_label = QLabel("Dettaglio Analitico per Categoria")
        dettaglio_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #34495e; padding-top: 10px;")
        layout_categorie.addWidget(dettaglio_label)

        self.table_categorie = TabellaIsolata(0, 4, self)
        self.table_categorie.setHorizontalHeaderLabels(["Tipo", "Categoria", "Totale", "N. Movimenti"])
        self.table_categorie.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_categorie.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_categorie.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_categorie.setAlternatingRowColors(True)
        self.table_categorie.verticalHeader().setVisible(False)
        self.table_categorie.setStyleSheet("QTableWidget { border: 1px solid #ccc; border-radius: 5px; } QHeaderView::section { background-color: #f8f9fa; font-weight: bold; border: 1px solid #ddd; padding: 4px; }")
        
        # FIX: Forziamo l'espansione
        self.table_categorie.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table_categorie.setMinimumHeight(200)

        categorie_header = self.table_categorie.horizontalHeader()
        categorie_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        categorie_header.setSectionResizeMode(1, QHeaderView.Stretch)
        categorie_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        categorie_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout_categorie.addWidget(self.table_categorie)
        
        splitter_tabelle.addWidget(widget_categorie)

        # Distribuzione dinamica del peso nello splitter (40% sopra, 60% sotto)
        splitter_tabelle.setStretchFactor(0, 1)
        splitter_tabelle.setStretchFactor(1, 2)
        tabelle_layout.addWidget(splitter_tabelle)

        self.tabs.addTab(self.tab_tabelle, "Dati e Tabelle")

        # ------------------------------------------
        # SCHEDA 2: GRAFICI INTERATTIVI
        # ------------------------------------------
        self.tab_grafici = QWidget()
        grafici_layout = QVBoxLayout(self.tab_grafici)
        grafici_layout.setContentsMargins(15, 15, 15, 15)
        grafici_layout.setSpacing(15)

        # 1. Grafico Linee (Trend)
        self.plot_trend = pg.PlotWidget(title="Trend Mensile (Entrate vs Uscite)")
        self.plot_trend.setBackground('w') 
        self.plot_trend.showGrid(x=True, y=True, alpha=0.3)
        self.plot_trend.addLegend()
        self.plot_trend.getPlotItem().getAxis('bottom').setHeight(40)
        grafici_layout.addWidget(self.plot_trend)

        # 2. Grafico Barre (Analisi Spese)
        self.plot_categorie = pg.PlotWidget(title="Top Costi Aziendali per Categoria")
        self.plot_categorie.setBackground('w')
        self.plot_categorie.showGrid(x=False, y=True, alpha=0.3)
        self.plot_categorie.getPlotItem().getAxis('bottom').setHeight(45)
        grafici_layout.addWidget(self.plot_categorie)

        self.tabs.addTab(self.tab_grafici, "Grafici Interattivi")

        self._on_toggle_filtro_periodo(False)

    def _on_toggle_filtro_periodo(self, enabled: bool):
        self.data_inizio.setEnabled(enabled)
        self.data_fine.setEnabled(enabled)

    def _reset_and_refresh(self, show_errors: bool):
        self.imposta_periodo_default(show_errors=show_errors)
        self.genera_report(show_errors=show_errors)

    def imposta_periodo_default(self, show_errors: bool = True):
        oggi = QDate.currentDate()
        data_inizio = oggi
        data_fine = oggi

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT MIN(data_op), MAX(data_op) FROM movimenti WHERE user_id=?", (self.user_id,))
                row = c.fetchone()

            if row and row[0]:
                inizio_dt = datetime.strptime(row[0], "%Y-%m-%d")
                fine_dt = datetime.strptime(row[1] or row[0], "%Y-%m-%d")
                data_inizio = QDate(inizio_dt.year, inizio_dt.month, inizio_dt.day)
                data_fine = QDate(fine_dt.year, fine_dt.month, fine_dt.day)
        except (sqlite3.Error, ValueError) as exc:
            if show_errors:
                QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")

        self.data_inizio.setDate(data_inizio)
        self.data_fine.setDate(data_fine)

    def _calcola_totali_manutenzioni_azienda(
        self,
        data_da_db: str | None = None,
        data_a_db: str | None = None,
        show_errors: bool = True,
    ):
        params = [self.user_id]
        where_clause = "WHERE user_id=?"

        if data_da_db and data_a_db:
            where_clause += " AND data_manutenzione BETWEEN ? AND ?"
            params.extend([data_da_db, data_a_db])

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    f"""
                    SELECT
                        COALESCE(SUM(COALESCE(costo, 0)), 0),
                        COUNT(id)
                    FROM manutenzioni_macchinari
                    {where_clause}
                """,
                    tuple(params),
                )
                row = c.fetchone()
        except sqlite3.Error as exc:
            if show_errors:
                QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return 0.0, 0

        totale = float((row[0] if row else 0) or 0)
        numero = int((row[1] if row else 0) or 0)
        return totale, numero

    def _append_table_row(self, table: QTableWidget, row_index: int, values: list[str], right_align_indexes=None):
        if right_align_indexes is None:
            right_align_indexes = []

        table.setRowCount(row_index + 1)

        for col_index, value in enumerate(values):
            item = QTableWidgetItem(value)
            if col_index in right_align_indexes:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            else:
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            table.setItem(row_index, col_index, item)

    def genera_report(self, show_errors: bool = True):
        use_filter = bool(self.checkbox_usa_filtro.isChecked())
        data_inizio_db = None
        data_fine_db = None
        params = [self.user_id]
        where_clause = "WHERE user_id=?"
        periodo_label = "Storico completo"

        if use_filter:
            data_inizio = self.data_inizio.date()
            data_fine = self.data_fine.date()

            if data_inizio > data_fine:
                if show_errors:
                    QMessageBox.critical(self, "Errore", "La data INIZIO non puo essere successiva alla data FINE.")
                return

            data_inizio_db = data_inizio.toString("yyyy-MM-dd")
            data_fine_db = data_fine.toString("yyyy-MM-dd")
            where_clause += " AND data_op BETWEEN ? AND ?"
            params.extend([data_inizio_db, data_fine_db])
            periodo_label = f"{data_inizio.toString('dd/MM/yyyy')} - {data_fine.toString('dd/MM/yyyy')}"

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    f"""
                    SELECT
                        COUNT(id),
                        COALESCE(SUM(CASE WHEN tipo='ENTRATA' THEN importo ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN tipo='USCITA' THEN importo ELSE 0 END), 0),
                        COALESCE(SUM(iva_importo), 0)
                    FROM movimenti
                    {where_clause}
                """,
                    tuple(params),
                )
                row = c.fetchone()

                c.execute(
                    f"""
                    SELECT
                        tipo,
                        COALESCE(NULLIF(TRIM(categoria), ''), '(Senza categoria)') AS categoria,
                        COALESCE(SUM(importo), 0) AS totale,
                        COUNT(id) AS qta
                    FROM movimenti
                    {where_clause}
                    GROUP BY tipo, categoria
                    ORDER BY tipo, totale DESC
                """,
                    tuple(params),
                )
                righe_categoria = c.fetchall()
        except sqlite3.Error as exc:
            if show_errors:
                QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        numero_movimenti = int((row[0] if row else 0) or 0)
        tot_entrate = float((row[1] if row else 0) or 0)
        tot_uscite_movimenti = float((row[2] if row else 0) or 0)
        tot_uscite_manutenzioni, numero_manutenzioni = self._calcola_totali_manutenzioni_azienda(
            data_da_db=data_inizio_db,
            data_a_db=data_fine_db,
            show_errors=show_errors,
        )
        tot_uscite = tot_uscite_movimenti + tot_uscite_manutenzioni
        tot_iva = float((row[3] if row else 0) or 0)
        saldo = tot_entrate - tot_uscite

        righe_riepilogo = [
            ("Periodo", periodo_label),
            ("Movimenti totali", str(numero_movimenti)),
            ("Totale Entrate", format_eur(tot_entrate)),
            ("Uscite manutenzioni", format_eur(tot_uscite_manutenzioni)),
            ("Totale Uscite", format_eur(tot_uscite)),
            ("Totale IVA", format_eur(tot_iva)),
            ("Saldo Netto", format_eur(saldo)),
        ]

        self.table_riepilogo.setRowCount(0)
        for row_index, (metrica, valore) in enumerate(righe_riepilogo):
            self._append_table_row(self.table_riepilogo, row_index, [metrica, valore], right_align_indexes=[1])

        self.table_categorie.setRowCount(0)
        categorie_rows = []
        for tipo, categoria, totale, qta in righe_categoria:
            categorie_rows.append(
                [
                    str(tipo or "-"),
                    str(categoria or "-"),
                    format_eur(float(totale or 0)),
                    format_number(int(qta or 0), 0),
                ]
            )

        if numero_manutenzioni > 0 or abs(tot_uscite_manutenzioni) > 1e-9:
            categorie_rows.append(
                [
                    "USCITA",
                    "Manutenzioni macchinari",
                    format_eur(tot_uscite_manutenzioni),
                    format_number(int(numero_manutenzioni), 0),
                ]
            )

        for row_index, values in enumerate(categorie_rows):
            self._append_table_row(self.table_categorie, row_index, values, right_align_indexes=[2, 3])

        # ==========================================
        # AGGIORNAMENTO GRAFICI PYQTGRAPH
        # ==========================================
        
        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    f"""
                    SELECT
                        strftime('%Y-%m', data_op) as mese,
                        COALESCE(SUM(CASE WHEN tipo='ENTRATA' THEN importo ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN tipo='USCITA' THEN importo ELSE 0 END), 0)
                    FROM movimenti
                    {where_clause}
                    GROUP BY mese
                    ORDER BY mese
                """,
                    tuple(params),
                )
                trend_rows = c.fetchall()
        except sqlite3.Error:
            trend_rows = []

        self.plot_trend.clear()
        mesi_ticks = []
        entrate_vals = []
        uscite_vals = []

        for idx, (mese, ent, usc) in enumerate(trend_rows):
            mesi_ticks.append((idx, str(mese)))
            entrate_vals.append(ent)
            uscite_vals.append(usc)

        if mesi_ticks:
            ax = self.plot_trend.getAxis('bottom')
            ax.setTicks([mesi_ticks])
            self.plot_trend.plot(
                [x[0] for x in mesi_ticks], entrate_vals, 
                pen=pg.mkPen(color='#28a745', width=3), name="Entrate", symbol='o', symbolBrush='#28a745'
            )
            self.plot_trend.plot(
                [x[0] for x in mesi_ticks], uscite_vals, 
                pen=pg.mkPen(color='#dc3545', width=3), name="Uscite", symbol='t', symbolBrush='#dc3545'
            )

        self.plot_categorie.clear()

        spese = [(cat, tot) for tipo, cat, tot, qta in righe_categoria if tipo == "USCITA"]
        if tot_uscite_manutenzioni > 0:
            spese.append(("Manutenzioni", tot_uscite_manutenzioni))

        spese = sorted(spese, key=lambda x: float(x[1] or 0), reverse=True)[:8]

        if spese:
            cat_ticks = [(idx, str(cat)[:12] + ("." if len(str(cat))>12 else "")) for idx, (cat, tot) in enumerate(spese)]
            valori = [float(tot) for cat, tot in spese]

            ax_cat = self.plot_categorie.getAxis('bottom')
            ax_cat.setTicks([cat_ticks])

            bar_chart = pg.BarGraphItem(x=[x[0] for x in cat_ticks], height=valori, width=0.6, brush='#007bff', pen='w')
            self.plot_categorie.addItem(bar_chart)