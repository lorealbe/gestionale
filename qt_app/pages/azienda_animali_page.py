
from datetime import datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_utils import format_number, TabellaIsolata
from database import (
    add_azienda_animale_entry,
    delete_azienda_animale_entry,
    list_azienda_animali_entries,
    merge_azienda_animale_groups,
    remove_azienda_animale_capi,
    set_azienda_animale_capi,
    set_azienda_animale_finalita,
    set_azienda_animale_group_name,
    set_azienda_animale_riproduzione,
    split_azienda_animale_group,
)


class AziendaAnimaliPage(QWidget):
    ANIMAL_TYPE_OPTIONS = ("Bovini", "Ovini", "Caprini", "Suini", "Avicoli", "Equini", "Altro")
    ANIMAL_TYPE_TO_DB = {
        "Bovini": "BOVINI",
        "Ovini": "OVINI",
        "Caprini": "CAPRINI",
        "Suini": "SUINI",
        "Avicoli": "AVICOLI",
        "Equini": "EQUINI",
        "Altro": "ALTRO",
    }
    PURPOSE_OPTIONS = ("Da Latte", "Da Carne")
    PURPOSE_TO_DB = {"Da Latte": "LATTE", "Da Carne": "CARNE"}

    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = int(user_id)

        self._entries_by_id = {}
        self._merge_candidates_by_label = {}

        self._build_ui()
        self.carica_report_animali(show_errors=False)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        frame_add = QFrame(self)
        frame_add.setFrameShape(QFrame.StyledPanel)
        add_layout = QGridLayout(frame_add)
        add_layout.setContentsMargins(10, 10, 10, 10)
        add_layout.setHorizontalSpacing(8)
        add_layout.setVerticalSpacing(8)

        self.input_add_group_name = QLineEdit(self)
        self.input_add_group_name.setPlaceholderText("Nome gruppo")

        self.combo_add_tipo = QComboBox(self)
        self.combo_add_tipo.addItems(self.ANIMAL_TYPE_OPTIONS)
        self.combo_add_tipo.currentIndexChanged.connect(self._on_add_tipo_changed)

        self.combo_add_finalita = QComboBox(self)
        self.combo_add_finalita.addItems(self.PURPOSE_OPTIONS)

        self.input_add_altro = QLineEdit(self)
        self.input_add_altro.setPlaceholderText("Specifica tipo animale")

        self.check_add_riproduzione = QCheckBox("Destinato alla riproduzione", self)

        self.spin_add_capi = QSpinBox(self)
        self.spin_add_capi.setMinimum(1)
        self.spin_add_capi.setMaximum(1_000_000_000)
        self.spin_add_capi.setValue(1)

        add_layout.addWidget(QLabel("Nome gruppo:"), 0, 0)
        add_layout.addWidget(self.input_add_group_name, 0, 1)
        add_layout.addWidget(QLabel("Tipo animale:"), 0, 2)
        add_layout.addWidget(self.combo_add_tipo, 0, 3)

        add_layout.addWidget(QLabel("Destinazione:"), 1, 0)
        add_layout.addWidget(self.combo_add_finalita, 1, 1)
        add_layout.addWidget(QLabel("Specifica tipo:"), 1, 2)
        add_layout.addWidget(self.input_add_altro, 1, 3)

        add_layout.addWidget(QLabel("Numero capi:"), 2, 0)
        add_layout.addWidget(self.spin_add_capi, 2, 1)
        add_layout.addWidget(self.check_add_riproduzione, 2, 2, 1, 2)

        add_buttons = QHBoxLayout()
        add_buttons.setSpacing(8)

        button_add = QPushButton("Conferma aggiunta", self)
        button_add.clicked.connect(self.aggiungi_animale)
        add_buttons.addWidget(button_add)

        button_reset = QPushButton("Annulla", self)
        button_reset.clicked.connect(self._reset_add_form)
        add_buttons.addWidget(button_reset)

        add_buttons.addStretch(1)
        add_layout.addLayout(add_buttons, 3, 0, 1, 4)

        main_layout.addWidget(frame_add)

        self.table_animali = TabellaIsolata(0, 6, self)
        self.table_animali.setHorizontalHeaderLabels(["ID", "Gruppo", "Tipo", "Destinazione", "Riproduzione", "Capi"])
        self.table_animali.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_animali.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_animali.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_animali.setAlternatingRowColors(True)
        self.table_animali.verticalHeader().setVisible(False)
        self.table_animali.itemSelectionChanged.connect(self._on_selection_changed)

        header = self.table_animali.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)

        main_layout.addWidget(self.table_animali, 1)

        self.label_selected = QLabel("Seleziona un gruppo per modifiche.")
        self.label_selected.setStyleSheet("font-weight: 600;")
        main_layout.addWidget(self.label_selected)

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(10)

        self.group_modifica = QGroupBox("Modifica gruppo selezionato", self)
        modifica_layout = QGridLayout(self.group_modifica)
        modifica_layout.setHorizontalSpacing(8)
        modifica_layout.setVerticalSpacing(8)

        self.spin_remove_capi = QSpinBox(self.group_modifica)
        self.spin_remove_capi.setMinimum(1)
        self.spin_remove_capi.setMaximum(1_000_000_000)
        self.spin_remove_capi.setValue(1)

        button_remove_capi = QPushButton("Rimuovi capi", self.group_modifica)
        button_remove_capi.clicked.connect(self.rimuovi_capi_selezionati)

        self.spin_add_capi = QSpinBox(self.group_modifica)
        self.spin_add_capi.setMinimum(1)
        self.spin_add_capi.setMaximum(1_000_000_000)
        self.spin_add_capi.setValue(1)

        button_add_capi = QPushButton("Aggiungi capi", self.group_modifica)
        button_add_capi.clicked.connect(self.aggiungi_capi_selezionati)

        self.input_rename_group = QLineEdit(self.group_modifica)
        self.input_rename_group.setPlaceholderText("Nuovo nome gruppo")

        button_rename_group = QPushButton("Salva nome gruppo", self.group_modifica)
        button_rename_group.clicked.connect(self.rinomina_gruppo_selezionato)

        self.combo_set_finalita = QComboBox(self.group_modifica)
        self.combo_set_finalita.addItems(self.PURPOSE_OPTIONS)

        self.button_set_finalita = QPushButton("Salva destinazione", self.group_modifica)
        self.button_set_finalita.clicked.connect(self.modifica_destinazione_selezionata)

        self.check_set_riproduzione = QCheckBox("Destinato alla riproduzione", self.group_modifica)

        button_set_riproduzione = QPushButton("Salva riproduzione", self.group_modifica)
        button_set_riproduzione.clicked.connect(self.modifica_riproduzione_selezionata)

        button_delete_group = QPushButton("Rimuovi categoria selezionata", self.group_modifica)
        button_delete_group.clicked.connect(self.rimuovi_gruppo_selezionato)

        modifica_layout.addWidget(QLabel("Capi da rimuovere:"), 0, 0)
        modifica_layout.addWidget(self.spin_remove_capi, 0, 1)
        modifica_layout.addWidget(button_remove_capi, 0, 2)

        modifica_layout.addWidget(QLabel("Capi da aggiungere:"), 1, 0)
        modifica_layout.addWidget(self.spin_add_capi, 1, 1)
        modifica_layout.addWidget(button_add_capi, 1, 2)

        modifica_layout.addWidget(QLabel("Nuovo nome gruppo:"), 2, 0)
        modifica_layout.addWidget(self.input_rename_group, 2, 1)
        modifica_layout.addWidget(button_rename_group, 2, 2)

        modifica_layout.addWidget(QLabel("Nuova destinazione:"), 3, 0)
        modifica_layout.addWidget(self.combo_set_finalita, 3, 1)
        modifica_layout.addWidget(self.button_set_finalita, 3, 2)

        modifica_layout.addWidget(QLabel("Riproduzione:"), 4, 0)
        modifica_layout.addWidget(self.check_set_riproduzione, 4, 1)
        modifica_layout.addWidget(button_set_riproduzione, 4, 2)

        modifica_layout.addWidget(button_delete_group, 5, 0, 1, 3)

        self.group_divisione = QGroupBox("Dividi gruppo", self)
        divisione_layout = QGridLayout(self.group_divisione)
        divisione_layout.setHorizontalSpacing(8)
        divisione_layout.setVerticalSpacing(8)

        self.spin_split_capi = QSpinBox(self.group_divisione)
        self.spin_split_capi.setMinimum(1)
        self.spin_split_capi.setMaximum(1_000_000_000)
        self.spin_split_capi.setValue(1)

        self.input_split_group_name = QLineEdit(self.group_divisione)
        self.input_split_group_name.setPlaceholderText("Nome nuovo gruppo")

        button_split = QPushButton("Conferma divisione", self.group_divisione)
        button_split.clicked.connect(self.dividi_gruppo_selezionato)

        divisione_layout.addWidget(QLabel("Capi nuovo gruppo:"), 0, 0)
        divisione_layout.addWidget(self.spin_split_capi, 0, 1)
        divisione_layout.addWidget(QLabel("Nuovo nome gruppo:"), 1, 0)
        divisione_layout.addWidget(self.input_split_group_name, 1, 1)
        divisione_layout.addWidget(button_split, 2, 0, 1, 2)

        self.group_unione = QGroupBox("Unisci gruppi", self)
        unione_layout = QGridLayout(self.group_unione)
        unione_layout.setHorizontalSpacing(8)
        unione_layout.setVerticalSpacing(8)

        self.combo_merge_target = QComboBox(self.group_unione)

        self.input_merge_group_name = QLineEdit(self.group_unione)
        self.input_merge_group_name.setPlaceholderText("Nome gruppo unificato")

        self.check_merge_date = QCheckBox("Usa data unione", self.group_unione)
        self.check_merge_date.toggled.connect(self._on_toggle_merge_date)

        self.date_merge = QDateEdit(self.group_unione)
        self.date_merge.setDisplayFormat("dd/MM/yyyy")
        self.date_merge.setCalendarPopup(True)
        self.date_merge.setDate(QDate.currentDate())
        self.date_merge.setEnabled(False)

        button_merge = QPushButton("Conferma unione", self.group_unione)
        button_merge.clicked.connect(self.unisci_gruppi_selezionati)

        unione_layout.addWidget(QLabel("Gruppo da unire:"), 0, 0)
        unione_layout.addWidget(self.combo_merge_target, 0, 1)
        unione_layout.addWidget(QLabel("Nuovo nome gruppo:"), 1, 0)
        unione_layout.addWidget(self.input_merge_group_name, 1, 1)
        unione_layout.addWidget(self.check_merge_date, 2, 0)
        unione_layout.addWidget(self.date_merge, 2, 1)
        unione_layout.addWidget(button_merge, 3, 0, 1, 2)

        actions_layout.addWidget(self.group_modifica, 2)
        actions_layout.addWidget(self.group_divisione, 1)
        actions_layout.addWidget(self.group_unione, 1)

        main_layout.addLayout(actions_layout)

        self.label_totale = QLabel("Totale capi registrati: 0")
        self.label_totale.setStyleSheet("font-weight: 600;")
        main_layout.addWidget(self.label_totale)

        self.label_stato = QLabel("")
        self.label_stato.setStyleSheet("color: #1f5f3f;")
        main_layout.addWidget(self.label_stato)

        self._on_add_tipo_changed()
        self._set_selection_controls_enabled(False)

    def _set_selection_controls_enabled(self, enabled: bool):
        self.group_modifica.setEnabled(enabled)
        self.group_divisione.setEnabled(enabled)
        self.group_unione.setEnabled(enabled)

    def _on_toggle_merge_date(self, _checked=False):
        self.date_merge.setEnabled(self.check_merge_date.isChecked())

    def _on_add_tipo_changed(self, _index=0):
        tipo_label = self.combo_add_tipo.currentText().strip()
        uses_finalita = tipo_label in ("Bovini", "Ovini")
        uses_altro = tipo_label == "Altro"

        self.combo_add_finalita.setEnabled(uses_finalita)
        if not uses_finalita:
            self.combo_add_finalita.setCurrentText(self.PURPOSE_OPTIONS[0])

        self.input_add_altro.setEnabled(uses_altro)
        if not uses_altro:
            self.input_add_altro.clear()

    def _reset_add_form(self):
        self.input_add_group_name.clear()
        self.combo_add_tipo.setCurrentText(self.ANIMAL_TYPE_OPTIONS[0])
        self.combo_add_finalita.setCurrentText(self.PURPOSE_OPTIONS[0])
        self.input_add_altro.clear()
        self.check_add_riproduzione.setChecked(False)
        self.spin_add_capi.setValue(1)
        self._on_add_tipo_changed()

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

    def _format_riproduzione_report(self, riproduzione):
        return "Si" if bool(riproduzione) else "No"

    def _append_row(self, row_index: int, values: list[str], right_align_indexes=None):
        if right_align_indexes is None:
            right_align_indexes = []

        self.table_animali.setRowCount(row_index + 1)
        for col_index, value in enumerate(values):
            item = QTableWidgetItem(value)
            if col_index in right_align_indexes:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            else:
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.table_animali.setItem(row_index, col_index, item)

    def _selected_entry_id(self):
        row = self.table_animali.currentRow()
        if row < 0:
            return None

        item = self.table_animali.item(row, 0)
        if item is None:
            return None

        try:
            entry_id = int(item.text().strip())
        except ValueError:
            return None

        if entry_id <= 0:
            return None
        return entry_id

    def _selected_entry(self):
        entry_id = self._selected_entry_id()
        if entry_id is None:
            return None
        return self._entries_by_id.get(entry_id)

    def _load_merge_candidates(self, current_entry: dict):
        self._merge_candidates_by_label = {}
        self.combo_merge_target.blockSignals(True)
        self.combo_merge_target.clear()

        current_id = int(current_entry.get("id", 0) or 0)
        tipo_corrente = (current_entry.get("tipo_animale") or "").strip().upper()
        finalita_corrente = (current_entry.get("finalita") or "").strip().upper()
        altro_corrente = (current_entry.get("altro_label") or "").strip()

        labels_seen = set()
        for entry in sorted(
            self._entries_by_id.values(),
            key=lambda item: ((item.get("group_name") or "").strip().lower(), int(item.get("id", 0) or 0)),
        ):
            entry_id = int(entry.get("id", 0) or 0)
            if entry_id <= 0 or entry_id == current_id:
                continue

            if int(entry.get("capi", 0) or 0) <= 0:
                continue

            same_tipo = (entry.get("tipo_animale") or "").strip().upper() == tipo_corrente
            same_finalita = (entry.get("finalita") or "").strip().upper() == finalita_corrente
            same_altro = (entry.get("altro_label") or "").strip() == altro_corrente
            if not (same_tipo and same_finalita and same_altro):
                continue

            group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
            capi = int(entry.get("capi", 0) or 0)
            base_label = f"{group_name} ({format_number(capi, 0)} capi)"
            label = base_label
            if label in labels_seen:
                label = f"{base_label} [ID {entry_id}]"
            labels_seen.add(label)

            self._merge_candidates_by_label[label] = entry_id
            self.combo_merge_target.addItem(label)

        self.combo_merge_target.blockSignals(False)

    def _on_selection_changed(self):
        entry = self._selected_entry()
        if not entry:
            self.label_selected.setText("Seleziona un gruppo per modifiche.")
            self._set_selection_controls_enabled(False)
            self._merge_candidates_by_label = {}
            self.combo_merge_target.clear()
            return

        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {int(entry.get('id', 0) or 0)}"
        self.label_selected.setText(f"Selezionato: {group_name}")
        self._set_selection_controls_enabled(True)

        capi = int(entry.get("capi", 0) or 0)
        self.spin_remove_capi.setMaximum(max(capi, 1))
        self.spin_remove_capi.setValue(1)

        self.spin_add_capi.setValue(1)
        self.input_rename_group.setText(group_name)
        self.check_set_riproduzione.setChecked(bool(entry.get("riproduzione", False)))

        tipo_db = (entry.get("tipo_animale") or "").strip().upper()
        finalita_db = (entry.get("finalita") or "").strip().upper()
        finalita_view = self._format_finalita_report(finalita_db)
        if finalita_view in self.PURPOSE_OPTIONS:
            self.combo_set_finalita.setCurrentText(finalita_view)
            self.combo_set_finalita.setEnabled(True)
            self.button_set_finalita.setEnabled(True)
        else:
            self.combo_set_finalita.setCurrentText(self.PURPOSE_OPTIONS[0])
            self.combo_set_finalita.setEnabled(False)
            self.button_set_finalita.setEnabled(False)

        self.spin_split_capi.setMinimum(1)
        self.spin_split_capi.setMaximum(max(capi - 1, 1))
        self.spin_split_capi.setValue(1)
        self.group_divisione.setEnabled(capi > 1)

        self.input_split_group_name.setText("")
        self.input_merge_group_name.setText(group_name)

        self._load_merge_candidates(entry)
        if self.combo_merge_target.count() <= 0:
            self.group_unione.setEnabled(False)
        else:
            self.group_unione.setEnabled(True)

        if tipo_db in ("BOVINI", "OVINI"):
            self.check_set_riproduzione.setEnabled(True)
        else:
            self.check_set_riproduzione.setEnabled(True)

    def carica_report_animali(self, show_errors=True):
        try:
            entries = list_azienda_animali_entries(self.user_id)
        except Exception as exc:
            if show_errors:
                QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        self._entries_by_id = {int(entry.get("id", 0) or 0): entry for entry in entries}

        self.table_animali.setRowCount(0)

        totale_capi = 0
        for row_index, entry in enumerate(entries):
            entry_id = int(entry.get("id", 0) or 0)
            group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
            tipo_text = self._format_tipo_animale_report(entry.get("tipo_animale", ""), entry.get("altro_label", ""))
            finalita_text = self._format_finalita_report(entry.get("finalita", ""))
            riproduzione_text = self._format_riproduzione_report(entry.get("riproduzione", False))
            capi = int(entry.get("capi", 0) or 0)
            totale_capi += capi

            self._append_row(
                row_index,
                [
                    str(entry_id),
                    group_name,
                    tipo_text,
                    finalita_text,
                    riproduzione_text,
                    format_number(capi, 0),
                ],
                right_align_indexes=[5],
            )

        self.label_totale.setText(f"Totale capi registrati: {format_number(totale_capi, 0)}")

        if self.table_animali.rowCount() <= 0:
            self.label_selected.setText("Nessun gruppo registrato.")
            self._set_selection_controls_enabled(False)
            return

        self.table_animali.selectRow(0)
        self._on_selection_changed()

    def aggiungi_animale(self):
        group_name = self.input_add_group_name.text().strip()
        if not group_name:
            QMessageBox.critical(self, "Errore", "Inserisci un nome gruppo.")
            return

        tipo_label = self.combo_add_tipo.currentText().strip()
        tipo_db = self.ANIMAL_TYPE_TO_DB.get(tipo_label, "")
        if not tipo_db:
            QMessageBox.critical(self, "Errore", "Seleziona un tipo animale valido.")
            return

        capi = int(self.spin_add_capi.value() or 0)
        if capi <= 0:
            QMessageBox.critical(self, "Errore", "Numero capi non valido.")
            return

        finalita_db = ""
        if tipo_label in ("Bovini", "Ovini"):
            finalita_label = self.combo_add_finalita.currentText().strip()
            finalita_db = self.PURPOSE_TO_DB.get(finalita_label, "")
            if not finalita_db:
                QMessageBox.critical(self, "Errore", "Seleziona una destinazione valida.")
                return

        altro_label = self.input_add_altro.text().strip()
        if tipo_label == "Altro" and not altro_label:
            QMessageBox.critical(self, "Errore", "Specifica il tipo animale per la voce Altro.")
            return

        try:
            add_azienda_animale_entry(
                user_id=self.user_id,
                tipo_animale=tipo_db,
                capi=capi,
                finalita=finalita_db,
                altro_label=altro_label,
                group_name=group_name,
                riproduzione=bool(self.check_add_riproduzione.isChecked()),
            )
        except (Exception, ValueError) as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return

        self.label_stato.setText("Animale registrato correttamente.")
        self.carica_report_animali(show_errors=False)
        self._reset_add_form()

    def rimuovi_capi_selezionati(self):
        entry = self._selected_entry()
        if not entry:
            QMessageBox.warning(self, "Selezione richiesta", "Seleziona una categoria dal report animali.")
            return

        entry_id = int(entry.get("id", 0) or 0)
        capi_da_rimuovere = int(self.spin_remove_capi.value() or 0)

        try:
            categoria_azzerata = remove_azienda_animale_capi(self.user_id, entry_id, capi_da_rimuovere)
        except (Exception, ValueError) as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return

        if categoria_azzerata:
            self.label_stato.setText("Rimozione completata: categoria azzerata e rimossa.")
        else:
            self.label_stato.setText(
                f"Rimozione completata: rimossi {format_number(capi_da_rimuovere, 0)} capi dal gruppo selezionato."
            )

        self.carica_report_animali(show_errors=False)

    def aggiungi_capi_selezionati(self):
        entry = self._selected_entry()
        if not entry:
            QMessageBox.warning(self, "Selezione richiesta", "Seleziona una categoria dal report animali.")
            return

        entry_id = int(entry.get("id", 0) or 0)
        capi_attuali = int(entry.get("capi", 0) or 0)
        capi_da_aggiungere = int(self.spin_add_capi.value() or 0)
        nuovo_capi = capi_attuali + capi_da_aggiungere

        try:
            categoria_rimossa = set_azienda_animale_capi(self.user_id, entry_id, nuovo_capi)
        except (Exception, ValueError) as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return

        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
        if categoria_rimossa:
            self.label_stato.setText(f"Categoria rimossa: {group_name} (nuovo valore 0).")
        else:
            self.label_stato.setText(
                f"Aggiunta completata: {group_name} +{format_number(capi_da_aggiungere, 0)} capi "
                f"(totale {format_number(nuovo_capi, 0)})."
            )

        self.carica_report_animali(show_errors=False)

    def rinomina_gruppo_selezionato(self):
        entry = self._selected_entry()
        if not entry:
            QMessageBox.warning(self, "Selezione richiesta", "Seleziona una categoria dal report animali.")
            return

        entry_id = int(entry.get("id", 0) or 0)
        nuovo_nome = self.input_rename_group.text().strip()
        if not nuovo_nome:
            QMessageBox.critical(self, "Errore", "Inserisci un nome gruppo valido.")
            return

        nome_attuale = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"

        try:
            nome_aggiornato = set_azienda_animale_group_name(self.user_id, entry_id, nuovo_nome)
        except (Exception, ValueError) as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return

        if nome_aggiornato:
            self.label_stato.setText(f"Nome gruppo aggiornato: {nome_attuale} -> {nuovo_nome}.")
        else:
            self.label_stato.setText(f"Nome gruppo invariato: {nuovo_nome}.")

        self.carica_report_animali(show_errors=False)

    def modifica_destinazione_selezionata(self):
        entry = self._selected_entry()
        if not entry:
            QMessageBox.warning(self, "Selezione richiesta", "Seleziona una categoria dal report animali.")
            return

        entry_id = int(entry.get("id", 0) or 0)
        destinazione_label = self.combo_set_finalita.currentText().strip()
        finalita_db = self.PURPOSE_TO_DB.get(destinazione_label, "")
        if not finalita_db:
            QMessageBox.critical(self, "Errore", "Seleziona una destinazione valida.")
            return

        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"

        try:
            categoria_unificata = set_azienda_animale_finalita(self.user_id, entry_id, finalita_db)
        except (Exception, ValueError) as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return

        if categoria_unificata:
            self.label_stato.setText(
                f"Destinazione aggiornata per {group_name}: categoria unificata con destinazione {destinazione_label}."
            )
        else:
            self.label_stato.setText(f"Destinazione aggiornata per {group_name}: {destinazione_label}.")

        self.carica_report_animali(show_errors=False)

    def modifica_riproduzione_selezionata(self):
        entry = self._selected_entry()
        if not entry:
            QMessageBox.warning(self, "Selezione richiesta", "Seleziona una categoria dal report animali.")
            return

        entry_id = int(entry.get("id", 0) or 0)
        riproduzione_attiva = bool(self.check_set_riproduzione.isChecked())
        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"

        try:
            aggiornata = set_azienda_animale_riproduzione(self.user_id, entry_id, riproduzione_attiva)
        except (Exception, ValueError) as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return

        if aggiornata:
            stato_label = "attivata" if riproduzione_attiva else "disattivata"
            self.label_stato.setText(f"Riproduzione {stato_label} per {group_name}.")
        else:
            self.label_stato.setText(f"Nessuna modifica: riproduzione invariata per {group_name}.")

        self.carica_report_animali(show_errors=False)

    def rimuovi_gruppo_selezionato(self):
        entry = self._selected_entry()
        if not entry:
            QMessageBox.warning(self, "Selezione richiesta", "Seleziona una categoria dal report animali.")
            return

        entry_id = int(entry.get("id", 0) or 0)
        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"

        conferma = QMessageBox.question(
            self,
            "Conferma rimozione",
            f"Vuoi rimuovere tutta la categoria '{group_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if conferma != QMessageBox.Yes:
            return

        try:
            delete_azienda_animale_entry(self.user_id, entry_id)
        except (Exception, ValueError) as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return

        self.label_stato.setText(f"Categoria rimossa: {group_name}.")
        self.carica_report_animali(show_errors=False)

    def dividi_gruppo_selezionato(self):
        entry = self._selected_entry()
        if not entry:
            QMessageBox.warning(self, "Selezione richiesta", "Seleziona una categoria dal report animali.")
            return

        entry_id = int(entry.get("id", 0) or 0)
        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
        capi_totali = int(entry.get("capi", 0) or 0)

        capi_nuovo_gruppo = int(self.spin_split_capi.value() or 0)
        if capi_nuovo_gruppo <= 0 or capi_nuovo_gruppo >= capi_totali:
            QMessageBox.critical(
                self,
                "Errore",
                "Il nuovo gruppo deve avere almeno 1 capo e meno capi del gruppo selezionato.",
            )
            return

        nuovo_nome = self.input_split_group_name.text().strip()
        if not nuovo_nome:
            QMessageBox.critical(self, "Errore", "Inserisci il nome del nuovo gruppo.")
            return

        capi_restanti_preview = capi_totali - capi_nuovo_gruppo
        conferma = QMessageBox.question(
            self,
            "Conferma divisione",
            "Riepilogo divisione:\n"
            f"- Gruppo attuale: {group_name} ({format_number(capi_totali, 0)} capi)\n"
            f"- Nuovo gruppo: {nuovo_nome} ({format_number(capi_nuovo_gruppo, 0)} capi)\n"
            f"- Capi restanti nel gruppo attuale: {format_number(capi_restanti_preview, 0)}\n\n"
            "Confermi l'operazione?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if conferma != QMessageBox.Yes:
            return

        try:
            capi_restanti = split_azienda_animale_group(
                self.user_id,
                entry_id,
                capi_nuovo_gruppo,
                nuovo_nome,
            )
        except (Exception, ValueError) as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return

        self.label_stato.setText(
            "Divisione completata: "
            f"{group_name} ora ha {format_number(capi_restanti, 0)} capi, "
            f"nuovo gruppo '{nuovo_nome}' con {format_number(capi_nuovo_gruppo, 0)} capi."
        )
        self.carica_report_animali(show_errors=False)

    def unisci_gruppi_selezionati(self):
        entry = self._selected_entry()
        if not entry:
            QMessageBox.warning(self, "Selezione richiesta", "Seleziona una categoria dal report animali.")
            return

        entry_id = int(entry.get("id", 0) or 0)
        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
        capi_corrente = int(entry.get("capi", 0) or 0)

        scelta = self.combo_merge_target.currentText().strip()
        entry_secondario_id = int(self._merge_candidates_by_label.get(scelta, 0) or 0)
        if entry_secondario_id <= 0:
            QMessageBox.critical(self, "Errore", "Seleziona un gruppo compatibile da unire.")
            return

        secondario = self._entries_by_id.get(entry_secondario_id)
        if not secondario:
            QMessageBox.critical(self, "Errore", "Il gruppo secondario non e piu disponibile.")
            return

        group_name_secondario = (secondario.get("group_name") or "").strip() or f"Gruppo {entry_secondario_id}"
        capi_secondario = int(secondario.get("capi", 0) or 0)

        nuovo_nome = self.input_merge_group_name.text().strip()
        if not nuovo_nome:
            QMessageBox.critical(self, "Errore", "Inserisci il nome del gruppo unificato.")
            return

        merge_date_db = None
        merge_date_label = "Data odierna"
        if self.check_merge_date.isChecked():
            merge_date_db = self.date_merge.date().toString("yyyy-MM-dd")
            merge_date_label = self.date_merge.date().toString("dd/MM/yyyy")

        conferma = QMessageBox.question(
            self,
            "Conferma unione",
            "Riepilogo unione:\n"
            f"- Gruppo 1: {group_name} ({format_number(capi_corrente, 0)} capi)\n"
            f"- Gruppo 2: {group_name_secondario} ({format_number(capi_secondario, 0)} capi)\n"
            f"- Nuovo nome gruppo: {nuovo_nome}\n"
            f"- Data unione: {merge_date_label}\n"
            f"- Totale capi gruppo unificato: {format_number(capi_corrente + capi_secondario, 0)}\n\n"
            "Confermi l'operazione?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if conferma != QMessageBox.Yes:
            return

        try:
            capi_totali = merge_azienda_animale_groups(
                self.user_id,
                entry_id,
                entry_secondario_id,
                nuovo_nome,
                merge_date=merge_date_db,
            )
        except (Exception, ValueError) as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return

        data_effettiva = merge_date_label if merge_date_db else datetime.now().strftime("%d/%m/%Y")
        self.label_stato.setText(
            "Unione completata: "
            f"{group_name} + {group_name_secondario} -> {nuovo_nome} "
            f"({format_number(capi_totali, 0)} capi), data unione {data_effettiva}."
        )
        self.carica_report_animali(show_errors=False)
