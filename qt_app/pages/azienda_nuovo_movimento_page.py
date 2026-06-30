import importlib
import re
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from PySide6.QtCore import QDate, QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QStyledItemDelegate,
    QDateEdit,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QSplitter,
    QSizePolicy,
    QCompleter
)

from app_utils import format_number, is_blank, parse_decimal, TabellaIsolata
from database import (
    get_fatture_user_dir,
    get_movimento_animali_entry_ids,
    list_azienda_animali_entries,
    set_movimento_animali_links,
    to_storage_fattura_path,
    list_soggetti
)
from services.product_parser_utils import (
    build_basic_product_storage_line,
    build_detailed_product_storage_line,
    extract_products_rows_from_parser_text,
    normalize_cost_type,
    normalize_product_category,
    serialize_product_storage_lines,
)

# IMPORTIAMO I MODELLI PEEWEE
from models import db, Movimento, Fattura


class CheckableComboBox(QComboBox):
    class Delegate(QStyledItemDelegate):
        def sizeHint(self, option, index):
            size = super().sizeHint(option, index)
            size.setHeight(28)
            return size

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText("Seleziona gruppi...")
        self.setItemDelegate(CheckableComboBox.Delegate())
        self.model().dataChanged.connect(self._update_text)
        self.lineEdit().installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj == self.lineEdit() and event.type() == event.Type.MouseButtonRelease:
            self.showPopup()
            return True
        return super().eventFilter(obj, event)

    def addItem(self, text, data=None, checked=False):
        super().addItem(text, data)
        item = self.model().item(self.count() - 1, 0)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _update_text(self):
        texts = []
        for i in range(self.count()):
            item = self.model().item(i, 0)
            if item.checkState() == Qt.Checked:
                texts.append(item.text())
        if texts:
            self.lineEdit().setText(", ".join(texts))
        else:
            self.lineEdit().setText("Nessun gruppo")

    def checked_data(self):
        res = []
        for i in range(self.count()):
            item = self.model().item(i, 0)
            if item.checkState() == Qt.Checked:
                res.append(self.itemData(i))
        return res

    def set_checked_data(self, data_list):
        self.model().blockSignals(True)
        for i in range(self.count()):
            item = self.model().item(i, 0)
            if self.itemData(i) in data_list:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
        self.model().blockSignals(False)
        self._update_text()



class AziendaNuovoMovimentoPage(QWidget):
    movimento_saved = Signal(int)
    edit_cancelled = Signal()

    _PARSER_DB_FIELDS = (
        "invoice_number", "invoice_date", "due_date", "supplier_name",
        "supplier_vat", "customer_name", "customer_vat", "total_amount",
        "taxable_total", "vat_total", "payment_terms", "warnings",
        "products", "fields_view",
    )

    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = int(user_id)

        self.movimento_in_modifica_id = None
        self.pending_fattura_movimento_id = None
        self.pending_fattura_movimento_path = None
        self.pending_parser_movimento_data = None
        self._parser_fatture_parse_fn = None
        self._parser_feedback_busy = False
        self._parser_feedback_prev_enabled = {}
        self._table_prodotti_updating = False
        self.fatture_queue = []

        self._build_ui()
        self._reset_form()
        self._carica_categorie_salvate(show_errors=False)

    def _build_ui(self):
        STYLE_BTN_SALVA = "background-color: #28a745; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_SECONDARIO = "background-color: #6c757d; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_INFO = "background-color: #17a2b8; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        header_layout = QVBoxLayout()
        titolo = QLabel("➕ Registra Movimento e Importa Fattura")
        titolo.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        sottotitolo = QLabel("Carica un file XML per compilare automaticamente i campi oppure procedi manualmente.")
        sottotitolo.setStyleSheet("font-size: 14px; color: #7f8c8d;")
        header_layout.addWidget(titolo)
        header_layout.addWidget(sottotitolo)
        main_layout.addLayout(header_layout)

        main_splitter = QSplitter(Qt.Vertical)

        # --- WIDGET SUPERIORE: IL FORM ---
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0,0,0,0)

        frame_form = QFrame()
        frame_form.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        form_layout = QGridLayout(frame_form)
        form_layout.setContentsMargins(15, 15, 15, 15)

        self.input_data = QDateEdit(self)
        self.input_data.setStyleSheet("padding: 5px;")
        self.input_data.setDisplayFormat("dd/MM/yyyy")
        self.input_data.setCalendarPopup(True)

        self.combo_tipo = QComboBox(self)
        self.combo_tipo.setStyleSheet("padding: 5px;")
        self.combo_tipo.addItems(["ENTRATA", "USCITA"])

        self.combo_stato_pagamento = QComboBox(self)
        self.combo_stato_pagamento.setStyleSheet("padding: 5px;")
        self.combo_stato_pagamento.addItems(["PAGATO", "DA PAGARE"])

        self.combo_categoria = QComboBox(self)
        self.combo_categoria.setStyleSheet("padding: 5px;")
        self.combo_categoria.setEditable(True)
        self.combo_categoria.setInsertPolicy(QComboBox.NoInsert)

        button_refresh_categorie = QPushButton("Aggiorna")
        button_refresh_categorie.setStyleSheet(STYLE_BTN_SECONDARIO)
        button_refresh_categorie.clicked.connect(lambda: self._carica_categorie_salvate(show_errors=True))

        self.input_descrizione = QLineEdit(self)
        self.input_descrizione.setStyleSheet("padding: 5px;")
        self.input_descrizione.setPlaceholderText("Es. Fattura Consorzio Agrario...")
        
        try:
            soggetti = list_soggetti(self.user_id)
            nomi = [s["ragione_sociale"] for s in soggetti]
            completer = QCompleter(nomi, self)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains) 
            self.input_descrizione.setCompleter(completer)
        except Exception:
            pass
            
        self.input_importo = QLineEdit(self)
        self.input_importo.setStyleSheet("padding: 5px;")
        self.input_importo.setPlaceholderText("Imponibile")

        self.input_iva = QLineEdit(self)
        self.input_iva.setStyleSheet("padding: 5px;")
        self.input_iva.setPlaceholderText("IVA")

        form_layout.addWidget(QLabel("<b>Data:</b>"), 0, 0)
        form_layout.addWidget(self.input_data, 0, 1)
        form_layout.addWidget(QLabel("<b>Tipo:</b>"), 0, 2)
        form_layout.addWidget(self.combo_tipo, 0, 3)
        form_layout.addWidget(QLabel("<b>Stato:</b>"), 0, 4)                 
        form_layout.addWidget(self.combo_stato_pagamento, 0, 5)

        form_layout.addWidget(QLabel("<b>Categoria:</b>"), 1, 0)
        form_layout.addWidget(self.combo_categoria, 1, 1, 1, 2)
        form_layout.addWidget(button_refresh_categorie, 1, 3)

        form_layout.addWidget(QLabel("<b>Descrizione:</b>"), 2, 0)
        form_layout.addWidget(self.input_descrizione, 2, 1, 1, 3)

        form_layout.addWidget(QLabel("<b>Imponibile (€):</b>"), 3, 0)
        form_layout.addWidget(self.input_importo, 3, 1)
        form_layout.addWidget(QLabel("<b>IVA (€):</b>"), 3, 2)
        form_layout.addWidget(self.input_iva, 3, 3)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        form_layout.addWidget(line, 4, 0, 1, 6)

        self.label_nome_fattura = QLabel("Nessuna fattura caricata")
        self.label_nome_fattura.setStyleSheet("color: #e67e22; font-weight: bold;")
        
        self.button_importa_fattura = QPushButton("📥 Importa Fattura XML")
        self.button_importa_fattura.setStyleSheet(STYLE_BTN_INFO)
        self.button_importa_fattura.clicked.connect(self.importa_fattura_xml)
        
        self.button_rimuovi_fattura = QPushButton("Rimuovi XML")
        self.button_rimuovi_fattura.setStyleSheet(STYLE_BTN_SECONDARIO)
        self.button_rimuovi_fattura.clicked.connect(self.rimuovi_fattura_movimento)

        form_layout.addWidget(QLabel("<b>Fattura caricata:</b>"), 5, 0)
        form_layout.addWidget(self.label_nome_fattura, 5, 1, 1, 2)

        fattura_actions = QHBoxLayout()
        fattura_actions.setSpacing(10)
        fattura_actions.addWidget(self.button_importa_fattura)
        fattura_actions.addWidget(self.button_rimuovi_fattura)
        fattura_actions.addStretch(1)
        form_layout.addLayout(fattura_actions, 5, 3, 1, 3)

        top_layout.addWidget(frame_form)
        main_splitter.addWidget(top_widget)

        # --- WIDGET INFERIORE: TABELLA PRODOTTI ---
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0,0,0,0)
        bottom_layout.setSpacing(5)

        header_prodotti_layout = QHBoxLayout()
        prodotti_title = QLabel("🛒 Prodotti rilevati in fattura")
        prodotti_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #34495e; padding-top: 5px;")
        header_prodotti_layout.addWidget(prodotti_title)
        
        self.btn_add_riga = QPushButton("➕ Aggiungi prodotto")
        self.btn_add_riga.setStyleSheet("background-color: #27ae60; color: white; border-radius: 4px; padding: 5px; font-weight: bold;")
        self.btn_add_riga.clicked.connect(self._aggiungi_riga_prodotto)
        header_prodotti_layout.addWidget(self.btn_add_riga)
        
        self.btn_remove_riga = QPushButton("➖ Rimuovi prodotto selezionato")
        self.btn_remove_riga.setStyleSheet("background-color: #e74c3c; color: white; border-radius: 4px; padding: 5px; font-weight: bold;")
        self.btn_remove_riga.clicked.connect(self._rimuovi_riga_prodotto)
        header_prodotti_layout.addWidget(self.btn_remove_riga)
        
        header_prodotti_layout.addStretch()
        bottom_layout.addLayout(header_prodotti_layout)

        self.label_prodotti_stato = QLabel("Importa una fattura PDF/XML per vederne il riepilogo.")
        self.label_prodotti_stato.setStyleSheet("color: #7f8c8d; font-style: italic;")
        bottom_layout.addWidget(self.label_prodotti_stato)

        self.progress_parser = QProgressBar(self)
        self.progress_parser.setRange(0, 0)
        self.progress_parser.setTextVisible(False)
        self.progress_parser.setFixedHeight(8)
        self.progress_parser.setVisible(False)
        bottom_layout.addWidget(self.progress_parser)

        self.table_prodotti = TabellaIsolata(0, 10, self)
        self.table_prodotti.setHorizontalHeaderLabels(
            ["#", "Descrizione", "Categoria", "Qta", "Prezzo", "Prezzo unit.", "IVA %", "Totale", "Tipo costo", "Gruppi"]
        )
        self.table_prodotti.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked | QAbstractItemView.EditKeyPressed)
        self.table_prodotti.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_prodotti.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_prodotti.setAlternatingRowColors(True)
        self.table_prodotti.verticalHeader().setVisible(False)
        self.table_prodotti.setStyleSheet("QTableWidget { border: 1px solid #ccc; border-radius: 5px; } QHeaderView::section { background-color: #f8f9fa; font-weight: bold; border: 1px solid #ddd; }")
        self.table_prodotti.itemChanged.connect(self._on_table_prodotti_item_changed)
        
        self.table_prodotti.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        prodotti_header = self.table_prodotti.horizontalHeader()
        prodotti_header.setSectionResizeMode(1, QHeaderView.Stretch)
        for i in [0, 2, 3, 4, 5, 6, 7, 8, 9]:
            prodotti_header.setSectionResizeMode(i, QHeaderView.ResizeToContents)

        self.table_prodotti.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.table_prodotti.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        bottom_layout.addWidget(self.table_prodotti)
        main_splitter.addWidget(bottom_widget)
        main_splitter.setSizes([350, 450])
        main_layout.addWidget(main_splitter)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.button_salva = QPushButton("✅ Salva Movimento")
        self.button_salva.setStyleSheet(STYLE_BTN_SALVA)
        self.button_salva.clicked.connect(self.salva_movimento)
        action_row.addWidget(self.button_salva)

        self.button_annulla = QPushButton("Annulla Modifica")
        self.button_annulla.setStyleSheet(STYLE_BTN_SECONDARIO)
        self.button_annulla.clicked.connect(self.annulla_modifica)
        action_row.addWidget(self.button_annulla)

        action_row.addStretch()
        main_layout.addLayout(action_row)
        main_layout.addStretch()

    def _format_tipo_animale_report(self, tipo_animale, altro_label):
        tipo = (tipo_animale or "").strip().upper()
        if tipo == "ALTRO":
            extra = (altro_label or "").strip()
            return f"Altro ({extra})" if extra else "Altro"
        return tipo.title() if tipo else "-"

    def _format_finalita_report(self, finalita):
        value = (finalita or "").strip().upper()
        if value == "LATTE": return "Da Latte"
        if value == "CARNE": return "Da Carne"
        return "-"

    def _label_gruppo_animale_movimento(self, entry):
        entry_id = int(entry.get("id", 0) or 0)
        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
        tipo_text = self._format_tipo_animale_report(entry.get("tipo_animale", ""), entry.get("altro_label", ""))
        finalita_text = self._format_finalita_report(entry.get("finalita", ""))
        capi = int(entry.get("capi", 0) or 0)
        return f"{group_name} | {tipo_text} | {finalita_text} | {format_number(capi, 0)} capi"

    def _carica_categorie_salvate(self, show_errors=True):
        current_text = self.combo_categoria.currentText().strip()
        try:
            # PEEWEE ORM (1 RIGA)
            query = Movimento.select(Movimento.categoria).where((Movimento.user == self.user_id) & Movimento.categoria.is_null(False)).distinct()
            values = sorted([m.categoria.strip() for m in query if m.categoria.strip()], key=str.lower)
        except Exception as exc:
            if show_errors: QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        self.combo_categoria.blockSignals(True)
        self.combo_categoria.clear()
        self.combo_categoria.addItems(values)
        self.combo_categoria.setCurrentText(current_text)
        self.combo_categoria.blockSignals(False)

    def _get_selected_group_entry_ids_from_table(self):
        if not isinstance(self.pending_parser_movimento_data, dict): return []
        righe = self.pending_parser_movimento_data.get("products_rows", [])
        ids = set()
        for riga in righe:
            for gid in riga.get("groups_ids", []): ids.add(int(gid))
        return list(ids)

    def _append_row(self, table: QTableWidget, row_index: int, values: list[str], right_align_indexes=None, editable_columns=None):
        if right_align_indexes is None: right_align_indexes = []
        editable_set = set(editable_columns or [])
        table.setRowCount(row_index + 1)
        for col_index, value in enumerate(values):
            item = QTableWidgetItem(value)
            if col_index in right_align_indexes: item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            else: item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            
            if col_index in editable_set: item.setFlags(item.flags() | Qt.ItemIsEditable)
            else: item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            
            table.setItem(row_index, col_index, item)

    def _aggiorna_tabella_prodotti_fattura_movimento(self, parser_data):
        self._table_prodotti_updating = True
        try:
            self.table_prodotti.clearSpans() 
            self.table_prodotti.setRowCount(0)

            righe = []
            if isinstance(parser_data, dict):
                raw_rows = parser_data.get("products_rows")
                if isinstance(raw_rows, list): righe = raw_rows

            if not righe:
                self.label_prodotti_stato.setText("Nessun prodotto rilevato nella fattura selezionata.")
                self._mostra_riga_vuota_tabella()
                return

            try: entries = list_azienda_animali_entries(self.user_id)
            except Exception: entries = []

            for idx, riga in enumerate(righe, start=1):
                descrizione = str(riga.get("description") or "-").strip() or "-"
                categoria = normalize_product_category(riga.get("category"))
                qta = str(riga.get("quantity") or "-").strip() or "-"
                prezzo = str(riga.get("price") or "-").strip() or "-"
                prezzo_unit = str(riga.get("unit_price") or "-").strip() or "-"
                iva = str(riga.get("vat_rate") or "-").strip() or "-"
                totale = str(riga.get("line_total") or "-").strip() or "-"
                tipo_costo = normalize_cost_type(riga.get("cost_type"))
                
                testo_gruppi = str(riga.get("groups", "")).strip()
                if "groups_ids" not in riga:
                    matched_ids = []
                    if not testo_gruppi or testo_gruppi in ("-", "Tutti i gruppi"):
                        for entry in entries:
                            entry_id = int(entry.get("id", 0) or 0)
                            tipo_db = (entry.get("tipo_animale") or "").strip().upper()
                            if entry_id > 0 and tipo_db != 'ARCHIVIO': matched_ids.append(entry_id)
                    else:
                        for entry in entries:
                            label = self._label_gruppo_animale_movimento(entry)
                            if label in testo_gruppi: matched_ids.append(int(entry.get("id", 0)))
                    riga["groups_ids"] = matched_ids

                self._append_row(
                    self.table_prodotti, idx - 1,
                    [str(idx), descrizione, categoria, qta, prezzo, prezzo_unit, iva, totale, "", ""],
                    right_align_indexes=[3, 4, 5, 6, 7], editable_columns=[1, 2, 3, 4, 5, 6, 7],
                )

                combo_costo = QComboBox(self)
                combo_costo.addItems(["Variabili", "Fissi"])
                combo_costo.setCurrentText(tipo_costo if tipo_costo in ["Variabili", "Fissi"] else "Variabili")
                combo_costo.currentTextChanged.connect(lambda testo, r_idx=idx-1: self._on_combo_costo_changed(r_idx, testo))
                self.table_prodotti.setCellWidget(idx - 1, 8, combo_costo)

                combo_gruppi = CheckableComboBox(self)
                for entry in entries:
                    entry_id = int(entry.get("id", 0) or 0)
                    if entry_id > 0:
                        label = self._label_gruppo_animale_movimento(entry)
                        combo_gruppi.addItem(label, data=entry_id)
                
                combo_gruppi.set_checked_data(riga.get("groups_ids", []))
                riga["groups"] = combo_gruppi.lineEdit().text()
                
                combo_gruppi.model().dataChanged.connect(
                    lambda top_left, bottom_right, roles, r_idx=idx-1, cb=combo_gruppi: 
                    self._on_combo_gruppi_changed(r_idx, cb.checked_data(), cb.lineEdit().text())
                )
                self.table_prodotti.setCellWidget(idx - 1, 9, combo_gruppi)

            self.label_prodotti_stato.setText(f"Prodotti rilevati: {len(righe)}")
            self._adatta_altezza_tabella()
        finally:
            self._table_prodotti_updating = False
    
    def _set_parser_feedback(self, busy: bool, message: str | None = None):
        if busy and not self._parser_feedback_busy:
            self._parser_feedback_prev_enabled = {
                "importa": self.button_importa_fattura.isEnabled(),
                "rimuovi": self.button_rimuovi_fattura.isEnabled(),
                "salva": self.button_salva.isEnabled(),
                "annulla": self.button_annulla.isEnabled(),
            }

        self._parser_feedback_busy = bool(busy)
        self.progress_parser.setVisible(self._parser_feedback_busy)

        if self._parser_feedback_busy:
            self.button_importa_fattura.setEnabled(False)
            self.button_rimuovi_fattura.setEnabled(False)
            self.button_salva.setEnabled(False)
            self.button_annulla.setEnabled(False)
            if message is not None: self.label_prodotti_stato.setText(message)
            return

        self.button_importa_fattura.setEnabled(self._parser_feedback_prev_enabled.get("importa", True))
        self.button_rimuovi_fattura.setEnabled(self._parser_feedback_prev_enabled.get("rimuovi", True))
        self.button_salva.setEnabled(self._parser_feedback_prev_enabled.get("salva", True))
        self.button_annulla.setEnabled(self._parser_feedback_prev_enabled.get("annulla", False))
        if message is not None: self.label_prodotti_stato.setText(message)

    def _on_table_prodotti_item_changed(self, item: QTableWidgetItem):
        if self._table_prodotti_updating: return
        if item is None or item.column() != 8: return
        if not isinstance(self.pending_parser_movimento_data, dict): return

        righe = self.pending_parser_movimento_data.get("products_rows")
        if not isinstance(righe, list) or item.row() >= len(righe): return

        normalized = normalize_cost_type(item.text())
        righe[item.row()]["cost_type"] = normalized

        if item.text() != normalized:
            self._table_prodotti_updating = True
            item.setText(normalized)
            self._table_prodotti_updating = False

    def _on_combo_costo_changed(self, row_idx, text):
        if not isinstance(self.pending_parser_movimento_data, dict): return
        righe = self.pending_parser_movimento_data.get("products_rows")
        if isinstance(righe, list) and row_idx < len(righe):
            righe[row_idx]["cost_type"] = text

    def _on_combo_gruppi_changed(self, row_idx, selected_ids, selected_text):
        if not isinstance(self.pending_parser_movimento_data, dict): return
        righe = self.pending_parser_movimento_data.get("products_rows")
        if isinstance(righe, list) and row_idx < len(righe):
            righe[row_idx]["groups_ids"] = selected_ids
            righe[row_idx]["groups"] = selected_text if selected_text else "Nessun gruppo"

    def _sincronizza_products_parser_da_form(self, parser_data, selected_group_ids):
        if not isinstance(parser_data, dict): return
        
        righe_aggiornate = []
        for row in range(self.table_prodotti.rowCount()):
            desc = self.table_prodotti.item(row, 1).text().strip() if self.table_prodotti.item(row, 1) else ""
            cat = self.table_prodotti.item(row, 2).text().strip() if self.table_prodotti.item(row, 2) else ""
            qta = self.table_prodotti.item(row, 3).text().strip() if self.table_prodotti.item(row, 3) else ""
            prezzo = self.table_prodotti.item(row, 4).text().strip() if self.table_prodotti.item(row, 4) else ""
            prezzo_u = self.table_prodotti.item(row, 5).text().strip() if self.table_prodotti.item(row, 5) else ""
            iva = self.table_prodotti.item(row, 6).text().strip() if self.table_prodotti.item(row, 6) else ""
            totale = self.table_prodotti.item(row, 7).text().strip() if self.table_prodotti.item(row, 7) else ""
            
            combo_costo = self.table_prodotti.cellWidget(row, 8)
            tipo_costo = combo_costo.currentText() if combo_costo else "Variabili"
            
            combo_gruppi = self.table_prodotti.cellWidget(row, 9)
            groups_text = combo_gruppi.lineEdit().text() if combo_gruppi else ""
            groups_ids = combo_gruppi.checked_data() if combo_gruppi else []
            
            righe_aggiornate.append({
                "description": desc, "category": cat, "quantity": qta, "price": prezzo,
                "unit_price": prezzo_u, "vat_rate": iva, "line_total": totale, 
                "cost_type": tipo_costo, "groups": groups_text, "groups_ids": groups_ids
            })
            
        parser_data["products_rows"] = righe_aggiornate
        righe = parser_data.get("products_rows")
        if not isinstance(righe, list): return

        try: entries = list_azienda_animali_entries(self.user_id)
        except Exception: entries = []

        opzioni = []
        for entry in entries:
            entry_id = int(entry.get("id", 0) or 0)
            capi = int(entry.get("capi", 0) or 0)
            if entry_id > 0 and capi > 0:
                opzioni.append((entry_id, self._label_gruppo_animale_movimento(entry)))

        labels_by_id = {entry_id: label for entry_id, label in opzioni}
        normalized_selected_ids = []
        for raw in selected_group_ids or []:
            entry_id = int(raw or 0)
            if entry_id in labels_by_id and entry_id not in normalized_selected_ids:
                normalized_selected_ids.append(entry_id)

        if not normalized_selected_ids and opzioni:
            normalized_selected_ids = [entry_id for entry_id, _label in opzioni]

        selected_labels = [labels_by_id[entry_id] for entry_id in normalized_selected_ids if entry_id in labels_by_id]
        if opzioni and normalized_selected_ids and len(normalized_selected_ids) == len(opzioni): groups_text = "Tutti i gruppi"
        elif selected_labels: groups_text = ", ".join(selected_labels)
        elif opzioni: groups_text = "Nessun gruppo"
        else: groups_text = "Nessun gruppo disponibile"

        prodotti = []
        for riga in righe:
            descrizione = str(riga.get("description") or "-").strip() or "-"
            categoria = normalize_product_category(riga.get("category"))
            tipo_costo = normalize_cost_type(riga.get("cost_type"))
            quantita_text = str(riga.get("quantity") or "-").strip() or "-"
            prezzo_text = str(riga.get("price") or "-").strip() or "-"
            prezzo_unit_text = str(riga.get("unit_price") or "-").strip() or "-"
            iva_text = str(riga.get("vat_rate") or "-").strip() or "-"
            totale_text = str(riga.get("line_total") or "-").strip() or "-"
            quantita = parse_decimal(quantita_text, allow_zero=True, allow_negative=False)
            totale = parse_decimal(totale_text, allow_zero=True, allow_negative=False)
            
            if quantita is None or totale is None or quantita <= 0 or totale <= 0: continue

            riga["category"] = categoria
            riga["cost_type"] = tipo_costo
            if "groups" not in riga or riga["groups"] in (None, "", "-"): riga["groups"] = groups_text

            prodotti.append(build_detailed_product_storage_line(
                    descrizione, quantita_text, totale_text, tipo_costo, categoria, riga["groups"],
                    price_text=prezzo_text, unit_price_text=prezzo_unit_text, vat_rate_text=iva_text,
                ))

        parser_data["products"] = serialize_product_storage_lines(prodotti, separator="\n")
        
    def _normalizza_importo(self, raw, allow_zero=False):
        return parse_decimal(raw, allow_zero=allow_zero, allow_negative=False)

    def _valore_parser_to_float(self, value, allow_zero=False):
        if value is None: return None
        if isinstance(value, (int, float)): number = float(value)
        else:
            try: number = float(value)
            except (TypeError, ValueError): return self._normalizza_importo(str(value), allow_zero=allow_zero)
        if number < 0: return None
        if number == 0 and not allow_zero: return None
        return number

    def _valore_parser_to_text(self, value, decimals=2):
        number = self._valore_parser_to_float(value, allow_zero=True)
        if number is not None: return format_number(number, decimals)
        if value in (None, ""): return "-"
        return str(value).strip()

    def _estrai_valore_campo_parser(self, fields, field_name):
        field = fields.get(field_name)
        if field is None: return ""
        valore = getattr(field, "normalized_value", None)
        if valore in (None, ""): valore = getattr(field, "raw_value", None)
        return str(valore).strip() if valore is not None else ""

    def _estrai_importo_parser(self, fields, field_name, allow_zero):
        field = fields.get(field_name)
        if field is None: return None
        valore = getattr(field, "normalized_value", None)
        if valore in (None, ""): valore = getattr(field, "raw_value", None)
        if valore in (None, ""): return None
        if isinstance(valore, (int, float)):
            numero = float(valore)
            if numero < 0: return None
            if not allow_zero and numero <= 0: return None
            return numero
        return self._normalizza_importo(str(valore), allow_zero=allow_zero)

    def _normalizza_data_fattura(self, raw_data):
        if not raw_data: return ""
        testo_data = str(raw_data).strip().replace(".", "/").replace("-", "/")
        formati = []
        if re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", testo_data): formati = ["%Y/%m/%d"]
        elif re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", testo_data): formati = ["%d/%m/%Y", "%d/%m/%y"]
        for formato in formati:
            try:
                data = datetime.strptime(testo_data, formato)
                return data.strftime("%d/%m/%Y")
            except ValueError: continue
        return ""

    def _testo_da_struttura_parser(self, struttura):
        if not isinstance(struttura, dict): return ""
        righe = []
        for blocco in struttura.values():
            if not isinstance(blocco, list): continue
            for riga in blocco:
                testo_riga = str(riga).strip()
                if testo_riga: righe.append(testo_riga)
        return "\n".join(righe)

    def _normalizza_risultato_parser(self, risultato):
        if not isinstance(risultato, dict): return risultato
        fields = {}
        for key in (
            "invoice_number", "invoice_date", "due_date", "supplier_name",
            "supplier_vat", "customer_name", "customer_vat", "total_amount",
            "taxable_total", "vat_total", "payment_terms", "invoice_header",
        ):
            value = risultato.get(key)
            if value not in (None, ""):
                fields[key] = SimpleNamespace(raw_value=value, normalized_value=value)

        raw_items = risultato.get("line_items", []) or []
        normalized_items = []
        for item in raw_items:
            if isinstance(item, dict):
                normalized_items.append(
                    SimpleNamespace(
                        description=item.get("description"), quantity=item.get("quantity"), price=item.get("price"),
                        unit_price=item.get("unit_price", item.get("price")), line_total=item.get("line_total"),
                        vat_rate=item.get("vat_rate", item.get("vat")), category=item.get("category"), cost_type=item.get("cost_type"),
                    )
                )
            else: normalized_items.append(item)

        return SimpleNamespace(fields=fields, line_items=normalized_items, warnings=risultato.get("warnings", []) or [], structure=risultato.get("structure", {}) or {})

    def _estrai_intestazione_fattura(self, testo, file_path):
        righe = []
        for riga in testo.splitlines():
            pulita = re.sub(r"\s+", " ", riga).strip()
            if pulita: righe.append(pulita)
        if not righe: return f"Fattura importata: {Path(file_path).name}"

        parole_escluse = ("fattura", "invoice", "numero", "data", "date", "totale", "iva", "imponibile", "pagamento", "scadenza", "iban", "banca", "documento", "cliente", "fornitore",)
        for riga in righe[:40]:
            testo_riga = riga.lower()
            if len(riga) < 3 or not re.search(r"[A-Za-z]", riga): continue
            if re.fullmatch(r"[0-9EUR.,/\\\-\s]+", riga): continue
            if any(parola in testo_riga for parola in parole_escluse): continue
            return riga[:120]

        for riga in righe[:15]:
            if re.search(r"[A-Za-z]", riga): return riga[:120]
        return f"Fattura importata: {Path(file_path).name}"

    def _get_parser_fatture_function(self):
        parse_invoice_pdf = getattr(self, "_parser_fatture_parse_fn", None)
        if parse_invoice_pdf is not None: return parse_invoice_pdf

        project_root = None
        current_file = Path(__file__).resolve()
        for parent in current_file.parents:
            candidate = parent / "parserFatture" / "parserFatture.py"
            if candidate.exists():
                project_root = parent
                break

        if project_root is not None:
            project_root_str = str(project_root)
            if project_root_str not in sys.path: sys.path.insert(0, project_root_str)

        try:
            parser_module = importlib.import_module("parserFatture.parserFatture")
            parse_invoice_pdf = getattr(parser_module, "parse_invoice_pdf")
        except Exception as exc: raise RuntimeError("parserFatture non disponibile. Verifica il modulo parserFatture/parserFatture.py") from exc

        self._parser_fatture_parse_fn = parse_invoice_pdf
        return parse_invoice_pdf

    def avvia_parser_fattura_async(self, file_path, on_success, on_error, on_done=None, on_progress=None):
        parse_fn = self._get_parser_fatture_function()
        thread = QThread(self)
        worker = _InvoiceParserWorker(parse_fn, str(file_path))
        if not hasattr(self, "_parser_callback_proxies_in_corso"): self._parser_callback_proxies_in_corso = set()

        def _release_proxy(proxy):
            self._parser_callback_proxies_in_corso.discard(proxy)
            proxy.deleteLater()

        proxy = _InvoiceParserCallbackProxy(on_success=on_success, on_error=on_error, on_done=on_done, on_progress=on_progress, release_cb=_release_proxy, parent=self)
        worker.moveToThread(thread)
        self._parser_callback_proxies_in_corso.add(proxy)

        thread.started.connect(worker.run)
        worker.success.connect(proxy.handle_success)
        worker.error.connect(proxy.handle_error)
        worker.progress.connect(proxy.handle_progress)
        worker.finished.connect(proxy.handle_finished)

        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        if not hasattr(self, "_parser_threads_in_corso"): self._parser_threads_in_corso = set()
        if not hasattr(self, "_parser_workers_in_corso"): self._parser_workers_in_corso = set()

        self._parser_threads_in_corso.add(thread)
        self._parser_workers_in_corso.add(worker)

        thread.finished.connect(lambda: self._parser_threads_in_corso.discard(thread))
        thread.finished.connect(lambda: self._parser_workers_in_corso.discard(worker))
        thread.start()

    def _costruisci_dati_parser_movimento(self, risultato, fields):
        warnings = getattr(risultato, "warnings", []) or []
        line_items = getattr(risultato, "line_items", []) or []

        prodotti = []
        prodotti_rows = []
        for line in line_items:
            descrizione = str(getattr(line, "description", "") or "").strip()
            categoria_raw = getattr(line, "category", None)
            quantita_raw = getattr(line, "quantity", None)
            prezzo_raw = getattr(line, "price", None)
            prezzo_unit_raw = getattr(line, "unit_price", None)
            if prezzo_raw in (None, ""): prezzo_raw = prezzo_unit_raw
            totale_raw = getattr(line, "line_total", None)
            iva_raw = getattr(line, "vat_rate", None)
            tipo_costo_raw = getattr(line, "cost_type", None)

            quantita = self._valore_parser_to_float(quantita_raw, allow_zero=True)
            totale = self._valore_parser_to_float(totale_raw, allow_zero=True)

            if not descrizione and quantita is None and totale is None and prezzo_unit_raw in (None, ""): continue

            prodotti_rows.append({
                    "description": descrizione or "-", "category": normalize_product_category(categoria_raw),
                    "quantity": self._valore_parser_to_text(quantita_raw, 3), "price": self._valore_parser_to_text(prezzo_raw, 4),
                    "unit_price": self._valore_parser_to_text(prezzo_unit_raw, 4), "vat_rate": self._valore_parser_to_text(iva_raw, 2),
                    "line_total": self._valore_parser_to_text(totale_raw, 2), "cost_type": normalize_cost_type(tipo_costo_raw), "groups": "-",
                })

            if not descrizione or quantita is None or totale is None or quantita <= 0 or totale <= 0: continue
            prodotti.append(build_basic_product_storage_line(descrizione, format_number(quantita, 3), format_number(totale, 2)))

        campi_riepilogo = []
        for field_name in sorted(fields):
            field = fields.get(field_name)
            if field is None: continue
            valore = getattr(field, "normalized_value", None)
            if valore in (None, ""): valore = getattr(field, "raw_value", None)
            valore_text = str(valore).strip() if valore not in (None, "") else "-"
            conf = getattr(field, "confidence", 0.0) or 0.0
            try: conf_pct = int(round(float(conf) * 100))
            except (TypeError, ValueError): conf_pct = 0
            needs_review = bool(getattr(field, "requires_confirmation", False))
            campi_riepilogo.append(f"{field_name.replace('_', ' ').title()}: {valore_text} ({conf_pct}%){' [Conferma]' if needs_review else ''}")

        return {
            "invoice_number": self._estrai_valore_campo_parser(fields, "invoice_number"), "invoice_date": self._estrai_valore_campo_parser(fields, "invoice_date"),
            "due_date": self._estrai_valore_campo_parser(fields, "due_date"), "supplier_name": self._estrai_valore_campo_parser(fields, "supplier_name"),
            "supplier_vat": self._estrai_valore_campo_parser(fields, "supplier_vat"), "customer_name": self._estrai_valore_campo_parser(fields, "customer_name"),
            "customer_vat": self._estrai_valore_campo_parser(fields, "customer_vat"), "total_amount": self._estrai_valore_campo_parser(fields, "total_amount"),
            "taxable_total": self._estrai_valore_campo_parser(fields, "taxable_total"), "vat_total": self._estrai_valore_campo_parser(fields, "vat_total"),
            "payment_terms": self._estrai_valore_campo_parser(fields, "payment_terms"), "warnings": " | ".join(str(w).strip() for w in warnings if str(w).strip()),
            "products": serialize_product_storage_lines(prodotti, separator="\n"), "products_rows": prodotti_rows, "fields_view": " | ".join(campi_riepilogo),
        }

    def _estrai_valori_parser_db(self, parser_data):
        if not isinstance(parser_data, dict): return (None,) * len(self._PARSER_DB_FIELDS)
        return tuple(parser_data.get(field_name) for field_name in self._PARSER_DB_FIELDS)

    def _applica_dati_parser_al_form(self, dati):
        mapping = (("data", self.input_data), ("tipo", self.combo_tipo), ("categoria", self.combo_categoria), ("descrizione", self.input_descrizione), ("importo", self.input_importo), ("iva", self.input_iva))
        for chiave, widget in mapping:
            valore = dati.get(chiave)
            if not valore: continue
            if widget is self.input_data:
                data = QDate.fromString(str(valore), "dd/MM/yyyy")
                if data.isValid(): self.input_data.setDate(data)
            elif widget in (self.combo_tipo, self.combo_categoria): widget.setCurrentText(str(valore))
            else: widget.setText(str(valore))

    def analizza_fattura_con_parser_fatture(self, pdf_path, file_path, risultato=None):
        if risultato is None:
            parse_invoice_pdf = self._get_parser_fatture_function()
            risultato = parse_invoice_pdf(str(pdf_path))
            
        risultato = self._normalizza_risultato_parser(risultato)
        fields = getattr(risultato, "fields", {}) or {}
        parser_data = self._costruisci_dati_parser_movimento(risultato, fields)

        data_raw = self._estrai_valore_campo_parser(fields, "invoice_date")
        data_out = self._normalizza_data_fattura(data_raw)

        imponibile = self._estrai_importo_parser(fields, "taxable_total", allow_zero=False)
        iva = self._estrai_importo_parser(fields, "vat_total", allow_zero=True)
        totale = self._estrai_importo_parser(fields, "total_amount", allow_zero=False)

        if imponibile is None and totale is not None:
            if iva is not None and totale >= iva: imponibile = totale - iva
            else: imponibile = totale
        if iva is None: iva = 0.0

        struttura = getattr(risultato, "structure", {}) or {}
        testo_struttura = self._testo_da_struttura_parser(struttura)
        
        tipo = "ENTRATA" if ("nota di credito" in testo_struttura.lower() or "rimborso" in testo_struttura.lower()) else "USCITA"
        descrizione = ""
        
        if isinstance(struttura, dict):
            raw_headers = struttura.get("invoice_header")
            if isinstance(raw_headers, list):
                for raw_header in raw_headers:
                    header_text = str(raw_header or "").strip()
                    if header_text:
                        descrizione = header_text
                        break

        if not descrizione: descrizione = self._estrai_valore_campo_parser(fields, "invoice_header")
        if not descrizione and testo_struttura: descrizione = self._estrai_intestazione_fattura(testo_struttura, file_path)
        if not descrizione: descrizione = self._estrai_valore_campo_parser(fields, "supplier_name")
        if not descrizione:
            numero_fattura = self._estrai_valore_campo_parser(fields, "invoice_number")
            descrizione = f"Fattura {numero_fattura}" if numero_fattura else f"Fattura importata: {Path(file_path).name}"

        return {
            "data": data_out or datetime.now().strftime("%d/%m/%Y"), "tipo": tipo, "categoria": "Fattura",
            "descrizione": descrizione, "importo": format_number(imponibile, 2) if imponibile is not None else "",
            "iva": format_number(iva, 2), "parser_data": parser_data,
        }

    def archivia_fattura_caricata(self, file_path, origine):
        src = Path(file_path)
        if not src.exists(): raise RuntimeError("File fattura non trovato.")

        archivio_dir = get_fatture_user_dir(self.user_id)
        nome_pulito = re.sub(r"[^A-Za-z0-9._-]", "_", src.name)
        nome_dest = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{nome_pulito}"
        dest = archivio_dir / nome_dest
        shutil.copy2(src, dest)
        percorso_db = to_storage_fattura_path(dest)

        # PEEWEE ORM
        fattura = Fattura.create(
            user=self.user_id,
            origine=origine,
            nome_originale=src.name,
            percorso_file=percorso_db,
            data_caricamento=datetime.now().isoformat(timespec="seconds")
        )
        return fattura.id, str(dest)

    def importa_fattura_xml(self):
        if self.movimento_in_modifica_id is not None: self.annulla_modifica()
        file_paths, _ = QFileDialog.getOpenFileNames(self, "Seleziona Fatture Elettroniche", "", "Fatture XML (*.xml *.p7m)")
        if not file_paths: return

        self.fatture_queue.extend(file_paths)
        self._processa_prossima_fattura_in_coda()

    def _processa_prossima_fattura_in_coda(self):
        if not self.fatture_queue: return
        file_path = self.fatture_queue.pop(0)
        rimanenti = len(self.fatture_queue)

        try:
            fattura_id, percorso_archiviato = self.archivia_fattura_caricata(file_path, "MOVIMENTO")
        except Exception as exc:
            QMessageBox.critical(self, "Importazione fallita", f"Impossibile salvare la fattura {Path(file_path).name}: {exc}")
            self._processa_prossima_fattura_in_coda()
            return

        self.pending_fattura_movimento_id = int(fattura_id or 0)
        self.pending_fattura_movimento_path = percorso_archiviato
        
        testo_label = Path(percorso_archiviato).name
        if rimanenti > 0: testo_label += f"  ( + altre {rimanenti} in coda )"
        self.label_nome_fattura.setText(testo_label)
        
        try:
            # USIAMO LA NUOVA FUNZIONE CENTRALIZZATA!
            risultato_xml = self.parse_xml_fattura_standard(percorso_archiviato)
            dati = {
                "data": self._normalizza_data_fattura(risultato_xml.get("invoice_date")) or datetime.now().strftime("%d/%m/%Y"),
                "tipo": "USCITA", "categoria": "Fattura", "descrizione": risultato_xml.get("supplier_name", "Fornitore XML"),
                "importo": format_number(risultato_xml.get("taxable_total", 0.0), 2), "iva": format_number(risultato_xml.get("vat_total", 0.0), 2),
                "parser_data": risultato_xml
            }
            
            prodotti_testo = []
            for riga in risultato_xml.get("line_items", []): prodotti_testo.append(f"{riga['description']} | {riga['quantity']} | {riga['line_total']}")
            dati["parser_data"]["products"] = "\n".join(prodotti_testo)
            dati["parser_data"]["products_rows"] = risultato_xml.get("line_items", [])

            self._applica_dati_parser_al_form(dati)
            self.pending_parser_movimento_data = dati["parser_data"]
            self._aggiorna_tabella_prodotti_fattura_movimento(self.pending_parser_movimento_data)
            
            if is_blank(self.input_importo.text()): QMessageBox.warning(self, "Attenzione", "Importo non trovato automaticamente. Verificalo manualmente.")
            
        except Exception as exc:
            QMessageBox.warning(self, "Errore XML", f"Impossibile analizzare il file XML: {exc}")



    def rimuovi_fattura_movimento(self, skip_queue_prompt=False):
        self.pending_fattura_movimento_id = None
        self.pending_fattura_movimento_path = None
        self.pending_parser_movimento_data = None
        self.label_nome_fattura.setText("Nessuna fattura caricata")
        self._aggiorna_tabella_prodotti_fattura_movimento(None)
        
        if not skip_queue_prompt and hasattr(self, "fatture_queue") and self.fatture_queue:
            if QMessageBox.question(self, "Coda attiva", "Fattura rimossa. Passare alla prossima in coda?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
                self._processa_prossima_fattura_in_coda()
            else: self.fatture_queue.clear()

    def _carica_fattura_collegata_movimento(self, movimento_id: int, parser_products: str, parser_data: dict | None = None,):
        self.rimuovi_fattura_movimento()
        try:
            # PEEWEE ORM
            fattura = (Fattura.select(Fattura.nome_originale)
                        .where((Fattura.user == self.user_id) & (Fattura.movimento == movimento_id))
                        .order_by(Fattura.data_caricamento.desc(), Fattura.id.desc())
                        .first())
            if fattura and fattura.nome_originale:
                self.label_nome_fattura.setText(str(fattura.nome_originale))
        except Exception:
            pass

        active_data = parser_data if isinstance(parser_data, dict) else None
        rows = active_data.get("products_rows") if active_data is not None else None
        if not isinstance(rows, list):
            rows = extract_products_rows_from_parser_text(parser_products)
            if rows:
                for riga in rows:
                    riga["cost_type"] = normalize_cost_type(riga.get("cost_type"))
                    riga["category"] = normalize_product_category(riga.get("category"))
            if active_data is not None: active_data["products_rows"] = rows

        if active_data is not None and "products" not in active_data: active_data["products"] = parser_products

        if rows:
            if active_data is not None:
                self.pending_parser_movimento_data = active_data
                self._aggiorna_tabella_prodotti_fattura_movimento(active_data)
            else: self._aggiorna_tabella_prodotti_fattura_movimento({"products_rows": rows})
        else:
            if active_data is not None: self.pending_parser_movimento_data = active_data
            self._aggiorna_tabella_prodotti_fattura_movimento(None)

    def _reset_form(self, skip_queue_prompt=False):
        self.movimento_in_modifica_id = None
        self.button_salva.setText("✅ Salva Movimento")
        self.button_annulla.setEnabled(False)
        self.input_data.setDate(QDate.currentDate())
        self.combo_tipo.setCurrentText("ENTRATA")
        self.combo_stato_pagamento.setCurrentText("PAGATO")
        self.combo_categoria.setCurrentText("")
        self.input_descrizione.clear()
        self.input_importo.clear()
        self.input_iva.setText("0,00")
        self.rimuovi_fattura_movimento(skip_queue_prompt=skip_queue_prompt)

    def annulla_modifica(self):
        self._reset_form()
        self.edit_cancelled.emit()

    def carica_movimento_in_modifica(self, movimento_id: int):
        movimento_id_value = int(movimento_id or 0)
        if movimento_id_value <= 0: return QMessageBox.critical(self, "Errore", "Movimento non valido.")

        try:
            # PEEWEE ORM
            m = Movimento.get_or_none((Movimento.id == movimento_id_value) & (Movimento.user == self.user_id))
        except Exception as exc:
            return QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")

        if not m: return QMessageBox.critical(self, "Errore", "Movimento non trovato o non modificabile.")

        parser_values = [
            m.parser_invoice_number, m.parser_invoice_date, m.parser_due_date, m.parser_supplier_name, m.parser_supplier_vat,
            m.parser_customer_name, m.parser_customer_vat, m.parser_total_amount, m.parser_taxable_total, m.parser_vat_total,
            m.parser_payment_terms, m.parser_warnings, m.parser_products, m.parser_fields_view
        ]
        
        parser_data = None
        if parser_values and any(str(value or "").strip() for value in parser_values):
            parser_data = dict(zip(self._PARSER_DB_FIELDS, parser_values))

        parser_products = str(m.parser_products or "")
        if parser_data is not None:
            rows = extract_products_rows_from_parser_text(parser_products)
            if rows:
                for riga in rows:
                    riga["cost_type"] = normalize_cost_type(riga.get("cost_type"))
                    riga["category"] = normalize_product_category(riga.get("category"))
                parser_data["products_rows"] = rows

        try: data_qt = QDate.fromString(str(m.data_op or ""), "yyyy-MM-dd")
        except Exception: data_qt = QDate.currentDate()
        if not data_qt.isValid(): data_qt = QDate.currentDate()

        self.movimento_in_modifica_id = int(m.id)
        self.button_salva.setText("🔄 Aggiorna Movimento")
        self.button_annulla.setEnabled(True)

        self.input_data.setDate(data_qt)
        self.combo_tipo.setCurrentText(str(m.tipo or "ENTRATA"))
        self.combo_stato_pagamento.setCurrentText(str(m.stato_pagamento or "PAGATO"))
        self.combo_categoria.setCurrentText(str(m.categoria or ""))
        self.input_descrizione.setText(str(m.descrizione or ""))
        self.input_importo.setText(format_number(float(m.importo or 0), 2))
        self.input_iva.setText(format_number(float(m.iva_importo or 0), 2))

        self._carica_fattura_collegata_movimento(movimento_id_value, str(parser_products or ""), parser_data=parser_data,)

    def salva_movimento(self):
        data_qt = self.input_data.date()
        if not data_qt.isValid(): return QMessageBox.critical(self, "Errore", "Inserisci la data.")
        data_db = data_qt.toString("yyyy-MM-dd")

        importo_text = self.input_importo.text().strip()
        if not importo_text: return QMessageBox.critical(self, "Errore", "Inserisci l'importo.")

        importo_val = self._normalizza_importo(importo_text, allow_zero=False)
        if importo_val is None: return QMessageBox.critical(self, "Errore", "Importo non valido.")

        iva_text = self.input_iva.text().strip()
        if not iva_text: iva_val = 0.0
        else:
            iva_val = self._normalizza_importo(iva_text, allow_zero=True)
            if iva_val is None: return QMessageBox.critical(self, "Errore", "Valore IVA non valido.")

        tipo_value = self.combo_tipo.currentText().strip() or "ENTRATA"
        stato_pagamento_value = self.combo_stato_pagamento.currentText().strip() or "PAGATO"
        if tipo_value not in ("ENTRATA", "USCITA"): return QMessageBox.critical(self, "Errore", "Tipo movimento non valido.")

        categoria_value = self.combo_categoria.currentText().strip()
        descrizione_value = self.input_descrizione.text().strip()

        # 1. Inizializziamo sempre i dati (vitale per le spese inserite a mano senza XML)
        if not isinstance(self.pending_parser_movimento_data, dict):
            self.pending_parser_movimento_data = {"products_rows": []}
        
        parser_data = self.pending_parser_movimento_data

        # 2. SINCRONIZZIAMO la tabella visiva PRIMA di estrarre i gruppi
        self._sincronizza_products_parser_da_form(parser_data, [])
        
        # 3. ORA possiamo estrarre i gruppi in modo affidabile, perché sono stati letti!
        selected_gruppi_ids = self._get_selected_group_entry_ids_from_table()
        
        # Sincronizziamo di nuovo per creare i testi di riepilogo perfetti
        self._sincronizza_products_parser_da_form(parser_data, selected_gruppi_ids)

        parser_values = self._estrai_valori_parser_db(parser_data)
        parser_dict = dict(zip(self._PARSER_DB_FIELDS, parser_values))

        try:
            # TRANSAZIONE INDISTRUTTIBILE PEEWEE
            with db.atomic():
                if self.movimento_in_modifica_id is None:
                    mov = Movimento.create(
                        user=self.user_id,
                        data_op=data_db,
                        tipo=tipo_value,
                        categoria=categoria_value,
                        descrizione=descrizione_value,
                        importo=importo_val,
                        iva_importo=iva_val,
                        stato_pagamento=stato_pagamento_value,
                        **{f"parser_{k}": v for k, v in parser_dict.items()}
                    )
                    movimento_id = mov.id
                    msg_ok = "Movimento salvato nel database!"
                else:
                    Movimento.update(
                        data_op=data_db,
                        tipo=tipo_value,
                        categoria=categoria_value,
                        descrizione=descrizione_value,
                        importo=importo_val,
                        iva_importo=iva_val,
                        stato_pagamento=stato_pagamento_value,
                        **{f"parser_{k}": v for k, v in parser_dict.items()}
                    ).where((Movimento.id == self.movimento_in_modifica_id) & (Movimento.user == self.user_id)).execute()
                    
                    movimento_id = int(self.movimento_in_modifica_id)
                    msg_ok = "Movimento aggiornato nel database!"

                if movimento_id > 0:
                    set_movimento_animali_links(self.user_id, movimento_id, selected_gruppi_ids)
                    
                    # --- NUOVA LOGICA: ALLOCAZIONE COSTI SUI SINGOLI CAPI ---
                    if tipo_value == 'USCITA' and selected_gruppi_ids:
                        from database import alloca_costi_a_capi
                        alloca_costi_a_capi(self.user_id, selected_gruppi_ids, importo_val)

                if self.pending_fattura_movimento_id is not None and movimento_id > 0:
                    Fattura.update(movimento=movimento_id).where((Fattura.id == self.pending_fattura_movimento_id) & (Fattura.user == self.user_id)).execute()

        except Exception as exc:
            return QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")

        self._reset_form(skip_queue_prompt=True)
        self._carica_categorie_salvate(show_errors=False)

        if hasattr(self, "fatture_queue") and self.fatture_queue: self._processa_prossima_fattura_in_coda()
        else:
            QMessageBox.information(self, "Successo", msg_ok)
            self.movimento_saved.emit(movimento_id)

    def _aggiungi_riga_prodotto(self):
        if not isinstance(self.pending_parser_movimento_data, dict): self.pending_parser_movimento_data = {"products_rows": []}
        if self.table_prodotti.rowCount() == 1 and self.table_prodotti.columnSpan(0, 0) > 1:
            self.table_prodotti.clearSpans()
            self.table_prodotti.setRowCount(0)
            
        row_count = self.table_prodotti.rowCount()
        idx = row_count + 1
        
        self._table_prodotti_updating = True
        try:
            self._append_row(
                self.table_prodotti, row_count,
                [str(idx), "", "", "", "", "", "", "", "", ""],
                right_align_indexes=[3, 4, 5, 6, 7], editable_columns=[1, 2, 3, 4, 5, 6, 7],
            )
            
            combo_costo = QComboBox(self)
            combo_costo.addItems(["Variabili", "Fissi"])
            self.table_prodotti.setCellWidget(row_count, 8, combo_costo)

            combo_gruppi = CheckableComboBox(self)
            try:
                entries = list_azienda_animali_entries(self.user_id)
                for entry in entries:
                    entry_id = int(entry.get("id", 0) or 0)
                    tipo_db = (entry.get("tipo_animale") or "").strip().upper()
                    if entry_id > 0 and tipo_db != 'ARCHIVIO':
                        combo_gruppi.addItem(self._label_gruppo_animale_movimento(entry), data=entry_id)
            except Exception: pass
            
            self.table_prodotti.setCellWidget(row_count, 9, combo_gruppi)
            self._adatta_altezza_tabella()
        finally:
            self._table_prodotti_updating = False

    def _rimuovi_riga_prodotto(self):
        if self.table_prodotti.rowCount() == 1 and self.table_prodotti.columnSpan(0, 0) > 1: return
        current_row = self.table_prodotti.currentRow()
        if current_row >= 0:
            self.table_prodotti.removeRow(current_row)
            for row in range(self.table_prodotti.rowCount()):
                item = self.table_prodotti.item(row, 0)
                if item: item.setText(str(row + 1))
            if self.table_prodotti.rowCount() == 0: self._mostra_riga_vuota_tabella()
            else: self._adatta_altezza_tabella()
    
    def _adatta_altezza_tabella(self):
        header_h = self.table_prodotti.horizontalHeader().height()
        if header_h < 20: header_h = 30
        rows_h = sum((self.table_prodotti.rowHeight(i) if self.table_prodotti.rowHeight(i) > 0 else 30) for i in range(self.table_prodotti.rowCount()))
        self.table_prodotti.setFixedHeight(header_h + rows_h + 2)

    def _mostra_riga_vuota_tabella(self):
        self.table_prodotti.clearSpans()
        self.table_prodotti.setRowCount(1)
        item_empty = QTableWidgetItem("Nessun prodotto. Importa una fattura PDF o usa 'Aggiungi prodotto'.")
        item_empty.setTextAlignment(Qt.AlignCenter)
        
        from PySide6.QtGui import QColor
        item_empty.setForeground(QColor("#7f8c8d"))
        item_empty.setFlags(Qt.ItemIsEnabled)
        self.table_prodotti.setItem(0, 0, item_empty)
        self.table_prodotti.setSpan(0, 0, 1, self.table_prodotti.columnCount())
        self.table_prodotti.setRowHeight(0, 50)
        self._adatta_altezza_tabella()
    