import os
import sqlite3
import subprocess
import sys
from datetime import datetime

from PySide6.QtCore import QDate, Qt, Signal
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
    QSplitter
)

from app_utils import format_number, parse_decimal, TabellaIsolata
from database import (
    get_conn,
    get_movimento_animali_group_labels,
    list_azienda_animali_entries,
    resolve_fattura_path,
)
from services.product_parser_utils import normalize_multiline_display_text


class AziendaMovimentiPage(QWidget):
    edit_movimento_requested = Signal(int)
    movimenti_changed = Signal()

    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = int(user_id)

        self._filtro_gruppi_animali_map: dict[str, int] = {}
        self._fattura_dettaglio_corrente = None

        self._build_ui()
        self.carica_movimenti(show_errors=False)

    def _build_ui(self):
        STYLE_BTN_MODIFICA = "background-color: #ffc107; color: black; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_ELIMINA = "background-color: #dc3545; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_SECONDARIO = "background-color: #6c757d; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_INFO = "background-color: #17a2b8; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # HEADER
        header_layout = QVBoxLayout()
        titolo = QLabel("📜 Storico Movimenti e Fatture")
        titolo.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        sottotitolo = QLabel("Consulta le entrate, le uscite e apri rapidamente i documenti PDF.")
        sottotitolo.setStyleSheet("font-size: 14px; color: #7f8c8d;")
        header_layout.addWidget(titolo)
        header_layout.addWidget(sottotitolo)
        main_layout.addLayout(header_layout)

        # FILTRI
        frame_filtri = QFrame(self)
        frame_filtri.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        layout_filtri = QGridLayout(frame_filtri)
        layout_filtri.setContentsMargins(15, 15, 15, 15)
        layout_filtri.setHorizontalSpacing(10)
        layout_filtri.setVerticalSpacing(10)

        self.combo_categoria = QComboBox(self)
        self.combo_categoria.setStyleSheet("padding: 5px;")
        self.combo_categoria.addItem("Tutte")
        self.combo_categoria.currentIndexChanged.connect(self._on_filter_changed)

        self.combo_gruppo_animale = QComboBox(self)
        self.combo_gruppo_animale.setStyleSheet("padding: 5px;")
        self.combo_gruppo_animale.addItem("Tutti")
        self.combo_gruppo_animale.currentIndexChanged.connect(self._on_filter_changed)

        self.input_descrizione = QLineEdit(self)
        self.input_descrizione.setStyleSheet("padding: 5px;")
        self.input_descrizione.setPlaceholderText("Filtro descrizione")
        self.input_descrizione.returnPressed.connect(lambda: self.carica_movimenti(show_errors=True))

        layout_filtri.addWidget(QLabel("<b>Categoria:</b>"), 0, 0)
        layout_filtri.addWidget(self.combo_categoria, 0, 1)
        layout_filtri.addWidget(QLabel("<b>Gruppo animale:</b>"), 0, 2)
        layout_filtri.addWidget(self.combo_gruppo_animale, 0, 3)
        layout_filtri.addWidget(QLabel("<b>Descrizione:</b>"), 0, 4)
        layout_filtri.addWidget(self.input_descrizione, 0, 5)

        self.check_data_da = QCheckBox("Data da", self)
        self.check_data_da.setStyleSheet("font-weight: bold;")
        self.check_data_da.toggled.connect(self._on_toggle_data_filter)
        self.date_data_da = QDateEdit(self)
        self.date_data_da.setStyleSheet("padding: 5px;")
        self.date_data_da.setDisplayFormat("dd/MM/yyyy")
        self.date_data_da.setCalendarPopup(True)
        self.date_data_da.setDate(QDate.currentDate())
        self.date_data_da.setEnabled(False)

        self.check_data_a = QCheckBox("Data a", self)
        self.check_data_a.setStyleSheet("font-weight: bold;")
        self.check_data_a.toggled.connect(self._on_toggle_data_filter)
        self.date_data_a = QDateEdit(self)
        self.date_data_a.setStyleSheet("padding: 5px;")
        self.date_data_a.setDisplayFormat("dd/MM/yyyy")
        self.date_data_a.setCalendarPopup(True)
        self.date_data_a.setDate(QDate.currentDate())
        self.date_data_a.setEnabled(False)

        button_applica = QPushButton("Applica filtri", self)
        button_applica.setStyleSheet(STYLE_BTN_INFO)
        button_applica.clicked.connect(lambda: self.carica_movimenti(show_errors=True))

        button_pulisci = QPushButton("Pulisci", self)
        button_pulisci.setStyleSheet(STYLE_BTN_SECONDARIO)
        button_pulisci.clicked.connect(self.pulisci_filtri)

        layout_filtri.addWidget(self.check_data_da, 1, 0)
        layout_filtri.addWidget(self.date_data_da, 1, 1)
        layout_filtri.addWidget(self.check_data_a, 1, 2)
        layout_filtri.addWidget(self.date_data_a, 1, 3)
        layout_filtri.addWidget(button_applica, 1, 4)
        layout_filtri.addWidget(button_pulisci, 1, 5)

        main_layout.addWidget(frame_filtri)

        # SPLITTER PRINCIPALE VERTICALE
        main_splitter = QSplitter(Qt.Vertical)

        # WIDGET SUPERIORE (Tabella + Pulsanti Azione)
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        self.table_movimenti = TabellaIsolata(0, 7, self)
        self.table_movimenti.setHorizontalHeaderLabels(["ID", "Data", "Tipo", "Categoria", "Descrizione", "Importo", "IVA"])
        self.table_movimenti.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_movimenti.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_movimenti.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_movimenti.setAlternatingRowColors(True)
        self.table_movimenti.verticalHeader().setVisible(False)
        self.table_movimenti.setStyleSheet("QTableWidget { border: 1px solid #ccc; border-radius: 5px; } QHeaderView::section { background-color: #f8f9fa; font-weight: bold; border: 1px solid #ddd; }")
        self.table_movimenti.itemSelectionChanged.connect(self.carica_dettagli_fattura_movimento_selezionato)
        self.table_movimenti.cellDoubleClicked.connect(lambda _row, _col: self.richiedi_modifica_movimento())

        header = self.table_movimenti.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)

        top_layout.addWidget(self.table_movimenti)

        row_actions = QHBoxLayout()
        row_actions.setSpacing(10)

        button_ricarica = QPushButton("Ricarica")
        button_ricarica.setStyleSheet(STYLE_BTN_SECONDARIO)
        button_ricarica.clicked.connect(lambda: self.carica_movimenti(show_errors=True))
        row_actions.addWidget(button_ricarica)

        button_modifica = QPushButton("Modifica Selezionato")
        button_modifica.setStyleSheet(STYLE_BTN_MODIFICA)
        button_modifica.clicked.connect(self.richiedi_modifica_movimento)
        row_actions.addWidget(button_modifica)

        button_apri_fattura = QPushButton("Apri PDF Fattura")
        button_apri_fattura.setStyleSheet(STYLE_BTN_INFO)
        button_apri_fattura.clicked.connect(self.apri_fattura_movimento_selezionato)
        row_actions.addWidget(button_apri_fattura)

        button_elimina = QPushButton("Elimina Selezionato")
        button_elimina.setStyleSheet(STYLE_BTN_ELIMINA)
        button_elimina.clicked.connect(self.elimina_movimento_selezionato)
        row_actions.addWidget(button_elimina)

        row_actions.addStretch()
        top_layout.addLayout(row_actions)
        main_splitter.addWidget(top_widget)

        # WIDGET INFERIORE (Dettagli)
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        dettagli_title = QLabel("📄 Dati della Fattura collegata")
        dettagli_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #34495e; padding-top: 10px;")
        bottom_layout.addWidget(dettagli_title)

        self.table_dettagli = TabellaIsolata(0, 2, self)
        self.table_dettagli.setHorizontalHeaderLabels(["Campo", "Valore Letto da PDF"])
        self.table_dettagli.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_dettagli.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_dettagli.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_dettagli.setAlternatingRowColors(True)
        self.table_dettagli.verticalHeader().setVisible(False)
        self.table_dettagli.setStyleSheet("QTableWidget { border: 1px solid #ccc; border-radius: 5px; } QHeaderView::section { background-color: #f8f9fa; font-weight: bold; border: 1px solid #ddd; }")

        dettagli_header = self.table_dettagli.horizontalHeader()
        dettagli_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        dettagli_header.setSectionResizeMode(1, QHeaderView.Stretch)

        bottom_layout.addWidget(self.table_dettagli)
        main_splitter.addWidget(bottom_widget)

        main_splitter.setSizes([500, 300]) # Proporzioni iniziali
        main_layout.addWidget(main_splitter, 1)

        self._azzera_dettagli_fattura()

    def _on_toggle_data_filter(self, _checked=False):
        self.date_data_da.setEnabled(self.check_data_da.isChecked())
        self.date_data_a.setEnabled(self.check_data_a.isChecked())

    def _on_filter_changed(self):
        self.carica_movimenti(show_errors=False)

    def _set_combo_items(self, combo: QComboBox, values: list[str], fallback_value: str):
        current = combo.currentText().strip()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(values)
        if current and current in values:
            combo.setCurrentText(current)
        else:
            combo.setCurrentText(fallback_value)
        combo.blockSignals(False)

    def _format_tipo_animale_report(self, tipo_animale, altro_label):
        tipo = (tipo_animale or "").strip().upper()
        if tipo == "ALTRO":
            extra = (altro_label or "").strip()
            return f"Altro ({extra})" if extra else "Altro"
        return tipo.title() if tipo else "-"

    def _format_finalita_report(self, finalita):
        value = (finalita or "").strip().upper()
        if value == "LATTE":
            return "Da Latte"
        if value == "CARNE":
            return "Da Carne"
        return "-"

    def _label_gruppo_animale_movimento(self, entry):
        entry_id = int(entry.get("id", 0) or 0)
        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
        tipo_text = self._format_tipo_animale_report(entry.get("tipo_animale", ""), entry.get("altro_label", ""))
        finalita_text = self._format_finalita_report(entry.get("finalita", ""))
        capi = int(entry.get("capi", 0) or 0)
        return f"{group_name} | {tipo_text} | {finalita_text} | {format_number(capi, 0)} capi"

    def _carica_categorie_filtro(self, show_errors=True):
        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    """
                    SELECT DISTINCT TRIM(categoria) AS cat
                    FROM movimenti
                    WHERE user_id=?
                      AND categoria IS NOT NULL
                      AND TRIM(categoria) <> ''
                    ORDER BY cat COLLATE NOCASE
                """,
                    (self.user_id,),
                )
                rows = c.fetchall()
        except sqlite3.Error as exc:
            if show_errors:
                QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        categorie = [row[0] for row in rows if row[0]]
        self._set_combo_items(self.combo_categoria, ["Tutte", *categorie], "Tutte")

    def _carica_gruppi_filtro(self, show_errors=True):
        try:
            entries = list_azienda_animali_entries(self.user_id)
        except sqlite3.Error as exc:
            if show_errors:
                QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        candidati = [entry for entry in entries if int(entry.get("id", 0) or 0) > 0]
        candidati.sort(key=lambda item: ((item.get("group_name") or "").strip().lower(), int(item.get("id", 0) or 0)))

        mapping = {}
        labels = []
        labels_seen = set()
        for entry in candidati:
            entry_id = int(entry.get("id", 0) or 0)
            if entry_id <= 0:
                continue

            label = self._label_gruppo_animale_movimento(entry)
            if label in labels_seen:
                label = f"{label} [ID {entry_id}]"
            labels_seen.add(label)

            mapping[label] = entry_id
            labels.append(label)

        self._filtro_gruppi_animali_map = mapping
        self._set_combo_items(self.combo_gruppo_animale, ["Tutti", *labels], "Tutti")

    def pulisci_filtri(self):
        self.combo_categoria.blockSignals(True)
        self.combo_gruppo_animale.blockSignals(True)
        self.combo_categoria.setCurrentText("Tutte")
        self.combo_gruppo_animale.setCurrentText("Tutti")
        self.combo_categoria.blockSignals(False)
        self.combo_gruppo_animale.blockSignals(False)
        self.input_descrizione.clear()

        self.check_data_da.setChecked(False)
        self.check_data_a.setChecked(False)
        self.date_data_da.setDate(QDate.currentDate())
        self.date_data_a.setDate(QDate.currentDate())

        self.carica_movimenti(show_errors=False)

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

    def carica_movimenti(self, show_errors=True):
        self._carica_categorie_filtro(show_errors=show_errors)
        self._carica_gruppi_filtro(show_errors=show_errors)

        filtro_categoria = self.combo_categoria.currentText().strip()
        filtro_gruppo_animale = self.combo_gruppo_animale.currentText().strip()
        filtro_descrizione = self.input_descrizione.text().strip()

        data_da_iso = self.date_data_da.date().toString("yyyy-MM-dd") if self.check_data_da.isChecked() else None
        data_a_iso = self.date_data_a.date().toString("yyyy-MM-dd") if self.check_data_a.isChecked() else None

        if data_da_iso and data_a_iso and data_da_iso > data_a_iso:
            if show_errors:
                QMessageBox.critical(self, "Errore", "La Data DA non puo essere successiva alla Data A.")
            return

        query = (
            """
                    SELECT
                        id, data_op, tipo, categoria, descrizione, importo, iva_importo,
                        parser_taxable_total, parser_vat_total, parser_total_amount
                    FROM movimenti
                    WHERE user_id=?
                """
        )
        params = [self.user_id]

        if filtro_categoria and filtro_categoria != "Tutte":
            query += " AND TRIM(COALESCE(categoria, '')) = ?"
            params.append(filtro_categoria)

        if filtro_gruppo_animale and filtro_gruppo_animale != "Tutti":
            entry_id = int((self._filtro_gruppi_animali_map or {}).get(filtro_gruppo_animale, 0) or 0)
            if entry_id > 0:
                query += (
                    """
                    AND EXISTS (
                        SELECT 1
                        FROM movimenti_animali_link mal
                        WHERE mal.user_id = movimenti.user_id
                          AND mal.movimento_id = movimenti.id
                          AND mal.animale_entry_id = ?
                    )
                """
                )
                params.append(entry_id)

        if filtro_descrizione:
            query += " AND LOWER(COALESCE(descrizione, '')) LIKE ?"
            params.append(f"%{filtro_descrizione.lower()}%")

        if data_da_iso:
            query += " AND data_op >= ?"
            params.append(data_da_iso)

        if data_a_iso:
            query += " AND data_op <= ?"
            params.append(data_a_iso)

        query += " ORDER BY data_op DESC, id DESC"

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(query, tuple(params))
                rows = c.fetchall()
        except sqlite3.Error as exc:
            if show_errors:
                QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        self.table_movimenti.setRowCount(0)

        for row_index, (
            mov_id,
            data_op,
            tipo,
            categoria,
            descrizione,
            importo,
            iva_importo,
            parser_taxable_total,
            parser_vat_total,
            parser_total_amount,
        ) in enumerate(rows):
            try:
                data_view = datetime.strptime(data_op, "%Y-%m-%d").strftime("%d/%m/%Y")
            except ValueError:
                data_view = data_op

            importo_view = parse_decimal(importo, allow_zero=True, allow_negative=False)
            if importo_view is None:
                importo_view = 0.0

            iva_view = parse_decimal(iva_importo, allow_zero=True, allow_negative=False)
            if iva_view is None:
                iva_view = 0.0

            if iva_view <= 0 and (categoria or "").strip().upper() == "LATTE":
                iva_parser = parse_decimal(parser_vat_total, allow_zero=True, allow_negative=False)
                imponibile_parser = parse_decimal(parser_taxable_total, allow_zero=True, allow_negative=False)
                totale_parser = parse_decimal(parser_total_amount, allow_zero=False, allow_negative=False)

                if iva_parser is not None and iva_parser > 0:
                    iva_view = iva_parser
                    if imponibile_parser is not None and imponibile_parser >= 0:
                        importo_view = imponibile_parser
                    elif totale_parser is not None and totale_parser >= iva_view:
                        importo_view = totale_parser - iva_view

            self._append_row(
                self.table_movimenti,
                row_index,
                [
                    str(int(mov_id or 0)),
                    str(data_view or ""),
                    str(tipo or ""),
                    str(categoria or ""),
                    str(descrizione or ""),
                    format_number(importo_view, 2),
                    format_number(iva_view, 2),
                ],
                right_align_indexes=[5, 6],
            )

        self._azzera_dettagli_fattura()

    def _selected_movimento_id(self):
        row = self.table_movimenti.currentRow()
        if row < 0:
            return None

        item = self.table_movimenti.item(row, 0)
        if item is None:
            return None

        try:
            return int(item.text().strip())
        except ValueError:
            return None

    def _azzera_dettagli_fattura(self, text="Seleziona un movimento per vedere la fattura collegata."):
        self._fattura_dettaglio_corrente = None
        self.table_dettagli.setRowCount(0)
        self._append_row(self.table_dettagli, 0, ["Info", text])

    def _gruppi_animali_collegati_movimento_testo(self, movimento_id: int):
        try:
            labels = get_movimento_animali_group_labels(self.user_id, movimento_id)
        except sqlite3.Error:
            return "-"

        if not labels:
            return "Nessun gruppo collegato"
        return "\n".join(labels)

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

    def _format_importo_parser(self, raw_value):
        testo = (raw_value or "").strip()
        if not testo:
            return ""

        numero = parse_decimal(testo, allow_zero=True, allow_negative=False)
        if numero is None:
            return testo
        return format_number(numero, 2)

    def _format_data_caricamento(self, raw_value):
        testo = (raw_value or "").strip()
        if not testo:
            return ""

        for fmt_in in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
        ):
            try:
                data = datetime.strptime(testo, fmt_in)
                if "%H" in fmt_in:
                    return data.strftime("%d/%m/%Y %H:%M")
                return data.strftime("%d/%m/%Y")
            except ValueError:
                continue

        return testo.replace("T", " ")

    def carica_dettagli_fattura_movimento_selezionato(self):
        mov_id = self._selected_movimento_id()
        if mov_id is None:
            self._azzera_dettagli_fattura("Seleziona un movimento per vedere la fattura collegata.")
            return

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    """
                    SELECT
                        f.id,
                        f.data_caricamento,
                        f.origine,
                        f.nome_originale,
                        f.percorso_file,
                        m.parser_invoice_number,
                        m.parser_invoice_date,
                        m.parser_due_date,
                        m.parser_supplier_name,
                        m.parser_supplier_vat,
                        m.parser_customer_name,
                        m.parser_customer_vat,
                        m.parser_total_amount,
                        m.parser_taxable_total,
                        m.parser_vat_total,
                        m.parser_payment_terms,
                        m.parser_warnings,
                        m.parser_products,
                        m.parser_fields_view
                    FROM fatture f
                    LEFT JOIN movimenti m
                      ON m.id = f.movimento_id
                     AND m.user_id = f.user_id
                    WHERE f.user_id=?
                      AND (
                            f.movimento_id=?
                            OR (
                                f.produzione_id IS NOT NULL
                                AND EXISTS (
                                    SELECT 1
                                    FROM produzione_latte p
                                    WHERE p.id = f.produzione_id
                                      AND p.user_id = f.user_id
                                      AND p.movimento_id = ?
                                )
                            )
                      )
                    ORDER BY f.data_caricamento DESC, f.id DESC
                    LIMIT 1
                """,
                    (self.user_id, mov_id, mov_id),
                )
                row = c.fetchone()
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            self._azzera_dettagli_fattura("Errore durante il caricamento della fattura collegata.")
            return

        if not row:
            self._azzera_dettagli_fattura("Nessuna fattura collegata al movimento selezionato.")
            return

        (
            fattura_id,
            data_caricamento,
            origine,
            nome_originale,
            percorso_file,
            parser_invoice_number,
            parser_invoice_date,
            parser_due_date,
            parser_supplier_name,
            parser_supplier_vat,
            parser_customer_name,
            parser_customer_vat,
            parser_total_amount,
            parser_taxable_total,
            parser_vat_total,
            parser_payment_terms,
            parser_warnings,
            parser_products,
            parser_fields_view,
        ) = row

        gruppi_animali_collegati = self._gruppi_animali_collegati_movimento_testo(mov_id)

        self._fattura_dettaglio_corrente = {
            "id": fattura_id,
            "data_caricamento": self._format_data_caricamento(data_caricamento),
            "origine": origine or "",
            "nome_originale": nome_originale or "",
            "percorso_file": percorso_file or "",
            "invoice_number": parser_invoice_number or "",
            "invoice_date": self._format_data_parser(parser_invoice_date),
            "due_date": self._format_data_parser(parser_due_date),
            "supplier_name": parser_supplier_name or "",
            "supplier_vat": parser_supplier_vat or "",
            "customer_name": parser_customer_name or "",
            "customer_vat": parser_customer_vat or "",
            "total_amount": self._format_importo_parser(parser_total_amount),
            "taxable_total": self._format_importo_parser(parser_taxable_total),
            "vat_total": self._format_importo_parser(parser_vat_total),
            "payment_terms": parser_payment_terms or "",
            "warnings": parser_warnings or "",
            "products": normalize_multiline_display_text(parser_products),
            "fields_view": parser_fields_view or "",
            "gruppi_animali": normalize_multiline_display_text(gruppi_animali_collegati),
        }
        self._mostra_dettagli_fattura(self._fattura_dettaglio_corrente)

    def _mostra_dettagli_fattura(self, dettagli):
        self.table_dettagli.setRowCount(0)
        righe = [
            ("ID Fattura", dettagli.get("id", "")),
            ("Data caricamento", dettagli.get("data_caricamento", "")),
            ("Origine", dettagli.get("origine", "")),
            ("Nome file", dettagli.get("nome_originale", "")),
            ("Numero fattura", dettagli.get("invoice_number", "")),
            ("Data fattura", dettagli.get("invoice_date", "")),
            ("Scadenza", dettagli.get("due_date", "")),
            ("Fornitore", dettagli.get("supplier_name", "")),
            ("P.IVA Fornitore", dettagli.get("supplier_vat", "")),
            ("Cliente", dettagli.get("customer_name", "")),
            ("P.IVA Cliente", dettagli.get("customer_vat", "")),
            ("Totale documento", dettagli.get("total_amount", "")),
            ("Totale imponibile", dettagli.get("taxable_total", "")),
            ("Totale IVA", dettagli.get("vat_total", "")),
            ("Condizioni pagamento", dettagli.get("payment_terms", "")),
            ("Gruppi animali collegati", dettagli.get("gruppi_animali", "")),
            ("Prodotti", dettagli.get("products", "")),
        ]

        for idx, (campo, valore) in enumerate(righe):
            self._append_row(self.table_dettagli, idx, [str(campo), str(valore or "")])

    def _apri_file_locale(self, file_path):
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(file_path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(file_path)], check=False)
            else:
                subprocess.run(["xdg-open", str(file_path)], check=False)
        except Exception as exc:
            QMessageBox.critical(self, "Errore apertura", f"Impossibile aprire il file:\n{exc}")

    def apri_fattura_movimento_selezionato(self):
        dettagli = self._fattura_dettaglio_corrente
        if not dettagli:
            QMessageBox.warning(self, "Attenzione", "Seleziona un movimento con fattura collegata.")
            return

        percorso = dettagli.get("percorso_file", "")
        if not percorso:
            QMessageBox.critical(self, "Errore", "La fattura selezionata non ha un percorso file valido.")
            return

        percorso_fattura = resolve_fattura_path(percorso)
        if not percorso_fattura.exists():
            QMessageBox.critical(
                self,
                "File non trovato",
                f"La fattura non esiste piu nel percorso salvato:\n{percorso_fattura}",
            )
            return

        self._apri_file_locale(percorso_fattura)

    def _elimina_fatture_collegate_db(self, cursor, movimento_id):
        cursor.execute(
            "SELECT percorso_file FROM fatture WHERE user_id=? AND movimento_id=?",
            (self.user_id, movimento_id),
        )
        percorsi = [row[0] for row in cursor.fetchall() if row and row[0]]

        cursor.execute("DELETE FROM fatture WHERE user_id=? AND movimento_id=?", (self.user_id, movimento_id))
        fatture_eliminate = max(cursor.rowcount, 0)
        return fatture_eliminate, percorsi

    def _elimina_file_fatture(self, percorsi):
        file_eliminati = 0
        file_non_trovati = 0
        errori = []

        for percorso in sorted(set(p for p in percorsi if p)):
            file_path = resolve_fattura_path(percorso)
            try:
                if file_path.exists():
                    file_path.unlink()
                    file_eliminati += 1
                else:
                    file_non_trovati += 1
            except Exception as exc:
                errori.append(f"{file_path} ({exc})")

        return file_eliminati, file_non_trovati, errori

    def richiedi_modifica_movimento(self):
        mov_id = self._selected_movimento_id()
        if mov_id is None:
            QMessageBox.warning(self, "Attenzione", "Seleziona prima un movimento da modificare.")
            return

        self.edit_movimento_requested.emit(int(mov_id))

    def elimina_movimento_selezionato(self):
        mov_id = self._selected_movimento_id()
        if mov_id is None:
            QMessageBox.warning(self, "Attenzione", "Seleziona prima un movimento da eliminare.")
            return

        row = self.table_movimenti.currentRow()
        descrizione_item = self.table_movimenti.item(row, 4)
        descrizione = descrizione_item.text().strip() if descrizione_item else f"ID {mov_id}"

        conferma = QMessageBox.question(
            self,
            "Conferma eliminazione",
            f"Vuoi eliminare il movimento selezionato?\n\n{descrizione}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if conferma != QMessageBox.Yes:
            return

        fatture_eliminate = 0
        produzioni_eliminate = 0
        percorsi_fatture = []

        try:
            with get_conn() as conn:
                c = conn.cursor()

                c.execute("SELECT 1 FROM movimenti WHERE id=? AND user_id=?", (mov_id, self.user_id))
                if not c.fetchone():
                    QMessageBox.critical(self, "Errore", "Movimento non trovato o non eliminabile.")
                    return

                c.execute(
                    "SELECT COUNT(id) FROM produzione_latte WHERE user_id=? AND movimento_id=?",
                    (self.user_id, mov_id),
                )
                row_prod = c.fetchone()
                produzioni_eliminate = int((row_prod[0] if row_prod else 0) or 0)

                fatture_eliminate, percorsi_fatture = self._elimina_fatture_collegate_db(c, mov_id)

                c.execute("DELETE FROM movimenti WHERE id=? AND user_id=?", (mov_id, self.user_id))
                if c.rowcount == 0:
                    QMessageBox.critical(self, "Errore", "Movimento non trovato o non eliminabile.")
                    return
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        file_eliminati, file_non_trovati, file_errori = self._elimina_file_fatture(percorsi_fatture)

        self.carica_movimenti(show_errors=False)
        self.movimenti_changed.emit()

        msg_ok = "Movimento eliminato dal database!"
        if produzioni_eliminate > 0:
            msg_ok += f" Produzioni latte collegate eliminate: {produzioni_eliminate}."
        if fatture_eliminate > 0:
            msg_ok += f" Fatture collegate eliminate: {fatture_eliminate}."
            msg_ok += f" File fattura eliminati: {file_eliminati}."
            if file_non_trovati > 0:
                msg_ok += f" File non trovati: {file_non_trovati}."

        if file_errori:
            QMessageBox.warning(
                self,
                "Eliminazione completata con avvisi",
                msg_ok + "\n\nAlcuni file non sono stati eliminati:\n" + "\n".join(file_errori[:3]),
            )
        else:
            QMessageBox.information(self, "Successo", msg_ok)