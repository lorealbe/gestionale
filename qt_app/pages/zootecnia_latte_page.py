import sqlite3
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
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
)

from app_utils import format_eur, format_number, is_blank, parse_decimal
from database import (
    LITRI_PER_QUINTALE,
    get_conn,
    get_movimento_animali_entry_ids,
    get_produzione_latte_group_allocations,
    list_azienda_animali_entries,
    set_movimento_animali_links,
    set_produzione_latte_group_allocations,
)
from qt_app.pages.zootecnia_parser_support import ZootecniaParserSupport


class ZootecniaLattePage(ZootecniaParserSupport, QWidget):
    produzione_changed = Signal()

    _UNITA_QTA_LATTE = ("Quintali", "Litri")
    _UNITA_PREZZO_LATTE = ("EUR/Litro", "EUR/Quintale")

    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = int(user_id)

        self.produzione_in_modifica_id = None
        self.pending_fattura_latte_id = None
        self.pending_fattura_latte_path = None
        self.pending_parser_latte_data = None
        self._parser_latte_busy = False
        self._parser_latte_prev_status_text = ""

        self._latte_gruppi_entries_by_id = {}
        self._latte_litri_quote_by_group = {}

        self._build_ui()
        self.aggiorna_lista_gruppi_latte()
        self.carica_produzioni_latte(show_errors=False)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        frame_form = QFrame(self)
        form_layout = QGridLayout(frame_form)
        form_layout.setContentsMargins(10, 10, 10, 10)
        form_layout.setHorizontalSpacing(8)
        form_layout.setVerticalSpacing(8)

        self.input_data = QDateEdit(self)
        self.input_data.setDisplayFormat("dd/MM/yyyy")
        self.input_data.setCalendarPopup(True)
        self.input_data.setDate(QDate.currentDate())

        self.input_quantita = QLineEdit(self)
        self.input_quantita.setPlaceholderText("Quantita prodotta")

        self.combo_unita_quantita = QComboBox(self)
        self.combo_unita_quantita.addItems(self._UNITA_QTA_LATTE)

        self.input_prezzo = QLineEdit(self)
        self.input_prezzo.setText("0,00")

        self.combo_unita_prezzo = QComboBox(self)
        self.combo_unita_prezzo.addItems(self._UNITA_PREZZO_LATTE)

        form_layout.addWidget(QLabel("Data produzione:"), 0, 0)
        form_layout.addWidget(self.input_data, 0, 1)

        form_layout.addWidget(QLabel("Quantita prodotta:"), 1, 0)
        form_layout.addWidget(self.input_quantita, 1, 1)
        form_layout.addWidget(self.combo_unita_quantita, 1, 2)

        form_layout.addWidget(QLabel("Prezzo:"), 2, 0)
        form_layout.addWidget(self.input_prezzo, 2, 1)
        form_layout.addWidget(self.combo_unita_prezzo, 2, 2)

        layout.addWidget(frame_form)

        frame_gruppi = QFrame(self)
        gruppi_layout = QVBoxLayout(frame_gruppi)
        gruppi_layout.setContentsMargins(10, 10, 10, 10)
        gruppi_layout.setSpacing(8)

        gruppi_layout.addWidget(QLabel("Attribuzione gruppi animali (da latte)"))

        row_gruppi = QHBoxLayout()
        row_gruppi.setSpacing(8)

        self.list_gruppi = QListWidget(self)
        self.list_gruppi.setSelectionMode(QAbstractItemView.MultiSelection)
        self.list_gruppi.itemSelectionChanged.connect(self._on_selezione_gruppi_latte)
        row_gruppi.addWidget(self.list_gruppi, 1)

        col_buttons = QVBoxLayout()
        col_buttons.setSpacing(6)

        button_tutti = QPushButton("Seleziona tutti", self)
        button_tutti.clicked.connect(self.seleziona_tutti_gruppi_latte)
        col_buttons.addWidget(button_tutti)

        button_nessuno = QPushButton("Deseleziona", self)
        button_nessuno.clicked.connect(self.deseleziona_gruppi_latte)
        col_buttons.addWidget(button_nessuno)

        self.button_quote = QPushButton("Litri per gruppo...", self)
        self.button_quote.clicked.connect(self.apri_dialog_quote_litri_gruppi_latte)
        col_buttons.addWidget(self.button_quote)

        col_buttons.addStretch(1)
        row_gruppi.addLayout(col_buttons)

        gruppi_layout.addLayout(row_gruppi)

        self.label_gruppi_stato = QLabel("")
        self.label_gruppi_stato.setWordWrap(True)
        gruppi_layout.addWidget(self.label_gruppi_stato)

        layout.addWidget(frame_gruppi)

        row_actions = QHBoxLayout()
        row_actions.setSpacing(8)

        self.button_salva = QPushButton("Salva Produzione", self)
        self.button_salva.clicked.connect(self.salva_produzione_latte)
        row_actions.addWidget(self.button_salva)

        button_modifica = QPushButton("Modifica selezionata", self)
        button_modifica.clicked.connect(self.modifica_produzione_latte_selezionata)
        row_actions.addWidget(button_modifica)

        self.button_annulla = QPushButton("Annulla modifica", self)
        self.button_annulla.setEnabled(False)
        self.button_annulla.clicked.connect(lambda: self.annulla_modifica_produzione_latte(reset_fields=True))
        row_actions.addWidget(self.button_annulla)

        button_ricarica = QPushButton("Ricarica storico", self)
        button_ricarica.clicked.connect(lambda: self.carica_produzioni_latte(show_errors=True))
        row_actions.addWidget(button_ricarica)

        button_elimina = QPushButton("Elimina selezionata", self)
        button_elimina.clicked.connect(self.elimina_produzione_latte_selezionata)
        row_actions.addWidget(button_elimina)

        row_actions.addStretch(1)
        layout.addLayout(row_actions)

        self.label_modifica_stato = QLabel("")
        self.label_modifica_stato.setStyleSheet("color: #1f5f3f;")
        layout.addWidget(self.label_modifica_stato)

        frame_fattura = QFrame(self)
        fattura_layout = QHBoxLayout(frame_fattura)
        fattura_layout.setContentsMargins(10, 10, 10, 10)
        fattura_layout.setSpacing(8)

        fattura_layout.addWidget(QLabel("Fattura latte:"))
        self.label_nome_fattura = QLabel("Nessuna fattura caricata")
        fattura_layout.addWidget(self.label_nome_fattura, 1)

        self.button_importa_fattura = QPushButton("Carica Fattura", self)
        self.button_importa_fattura.clicked.connect(self.seleziona_fattura_latte)
        fattura_layout.addWidget(self.button_importa_fattura)

        self.button_rimuovi_fattura = QPushButton("Rimuovi", self)
        self.button_rimuovi_fattura.clicked.connect(self.rimuovi_fattura_latte)
        fattura_layout.addWidget(self.button_rimuovi_fattura)

        layout.addWidget(frame_fattura)

        self.progress_parser = QProgressBar(self)
        self.progress_parser.setRange(0, 0)
        self.progress_parser.setTextVisible(False)
        self.progress_parser.setFixedHeight(8)
        self.progress_parser.setVisible(False)
        layout.addWidget(self.progress_parser)

        riepilogo_label = QLabel("Riepilogo produzione latte")
        riepilogo_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(riepilogo_label)
        
        self.table_produzione = QTableWidget(0, 4, self)
        self.table_produzione.setHorizontalHeaderLabels(["ID", "Data", "Quintali", "Prezzo / L"])
        self.table_produzione.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_produzione.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_produzione.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_produzione.setAlternatingRowColors(True)
        self.table_produzione.verticalHeader().setVisible(False)
        self.table_produzione.itemSelectionChanged.connect(self._on_selezione_produzione_latte)
        self.table_produzione.cellDoubleClicked.connect(lambda _r, _c: self.modifica_produzione_latte_selezionata())

        table_header = self.table_produzione.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        layout.addWidget(self.table_produzione, 1)

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

    def _normalizza_unita_quantita_latte(self, raw_value):
        value = (raw_value or "").strip().lower()
        if value.startswith("l"):
            return self._UNITA_QTA_LATTE[1]
        return self._UNITA_QTA_LATTE[0]

    def _normalizza_unita_prezzo_latte(self, raw_value):
        value = (raw_value or "").strip().lower()
        if "quint" in value or value.endswith("/q") or value.endswith("/quintale"):
            return self._UNITA_PREZZO_LATTE[1]
        return self._UNITA_PREZZO_LATTE[0]

    def _parse_quantita_litri_latte(self, raw_value, unita_value):
        quantita = parse_decimal(raw_value, allow_zero=False, allow_negative=False)
        if quantita is None or quantita <= 0:
            return None

        unita_norm = self._normalizza_unita_quantita_latte(unita_value)
        if unita_norm == self._UNITA_QTA_LATTE[1]:
            return float(quantita)
        return float(quantita) * LITRI_PER_QUINTALE

    def _parse_prezzo_litro_latte(self, raw_value, unita_value):
        prezzo = parse_decimal(raw_value, allow_zero=True, allow_negative=False)
        if prezzo is None or prezzo < 0:
            return None

        unita_norm = self._normalizza_unita_prezzo_latte(unita_value)
        if unita_norm == self._UNITA_PREZZO_LATTE[1]:
            return float(prezzo) / LITRI_PER_QUINTALE
        return float(prezzo)

    def _normalizza_quota_litri_input(self, raw_value):
        value = parse_decimal(raw_value, allow_zero=True, allow_negative=False)
        if value is None or value <= 0:
            return None
        return float(value)

    def _label_gruppo_latte(self, entry):
        entry_id = int(entry.get("id", 0) or 0)
        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
        tipo = (entry.get("tipo_animale") or "").strip().upper()
        altro = (entry.get("altro_label") or "").strip()

        if tipo == "ALTRO":
            tipo_label = f"Altro ({altro})" if altro else "Altro"
        else:
            tipo_label = tipo.title() if tipo else "Tipo"

        capi = int(entry.get("capi", 0) or 0)
        return f"{group_name} | {tipo_label} | {format_number(capi, 0)} capi"

    def _carica_gruppi_latte_attivi(self):
        try:
            entries = list_azienda_animali_entries(self.user_id)
        except sqlite3.Error:
            return []

        gruppi_attivi = []
        for entry in entries:
            entry_id = int(entry.get("id", 0) or 0)
            capi = int(entry.get("capi", 0) or 0)
            finalita = (entry.get("finalita") or "").strip().upper()

            if entry_id <= 0 or capi <= 0 or finalita != "LATTE":
                continue

            gruppi_attivi.append(entry)

        gruppi_attivi.sort(
            key=lambda item: (
                (item.get("group_name") or "").strip().lower(),
                int(item.get("id", 0) or 0),
            )
        )
        return gruppi_attivi

    def get_gruppi_latte_selezionati_ids(self):
        selected = []
        for item in self.list_gruppi.selectedItems():
            entry_id = int(item.data(Qt.UserRole) or 0)
            if entry_id > 0:
                selected.append(entry_id)
        return selected

    def imposta_gruppi_latte_selezionati(self, entry_ids):
        self.aggiorna_lista_gruppi_latte(selected_entry_ids=entry_ids)

    def aggiorna_lista_gruppi_latte(self, selected_entry_ids=None):
        if selected_entry_ids is None:
            selected_entry_ids = self.get_gruppi_latte_selezionati_ids()

        selected_ids = set()
        for raw in selected_entry_ids or []:
            try:
                entry_id = int(raw)
            except (TypeError, ValueError):
                continue
            if entry_id > 0:
                selected_ids.add(entry_id)

        entries = self._carica_gruppi_latte_attivi()
        self._latte_gruppi_entries_by_id = {}

        self.list_gruppi.clear()

        label_seen = set()
        for entry in entries:
            entry_id = int(entry.get("id", 0) or 0)
            if entry_id <= 0:
                continue

            self._latte_gruppi_entries_by_id[entry_id] = entry

            label = self._label_gruppo_latte(entry)
            if label in label_seen:
                label = f"{label} [ID {entry_id}]"
            label_seen.add(label)

            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, entry_id)
            self.list_gruppi.addItem(item)
            if entry_id in selected_ids:
                item.setSelected(True)

        self._aggiorna_stato_gruppi_latte()

    def _on_selezione_gruppi_latte(self):
        self._pulisci_quote_litri_non_selezionate()
        self._aggiorna_stato_gruppi_latte()

    def _pulisci_quote_litri_non_selezionate(self):
        selected_ids = set(self.get_gruppi_latte_selezionati_ids())
        filtered = {}
        for entry_id, litri in self._latte_litri_quote_by_group.items():
            if entry_id not in selected_ids:
                continue
            if float(litri or 0) <= 0:
                continue
            filtered[int(entry_id)] = float(litri)
        self._latte_litri_quote_by_group = filtered

    def _litri_totali_correnti(self):
        quantita_text = self.input_quantita.text().strip()
        if is_blank(quantita_text):
            return None

        return self._parse_quantita_litri_latte(quantita_text, self.combo_unita_quantita.currentText())

    def _quote_litri_gruppi_per_salvataggio(self, gruppi_ids, litri_totali):
        if len(gruppi_ids) <= 1:
            self._latte_litri_quote_by_group = {}
            return {}

        quote = {}
        for entry_id in gruppi_ids:
            litri = self._latte_litri_quote_by_group.get(int(entry_id))
            if litri is None:
                continue
            litri_value = self._normalizza_quota_litri_input(litri)
            if litri_value is None:
                continue
            quote[int(entry_id)] = litri_value

        totale_esplicito = sum(quote.values())
        if totale_esplicito > float(litri_totali) + 1e-6:
            QMessageBox.critical(
                self,
                "Errore",
                "La somma dei litri specificati per i gruppi supera i litri totali della produzione.",
            )
            return None

        self._latte_litri_quote_by_group = dict(quote)
        return quote

    def _label_breve_gruppo_latte(self, entry_id):
        entry = self._latte_gruppi_entries_by_id.get(int(entry_id), {})
        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
        capi = int(entry.get("capi", 0) or 0)
        return f"{group_name} ({format_number(capi, 0)} capi)"

    def apri_dialog_quote_litri_gruppi_latte(self):
        gruppi_ids = self.get_gruppi_latte_selezionati_ids()
        if len(gruppi_ids) <= 1:
            QMessageBox.information(
                self,
                "Quote litri per gruppo",
                "Seleziona almeno due gruppi per specificare i litri prodotti da ciascun gruppo.",
            )
            return

        litri_totali = self._litri_totali_correnti()
        if litri_totali is None:
            QMessageBox.critical(
                self,
                "Errore",
                "Inserisci prima la quantita prodotta (valore valido) per poter ripartire i litri per gruppo.",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Litri prodotti per gruppo")
        dialog.setModal(True)
        dialog.resize(760, 320)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        info = QLabel(
            f"Litri totali produzione: {format_number(litri_totali, 2)} L\n"
            "Compila solo i gruppi con litri espliciti. I restanti litri saranno ripartiti in base ai capi."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        layout.addLayout(form)

        edit_by_group = {}
        for row_index, entry_id in enumerate(gruppi_ids):
            label = QLabel(self._label_breve_gruppo_latte(entry_id))
            edit = QLineEdit(dialog)
            edit.setPlaceholderText("Litri")
            litri_existing = self._latte_litri_quote_by_group.get(int(entry_id))
            if litri_existing is not None and float(litri_existing or 0) > 0:
                edit.setText(format_number(float(litri_existing), 2))

            form.addWidget(label, row_index, 0)
            form.addWidget(edit, row_index, 1)
            form.addWidget(QLabel("L"), row_index, 2)
            edit_by_group[int(entry_id)] = edit

        label_esito = QLabel("")
        label_esito.setStyleSheet("color: #1f5f3f;")
        layout.addWidget(label_esito)

        def _aggiorna_esito_preview():
            totale_esplicito = 0.0
            for edit in edit_by_group.values():
                litri_val = self._normalizza_quota_litri_input(edit.text())
                if litri_val is None:
                    continue
                totale_esplicito += litri_val

            residuo = max(litri_totali - totale_esplicito, 0.0)
            label_esito.setText(
                f"Litri espliciti: {format_number(totale_esplicito, 2)} L | "
                f"Residuo automatico (per capi): {format_number(residuo, 2)} L"
            )

        def _auto_per_capi():
            for edit in edit_by_group.values():
                edit.clear()
            _aggiorna_esito_preview()

        def _conferma():
            nuove_quote = {}
            for entry_id, edit in edit_by_group.items():
                litri_val = self._normalizza_quota_litri_input(edit.text())
                if litri_val is None:
                    continue
                nuove_quote[entry_id] = litri_val

            totale_esplicito = sum(nuove_quote.values())
            if totale_esplicito > litri_totali + 1e-6:
                QMessageBox.critical(
                    dialog,
                    "Errore",
                    "La somma dei litri inseriti supera i litri totali della produzione.",
                )
                return

            self._latte_litri_quote_by_group = nuove_quote
            dialog.accept()
            self._aggiorna_stato_gruppi_latte()

        row_btn = QHBoxLayout()
        row_btn.setSpacing(8)

        button_auto = QPushButton("Auto per capi", dialog)
        button_auto.clicked.connect(_auto_per_capi)
        row_btn.addWidget(button_auto)

        row_btn.addStretch(1)

        button_ok = QPushButton("Conferma", dialog)
        button_ok.clicked.connect(_conferma)
        row_btn.addWidget(button_ok)

        button_cancel = QPushButton("Annulla", dialog)
        button_cancel.clicked.connect(dialog.reject)
        row_btn.addWidget(button_cancel)

        layout.addLayout(row_btn)

        for edit in edit_by_group.values():
            edit.textChanged.connect(_aggiorna_esito_preview)

        _aggiorna_esito_preview()
        dialog.exec()

    def _aggiorna_stato_gruppi_latte(self):
        totale = int(self.list_gruppi.count())
        if totale <= 0:
            self.button_quote.setEnabled(False)
            self.label_gruppi_stato.setText(
                "Nessun gruppo da latte disponibile. Configurali in Azienda > Gruppi animali."
            )
            return

        selected_ids = self.get_gruppi_latte_selezionati_ids()
        self.button_quote.setEnabled(len(selected_ids) > 1)

        if not selected_ids:
            self.label_gruppi_stato.setText(
                "Seleziona almeno un gruppo. Puoi selezionare piu gruppi solo se dello stesso tipo animale."
            )
            return

        selected_types = {
            (self._latte_gruppi_entries_by_id.get(entry_id, {}).get("tipo_animale") or "").strip().upper()
            for entry_id in selected_ids
        }
        selected_types.discard("")

        if len(selected_types) > 1:
            self.label_gruppi_stato.setText(
                "Selezione non valida: i gruppi scelti appartengono a tipi animali diversi."
            )
            return

        self._pulisci_quote_litri_non_selezionate()
        if len(selected_ids) > 1:
            quote = {
                entry_id: float(litri)
                for entry_id, litri in self._latte_litri_quote_by_group.items()
                if entry_id in set(selected_ids) and float(litri or 0) > 0
            }
            if quote:
                totale_quote = sum(quote.values())
                self.label_gruppi_stato.setText(
                    f"Gruppi selezionati: {len(selected_ids)} su {totale}. "
                    f"Quote litri esplicite: {len(quote)} gruppi ({format_number(totale_quote, 2)} L). "
                    "Litri restanti ripartiti automaticamente in base ai capi."
                )
            else:
                self.label_gruppi_stato.setText(
                    f"Gruppi selezionati: {len(selected_ids)} su {totale}. "
                    "Nessuna quota litri esplicita: ripartizione automatica in base ai capi."
                )
            return

        self._latte_litri_quote_by_group = {}
        self.label_gruppi_stato.setText(f"Gruppi selezionati: {len(selected_ids)} su {totale}.")

    def deseleziona_gruppi_latte(self):
        self.list_gruppi.clearSelection()
        self._latte_litri_quote_by_group = {}
        self._aggiorna_stato_gruppi_latte()

    def seleziona_tutti_gruppi_latte(self):
        if self.list_gruppi.count() <= 0:
            return

        first_item = self.list_gruppi.item(0)
        first_id = int(first_item.data(Qt.UserRole) or 0)
        first_entry = self._latte_gruppi_entries_by_id.get(first_id, {})
        tipo_base = (first_entry.get("tipo_animale") or "").strip().upper()

        self.list_gruppi.clearSelection()
        for index in range(self.list_gruppi.count()):
            item = self.list_gruppi.item(index)
            entry_id = int(item.data(Qt.UserRole) or 0)
            entry = self._latte_gruppi_entries_by_id.get(entry_id, {})
            tipo = (entry.get("tipo_animale") or "").strip().upper()
            if tipo and tipo == tipo_base:
                item.setSelected(True)

        self._pulisci_quote_litri_non_selezionate()
        self._aggiorna_stato_gruppi_latte()

    def _valida_gruppi_latte_selezionati(self):
        selected_ids = []
        seen = set()
        for entry_id in self.get_gruppi_latte_selezionati_ids():
            if entry_id <= 0 or entry_id in seen:
                continue
            seen.add(entry_id)
            selected_ids.append(entry_id)

        if not selected_ids:
            QMessageBox.critical(self, "Errore", "Seleziona almeno un gruppo da latte.")
            return None

        entries = self._carica_gruppi_latte_attivi()
        entries_by_id = {int(entry.get("id", 0) or 0): entry for entry in entries}

        missing_ids = [entry_id for entry_id in selected_ids if entry_id not in entries_by_id]
        if missing_ids:
            QMessageBox.critical(
                self,
                "Errore",
                "Uno o piu gruppi selezionati non sono piu disponibili. Aggiorna e riprova.",
            )
            self.aggiorna_lista_gruppi_latte()
            return None

        selected_types = {
            (entries_by_id[entry_id].get("tipo_animale") or "").strip().upper() for entry_id in selected_ids
        }
        selected_types.discard("")
        if len(selected_types) > 1:
            QMessageBox.critical(
                self,
                "Errore",
                "Puoi attribuire la produzione a piu gruppi solo se appartengono allo stesso tipo animale.",
            )
            return None

        group_names = []
        for entry_id in selected_ids:
            entry = entries_by_id[entry_id]
            group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
            group_names.append(group_name)

        return {"entry_ids": selected_ids, "group_names": group_names}

    def _format_data_table(self, data_iso: str) -> str:
        value = (data_iso or "").strip()
        if not value:
            return ""
        try:
            return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return value

    def _parse_data_iso(self) -> str:
        data = self.input_data.date()
        if not data.isValid():
            raise ValueError("Inserisci la data di produzione.")
        return data.toString("yyyy-MM-dd")

    def _carica_fattura_collegata_produzione(self, produzione_id: int, movimento_id: int | None):
        self.rimuovi_fattura_latte()

        movimento_id_value = int(movimento_id or 0)
        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    """
                    SELECT nome_originale
                    FROM fatture
                    WHERE user_id=?
                      AND (
                        produzione_id=?
                        OR (? > 0 AND movimento_id=?)
                      )
                    ORDER BY data_caricamento DESC, id DESC
                    LIMIT 1
                """,
                    (self.user_id, produzione_id, movimento_id_value, movimento_id_value),
                )
                row = c.fetchone()
        except sqlite3.Error:
            row = None

        if row and row[0]:
            self.label_nome_fattura.setText(str(row[0]))

    def _on_selezione_produzione_latte(self):
        if self.produzione_in_modifica_id is not None:
            return

        selezionato = self._selected_produzione_id()
        if selezionato is None:
            self.label_modifica_stato.setText("")
            return

        self.label_modifica_stato.setText(
            "Produzione selezionata. Premi 'Modifica selezionata' per aggiornare dati e quantita per gruppo."
        )

    def modifica_produzione_latte_selezionata(self):
        self.prepara_modifica_produzione_latte(show_errors=True)

    def prepara_modifica_produzione_latte(self, show_errors=False):
        produzione_id = self._selected_produzione_id()
        if produzione_id is None:
            if show_errors:
                QMessageBox.warning(self, "Attenzione", "Seleziona prima una produzione da modificare.")
            return

        row = self.table_produzione.currentRow()
        data_value = self.table_produzione.item(row, 1).text() if self.table_produzione.item(row, 1) else ""
        quantita_value = self.table_produzione.item(row, 2).text() if self.table_produzione.item(row, 2) else ""
        prezzo_value = self.table_produzione.item(row, 3).text() if self.table_produzione.item(row, 3) else ""

        self.produzione_in_modifica_id = int(produzione_id)
        parsed = QDate.fromString(data_value, "dd/MM/yyyy")
        self.input_data.setDate(parsed if parsed.isValid() else QDate.currentDate())
        self.input_quantita.setText(quantita_value)
        self.combo_unita_quantita.setCurrentText(self._UNITA_QTA_LATTE[0])
        self.input_prezzo.setText(prezzo_value or "0,00")
        self.combo_unita_prezzo.setCurrentText(self._UNITA_PREZZO_LATTE[0])

        linked_group_ids = []
        group_allocations = {}
        movimento_id = 0

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT movimento_id FROM produzione_latte WHERE id=? AND user_id=?",
                    (self.produzione_in_modifica_id, self.user_id),
                )
                row_mov = c.fetchone()

            movimento_id = int((row_mov[0] if row_mov else 0) or 0)
            if movimento_id > 0:
                linked_group_ids = get_movimento_animali_entry_ids(self.user_id, movimento_id)
            group_allocations = get_produzione_latte_group_allocations(self.user_id, self.produzione_in_modifica_id)
        except (sqlite3.Error, ValueError):
            linked_group_ids = []
            group_allocations = {}
            movimento_id = 0

        self.imposta_gruppi_latte_selezionati(linked_group_ids)
        self._latte_litri_quote_by_group = {
            int(entry_id): float(litri)
            for entry_id, litri in group_allocations.items()
            if int(entry_id) in set(linked_group_ids) and float(litri or 0) > 0
        }

        self.button_salva.setText("Aggiorna Produzione")
        self.button_annulla.setEnabled(True)

        quote_count = len(self._latte_litri_quote_by_group)
        self.label_modifica_stato.setText(
            f"Modifica produzione ID {self.produzione_in_modifica_id} attiva. Quote gruppi caricate: {quote_count}."
        )
        self._aggiorna_stato_gruppi_latte()
        self._carica_fattura_collegata_produzione(self.produzione_in_modifica_id, movimento_id)

    def annulla_modifica_produzione_latte(self, reset_fields=False):
        self.produzione_in_modifica_id = None
        self.button_salva.setText("Salva Produzione")
        self.button_annulla.setEnabled(False)
        self.label_modifica_stato.setText("")

        self.table_produzione.clearSelection()

        if reset_fields:
            self.input_data.setDate(QDate.currentDate())
            self.input_quantita.clear()
            self.combo_unita_quantita.setCurrentText(self._UNITA_QTA_LATTE[0])
            self.input_prezzo.setText("0,00")
            self.combo_unita_prezzo.setCurrentText(self._UNITA_PREZZO_LATTE[0])
            self._latte_litri_quote_by_group = {}
            self.deseleziona_gruppi_latte()

        self._aggiorna_stato_gruppi_latte()

    def salva_produzione_latte(self):
        try:
            data_db = self._parse_data_iso()
        except ValueError as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return

        if is_blank(self.input_quantita.text()):
            QMessageBox.critical(self, "Errore", "Inserisci la quantita prodotta.")
            return

        litri_val = self._parse_quantita_litri_latte(self.input_quantita.text(), self.combo_unita_quantita.currentText())
        if litri_val is None or litri_val <= 0:
            QMessageBox.critical(self, "Errore", "Quantita non valida.")
            return

        quintali_val = litri_val / LITRI_PER_QUINTALE

        prezzo_text = self.input_prezzo.text().strip()
        if is_blank(prezzo_text):
            prezzo_val = 0.0
        else:
            prezzo_val = self._parse_prezzo_litro_latte(prezzo_text, self.combo_unita_prezzo.currentText())
            if prezzo_val is None:
                QMessageBox.critical(self, "Errore", "Prezzo non valido.")
                return

        gruppi_info = self._valida_gruppi_latte_selezionati()
        if gruppi_info is None:
            return

        gruppi_ids = gruppi_info["entry_ids"]
        gruppi_text = ", ".join(gruppi_info["group_names"])

        quote_litri_gruppi = self._quote_litri_gruppi_per_salvataggio(gruppi_ids, litri_val)
        if quote_litri_gruppi is None:
            return

        importo_entrata = litri_val * prezzo_val
        descrizione_mov = (
            f"Produzione latte: {format_number(quintali_val, 2)} q "
            f"({format_number(litri_val, 2)} L) x {format_eur(prezzo_val, 4)}/L"
            f" | Gruppi: {gruppi_text}"
        )

        parser_data = self.pending_parser_latte_data if isinstance(self.pending_parser_latte_data, dict) else None
        parser_values = self._estrai_valori_parser_db(parser_data)

        importo_movimento = importo_entrata
        iva_importo_movimento = 0.0

        if parser_data is not None:
            parser_vat = parse_decimal(parser_data.get("vat_total"), allow_zero=True, allow_negative=False)
            parser_taxable = parse_decimal(parser_data.get("taxable_total"), allow_zero=True, allow_negative=False)
            parser_total = parse_decimal(parser_data.get("total_amount"), allow_zero=False, allow_negative=False)

            if parser_taxable is not None and parser_vat is not None:
                importo_movimento = max(parser_taxable, 0.0)
                iva_importo_movimento = max(parser_vat, 0.0)
            elif parser_total is not None and parser_vat is not None and parser_total >= parser_vat:
                iva_importo_movimento = max(parser_vat, 0.0)
                importo_movimento = max(parser_total - iva_importo_movimento, 0.0)
            elif parser_vat is not None and parser_vat > 0 and importo_entrata >= parser_vat:
                iva_importo_movimento = parser_vat
                importo_movimento = max(importo_entrata - iva_importo_movimento, 0.0)

        try:
            with get_conn() as conn:
                c = conn.cursor()
                movimento_id = None
                produzione_id = None

                def _insert_movimento_latte(target_cursor):
                    if parser_data is not None:
                        target_cursor.execute(
                            """
                            INSERT INTO movimenti (
                                user_id, data_op, tipo, categoria, descrizione, importo, iva_importo,
                                parser_invoice_number, parser_invoice_date, parser_due_date,
                                parser_supplier_name, parser_supplier_vat,
                                parser_customer_name, parser_customer_vat,
                                parser_total_amount, parser_taxable_total, parser_vat_total,
                                parser_payment_terms, parser_warnings, parser_products, parser_fields_view
                            )
                            VALUES (?, ?, 'ENTRATA', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                            (
                                self.user_id,
                                data_db,
                                "Latte",
                                descrizione_mov,
                                importo_movimento,
                                iva_importo_movimento,
                                *parser_values,
                            ),
                        )
                    else:
                        target_cursor.execute(
                            """
                            INSERT INTO movimenti (user_id, data_op, tipo, categoria, descrizione, importo, iva_importo)
                            VALUES (?, ?, 'ENTRATA', ?, ?, ?, ?)
                        """,
                            (
                                self.user_id,
                                data_db,
                                "Latte",
                                descrizione_mov,
                                importo_movimento,
                                iva_importo_movimento,
                            ),
                        )
                    return int(target_cursor.lastrowid or 0)

                if self.produzione_in_modifica_id is None:
                    movimento_id = _insert_movimento_latte(c)
                    c.execute(
                        """
                        INSERT INTO produzione_latte (user_id, data_op, litri, prezzo_litro, movimento_id)
                        VALUES (?, ?, ?, ?, ?)
                    """,
                        (self.user_id, data_db, litri_val, prezzo_val, movimento_id),
                    )
                    produzione_id = int(c.lastrowid or 0)
                    msg_ok = "Produzione latte salvata"
                else:
                    produzione_id = int(self.produzione_in_modifica_id)

                    c.execute(
                        "SELECT movimento_id FROM produzione_latte WHERE id=? AND user_id=?",
                        (produzione_id, self.user_id),
                    )
                    row = c.fetchone()
                    if not row:
                        QMessageBox.critical(self, "Errore", "Produzione non trovata o non modificabile.")
                        return
                    movimento_id = int((row[0] if row else 0) or 0)

                    c.execute(
                        """
                        UPDATE produzione_latte
                        SET data_op=?, litri=?, prezzo_litro=?
                        WHERE id=? AND user_id=?
                    """,
                        (data_db, litri_val, prezzo_val, produzione_id, self.user_id),
                    )
                    if c.rowcount == 0:
                        QMessageBox.critical(self, "Errore", "Produzione non trovata o non modificabile.")
                        return

                    if movimento_id > 0:
                        if parser_data is None:
                            c.execute(
                                "SELECT importo, iva_importo FROM movimenti WHERE id=? AND user_id=?",
                                (movimento_id, self.user_id),
                            )
                            row_prev = c.fetchone()
                            if row_prev:
                                prev_importo = float((row_prev[0] or 0) if row_prev[0] is not None else 0)
                                prev_iva = float((row_prev[1] or 0) if row_prev[1] is not None else 0)
                                prev_totale = max(prev_importo + prev_iva, 0.0)
                                if prev_totale > 0 and prev_iva > 0 and importo_entrata > 0:
                                    iva_importo_movimento = importo_entrata * (prev_iva / prev_totale)
                                    importo_movimento = max(importo_entrata - iva_importo_movimento, 0.0)

                        if parser_data is not None:
                            c.execute(
                                """
                                UPDATE movimenti
                                SET data_op=?, tipo='ENTRATA', categoria=?, descrizione=?, importo=?, iva_importo=?,
                                    parser_invoice_number=?, parser_invoice_date=?, parser_due_date=?,
                                    parser_supplier_name=?, parser_supplier_vat=?,
                                    parser_customer_name=?, parser_customer_vat=?,
                                    parser_total_amount=?, parser_taxable_total=?, parser_vat_total=?,
                                    parser_payment_terms=?, parser_warnings=?, parser_products=?, parser_fields_view=?
                                WHERE id=? AND user_id=?
                            """,
                                (
                                    data_db,
                                    "Latte",
                                    descrizione_mov,
                                    importo_movimento,
                                    iva_importo_movimento,
                                    *parser_values,
                                    movimento_id,
                                    self.user_id,
                                ),
                            )
                        else:
                            c.execute(
                                """
                                UPDATE movimenti
                                SET data_op=?, tipo='ENTRATA', categoria=?, descrizione=?, importo=?, iva_importo=?
                                WHERE id=? AND user_id=?
                            """,
                                (
                                    data_db,
                                    "Latte",
                                    descrizione_mov,
                                    importo_movimento,
                                    iva_importo_movimento,
                                    movimento_id,
                                    self.user_id,
                                ),
                            )
                        if c.rowcount == 0:
                            movimento_id = 0

                    if movimento_id <= 0:
                        movimento_id = _insert_movimento_latte(c)
                        c.execute(
                            "UPDATE produzione_latte SET movimento_id=? WHERE id=? AND user_id=?",
                            (movimento_id, produzione_id, self.user_id),
                        )

                    if movimento_id > 0:
                        set_movimento_animali_links(self.user_id, movimento_id, gruppi_ids, cursor=c)

                    msg_ok = "Produzione latte aggiornata"

                if self.produzione_in_modifica_id is None and movimento_id is not None:
                    set_movimento_animali_links(self.user_id, movimento_id, gruppi_ids, cursor=c)

                if self.pending_fattura_latte_id is not None and movimento_id is not None and produzione_id is not None:
                    c.execute(
                        """
                        UPDATE fatture
                        SET movimento_id=?, produzione_id=?
                        WHERE id=? AND user_id=?
                    """,
                        (movimento_id, produzione_id, self.pending_fattura_latte_id, self.user_id),
                    )

                if produzione_id is not None:
                    set_produzione_latte_group_allocations(
                        self.user_id,
                        produzione_id,
                        movimento_id,
                        quote_litri_gruppi,
                        cursor=c,
                    )
        except ValueError as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        self.annulla_modifica_produzione_latte(reset_fields=True)
        self.rimuovi_fattura_latte()
        self.carica_produzioni_latte(show_errors=False)
        self.produzione_changed.emit()

        QMessageBox.information(
            self,
            "Successo",
            f"{msg_ok} ({format_number(quintali_val, 2)} q)! Entrata automatica: {format_eur(importo_entrata)}",
        )

    def carica_produzioni_latte(self, show_errors=True):
        self.table_produzione.setRowCount(0)

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    """
                    SELECT id, data_op, litri, prezzo_litro, movimento_id
                    FROM produzione_latte
                    WHERE user_id=?
                    ORDER BY data_op DESC, id DESC
                """,
                    (self.user_id,),
                )
                rows = c.fetchall()
        except sqlite3.Error as exc:
            if show_errors:
                QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        for row_index, (prod_id, data_op, litri, prezzo_litro, _movimento_id) in enumerate(rows):
            quintali = float(litri or 0) / LITRI_PER_QUINTALE
            self._append_row(
                row_index,
                [
                    str(int(prod_id or 0)),
                    self._format_data_table(str(data_op or "")),
                    format_number(quintali, 2),
                    format_number(float(prezzo_litro or 0), 4),
                ],
                right_align_indexes=[2, 3],
            )

    def elimina_produzione_latte_selezionata(self):
        produzione_id = self._selected_produzione_id()
        if produzione_id is None:
            QMessageBox.warning(self, "Attenzione", "Seleziona prima una riga di produzione da eliminare.")
            return

        row = self.table_produzione.currentRow()
        data_value = self.table_produzione.item(row, 1).text() if self.table_produzione.item(row, 1) else ""
        quintali_value = self.table_produzione.item(row, 2).text() if self.table_produzione.item(row, 2) else ""

        conferma = QMessageBox.question(
            self,
            "Conferma eliminazione",
            f"Vuoi eliminare la produzione selezionata?\n\nData: {data_value} - Quintali: {quintali_value}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if conferma != QMessageBox.Yes:
            return

        era_in_modifica = self.produzione_in_modifica_id == produzione_id
        fatture_eliminate = 0
        percorsi_fatture = []

        try:
            with get_conn() as conn:
                c = conn.cursor()

                c.execute("SELECT movimento_id FROM produzione_latte WHERE id=? AND user_id=?", (produzione_id, self.user_id))
                row_mov = c.fetchone()
                if not row_mov:
                    QMessageBox.critical(self, "Errore", "Produzione non trovata o non eliminabile.")
                    return

                movimento_id = int((row_mov[0] if row_mov else 0) or 0)

                c.execute("DELETE FROM produzione_latte WHERE id=? AND user_id=?", (produzione_id, self.user_id))
                if c.rowcount == 0:
                    QMessageBox.critical(self, "Errore", "Produzione non trovata o non eliminabile.")
                    return

                if movimento_id > 0:
                    fatture_eliminate, percorsi_fatture = self.elimina_fatture_collegate_db(c, movimento_id)
                    c.execute("DELETE FROM movimenti WHERE id=? AND user_id=?", (movimento_id, self.user_id))
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        file_eliminati, file_non_trovati, file_errori = self.elimina_file_fatture(percorsi_fatture)

        self.carica_produzioni_latte(show_errors=False)
        if era_in_modifica:
            self.annulla_modifica_produzione_latte(reset_fields=True)
        self.produzione_changed.emit()

        msg_ok = "Produzione eliminata dal database!"
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

    def seleziona_fattura_latte(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Seleziona fattura PDF (Latte)", "", "PDF Files (*.pdf)")
        if not file_path:
            return

        try:
            fattura_id, percorso_archiviato = self.archivia_fattura_caricata(file_path, "LATTE")
        except Exception as exc:
            QMessageBox.critical(self, "Caricamento fattura", f"Impossibile salvare la fattura: {exc}")
            return

        self.pending_fattura_latte_id = fattura_id
        self.pending_fattura_latte_path = percorso_archiviato
        self.pending_parser_latte_data = None
        self.label_nome_fattura.setText(Path(percorso_archiviato).name)
        self._set_parser_feedback_latte(True, "Analisi fattura in corso...")

        def _on_success(risultato):
            try:
                dati_latte = self.analizza_fattura_latte_con_parser_fatture(
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

            self._applica_dati_parser_al_form_latte(dati_latte)
            self.pending_parser_latte_data = dati_latte.get("parser_data")

            iva_label = format_number(dati_latte.get("iva_percent", 0.0), 2)
            QMessageBox.information(
                self,
                "Importazione completata",
                "Valori produzione impostati da fattura:\n"
                f"- Quantita: {self.input_quantita.text()} {self.combo_unita_quantita.currentText()}\n"
                f"- Prezzo (IVA inclusa): {self.input_prezzo.text()} {self.combo_unita_prezzo.currentText()}\n"
                f"- Aliquota IVA applicata: {iva_label}%",
            )

        def _on_error(message):
            QMessageBox.warning(
                self,
                "Analisi non completata",
                f"Fattura salvata correttamente, ma analisi automatica non disponibile: {message}",
            )

        def _on_progress(message):
            self._set_parser_feedback_latte(True, f"Analisi fattura: {message}")

        def _on_done():
            self._set_parser_feedback_latte(False)

        try:
            self.avvia_parser_fattura_async(
                percorso_archiviato,
                on_success=_on_success,
                on_error=_on_error,
                on_done=_on_done,
                on_progress=_on_progress,
            )
        except Exception as exc:
            self._set_parser_feedback_latte(False)
            QMessageBox.warning(
                self,
                "Analisi non avviata",
                f"Fattura salvata correttamente, ma il parser non si e avviato: {exc}",
            )

    def rimuovi_fattura_latte(self):
        self.pending_fattura_latte_id = None
        self.pending_fattura_latte_path = None
        self.pending_parser_latte_data = None
        self.label_nome_fattura.setText("Nessuna fattura caricata")

    def _set_parser_feedback_latte(self, busy: bool, message: str | None = None):
        if busy:
            if not self._parser_latte_busy:
                self._parser_latte_prev_status_text = self.label_modifica_stato.text()
            self._parser_latte_busy = True
            self.progress_parser.setVisible(True)
            self.button_importa_fattura.setEnabled(False)
            self.button_rimuovi_fattura.setEnabled(False)
            self.button_salva.setEnabled(False)
            if message is not None:
                self.label_modifica_stato.setText(message)
            return

        self._parser_latte_busy = False
        self.progress_parser.setVisible(False)
        self.button_importa_fattura.setEnabled(True)
        self.button_rimuovi_fattura.setEnabled(True)
        self.button_salva.setEnabled(True)

        if message is not None:
            self.label_modifica_stato.setText(message)
            return

        if self.produzione_in_modifica_id is None:
            self.label_modifica_stato.setText("")
        else:
            self.label_modifica_stato.setText(self._parser_latte_prev_status_text)

    def _applica_dati_parser_al_form_latte(self, dati):
        if not isinstance(dati, dict):
            return

        data_value = dati.get("data")
        if data_value:
            parsed = QDate.fromString(str(data_value), "dd/MM/yyyy")
            if parsed.isValid():
                self.input_data.setDate(parsed)

        quantita_value = dati.get("quintali")
        if quantita_value:
            self.input_quantita.setText(str(quantita_value))

        prezzo_value = dati.get("prezzo_litro")
        if prezzo_value:
            self.input_prezzo.setText(str(prezzo_value))

        self.combo_unita_quantita.setCurrentText("Quintali")
        self.combo_unita_prezzo.setCurrentText("EUR/Litro")

    def analizza_fattura_latte_con_parser_fatture(self, pdf_path, file_path, risultato=None):
        if risultato is None:
            parse_invoice_pdf = self._get_parser_fatture_function()
            risultato = parse_invoice_pdf(str(pdf_path))
        risultato = self._normalizza_risultato_parser(risultato)
        fields = getattr(risultato, "fields", {}) or {}
        parser_data = self._costruisci_dati_parser_movimento(risultato, fields)

        data_raw = self._estrai_valore_campo_parser(fields, "invoice_date")
        data_out = self._normalizza_data_fattura(data_raw) or datetime.now().strftime("%d/%m/%Y")

        line_items = getattr(risultato, "line_items", []) or []
        linea_latte = self._seleziona_linea_latte(line_items)
        if linea_latte is None:
            raise RuntimeError("Impossibile individuare riga prodotto latte con quantita e prezzo validi nella fattura.")

        quintali = self._valore_parser_to_float(getattr(linea_latte, "quantity", None), allow_zero=False)
        if quintali is None or quintali <= 0:
            raise RuntimeError("Quantita in quintali non trovata o non valida nella fattura.")

        prezzo_quintale = self._valore_parser_to_float(getattr(linea_latte, "unit_price", None), allow_zero=False)
        if prezzo_quintale is None:
            line_total = self._valore_parser_to_float(getattr(linea_latte, "line_total", None), allow_zero=False)
            if line_total is not None and line_total > 0:
                prezzo_quintale = line_total / quintali

        if prezzo_quintale is None or prezzo_quintale <= 0:
            raise RuntimeError("Prezzo al quintale non trovato o non valido nella fattura.")

        iva_percent = self._valore_parser_to_float(getattr(linea_latte, "vat_rate", None), allow_zero=True)
        if iva_percent is None or iva_percent < 0:
            iva_percent = self._calcola_aliquota_iva_parser(fields, risultato)
        if iva_percent is None or iva_percent < 0:
            iva_percent = 0.0

        prezzo_quintale_lordo = prezzo_quintale * (1.0 + (iva_percent / 100.0))
        prezzo_litro_lordo = prezzo_quintale_lordo / LITRI_PER_QUINTALE

        return {
            "data": data_out,
            "quintali": format_number(quintali, 2),
            "prezzo_litro": format_number(prezzo_litro_lordo, 4),
            "iva_percent": iva_percent,
            "file": str(Path(file_path).name),
            "parser_data": parser_data,
        }

    def _seleziona_linea_latte(self, line_items):
        candidati = []
        for item in line_items:
            quantity = self._valore_parser_to_float(getattr(item, "quantity", None), allow_zero=False)
            if quantity is None or quantity <= 0:
                continue

            unit_price = self._valore_parser_to_float(getattr(item, "unit_price", None), allow_zero=False)
            line_total = self._valore_parser_to_float(getattr(item, "line_total", None), allow_zero=False)
            if unit_price is None and line_total is None:
                continue

            description = str(getattr(item, "description", "") or "").strip().lower()
            score = 0
            if "latte" in description:
                score += 4
            if "q" in description or "quint" in description:
                score += 2

            candidati.append((score, line_total or 0.0, item))

        if not candidati:
            return None

        candidati.sort(key=lambda data: (data[0], data[1]), reverse=True)
        return candidati[0][2]
