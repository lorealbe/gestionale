import sqlite3
from datetime import datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_utils import format_number, parse_decimal
from database import get_conn
from services.product_parser_utils import (
    PRODUCT_CATEGORY_OPTIONS,
    extract_products_rows_from_parser_text,
    normalize_cost_type,
    normalize_product_category,
)


class AziendaProdottiPage(QWidget):
    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = int(user_id)

        self._build_ui()
        self.carica_storico_prodotti(show_errors=False)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.label_stato = QLabel("Nessun prodotto caricato.")
        top_row.addWidget(self.label_stato)
        top_row.addStretch(1)

        button_ricarica = QPushButton("Ricarica", self)
        button_ricarica.clicked.connect(lambda: self.carica_storico_prodotti(show_errors=True))
        top_row.addWidget(button_ricarica)

        main_layout.addLayout(top_row)

        frame_filtri = QFrame(self)
        frame_filtri.setFrameShape(QFrame.StyledPanel)
        layout_filtri = QGridLayout(frame_filtri)
        layout_filtri.setContentsMargins(10, 10, 10, 10)
        layout_filtri.setHorizontalSpacing(8)
        layout_filtri.setVerticalSpacing(8)

        self.check_data_da = QCheckBox("Data mov. da", self)
        self.check_data_da.toggled.connect(self._on_toggle_data_filters)
        self.date_data_da = QDateEdit(self)
        self.date_data_da.setDisplayFormat("dd/MM/yyyy")
        self.date_data_da.setCalendarPopup(True)
        self.date_data_da.setDate(QDate.currentDate())
        self.date_data_da.setEnabled(False)

        self.check_data_a = QCheckBox("a", self)
        self.check_data_a.toggled.connect(self._on_toggle_data_filters)
        self.date_data_a = QDateEdit(self)
        self.date_data_a.setDisplayFormat("dd/MM/yyyy")
        self.date_data_a.setCalendarPopup(True)
        self.date_data_a.setDate(QDate.currentDate())
        self.date_data_a.setEnabled(False)

        self.combo_tipo_costo = QComboBox(self)
        self.combo_tipo_costo.addItems(["Tutti", "Variabili", "Fissi"])
        self.combo_tipo_costo.currentIndexChanged.connect(self._on_filter_changed)

        layout_filtri.addWidget(self.check_data_da, 0, 0)
        layout_filtri.addWidget(self.date_data_da, 0, 1)
        layout_filtri.addWidget(self.check_data_a, 0, 2)
        layout_filtri.addWidget(self.date_data_a, 0, 3)
        layout_filtri.addWidget(QLabel("Tipo costo:"), 0, 4)
        layout_filtri.addWidget(self.combo_tipo_costo, 0, 5)

        self.input_numero_fattura = QLineEdit(self)
        self.input_numero_fattura.setPlaceholderText("N. fattura")
        self.input_numero_fattura.returnPressed.connect(lambda: self.carica_storico_prodotti(show_errors=True))

        self.input_fornitore = QLineEdit(self)
        self.input_fornitore.setPlaceholderText("Fornitore")
        self.input_fornitore.returnPressed.connect(lambda: self.carica_storico_prodotti(show_errors=True))

        layout_filtri.addWidget(QLabel("N. fattura:"), 1, 0)
        layout_filtri.addWidget(self.input_numero_fattura, 1, 1)
        layout_filtri.addWidget(QLabel("Fornitore:"), 1, 2)
        layout_filtri.addWidget(self.input_fornitore, 1, 3, 1, 3)

        self.input_prodotto = QLineEdit(self)
        self.input_prodotto.setPlaceholderText("Prodotto")
        self.input_prodotto.returnPressed.connect(lambda: self.carica_storico_prodotti(show_errors=True))

        self.combo_categoria = QComboBox(self)
        self.combo_categoria.addItems(["Tutte", *PRODUCT_CATEGORY_OPTIONS])
        self.combo_categoria.currentIndexChanged.connect(self._on_filter_changed)

        self.input_gruppo = QLineEdit(self)
        self.input_gruppo.setPlaceholderText("Gruppo")
        self.input_gruppo.returnPressed.connect(lambda: self.carica_storico_prodotti(show_errors=True))

        layout_filtri.addWidget(QLabel("Prodotto:"), 2, 0)
        layout_filtri.addWidget(self.input_prodotto, 2, 1)
        layout_filtri.addWidget(QLabel("Categoria:"), 2, 2)
        layout_filtri.addWidget(self.combo_categoria, 2, 3)
        layout_filtri.addWidget(QLabel("Gruppo:"), 2, 4)
        layout_filtri.addWidget(self.input_gruppo, 2, 5)

        row_buttons = QHBoxLayout()
        row_buttons.setSpacing(8)

        button_applica = QPushButton("Applica filtri", self)
        button_applica.clicked.connect(lambda: self.carica_storico_prodotti(show_errors=True))
        row_buttons.addWidget(button_applica)

        button_pulisci = QPushButton("Pulisci", self)
        button_pulisci.clicked.connect(self.pulisci_filtri)
        row_buttons.addWidget(button_pulisci)

        row_buttons.addStretch(1)
        layout_filtri.addLayout(row_buttons, 3, 0, 1, 6)

        main_layout.addWidget(frame_filtri)

        self.table_prodotti = QTableWidget(0, 10, self)
        self.table_prodotti.setHorizontalHeaderLabels(
            [
                "Data",
                "N. fattura",
                "Fornitore",
                "Prodotto",
                "Categoria",
                "Qta",
                "Totale",
                "Tipo costo",
                "Imputazione gruppi",
                "ID movimento",
            ]
        )
        self.table_prodotti.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_prodotti.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_prodotti.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_prodotti.setAlternatingRowColors(True)
        self.table_prodotti.verticalHeader().setVisible(False)

        header = self.table_prodotti.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(9, QHeaderView.ResizeToContents)

        main_layout.addWidget(self.table_prodotti, 1)

    def _on_toggle_data_filters(self, _checked=False):
        self.date_data_da.setEnabled(self.check_data_da.isChecked())
        self.date_data_a.setEnabled(self.check_data_a.isChecked())

    def _on_filter_changed(self, _index=0):
        self.carica_storico_prodotti(show_errors=False)

    def _append_row(self, table: QTableWidget, row_index: int, values: list[str], right_align_indexes=None):
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

    def _format_data_parser(self, raw_value):
        testo = (raw_value or "").strip()
        if not testo:
            return ""

        for fmt_in in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(testo, fmt_in).strftime("%d/%m/%Y")
            except ValueError:
                continue

        return testo

    def _format_data_storico_prodotti(self, raw_invoice_date, raw_movimento_date):
        invoice_date = (raw_invoice_date or "").strip()
        if invoice_date:
            formatted_invoice_date = self._format_data_parser(invoice_date)
            if formatted_invoice_date:
                return formatted_invoice_date

        movimento_date = (raw_movimento_date or "").strip()
        if not movimento_date:
            return "-"

        try:
            return datetime.strptime(movimento_date, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return movimento_date

    def _format_numero(self, raw_value, decimals):
        testo = str(raw_value or "").strip()
        if not testo or testo == "-":
            return "-"

        numero = parse_decimal(testo, allow_zero=True, allow_negative=False)
        if numero is None:
            return testo
        return format_number(numero, decimals)

    def pulisci_filtri(self):
        self.combo_tipo_costo.blockSignals(True)
        self.combo_categoria.blockSignals(True)
        self.combo_tipo_costo.setCurrentText("Tutti")
        self.combo_categoria.setCurrentText("Tutte")
        self.combo_tipo_costo.blockSignals(False)
        self.combo_categoria.blockSignals(False)

        self.input_numero_fattura.clear()
        self.input_fornitore.clear()
        self.input_prodotto.clear()
        self.input_gruppo.clear()

        self.check_data_da.setChecked(False)
        self.check_data_a.setChecked(False)
        self.date_data_da.setDate(QDate.currentDate())
        self.date_data_a.setDate(QDate.currentDate())

        self.carica_storico_prodotti(show_errors=False)

    def carica_storico_prodotti(self, show_errors=True):
        self.table_prodotti.setRowCount(0)

        filtro_data_da = self.date_data_da.date().toString("yyyy-MM-dd") if self.check_data_da.isChecked() else ""
        filtro_data_a = self.date_data_a.date().toString("yyyy-MM-dd") if self.check_data_a.isChecked() else ""
        filtro_numero_fattura = self.input_numero_fattura.text().strip()
        filtro_fornitore = self.input_fornitore.text().strip()
        filtro_prodotto = self.input_prodotto.text().strip().lower()
        filtro_categoria = self.combo_categoria.currentText().strip() or "Tutte"
        filtro_gruppo = self.input_gruppo.text().strip().lower()
        filtro_tipo_costo = self.combo_tipo_costo.currentText().strip() or "Tutti"

        if filtro_tipo_costo not in ("Tutti", "Variabili", "Fissi"):
            filtro_tipo_costo = "Tutti"
        if filtro_categoria not in (("Tutte",) + PRODUCT_CATEGORY_OPTIONS):
            filtro_categoria = "Tutte"

        if filtro_data_da and filtro_data_a and filtro_data_da > filtro_data_a:
            if show_errors:
                QMessageBox.critical(self, "Errore", "La Data DA non puo essere successiva alla Data A.")
            return

        query = (
            """
                    SELECT
                        m.id,
                        m.data_op,
                        m.parser_invoice_number,
                        m.parser_invoice_date,
                        m.parser_supplier_name,
                        m.parser_products
                    FROM movimenti m
                    WHERE m.user_id=?
                      AND TRIM(COALESCE(m.parser_products, '')) <> ''
                      AND EXISTS (
                          SELECT 1
                          FROM fatture f
                          WHERE f.user_id = m.user_id
                            AND UPPER(TRIM(COALESCE(f.origine, ''))) <> 'LATTE'
                            AND (
                                f.movimento_id = m.id
                                OR (
                                    f.produzione_id IS NOT NULL
                                    AND EXISTS (
                                        SELECT 1
                                        FROM produzione_latte p
                                        WHERE p.id = f.produzione_id
                                          AND p.user_id = f.user_id
                                          AND p.movimento_id = m.id
                                    )
                                )
                            )
                      )
                """
        )
        params = [self.user_id]

        if filtro_data_da:
            query += " AND m.data_op >= ?"
            params.append(filtro_data_da)

        if filtro_data_a:
            query += " AND m.data_op <= ?"
            params.append(filtro_data_a)

        if filtro_numero_fattura:
            query += " AND LOWER(COALESCE(m.parser_invoice_number, '')) LIKE ?"
            params.append(f"%{filtro_numero_fattura.lower()}%")

        if filtro_fornitore:
            query += " AND LOWER(COALESCE(m.parser_supplier_name, '')) LIKE ?"
            params.append(f"%{filtro_fornitore.lower()}%")

        query += " ORDER BY m.data_op DESC, m.id DESC"

        filtri_attivi = any(
            (
                filtro_data_da,
                filtro_data_a,
                filtro_numero_fattura,
                filtro_fornitore,
                filtro_prodotto,
                filtro_categoria != "Tutte",
                filtro_gruppo,
                filtro_tipo_costo != "Tutti",
            )
        )

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(query, tuple(params))
                rows = c.fetchall()
        except sqlite3.Error as exc:
            if show_errors:
                QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            self.label_stato.setText("Errore caricamento storico prodotti.")
            return

        movimenti_con_prodotti = set()
        righe_prodotti = 0

        for mov_id, data_op, invoice_number, invoice_date, supplier_name, products_text in rows:
            prodotti = extract_products_rows_from_parser_text(products_text)
            if not prodotti:
                continue

            data_view = self._format_data_storico_prodotti(invoice_date, data_op)
            numero_fattura = (invoice_number or "").strip() or "-"
            fornitore = (supplier_name or "").strip() or "-"
            movimento_inserito = False

            for prodotto in prodotti:
                descrizione = str(prodotto.get("description", "-") or "-").strip() or "-"
                categoria_prodotto = normalize_product_category(prodotto.get("category"))
                gruppi_text = str(prodotto.get("groups", "-") or "-").strip() or "-"
                tipo_costo = normalize_cost_type(prodotto.get("cost_type"))

                if filtro_tipo_costo != "Tutti" and tipo_costo != filtro_tipo_costo:
                    continue
                if filtro_prodotto and filtro_prodotto not in descrizione.lower():
                    continue
                if filtro_categoria != "Tutte" and categoria_prodotto != filtro_categoria:
                    continue
                if filtro_gruppo and filtro_gruppo not in gruppi_text.lower():
                    continue

                self._append_row(
                    self.table_prodotti,
                    righe_prodotti,
                    [
                        data_view,
                        numero_fattura,
                        fornitore,
                        descrizione,
                        categoria_prodotto,
                        self._format_numero(prodotto.get("quantity"), 3),
                        self._format_numero(prodotto.get("line_total"), 2),
                        tipo_costo,
                        gruppi_text,
                        str(int(mov_id or 0)),
                    ],
                    right_align_indexes=[5, 6, 9],
                )
                righe_prodotti += 1
                movimento_inserito = True

            if movimento_inserito:
                movimenti_con_prodotti.add(int(mov_id or 0))

        if righe_prodotti <= 0:
            if filtri_attivi:
                self.label_stato.setText("Nessun prodotto trovato con i filtri impostati.")
            else:
                self.label_stato.setText("Nessun prodotto trovato nelle fatture archiviate.")
            return

        suffix = " (filtri attivi)" if filtri_attivi else ""
        self.label_stato.setText(
            f"Prodotti trovati: {righe_prodotti} | Movimenti con fattura: {len(movimenti_con_prodotti)}{suffix}"
        )
