import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QSplitter,
    QDialog
)

from models import db, ProduzioneLatte, ProduzioneCarne, Movimento, Fattura
from app_utils import format_eur, format_number, is_blank, parse_decimal, TabellaIsolata
from database import (
    get_movimento_animali_entry_ids,
    list_azienda_animali_entries,
    remove_azienda_animale_capi,
    set_movimento_animali_links,
)
from qt_app.pages.zootecnia_parser_support import ZootecniaParserSupport


class ZootecniaCarnePage(ZootecniaParserSupport, QWidget):
    produzione_changed = Signal()

    KG_PER_QUINTALE = 100.0
    _UNITA_QTA = ("Kg", "Quintali")
    _UNITA_PREZZO = ("EUR/Kg", "EUR/Quintale")
    _PARSER_DB_FIELDS = (
        "invoice_number", "invoice_date", "due_date", "supplier_name",
        "supplier_vat", "customer_name", "customer_vat", "total_amount",
        "taxable_total", "vat_total", "payment_terms", "warnings",
        "products", "fields_view",
    )

    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = int(user_id)

        self.produzione_carne_in_modifica_id = None
        self.pending_fattura_carne_id = None
        self.pending_fattura_carne_path = None
        self.pending_parser_carne_data = None
        self._parser_carne_busy = False
        self._parser_carne_prev_status_text = ""

        self._carne_gruppi_entries_by_id = {}

        self._build_ui()
        self.aggiorna_lista_gruppi_carne()
        self.carica_produzioni_carne(show_errors=False)

    def _build_ui(self):
        STYLE_BTN_SALVA = "background-color: #28a745; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_MODIFICA = "background-color: #ffc107; color: black; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_ELIMINA = "background-color: #dc3545; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_SECONDARIO = "background-color: #6c757d; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_INFO = "background-color: #17a2b8; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(10)

        main_splitter = QSplitter(Qt.Vertical)

        # --- WIDGET SUPERIORE ---
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(15)

        # -- Colonna Sinistra (Form + Fattura)
        left_col = QVBoxLayout()
        left_col.setSpacing(15)

        # Form Produzione
        frame_form = QFrame(self)
        frame_form.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        form_layout = QGridLayout(frame_form)
        form_layout.setContentsMargins(15, 15, 15, 15)
        
        lbl_form = QLabel("🥩 Dati Produzione Carne")
        lbl_form.setStyleSheet("font-size: 16px; font-weight: bold; color: #34495e; border: none;")
        form_layout.addWidget(lbl_form, 0, 0, 1, 3)

        self.input_data = QDateEdit(self)
        self.input_data.setStyleSheet("padding: 5px;")
        self.input_data.setDisplayFormat("dd/MM/yyyy")
        self.input_data.setCalendarPopup(True)
        self.input_data.setDate(QDate.currentDate())

        self.input_quantita = QLineEdit(self)
        self.input_quantita.setStyleSheet("padding: 5px;")
        self.input_quantita.setPlaceholderText("Quantita venduta")

        self.combo_unita_quantita = QComboBox(self)
        self.combo_unita_quantita.setStyleSheet("padding: 5px;")
        self.combo_unita_quantita.addItems(self._UNITA_QTA)

        self.input_prezzo = QLineEdit(self)
        self.input_prezzo.setStyleSheet("padding: 5px;")
        self.input_prezzo.setText("0,00")

        self.combo_unita_prezzo = QComboBox(self)
        self.combo_unita_prezzo.setStyleSheet("padding: 5px;")
        self.combo_unita_prezzo.addItems(self._UNITA_PREZZO)

        form_layout.addWidget(QLabel("<b>Data produzione:</b>"), 1, 0)
        form_layout.addWidget(self.input_data, 1, 1, 1, 2)

        form_layout.addWidget(QLabel("<b>Quantita:</b>"), 2, 0)
        form_layout.addWidget(self.input_quantita, 2, 1)
        form_layout.addWidget(self.combo_unita_quantita, 2, 2)

        form_layout.addWidget(QLabel("<b>Prezzo:</b>"), 3, 0)
        form_layout.addWidget(self.input_prezzo, 3, 1)
        form_layout.addWidget(self.combo_unita_prezzo, 3, 2)

        left_col.addWidget(frame_form)

        # Form Fattura
        frame_fattura = QFrame(self)
        frame_fattura.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        fattura_layout = QVBoxLayout(frame_fattura)
        fattura_layout.setContentsMargins(15, 15, 15, 15)
        
        lbl_fattura = QLabel("📄 Fattura Collegata")
        lbl_fattura.setStyleSheet("font-size: 16px; font-weight: bold; color: #34495e; border: none;")
        fattura_layout.addWidget(lbl_fattura)
        
        row_fatt_info = QHBoxLayout()
        self.label_nome_fattura = QLabel("Nessuna fattura caricata")
        self.label_nome_fattura.setStyleSheet("color: #e67e22; font-weight: bold; border: none;")
        row_fatt_info.addWidget(self.label_nome_fattura, 1)
        fattura_layout.addLayout(row_fatt_info)

        row_fatt_btn = QHBoxLayout()
        self.button_importa_fattura = QPushButton("📥 Carica Fattura")
        self.button_importa_fattura.setStyleSheet(STYLE_BTN_INFO)
        self.button_importa_fattura.clicked.connect(self.seleziona_fattura_carne)
        
        self.button_rimuovi_fattura = QPushButton("Rimuovi")
        self.button_rimuovi_fattura.setStyleSheet(STYLE_BTN_SECONDARIO)
        self.button_rimuovi_fattura.clicked.connect(self.rimuovi_fattura_carne)
        
        row_fatt_btn.addWidget(self.button_importa_fattura)
        row_fatt_btn.addWidget(self.button_rimuovi_fattura)
        row_fatt_btn.addStretch(1)
        fattura_layout.addLayout(row_fatt_btn)
        
        left_col.addWidget(frame_fattura)
        left_col.addStretch(1)

        # -- Colonna Destra (Gruppi)
        frame_gruppi = QFrame(self)
        frame_gruppi.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        gruppi_layout = QVBoxLayout(frame_gruppi)
        gruppi_layout.setContentsMargins(15, 15, 15, 15)
        
        lbl_gruppi = QLabel("🐄 Gruppi da Carne")
        lbl_gruppi.setStyleSheet("font-size: 16px; font-weight: bold; color: #34495e; border: none;")
        gruppi_layout.addWidget(lbl_gruppi)

        row_gruppi = QHBoxLayout()
        
        self.list_gruppi = QListWidget(self)
        self.list_gruppi.setStyleSheet("background-color: white; border: 1px solid #ccc; border-radius: 4px;")
        self.list_gruppi.setSelectionMode(QAbstractItemView.MultiSelection)
        self.list_gruppi.itemSelectionChanged.connect(self._on_selezione_gruppi_carne)
        row_gruppi.addWidget(self.list_gruppi, 1)

        col_buttons = QVBoxLayout()
        button_tutti = QPushButton("Seleziona tutti", self)
        button_tutti.setStyleSheet(STYLE_BTN_INFO)
        button_tutti.clicked.connect(self.seleziona_tutti_gruppi_carne)
        col_buttons.addWidget(button_tutti)

        button_nessuno = QPushButton("Deseleziona", self)
        button_nessuno.setStyleSheet(STYLE_BTN_SECONDARIO)
        button_nessuno.clicked.connect(self.deseleziona_gruppi_carne)
        col_buttons.addWidget(button_nessuno)

        col_buttons.addStretch(1)
        row_gruppi.addLayout(col_buttons)

        gruppi_layout.addLayout(row_gruppi)

        row_rimozione = QHBoxLayout()
        self.check_rimuovi_capi = QCheckBox("Rimuovi capi salvando", self)
        self.check_rimuovi_capi.setStyleSheet("font-weight: bold; border: none;")
        self.check_rimuovi_capi.toggled.connect(self._on_toggle_rimozione_capi_carne)
        row_rimozione.addWidget(self.check_rimuovi_capi)

        self.input_capi_da_rimuovere = QLineEdit(self)
        self.input_capi_da_rimuovere.setStyleSheet("padding: 5px; background: white;")
        self.input_capi_da_rimuovere.setPlaceholderText("Numero capi")
        self.input_capi_da_rimuovere.textChanged.connect(lambda _t: self._aggiorna_stato_gruppi_carne())
        row_rimozione.addWidget(self.input_capi_da_rimuovere)
        
        gruppi_layout.addLayout(row_rimozione)

        self.label_gruppi_stato = QLabel("")
        self.label_gruppi_stato.setWordWrap(True)
        self.label_gruppi_stato.setStyleSheet("color: #7f8c8d; font-style: italic; border: none;")
        gruppi_layout.addWidget(self.label_gruppi_stato)

        cards_layout.addLayout(left_col, 1)
        cards_layout.addWidget(frame_gruppi, 1)
        top_layout.addLayout(cards_layout)

        # Bottoni Azione
        row_actions = QHBoxLayout()
        self.button_salva = QPushButton("✅ Salva Produzione")
        self.button_salva.setStyleSheet(STYLE_BTN_SALVA)
        self.button_salva.clicked.connect(self.salva_produzione_carne)
        row_actions.addWidget(self.button_salva)

        button_modifica = QPushButton("Modifica Selezionata")
        button_modifica.setStyleSheet(STYLE_BTN_MODIFICA)
        button_modifica.clicked.connect(self.modifica_produzione_carne_selezionata)
        row_actions.addWidget(button_modifica)

        self.button_annulla = QPushButton("Annulla Modifica")
        self.button_annulla.setStyleSheet(STYLE_BTN_SECONDARIO)
        self.button_annulla.setEnabled(False)
        self.button_annulla.clicked.connect(lambda: self.annulla_modifica_produzione_carne(reset_fields=True))
        row_actions.addWidget(self.button_annulla)

        button_ricarica = QPushButton("Ricarica")
        button_ricarica.setStyleSheet(STYLE_BTN_SECONDARIO)
        button_ricarica.clicked.connect(lambda: self.carica_produzioni_carne(show_errors=True))
        row_actions.addWidget(button_ricarica)

        button_elimina = QPushButton("Elimina Selezionata")
        button_elimina.setStyleSheet(STYLE_BTN_ELIMINA)
        button_elimina.clicked.connect(self.elimina_produzione_carne_selezionata)
        row_actions.addWidget(button_elimina)

        row_actions.addStretch(1)
        top_layout.addLayout(row_actions)

        self.label_modifica_stato = QLabel("")
        self.label_modifica_stato.setStyleSheet("color: #1f5f3f; font-weight: bold;")
        top_layout.addWidget(self.label_modifica_stato)

        self.progress_parser = QProgressBar(self)
        self.progress_parser.setRange(0, 0)
        self.progress_parser.setTextVisible(False)
        self.progress_parser.setFixedHeight(8)
        self.progress_parser.setVisible(False)
        top_layout.addWidget(self.progress_parser)
        
        main_splitter.addWidget(top_widget)

        # --- WIDGET INFERIORE ---
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        riepilogo_label = QLabel("Riepilogo Storico")
        riepilogo_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #34495e;")
        bottom_layout.addWidget(riepilogo_label)

        self.table_produzione = TabellaIsolata(0, 5, self)
        self.table_produzione.setHorizontalHeaderLabels(["ID", "Data", "Kg", "Prezzo / Kg", "Totale"])
        self.table_produzione.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_produzione.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_produzione.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_produzione.setAlternatingRowColors(True)
        self.table_produzione.verticalHeader().setVisible(False)
        self.table_produzione.setStyleSheet("QTableWidget { border: 1px solid #ccc; border-radius: 5px; } QHeaderView::section { background-color: #f8f9fa; font-weight: bold; border: 1px solid #ddd; padding: 4px; }")
        self.table_produzione.itemSelectionChanged.connect(self._on_selezione_produzione_carne)
        self.table_produzione.cellDoubleClicked.connect(lambda _r, _c: self.modifica_produzione_carne_selezionata())

        table_header = self.table_produzione.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.Stretch)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)

        bottom_layout.addWidget(self.table_produzione, 1)
        main_splitter.addWidget(bottom_widget)

        main_splitter.setSizes([500, 300])
        main_layout.addWidget(main_splitter, 1)

        self._on_toggle_rimozione_capi_carne()

    def _append_row(self, row_index: int, values: list[str], right_align_indexes=None):
        if right_align_indexes is None:
            right_align_indexes = []

        self.table_produzione.setRowCount(row_index + 1)
        for col_index, value in enumerate(values):
            item = QTableWidgetItem(value)
            if col_index in right_align_indexes:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            else:
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.table_produzione.setItem(row_index, col_index, item)

    def _selected_produzione_id(self):
        row = self.table_produzione.currentRow()
        if row < 0:
            return None
        item = self.table_produzione.item(row, 0)
        if item is None:
            return None
        try:
            value = int(item.text().strip())
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def _normalizza_unita_quantita_carne(self, raw_value):
        value = (raw_value or "").strip().lower()
        if value.startswith("q"):
            return self._UNITA_QTA[1]
        return self._UNITA_QTA[0]

    def _normalizza_unita_prezzo_carne(self, raw_value):
        value = (raw_value or "").strip().lower()
        if "quint" in value or value.endswith("/q") or value.endswith("/quintale"):
            return self._UNITA_PREZZO[1]
        return self._UNITA_PREZZO[0]

    def _parse_quantita_kg_carne(self, raw_value, unita_value):
        quantita = parse_decimal(raw_value, allow_zero=False, allow_negative=False)
        if quantita is None or quantita <= 0:
            return None

        unita_norm = self._normalizza_unita_quantita_carne(unita_value)
        if unita_norm == self._UNITA_QTA[1]:
            return float(quantita) * self.KG_PER_QUINTALE
        return float(quantita)

    def _parse_prezzo_kg_carne(self, raw_value, unita_value):
        prezzo = parse_decimal(raw_value, allow_zero=True, allow_negative=False)
        if prezzo is None or prezzo < 0:
            return None

        unita_norm = self._normalizza_unita_prezzo_carne(unita_value)
        if unita_norm == self._UNITA_PREZZO[1]:
            return float(prezzo) / self.KG_PER_QUINTALE
        return float(prezzo)

    def _label_gruppo_carne(self, entry):
        entry_id = int(entry.get("id", 0) or 0)
        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
        tipo = (entry.get("tipo_animale") or "").strip().upper()
        altro = (entry.get("altro_label") or "").strip()

        if tipo == "ALTRO":
            tipo_label = f"Altro ({altro})" if altro else "Altro"
        else:
            tipo_label = tipo.title() if tipo else "Tipo"

        capi = int(entry.get("capi", 0) or 0)
        return f"{group_name} | {tipo_label} | Da Carne | {format_number(capi, 0)} capi"

    def _carica_gruppi_carne_attivi(self):
        try:
            entries = list_azienda_animali_entries(self.user_id)
        except Exception:
            return []

        gruppi_attivi = []
        for entry in entries:
            entry_id = int(entry.get("id", 0) or 0)
            capi = int(entry.get("capi", 0) or 0)
            finalita = (entry.get("finalita") or "").strip().upper()
            if entry_id <= 0 or capi <= 0 or finalita != "CARNE": continue
            gruppi_attivi.append(entry)

        gruppi_attivi.sort(key=lambda item: ((item.get("group_name") or "").strip().lower(), int(item.get("id", 0) or 0)))
        return gruppi_attivi


    def get_gruppi_carne_selezionati_ids(self):
        selected = []
        for item in self.list_gruppi.selectedItems():
            entry_id = int(item.data(Qt.UserRole) or 0)
            if entry_id > 0:
                selected.append(entry_id)
        return selected

    def imposta_gruppi_carne_selezionati(self, entry_ids):
        self.aggiorna_lista_gruppi_carne(selected_entry_ids=entry_ids)

    def aggiorna_lista_gruppi_carne(self, selected_entry_ids=None):
        if selected_entry_ids is None:
            selected_entry_ids = self.get_gruppi_carne_selezionati_ids()

        selected_ids = set()
        for raw in selected_entry_ids or []:
            try:
                entry_id = int(raw)
            except (TypeError, ValueError):
                continue
            if entry_id > 0:
                selected_ids.add(entry_id)

        entries = self._carica_gruppi_carne_attivi()
        self._carne_gruppi_entries_by_id = {}

        self.list_gruppi.clear()

        labels_seen = set()
        for entry in entries:
            entry_id = int(entry.get("id", 0) or 0)
            if entry_id <= 0:
                continue

            self._carne_gruppi_entries_by_id[entry_id] = entry
            label = self._label_gruppo_carne(entry)
            if label in labels_seen:
                label = f"{label} [ID {entry_id}]"
            labels_seen.add(label)

            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, entry_id)
            self.list_gruppi.addItem(item)
            if entry_id in selected_ids:
                item.setSelected(True)

        self._aggiorna_stato_gruppi_carne()

    def _on_selezione_gruppi_carne(self):
        self._aggiorna_stato_gruppi_carne()

    def deseleziona_gruppi_carne(self):
        self.list_gruppi.clearSelection()
        self._aggiorna_stato_gruppi_carne()

    def seleziona_tutti_gruppi_carne(self):
        if self.list_gruppi.count() <= 0:
            return
        self.list_gruppi.clearSelection()
        for index in range(self.list_gruppi.count()):
            self.list_gruppi.item(index).setSelected(True)
        self._aggiorna_stato_gruppi_carne()

    def _parse_capi_da_rimuovere_carne(self, raw_value):
        value = parse_decimal(raw_value, allow_zero=False, allow_negative=False)
        if value is None or value <= 0:
            return None

        value_float = float(value)
        value_int = int(round(value_float))
        if abs(value_float - value_int) > 1e-9:
            return None

        if value_int <= 0:
            return None
        return value_int

    def _valida_gruppi_carne_selezionati(self):
        selected_ids = []
        seen = set()
        for entry_id in self.get_gruppi_carne_selezionati_ids():
            if entry_id <= 0 or entry_id in seen:
                continue
            seen.add(entry_id)
            selected_ids.append(entry_id)

        entries = self._carica_gruppi_carne_attivi()
        entries_by_id = {int(entry.get("id", 0) or 0): entry for entry in entries}

        missing_ids = [entry_id for entry_id in selected_ids if entry_id not in entries_by_id]
        if missing_ids:
            QMessageBox.critical(
                self,
                "Errore",
                "Uno o piu gruppi da carne selezionati non sono piu disponibili. Aggiorna e riprova.",
            )
            self.aggiorna_lista_gruppi_carne()
            return None

        group_names = []
        for entry_id in selected_ids:
            entry = entries_by_id[entry_id]
            group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
            group_names.append(group_name)

        return {
            "entry_ids": selected_ids,
            "group_names": group_names,
            "entries_by_id": entries_by_id,
        }

    def _calcola_piano_rimozione_capi_carne(self, gruppi_ids, entries_by_id, capi_da_rimuovere):
        capi_target = int(capi_da_rimuovere or 0)
        if capi_target <= 0:
            return {}

        capi_by_group = {}
        for entry_id in gruppi_ids:
            entry = entries_by_id.get(int(entry_id), {})
            capi = int(entry.get("capi", 0) or 0)
            if capi <= 0:
                continue
            capi_by_group[int(entry_id)] = capi

        if not capi_by_group:
            raise ValueError("Non ci sono capi disponibili nei gruppi selezionati.")

        totale_capi_disponibili = sum(capi_by_group.values())
        if capi_target > totale_capi_disponibili:
            raise ValueError("I capi da rimuovere superano i capi disponibili nei gruppi da carne selezionati.")

        if len(capi_by_group) == 1:
            only_id = next(iter(capi_by_group))
            return {only_id: capi_target}

        piano = {entry_id: 0 for entry_id in capi_by_group}
        metriche = []
        assegnati = 0

        for entry_id in gruppi_ids:
            if entry_id not in capi_by_group:
                continue

            capi_correnti = capi_by_group[entry_id]
            quota = (capi_target * capi_correnti) / totale_capi_disponibili
            base = min(int(quota), capi_correnti)
            piano[entry_id] = base
            assegnati += base

            metriche.append(
                {
                    "entry_id": entry_id,
                    "resto": quota - base,
                    "capi": capi_correnti,
                }
            )

        residuo = capi_target - assegnati
        metriche.sort(
            key=lambda item: (item["resto"], item["capi"], -item["entry_id"]),
            reverse=True,
        )

        while residuo > 0:
            assegnato = False
            for item in metriche:
                entry_id = int(item["entry_id"])
                if piano[entry_id] >= capi_by_group[entry_id]:
                    continue

                piano[entry_id] += 1
                residuo -= 1
                assegnato = True
                if residuo <= 0:
                    break

            if not assegnato:
                break

        if residuo > 0:
            raise ValueError("Impossibile distribuire la rimozione capi sui gruppi selezionati.")

        return {entry_id: qty for entry_id, qty in piano.items() if int(qty or 0) > 0}

    def _valida_rimozione_capi_carne(self, gruppi_info):
        attiva = bool(self.check_rimuovi_capi.isChecked()) and self.produzione_carne_in_modifica_id is None
        if not attiva:
            return {
                "attiva": False,
                "totale": 0,
                "piano": {},
            }

        gruppi_ids = list(gruppi_info.get("entry_ids") or [])
        if not gruppi_ids:
            QMessageBox.critical(
                self,
                "Errore",
                "Per rimuovere capi seleziona almeno un gruppo con destinazione Da Carne.",
            )
            return None

        capi_da_rimuovere = self._parse_capi_da_rimuovere_carne(self.input_capi_da_rimuovere.text())
        if capi_da_rimuovere is None:
            QMessageBox.critical(
                self,
                "Errore",
                "Inserisci un numero intero valido di capi da rimuovere.",
            )
            return None

        try:
            piano_rimozione = self._calcola_piano_rimozione_capi_carne(
                gruppi_ids,
                gruppi_info.get("entries_by_id") or {},
                capi_da_rimuovere,
            )
        except ValueError as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return None

        return {
            "attiva": True,
            "totale": capi_da_rimuovere,
            "piano": piano_rimozione,
        }

    def _on_toggle_rimozione_capi_carne(self, _checked=False):
        in_modifica = self.produzione_carne_in_modifica_id is not None
        attiva = bool(self.check_rimuovi_capi.isChecked()) and not in_modifica

        if in_modifica and self.check_rimuovi_capi.isChecked():
            self.check_rimuovi_capi.setChecked(False)
            attiva = False

        self.check_rimuovi_capi.setEnabled(not in_modifica)
        self.input_capi_da_rimuovere.setEnabled(attiva)

        if not attiva:
            self.input_capi_da_rimuovere.clear()

        self._aggiorna_stato_gruppi_carne()

    def _aggiorna_stato_gruppi_carne(self):
        totale = int(self.list_gruppi.count())
        if totale <= 0:
            self.label_gruppi_stato.setText(
                "Nessun gruppo da carne disponibile. Configurali in Azienda > Gruppi animali."
            )
            return

        selected_ids = self.get_gruppi_carne_selezionati_ids()
        msg = f"Gruppi selezionati: {len(selected_ids)} su {totale}."

        in_modifica = self.produzione_carne_in_modifica_id is not None
        if in_modifica:
            self.label_gruppi_stato.setText(msg + " In modifica la rimozione capi e disattivata.")
            return

        if self.check_rimuovi_capi.isChecked():
            capi_text = (self.input_capi_da_rimuovere.text() or "").strip()
            if not selected_ids:
                msg += " Seleziona almeno un gruppo per poter rimuovere capi."
            elif not capi_text:
                msg += " Inserisci il numero capi da rimuovere."
            else:
                capi_value = self._parse_capi_da_rimuovere_carne(capi_text)
                if capi_value is None:
                    msg += " Numero capi non valido (usa un intero maggiore di zero)."
                else:
                    msg += f" Rimozione attiva: {format_number(capi_value, 0)} capi."

        self.label_gruppi_stato.setText(msg)

    def _parse_data_iso(self) -> str:
        data = self.input_data.date()
        if not data.isValid():
            raise ValueError("Inserisci la data di produzione.")
        return data.toString("yyyy-MM-dd")

    def _format_data_table(self, data_iso: str) -> str:
        value = (data_iso or "").strip()
        if not value:
            return ""
        try:
            return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return value

    def _on_selezione_produzione_carne(self):
        if self.produzione_carne_in_modifica_id is not None:
            return

        selezionato = self._selected_produzione_id()
        if selezionato is None:
            self.label_modifica_stato.setText("")
            return

        self.label_modifica_stato.setText("Produzione selezionata. Premi 'Modifica selezionata' per aggiornare i dati.")

    def modifica_produzione_carne_selezionata(self):
        self.prepara_modifica_produzione_carne(show_errors=True)

    def prepara_modifica_produzione_carne(self, show_errors=False):
        produzione_id = self._selected_produzione_id()
        if produzione_id is None:
            if show_errors: QMessageBox.warning(self, "Attenzione", "Seleziona prima una produzione carne da modificare.")
            return

        row = self.table_produzione.currentRow()
        data_value = self.table_produzione.item(row, 1).text() if self.table_produzione.item(row, 1) else ""
        quantita_value = self.table_produzione.item(row, 2).text() if self.table_produzione.item(row, 2) else ""
        prezzo_value = self.table_produzione.item(row, 3).text() if self.table_produzione.item(row, 3) else ""

        self.produzione_carne_in_modifica_id = int(produzione_id)
        parsed = QDate.fromString(data_value, "dd/MM/yyyy")
        self.input_data.setDate(parsed if parsed.isValid() else QDate.currentDate())
        self.input_quantita.setText(quantita_value)
        self.combo_unita_quantita.setCurrentText(self._UNITA_QTA[0])
        self.input_prezzo.setText(prezzo_value or "0,00")
        self.combo_unita_prezzo.setCurrentText(self._UNITA_PREZZO[0])

        try:
            prod = ProduzioneCarne.get_by_id(self.produzione_carne_in_modifica_id)
            movimento_id = prod.movimento.id if prod.movimento else 0
            linked_group_ids = get_movimento_animali_entry_ids(self.user_id, movimento_id) if movimento_id > 0 else []
        except Exception:
            linked_group_ids = []
            movimento_id = 0

        self.imposta_gruppi_carne_selezionati(linked_group_ids)
        self.check_rimuovi_capi.setChecked(False)
        self.input_capi_da_rimuovere.clear()
        self.button_salva.setText("Aggiorna Produzione")
        self.button_annulla.setEnabled(True)
        self.label_modifica_stato.setText(f"Modifica produzione carne ID {self.produzione_carne_in_modifica_id} attiva.")
        self._on_toggle_rimozione_capi_carne()
        self._carica_fattura_collegata_produzione_carne(movimento_id)


    def _carica_fattura_collegata_produzione_carne(self, movimento_id: int):
        self.rimuovi_fattura_carne()
        mov_id_val = int(movimento_id or 0)
        if mov_id_val <= 0: return
        try:
            fatt = Fattura.select().where((Fattura.user == self.user_id) & (Fattura.movimento == mov_id_val)).order_by(Fattura.data_caricamento.desc()).first()
            if fatt and fatt.nome_originale: self.label_nome_fattura.setText(str(fatt.nome_originale))
        except Exception: pass


    def annulla_modifica_produzione_carne(self, reset_fields=False):
        self.produzione_carne_in_modifica_id = None
        self.button_salva.setText("✅ Salva Produzione")
        self.button_annulla.setEnabled(False)
        self.label_modifica_stato.setText("")
        self.table_produzione.clearSelection()

        self.check_rimuovi_capi.setChecked(False)
        self.input_capi_da_rimuovere.clear()
        self._on_toggle_rimozione_capi_carne()

        if reset_fields:
            self.input_data.setDate(QDate.currentDate())
            self.input_quantita.clear()
            self.combo_unita_quantita.setCurrentText(self._UNITA_QTA[0])
            self.input_prezzo.setText("0,00")
            self.combo_unita_prezzo.setCurrentText(self._UNITA_PREZZO[0])
            self.deseleziona_gruppi_carne()

        self.aggiorna_lista_gruppi_carne()

    def salva_produzione_carne(self):
        try: data_db = self._parse_data_iso()
        except ValueError as exc: return QMessageBox.critical(self, "Errore", str(exc))

        if is_blank(self.input_quantita.text()): return QMessageBox.critical(self, "Errore", "Inserisci la quantita venduta.")
        kg_val = self._parse_quantita_kg_carne(self.input_quantita.text().strip(), self.combo_unita_quantita.currentText())
        if kg_val is None or kg_val <= 0: return QMessageBox.critical(self, "Errore", "Quantita non valida.")
        prezzo_kg_val = self._parse_prezzo_kg_carne(self.input_prezzo.text().strip(), self.combo_unita_prezzo.currentText())
        if prezzo_kg_val is None: return QMessageBox.critical(self, "Errore", "Prezzo non valido.")

        gruppi_info = self._valida_gruppi_carne_selezionati()
        if gruppi_info is None: return
        gruppi_ids = gruppi_info["entry_ids"]

        in_modifica = self.produzione_carne_in_modifica_id is not None
        rimozione_attiva = bool(self.check_rimuovi_capi.isChecked()) and not in_modifica
        capi_da_rimuovere = 0
        capi_selezionati = []

        if rimozione_attiva and capi_selezionati:
                    from models import CapoAnimale, AziendaAnimaliDettaglio
                    from database import sposta_capo_animale # <-- IMPORT AGGIUNTO
                    kg_pro_capite = kg_val / capi_da_rimuovere
                    ricavo_pro_capite = importo_movimento / capi_da_rimuovere
                    
                    # Troviamo l'archivio
                    archivio_venduti = AziendaAnimaliDettaglio.get_or_none((AziendaAnimaliDettaglio.user == self.user_id) & (AziendaAnimaliDettaglio.tipo_animale == 'ARCHIVIO') & (AziendaAnimaliDettaglio.finalita == 'VENDUTI'))
                    
                    for capo_id in capi_selezionati:
                        capo = CapoAnimale.get_by_id(capo_id)
                        capo.stato = 'VENDUTO_CARNE'
                        capo.data_uscita = data_db
                        capo.kg_carne_prodotti = kg_pro_capite
                        capo.ricavi_accumulati = (getattr(capo, 'ricavi_accumulati', 0.0) or 0.0) + ricavo_pro_capite
                        capo.save()
                        
                        # Trasferimento istantaneo in archivio
                        if archivio_venduti:
                            sposta_capo_animale(self.user_id, capo.id, archivio_venduti.id)
                        else:
                            # Fallback di sicurezza
                            gruppo = AziendaAnimaliDettaglio.get_by_id(capo.gruppo_id)
                            gruppo.capi -= 1
                            gruppo.save()
                        
                        rimozioni_effettuate.append(capo.marca_auricolare)

        quintali_val = kg_val / self.KG_PER_QUINTALE
        importo_movimento = kg_val * prezzo_kg_val
        iva_importo_movimento = 0.0
        descrizione_mov = f"Produzione carne: {format_number(kg_val, 2)} Kg ({format_number(quintali_val, 2)} q) x {format_eur(prezzo_kg_val, 4)}/Kg"
        if gruppi_ids: descrizione_mov += f" | Gruppi: {', '.join(gruppi_info['group_names'])}"
        if rimozione_attiva and capi_da_rimuovere > 0: descrizione_mov += f" | Capi macellati: {format_number(capi_da_rimuovere, 0)}"

        parser_data = self.pending_parser_carne_data if isinstance(self.pending_parser_carne_data, dict) else None
        parser_values = self._estrai_valori_parser_db(parser_data)
        parser_dict = dict(zip(self._PARSER_DB_FIELDS, parser_values)) if parser_values else {}

        if parser_data is not None:
            parser_vat = parse_decimal(parser_data.get("vat_total"), allow_zero=True, allow_negative=False)
            parser_total = parse_decimal(parser_data.get("total_amount"), allow_zero=False, allow_negative=False)
            if parser_vat is not None and parser_total is not None and parser_total >= parser_vat:
                iva_importo_movimento = max(parser_vat, 0.0)
                importo_movimento = max(parser_total - iva_importo_movimento, 0.0)

        rimozioni_effettuate = []
        try:
            with db.atomic(): 
                if self.produzione_carne_in_modifica_id is None:
                    mov = Movimento.create(
                        user=self.user_id, data_op=data_db, tipo='ENTRATA', categoria='Carne',
                        descrizione=descrizione_mov, importo=importo_movimento, iva_importo=iva_importo_movimento,
                        stato_pagamento='PAGATO', **{f"parser_{k}": v for k, v in parser_dict.items()}
                    )
                    prod = ProduzioneCarne.create(user=self.user_id, data_op=data_db, kg=kg_val, prezzo_kg=prezzo_kg_val, movimento=mov.id)
                    produzione_id = prod.id
                    movimento_id = mov.id
                    msg_ok = "Produzione carne salvata"
                else:
                    produzione_id = int(self.produzione_carne_in_modifica_id)
                    prod = ProduzioneCarne.get_by_id(produzione_id)
                    movimento_id = prod.movimento.id if prod.movimento else 0
                    
                    ProduzioneCarne.update(data_op=data_db, kg=kg_val, prezzo_kg=prezzo_kg_val).where(ProduzioneCarne.id == produzione_id).execute()
                    if movimento_id > 0:
                        Movimento.update(data_op=data_db, descrizione=descrizione_mov, importo=importo_movimento, iva_importo=iva_importo_movimento, **{f"parser_{k}": v for k, v in parser_dict.items()}).where(Movimento.id == movimento_id).execute()
                    else:
                        mov = Movimento.create(user=self.user_id, data_op=data_db, tipo='ENTRATA', categoria='Carne', descrizione=descrizione_mov, importo=importo_movimento, iva_importo=iva_importo_movimento, stato_pagamento='PAGATO', **{f"parser_{k}": v for k, v in parser_dict.items()})
                        movimento_id = mov.id
                        ProduzioneCarne.update(movimento=movimento_id).where(ProduzioneCarne.id == produzione_id).execute()
                    msg_ok = "Produzione carne aggiornata"

                if movimento_id > 0: set_movimento_animali_links(self.user_id, movimento_id, gruppi_ids)

                # --- NUOVA LOGICA: Assegna la vendita ai singoli capi scelti ---
                if rimozione_attiva and capi_selezionati:
                    from models import CapoAnimale, AziendaAnimaliDettaglio
                    kg_pro_capite = kg_val / capi_da_rimuovere
                    ricavo_pro_capite = importo_movimento / capi_da_rimuovere
                    
                    for capo_id in capi_selezionati:
                        capo = CapoAnimale.get_by_id(capo_id)
                        capo.stato = 'VENDUTO_CARNE'
                        capo.data_uscita = data_db
                        capo.kg_carne_prodotti = kg_pro_capite
                        capo.ricavi_accumulati = (getattr(capo, 'ricavi_accumulati', 0.0) or 0.0) + ricavo_pro_capite
                        capo.save()
                        
                        # Aggiorniamo il conteggio del suo gruppo
                        gruppo = AziendaAnimaliDettaglio.get_by_id(capo.gruppo_id)
                        gruppo.capi -= 1
                        gruppo.save()
                        
                        rimozioni_effettuate.append(capo.marca_auricolare)

                if self.pending_fattura_carne_id is not None and movimento_id > 0:
                    Fattura.update(movimento=movimento_id, produzione=produzione_id).where(Fattura.id == self.pending_fattura_carne_id).execute()

        except Exception as exc: return QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")

        self.annulla_modifica_produzione_carne(reset_fields=True)
        self.rimuovi_fattura_carne()
        self.carica_produzioni_carne(show_errors=False)
        self.produzione_changed.emit()

        msg_successo = f"{msg_ok}! Entrata: {format_eur(kg_val * prezzo_kg_val)}"
        if rimozioni_effettuate: msg_successo += "\nCapi venduti: " + ", ".join(rimozioni_effettuate)
        QMessageBox.information(self, "Successo", msg_successo)

    def carica_produzioni_carne(self, show_errors=True):
        self.table_produzione.setRowCount(0)
        try:
            rows = list(ProduzioneCarne.select().where(ProduzioneCarne.user == self.user_id).order_by(ProduzioneCarne.data_op.desc(), ProduzioneCarne.id.desc()).dicts())
        except Exception as exc:
            if show_errors: QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        for row_index, row in enumerate(rows):
            kg_value = float(row['kg'] or 0)
            prezzo_value = float(row['prezzo_kg'] or 0)
            self._append_row(row_index, [str(row['id']), self._format_data_table(str(row['data_op'] or "")), format_number(kg_value, 2), format_number(prezzo_value, 4), format_number(kg_value * prezzo_value, 2)], right_align_indexes=[2, 3, 4])


    def elimina_produzione_carne_selezionata(self):
        produzione_id = self._selected_produzione_id()
        if produzione_id is None: return QMessageBox.warning(self, "Attenzione", "Seleziona prima una riga di produzione carne da eliminare.")

        row = self.table_produzione.currentRow()
        if QMessageBox.question(self, "Conferma eliminazione", f"Vuoi eliminare la produzione selezionata?\n\nData: {self.table_produzione.item(row, 1).text()}", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return

        era_in_modifica = self.produzione_carne_in_modifica_id == produzione_id
        try:
            with db.atomic():
                prod = ProduzioneCarne.get_or_none((ProduzioneCarne.id == produzione_id) & (ProduzioneCarne.user == self.user_id))
                if not prod: return QMessageBox.critical(self, "Errore", "Produzione non trovata.")
                mov_id = prod.movimento.id if prod.movimento else None
                prod.delete_instance()
                
                if mov_id:
                    for f in Fattura.select().where(Fattura.movimento == mov_id):
                        try: Path(f.percorso_file).unlink(missing_ok=True)
                        except Exception: pass
                    Movimento.delete().where(Movimento.id == mov_id).execute()
        except Exception as exc: return QMessageBox.critical(self, "Errore DB", f"Errore: {exc}")

        self.carica_produzioni_carne(show_errors=False)
        if era_in_modifica: self.annulla_modifica_produzione_carne(reset_fields=True)
        self.produzione_changed.emit()
        QMessageBox.information(self, "Successo", "Produzione eliminata dal database!")


    def seleziona_fattura_carne(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Seleziona fattura PDF (Carne)", "", "PDF Files (*.pdf)")
        if not file_path:
            return

        try:
            fattura_id, percorso_archiviato = self.archivia_fattura_caricata(file_path, "CARNE")
        except Exception as exc:
            QMessageBox.critical(self, "Caricamento fattura", f"Impossibile salvare la fattura: {exc}")
            return

        self.pending_fattura_carne_id = fattura_id
        self.pending_fattura_carne_path = percorso_archiviato
        self.pending_parser_carne_data = None
        self.label_nome_fattura.setText(Path(percorso_archiviato).name)
        self._set_parser_feedback_carne(True, "Analisi fattura in corso...")

        def _on_success(risultato):
            try:
                dati_carne = self.analizza_fattura_carne_con_parser_fatture(
                    percorso_archiviato,
                    file_path,
                    risultato=risultato,
                )
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "Analisi non completata",
                    f"Fattura salvata correttamente, ma analisi automatica non disponibile: {exc}",
                )
                return

            self._applica_dati_parser_al_form_carne(dati_carne)
            self.pending_parser_carne_data = dati_carne.get("parser_data")

            iva_label = format_number(dati_carne.get("iva_percent", 0.0), 2)
            QMessageBox.information(
                self,
                "Importazione completata",
                "Valori produzione carne impostati da fattura:\n"
                f"- Quantita: {self.input_quantita.text()} {self.combo_unita_quantita.currentText()}\n"
                f"- Prezzo: {self.input_prezzo.text()} {self.combo_unita_prezzo.currentText()}\n"
                f"- Aliquota IVA applicata: {iva_label}%",
            )

        def _on_error(message):
            QMessageBox.warning(
                self,
                "Analisi non completata",
                f"Fattura salvata correttamente, ma analisi automatica non disponibile: {message}",
            )

        def _on_progress(message):
            self._set_parser_feedback_carne(True, f"Analisi fattura: {message}")

        def _on_done():
            self._set_parser_feedback_carne(False)

        try:
            self.avvia_parser_fattura_async(
                percorso_archiviato,
                on_success=_on_success,
                on_error=_on_error,
                on_done=_on_done,
                on_progress=_on_progress,
            )
        except Exception as exc:
            self._set_parser_feedback_carne(False)
            QMessageBox.warning(
                self,
                "Analisi non avviata",
                f"Fattura salvata correttamente, ma il parser non si e avviato: {exc}",
            )

    def rimuovi_fattura_carne(self):
        self.pending_fattura_carne_id = None
        self.pending_fattura_carne_path = None
        self.pending_parser_carne_data = None
        self.label_nome_fattura.setText("Nessuna fattura caricata")

    def _set_parser_feedback_carne(self, busy: bool, message: str | None = None):
        if busy:
            if not self._parser_carne_busy:
                self._parser_carne_prev_status_text = self.label_modifica_stato.text()
            self._parser_carne_busy = True
            self.progress_parser.setVisible(True)
            self.button_importa_fattura.setEnabled(False)
            self.button_rimuovi_fattura.setEnabled(False)
            self.button_salva.setEnabled(False)
            if message is not None:
                self.label_modifica_stato.setText(message)
            return

        self._parser_carne_busy = False
        self.progress_parser.setVisible(False)
        self.button_importa_fattura.setEnabled(True)
        self.button_rimuovi_fattura.setEnabled(True)
        self.button_salva.setEnabled(True)

        if message is not None:
            self.label_modifica_stato.setText(message)
            return

        if self.produzione_carne_in_modifica_id is None:
            self.label_modifica_stato.setText("")
        else:
            self.label_modifica_stato.setText(self._parser_carne_prev_status_text)

    def _applica_dati_parser_al_form_carne(self, dati):
        if not isinstance(dati, dict):
            return

        data_value = dati.get("data")
        if data_value:
            parsed = QDate.fromString(str(data_value), "dd/MM/yyyy")
            if parsed.isValid():
                self.input_data.setDate(parsed)

        quantita_value = dati.get("quantita")
        if quantita_value:
            self.input_quantita.setText(str(quantita_value))

        self.combo_unita_quantita.setCurrentText(self._normalizza_unita_quantita_carne(dati.get("quantita_unita")))

        prezzo_value = dati.get("prezzo")
        if prezzo_value:
            self.input_prezzo.setText(str(prezzo_value))

        self.combo_unita_prezzo.setCurrentText(self._normalizza_unita_prezzo_carne(dati.get("prezzo_unita")))

    def analizza_fattura_carne_con_parser_fatture(self, pdf_path, file_path, risultato=None):
        if risultato is None:
            parse_invoice_pdf = self._get_parser_fatture_function()
            risultato = parse_invoice_pdf(str(pdf_path))
        risultato = self._normalizza_risultato_parser(risultato)
        fields = getattr(risultato, "fields", {}) or {}
        parser_data = self._costruisci_dati_parser_movimento(risultato, fields)

        data_raw = self._estrai_valore_campo_parser(fields, "invoice_date")
        data_out = self._normalizza_data_fattura(data_raw) or datetime.now().strftime("%d/%m/%Y")

        line_items = getattr(risultato, "line_items", []) or []
        linea_carne = self._seleziona_linea_carne(line_items)
        if linea_carne is None:
            raise RuntimeError("Impossibile individuare riga prodotto carne con quantita e prezzo validi nella fattura.")

        quantita = self._valore_parser_to_float(getattr(linea_carne, "quantity", None), allow_zero=False)
        if quantita is None or quantita <= 0:
            raise RuntimeError("Quantita non trovata o non valida nella fattura.")

        prezzo_unita = self._valore_parser_to_float(getattr(linea_carne, "unit_price", None), allow_zero=False)
        if prezzo_unita is None:
            line_total = self._valore_parser_to_float(getattr(linea_carne, "line_total", None), allow_zero=False)
            if line_total is not None and line_total > 0:
                prezzo_unita = line_total / quantita

        if prezzo_unita is None or prezzo_unita <= 0:
            raise RuntimeError("Prezzo non trovato o non valido nella fattura.")

        descrizione = str(getattr(linea_carne, "description", "") or "").lower()
        quantita_unita = self._UNITA_QTA[1] if re.search(r"\bq\b|quint", descrizione) else self._UNITA_QTA[0]
        prezzo_unita_label = self._UNITA_PREZZO[1] if quantita_unita == self._UNITA_QTA[1] else self._UNITA_PREZZO[0]

        iva_percent = self._valore_parser_to_float(getattr(linea_carne, "vat_rate", None), allow_zero=True)
        if iva_percent is None or iva_percent < 0:
            iva_percent = self._calcola_aliquota_iva_parser(fields, risultato)
        if iva_percent is None or iva_percent < 0:
            iva_percent = 0.0

        prezzo_unita_lordo = prezzo_unita * (1.0 + (iva_percent / 100.0))

        return {
            "data": data_out,
            "quantita": format_number(quantita, 2),
            "quantita_unita": quantita_unita,
            "prezzo": format_number(prezzo_unita_lordo, 4),
            "prezzo_unita": prezzo_unita_label,
            "iva_percent": iva_percent,
            "file": str(Path(file_path).name),
            "parser_data": parser_data,
        }

    def _seleziona_linea_carne(self, line_items):
        candidati = []
        parole_carne = (
            "carne",
            "bov",
            "vitell",
            "manzo",
            "suin",
            "maial",
            "ovin",
            "agnell",
            "caprin",
            "pollo",
            "tacchin",
        )

        for item in line_items:
            quantita = self._valore_parser_to_float(getattr(item, "quantity", None), allow_zero=False)
            if quantita is None or quantita <= 0:
                continue

            prezzo_unita = self._valore_parser_to_float(getattr(item, "unit_price", None), allow_zero=False)
            line_total = self._valore_parser_to_float(getattr(item, "line_total", None), allow_zero=False)
            if prezzo_unita is None and line_total is None:
                continue

            descrizione = str(getattr(item, "description", "") or "").strip().lower()
            score = 0
            if any(parola in descrizione for parola in parole_carne):
                score += 4
            if "latte" in descrizione:
                score -= 3
            if re.search(r"\bq\b|quint", descrizione):
                score += 1

            candidati.append((score, line_total or 0.0, item))

        if not candidati:
            return None

        candidati.sort(key=lambda data: (data[0], data[1]), reverse=True)
        return candidati[0][2]

class SelezioneCapiVendutiDialog(QDialog):
    def __init__(self, user_id, gruppi_ids, capi_da_selezionare, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.gruppi_ids = gruppi_ids
        self.capi_da_selezionare = capi_da_selezionare
        self.capi_selezionati_ids = []
        
        self.setWindowTitle(f"Seleziona i {capi_da_selezionare} capi macellati/venduti")
        self.resize(500, 600)
        self.setModal(True)
        self._build_ui()
        self.carica_capi()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        info = QLabel(f"Hai indicato la vendita di <b>{self.capi_da_selezionare} capi</b>.<br>Seleziona esattamente quali animali sono usciti dall'azienda per attribuire a loro i ricavi e la quantità di carne.")
        layout.addWidget(info)
        
        self.list_capi = QListWidget()
        self.list_capi.setSelectionMode(QAbstractItemView.MultiSelection)
        self.list_capi.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self.list_capi)
        
        self.btn_conferma = QPushButton(f"Conferma Selezione (0/{self.capi_da_selezionare})")
        self.btn_conferma.setStyleSheet("background-color: #28a745; color: white; font-weight: bold; padding: 10px;")
        self.btn_conferma.setEnabled(False)
        self.btn_conferma.clicked.connect(self._conferma)
        layout.addWidget(self.btn_conferma)

    def carica_capi(self):
        from models import CapoAnimale
        capi = CapoAnimale.select().where((CapoAnimale.gruppo << self.gruppi_ids) & (CapoAnimale.stato == 'ATTIVO'))
        for capo in capi:
            item = QListWidgetItem(f"ID: {capo.marca_auricolare}")
            item.setData(Qt.UserRole, capo.id)
            self.list_capi.addItem(item)

    def _on_selection(self):
        count = len(self.list_capi.selectedItems())
        self.btn_conferma.setText(f"Conferma Selezione ({count}/{self.capi_da_selezionare})")
        self.btn_conferma.setEnabled(count == self.capi_da_selezionare)

    def _conferma(self):
        self.capi_selezionati_ids = [item.data(Qt.UserRole) for item in self.list_capi.selectedItems()]
        self.accept()