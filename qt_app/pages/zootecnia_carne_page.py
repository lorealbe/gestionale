import re
import sqlite3
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
)

from app_utils import format_eur, format_number, is_blank, parse_decimal
from database import (
    get_conn,
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
        self.input_quantita.setPlaceholderText("Quantita venduta")

        self.combo_unita_quantita = QComboBox(self)
        self.combo_unita_quantita.addItems(self._UNITA_QTA)

        self.input_prezzo = QLineEdit(self)
        self.input_prezzo.setText("0,00")

        self.combo_unita_prezzo = QComboBox(self)
        self.combo_unita_prezzo.addItems(self._UNITA_PREZZO)

        form_layout.addWidget(QLabel("Data produzione:"), 0, 0)
        form_layout.addWidget(self.input_data, 0, 1)

        form_layout.addWidget(QLabel("Quantita venduta:"), 1, 0)
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

        gruppi_layout.addWidget(QLabel("Gruppi da carne"))

        row_gruppi = QHBoxLayout()
        row_gruppi.setSpacing(8)

        self.list_gruppi = QListWidget(self)
        self.list_gruppi.setSelectionMode(QAbstractItemView.MultiSelection)
        self.list_gruppi.itemSelectionChanged.connect(self._on_selezione_gruppi_carne)
        row_gruppi.addWidget(self.list_gruppi, 1)

        col_buttons = QVBoxLayout()
        col_buttons.setSpacing(6)

        button_tutti = QPushButton("Seleziona tutti", self)
        button_tutti.clicked.connect(self.seleziona_tutti_gruppi_carne)
        col_buttons.addWidget(button_tutti)

        button_nessuno = QPushButton("Deseleziona", self)
        button_nessuno.clicked.connect(self.deseleziona_gruppi_carne)
        col_buttons.addWidget(button_nessuno)

        col_buttons.addStretch(1)
        row_gruppi.addLayout(col_buttons)

        gruppi_layout.addLayout(row_gruppi)

        row_rimozione = QHBoxLayout()
        row_rimozione.setSpacing(8)

        self.check_rimuovi_capi = QCheckBox(
            "Rimuovi capi dai gruppi selezionati durante il salvataggio",
            self,
        )
        self.check_rimuovi_capi.toggled.connect(self._on_toggle_rimozione_capi_carne)
        row_rimozione.addWidget(self.check_rimuovi_capi, 1)

        row_rimozione.addWidget(QLabel("Capi da rimuovere:"))
        self.input_capi_da_rimuovere = QLineEdit(self)
        self.input_capi_da_rimuovere.setPlaceholderText("Numero intero")
        self.input_capi_da_rimuovere.textChanged.connect(lambda _t: self._aggiorna_stato_gruppi_carne())
        row_rimozione.addWidget(self.input_capi_da_rimuovere)

        gruppi_layout.addLayout(row_rimozione)

        self.label_gruppi_stato = QLabel("")
        self.label_gruppi_stato.setWordWrap(True)
        gruppi_layout.addWidget(self.label_gruppi_stato)

        layout.addWidget(frame_gruppi)

        row_actions = QHBoxLayout()
        row_actions.setSpacing(8)

        self.button_salva = QPushButton("Salva Produzione Carne", self)
        self.button_salva.clicked.connect(self.salva_produzione_carne)
        row_actions.addWidget(self.button_salva)

        button_modifica = QPushButton("Modifica selezionata", self)
        button_modifica.clicked.connect(self.modifica_produzione_carne_selezionata)
        row_actions.addWidget(button_modifica)

        self.button_annulla = QPushButton("Annulla modifica", self)
        self.button_annulla.setEnabled(False)
        self.button_annulla.clicked.connect(lambda: self.annulla_modifica_produzione_carne(reset_fields=True))
        row_actions.addWidget(self.button_annulla)

        button_ricarica = QPushButton("Ricarica storico", self)
        button_ricarica.clicked.connect(lambda: self.carica_produzioni_carne(show_errors=True))
        row_actions.addWidget(button_ricarica)

        button_elimina = QPushButton("Elimina selezionata", self)
        button_elimina.clicked.connect(self.elimina_produzione_carne_selezionata)
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

        fattura_layout.addWidget(QLabel("Fattura carne:"))
        self.label_nome_fattura = QLabel("Nessuna fattura caricata")
        fattura_layout.addWidget(self.label_nome_fattura, 1)

        self.button_importa_fattura = QPushButton("Carica Fattura", self)
        self.button_importa_fattura.clicked.connect(self.seleziona_fattura_carne)
        fattura_layout.addWidget(self.button_importa_fattura)

        self.button_rimuovi_fattura = QPushButton("Rimuovi", self)
        self.button_rimuovi_fattura.clicked.connect(self.rimuovi_fattura_carne)
        fattura_layout.addWidget(self.button_rimuovi_fattura)

        layout.addWidget(frame_fattura)

        self.progress_parser = QProgressBar(self)
        self.progress_parser.setRange(0, 0)
        self.progress_parser.setTextVisible(False)
        self.progress_parser.setFixedHeight(8)
        self.progress_parser.setVisible(False)
        layout.addWidget(self.progress_parser)

        riepilogo_label = QLabel("Riepilogo produzione carne")
        riepilogo_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(riepilogo_label)

        self.table_produzione = QTableWidget(0, 5, self)
        self.table_produzione.setHorizontalHeaderLabels(["ID", "Data", "Kg", "Prezzo / Kg", "Totale"])
        self.table_produzione.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_produzione.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_produzione.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_produzione.setAlternatingRowColors(True)
        self.table_produzione.verticalHeader().setVisible(False)
        self.table_produzione.itemSelectionChanged.connect(self._on_selezione_produzione_carne)
        self.table_produzione.cellDoubleClicked.connect(lambda _r, _c: self.modifica_produzione_carne_selezionata())

        table_header = self.table_produzione.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)

        layout.addWidget(self.table_produzione, 1)
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
        except sqlite3.Error:
            return []

        gruppi_attivi = []
        for entry in entries:
            entry_id = int(entry.get("id", 0) or 0)
            capi = int(entry.get("capi", 0) or 0)
            finalita = (entry.get("finalita") or "").strip().upper()
            if entry_id <= 0 or capi <= 0 or finalita != "CARNE":
                continue
            gruppi_attivi.append(entry)

        gruppi_attivi.sort(
            key=lambda item: (
                (item.get("group_name") or "").strip().lower(),
                int(item.get("id", 0) or 0),
            )
        )
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
            if show_errors:
                QMessageBox.warning(self, "Attenzione", "Seleziona prima una produzione carne da modificare.")
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

        linked_group_ids = []
        movimento_id = 0

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT movimento_id FROM produzione_carne WHERE id=? AND user_id=?",
                    (self.produzione_carne_in_modifica_id, self.user_id),
                )
                row_mov = c.fetchone()

            movimento_id = int((row_mov[0] if row_mov else 0) or 0)
            if movimento_id > 0:
                linked_group_ids = get_movimento_animali_entry_ids(self.user_id, movimento_id)
        except (sqlite3.Error, ValueError):
            linked_group_ids = []
            movimento_id = 0

        self.imposta_gruppi_carne_selezionati(linked_group_ids)
        self.check_rimuovi_capi.setChecked(False)
        self.input_capi_da_rimuovere.clear()

        self.button_salva.setText("Aggiorna Produzione Carne")
        self.button_annulla.setEnabled(True)
        self.label_modifica_stato.setText(
            f"Modifica produzione carne ID {self.produzione_carne_in_modifica_id} attiva."
        )
        self._on_toggle_rimozione_capi_carne()
        self._carica_fattura_collegata_produzione_carne(movimento_id)

    def _carica_fattura_collegata_produzione_carne(self, movimento_id: int):
        self.rimuovi_fattura_carne()

        movimento_id_value = int(movimento_id or 0)
        if movimento_id_value <= 0:
            return

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    """
                    SELECT nome_originale
                    FROM fatture
                    WHERE user_id=? AND movimento_id=?
                    ORDER BY data_caricamento DESC, id DESC
                    LIMIT 1
                """,
                    (self.user_id, movimento_id_value),
                )
                row = c.fetchone()
        except sqlite3.Error:
            row = None

        if row and row[0]:
            self.label_nome_fattura.setText(str(row[0]))

    def annulla_modifica_produzione_carne(self, reset_fields=False):
        self.produzione_carne_in_modifica_id = None
        self.button_salva.setText("Salva Produzione Carne")
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
        try:
            data_db = self._parse_data_iso()
        except ValueError as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return

        if is_blank(self.input_quantita.text()):
            QMessageBox.critical(self, "Errore", "Inserisci la quantita venduta.")
            return

        kg_val = self._parse_quantita_kg_carne(self.input_quantita.text().strip(), self.combo_unita_quantita.currentText())
        if kg_val is None or kg_val <= 0:
            QMessageBox.critical(self, "Errore", "Quantita non valida.")
            return

        prezzo_kg_val = self._parse_prezzo_kg_carne(self.input_prezzo.text().strip(), self.combo_unita_prezzo.currentText())
        if prezzo_kg_val is None:
            QMessageBox.critical(self, "Errore", "Prezzo non valido.")
            return

        gruppi_info = self._valida_gruppi_carne_selezionati()
        if gruppi_info is None:
            return

        gruppi_ids = list(gruppi_info.get("entry_ids") or [])
        gruppi_text = ", ".join(gruppi_info.get("group_names") or [])

        rimozione_info = self._valida_rimozione_capi_carne(gruppi_info)
        if rimozione_info is None:
            return
        rimozione_attiva = bool(rimozione_info.get("attiva"))
        capi_da_rimuovere = int(rimozione_info.get("totale") or 0)

        quintali_val = kg_val / self.KG_PER_QUINTALE
        importo_entrata = kg_val * prezzo_kg_val
        descrizione_mov = (
            f"Produzione carne: {format_number(kg_val, 2)} Kg "
            f"({format_number(quintali_val, 2)} q) x {format_eur(prezzo_kg_val, 4)}/Kg"
        )
        if gruppi_ids:
            descrizione_mov += f" | Gruppi: {gruppi_text}"
        if rimozione_attiva and capi_da_rimuovere > 0:
            descrizione_mov += f" | Capi rimossi: {format_number(capi_da_rimuovere, 0)}"

        parser_data = self.pending_parser_carne_data if isinstance(self.pending_parser_carne_data, dict) else None
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

        rimozioni_effettuate = []
        try:
            with get_conn() as conn:
                c = conn.cursor()
                movimento_id = None
                produzione_id = None

                def _insert_movimento_carne(target_cursor):
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
                                "Carne",
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
                                "Carne",
                                descrizione_mov,
                                importo_movimento,
                                iva_importo_movimento,
                            ),
                        )
                    return int(target_cursor.lastrowid or 0)

                if self.produzione_carne_in_modifica_id is None:
                    movimento_id = _insert_movimento_carne(c)

                    c.execute(
                        """
                        INSERT INTO produzione_carne (user_id, data_op, kg, prezzo_kg, movimento_id)
                        VALUES (?, ?, ?, ?, ?)
                    """,
                        (self.user_id, data_db, kg_val, prezzo_kg_val, movimento_id),
                    )
                    produzione_id = int(c.lastrowid or 0)
                    msg_ok = "Produzione carne salvata"
                else:
                    produzione_id = int(self.produzione_carne_in_modifica_id)

                    c.execute(
                        "SELECT movimento_id FROM produzione_carne WHERE id=? AND user_id=?",
                        (produzione_id, self.user_id),
                    )
                    row = c.fetchone()
                    if not row:
                        QMessageBox.critical(self, "Errore", "Produzione carne non trovata o non modificabile.")
                        return
                    movimento_id = int((row[0] if row else 0) or 0)

                    c.execute(
                        """
                        UPDATE produzione_carne
                        SET data_op=?, kg=?, prezzo_kg=?
                        WHERE id=? AND user_id=?
                    """,
                        (data_db, kg_val, prezzo_kg_val, produzione_id, self.user_id),
                    )
                    if c.rowcount == 0:
                        QMessageBox.critical(self, "Errore", "Produzione carne non trovata o non modificabile.")
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
                                    "Carne",
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
                                    "Carne",
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
                        movimento_id = _insert_movimento_carne(c)
                        c.execute(
                            "UPDATE produzione_carne SET movimento_id=? WHERE id=? AND user_id=?",
                            (movimento_id, produzione_id, self.user_id),
                        )

                    msg_ok = "Produzione carne aggiornata"

                if movimento_id is not None:
                    set_movimento_animali_links(self.user_id, movimento_id, gruppi_ids, cursor=c)

                if self.produzione_carne_in_modifica_id is None and rimozione_attiva:
                    piano_rimozione = rimozione_info.get("piano") or {}
                    entries_by_id = gruppi_info.get("entries_by_id") or {}

                    for entry_id in gruppi_ids:
                        capi_rimossi = int(piano_rimozione.get(entry_id) or 0)
                        if capi_rimossi <= 0:
                            continue

                        remove_azienda_animale_capi(
                            self.user_id,
                            entry_id,
                            capi_rimossi,
                            cursor=c,
                        )

                        entry = entries_by_id.get(entry_id, {})
                        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
                        rimozioni_effettuate.append(f"{group_name}: -{format_number(capi_rimossi, 0)} capi")

                if self.pending_fattura_carne_id is not None and movimento_id is not None:
                    c.execute(
                        """
                        UPDATE fatture
                        SET movimento_id=?, produzione_id=NULL
                        WHERE id=? AND user_id=?
                    """,
                        (movimento_id, self.pending_fattura_carne_id, self.user_id),
                    )

        except ValueError as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        self.annulla_modifica_produzione_carne(reset_fields=True)
        self.rimuovi_fattura_carne()
        self.carica_produzioni_carne(show_errors=False)
        self.produzione_changed.emit()

        msg_successo = f"{msg_ok}! Entrata automatica: {format_eur(importo_entrata)}"
        if rimozioni_effettuate:
            msg_successo += "\nCapi rimossi dai gruppi da carne: " + ", ".join(rimozioni_effettuate)

        QMessageBox.information(self, "Successo", msg_successo)

    def carica_produzioni_carne(self, show_errors=True):
        self.table_produzione.setRowCount(0)

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    """
                    SELECT id, data_op, kg, prezzo_kg, movimento_id
                    FROM produzione_carne
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

        for row_index, (prod_id, data_op, kg, prezzo_kg, _movimento_id) in enumerate(rows):
            kg_value = float(kg or 0)
            prezzo_value = float(prezzo_kg or 0)
            totale = kg_value * prezzo_value
            self._append_row(
                row_index,
                [
                    str(int(prod_id or 0)),
                    self._format_data_table(str(data_op or "")),
                    format_number(kg_value, 2),
                    format_number(prezzo_value, 4),
                    format_number(totale, 2),
                ],
                right_align_indexes=[2, 3, 4],
            )

    def elimina_produzione_carne_selezionata(self):
        produzione_id = self._selected_produzione_id()
        if produzione_id is None:
            QMessageBox.warning(self, "Attenzione", "Seleziona prima una riga di produzione carne da eliminare.")
            return

        row = self.table_produzione.currentRow()
        data_value = self.table_produzione.item(row, 1).text() if self.table_produzione.item(row, 1) else ""
        kg_value = self.table_produzione.item(row, 2).text() if self.table_produzione.item(row, 2) else ""

        conferma = QMessageBox.question(
            self,
            "Conferma eliminazione",
            f"Vuoi eliminare la produzione carne selezionata?\n\nData: {data_value} - Kg: {kg_value}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if conferma != QMessageBox.Yes:
            return

        era_in_modifica = self.produzione_carne_in_modifica_id == produzione_id
        fatture_eliminate = 0
        percorsi_fatture = []

        try:
            with get_conn() as conn:
                c = conn.cursor()

                c.execute("SELECT movimento_id FROM produzione_carne WHERE id=? AND user_id=?", (produzione_id, self.user_id))
                row = c.fetchone()
                if not row:
                    QMessageBox.critical(self, "Errore", "Produzione carne non trovata o non eliminabile.")
                    return

                movimento_id = int((row[0] if row else 0) or 0)

                c.execute("DELETE FROM produzione_carne WHERE id=? AND user_id=?", (produzione_id, self.user_id))
                if c.rowcount == 0:
                    QMessageBox.critical(self, "Errore", "Produzione carne non trovata o non eliminabile.")
                    return

                if movimento_id > 0:
                    fatture_eliminate, percorsi_fatture = self.elimina_fatture_collegate_db(c, movimento_id)
                    c.execute("DELETE FROM movimenti WHERE id=? AND user_id=?", (movimento_id, self.user_id))
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        file_eliminati, file_non_trovati, file_errori = self.elimina_file_fatture(percorsi_fatture)

        self.carica_produzioni_carne(show_errors=False)
        if era_in_modifica:
            self.annulla_modifica_produzione_carne(reset_fields=True)
        self.produzione_changed.emit()

        msg_ok = "Produzione carne eliminata dal database!"
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
