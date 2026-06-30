from datetime import datetime

from PySide6.QtCore import QDate, Qt, QTimer
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
    QListWidget,
    QListWidgetItem,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QDialog,          
    QFileDialog,
    QSizePolicy
)

from app_utils import format_number, TabellaIsolata
from models import db, CapoAnimale, AziendaAnimaliDettaglio
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
    sposta_capo_animale
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
        self._assicura_gruppi_archivio()
        self.carica_report_animali(show_errors=False)


    def _assicura_gruppi_archivio(self):
        with db.atomic():
            venduti = AziendaAnimaliDettaglio.get_or_none((AziendaAnimaliDettaglio.user == self.user_id) & (AziendaAnimaliDettaglio.tipo_animale == 'ARCHIVIO') & (AziendaAnimaliDettaglio.finalita == 'VENDUTI'))
            if not venduti:
                venduti = AziendaAnimaliDettaglio.create(user=self.user_id, tipo_animale='ARCHIVIO', finalita='VENDUTI', group_name='Archivio Capi Venduti', capi=0, created_at=datetime.now().isoformat(), updated_at=datetime.now().isoformat())
            self.archivio_venduti_id = venduti.id
            
            deceduti = AziendaAnimaliDettaglio.get_or_none((AziendaAnimaliDettaglio.user == self.user_id) & (AziendaAnimaliDettaglio.tipo_animale == 'ARCHIVIO') & (AziendaAnimaliDettaglio.finalita == 'DECEDUTI'))
            if not deceduti:
                deceduti = AziendaAnimaliDettaglio.create(user=self.user_id, tipo_animale='ARCHIVIO', finalita='DECEDUTI', group_name='Archivio Capi Deceduti', capi=0, created_at=datetime.now().isoformat(), updated_at=datetime.now().isoformat())
            self.archivio_deceduti_id = deceduti.id

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

        self.spin_capi_nuovo_gruppo = QSpinBox(self)
        self.spin_capi_nuovo_gruppo.setMinimum(1)
        self.spin_capi_nuovo_gruppo.setMaximum(1_000_000_000)
        self.spin_capi_nuovo_gruppo.setValue(1)

        add_layout.addWidget(QLabel("Nome gruppo:"), 0, 0)
        add_layout.addWidget(self.input_add_group_name, 0, 1)
        add_layout.addWidget(QLabel("Tipo animale:"), 0, 2)
        add_layout.addWidget(self.combo_add_tipo, 0, 3)

        add_layout.addWidget(QLabel("Destinazione:"), 1, 0)
        add_layout.addWidget(self.combo_add_finalita, 1, 1)
        add_layout.addWidget(QLabel("Specifica tipo:"), 1, 2)
        add_layout.addWidget(self.input_add_altro, 1, 3)

        add_layout.addWidget(QLabel("Numero capi:"), 2, 0)
        add_layout.addWidget(self.spin_capi_nuovo_gruppo, 2, 1)
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

        # TABELLA GRUPPI
        self.table_animali = TabellaIsolata(0, 6, self)
        self.table_animali.setHorizontalHeaderLabels(["ID", "Gruppo", "Tipo", "Destinazione", "Riproduzione", "Capi"])
        self.table_animali.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_animali.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_animali.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_animali.setAlternatingRowColors(True)
        self.table_animali.verticalHeader().setVisible(False)
        self.table_animali.itemSelectionChanged.connect(self._on_selection_changed)

        # SOVRASCRITTURA TABELLA ISOLATA PER IMPEDIRE LO STRETCH E LO SPAZIO BIANCO
        self.table_animali.setMinimumHeight(0)
        self.table_animali.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table_animali.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.table_animali.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        header = self.table_animali.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)

        main_layout.addWidget(self.table_animali)

        self.label_selected = QLabel("Seleziona un gruppo per modifiche.")
        self.label_selected.setStyleSheet("font-weight: 600;")
        main_layout.addWidget(self.label_selected)

        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(10)

        
        # BOTTONE GESTIONE CAPI
        self.btn_gestisci_singoli = QPushButton("🐄 Gestisci singoli capi")
        self.btn_gestisci_singoli.setStyleSheet("background-color: #8e44ad; color: white; font-weight: bold; padding: 8px; border-radius: 5px;")
        self.btn_gestisci_singoli.clicked.connect(self.apri_gestione_singoli)
        self.btn_gestisci_singoli.setEnabled(False)
        main_layout.addWidget(self.btn_gestisci_singoli)

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


        # SPINTA VERSO L'ALTO
        main_layout.addStretch()

        self._on_add_tipo_changed()
        self._set_selection_controls_enabled(False)

    # ----------------------------------------------------
    # METODI PER L'ALTEZZA DINAMICA DELLA TABELLA
    # ----------------------------------------------------
    def _adatta_altezza_tabella(self):
        def _resize():
            try:
                header_h = self.table_animali.horizontalHeader().height()
                if header_h < 20: 
                    header_h = 32
                
                rows_h = 0
                for i in range(self.table_animali.rowCount()):
                    h = self.table_animali.rowHeight(i)
                    rows_h += h if h > 0 else 35
                    
                self.table_animali.setFixedHeight(header_h + rows_h + 2)
            except Exception:
                pass
        
        # Usando il timer aspettiamo 10ms in modo che Qt abbia disegnato la UI per calcolare perfettamente
        QTimer.singleShot(10, _resize)

    def _mostra_riga_vuota_tabella(self):
        self.table_animali.clearSpans()
        self.table_animali.setRowCount(1)
        item_empty = QTableWidgetItem("Nessun gruppo presente attualmente.")
        item_empty.setTextAlignment(Qt.AlignCenter)
        
        from PySide6.QtGui import QColor
        item_empty.setForeground(QColor("#7f8c8d"))
        item_empty.setFlags(Qt.ItemIsEnabled)
        self.table_animali.setItem(0, 0, item_empty)
        self.table_animali.setSpan(0, 0, 1, self.table_animali.columnCount())
        
        # Imponiamo che l'altezza di questa riga sia compatta e non si espanda
        self.table_animali.setRowHeight(0, 45)
        self._adatta_altezza_tabella()


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
        self.spin_capi_nuovo_gruppo.setValue(1)
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
            self.btn_gestisci_singoli.setEnabled(False)
            self._merge_candidates_by_label = {}
            self.combo_merge_target.clear()
            return

        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {int(entry.get('id', 0) or 0)}"
        tipo_db = (entry.get("tipo_animale") or "").strip().upper()
        
        # --- PROTEZIONE ARCHIVI ---
        if tipo_db == 'ARCHIVIO':
            self.label_selected.setText(f"Archivio Selezionato: {group_name} (Sola lettura)")
            self._set_selection_controls_enabled(False)
            self.btn_gestisci_singoli.setEnabled(True)
            self._merge_candidates_by_label = {}
            self.combo_merge_target.clear()
            return
        
        self.label_selected.setText(f"Selezionato: {group_name}")
        self._set_selection_controls_enabled(True)
        self.btn_gestisci_singoli.setEnabled(True)

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

        self.table_animali.clearSpans()
        self.table_animali.setRowCount(0)
        totale_capi = 0

        # Se non ci sono dati, chiamiamo la riga vuota
        if not entries:
            self._mostra_riga_vuota_tabella()
            self.label_totale.setText("Totale capi registrati: 0")
            self.label_selected.setText("Nessun gruppo registrato.")
            self._set_selection_controls_enabled(False)
            if hasattr(self, 'btn_gestisci_singoli'):
                self.btn_gestisci_singoli.setEnabled(False)
            return

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
            # Forza l'altezza della riga per mantenerla compatta
            self.table_animali.setRowHeight(row_index, 35)

        self._adatta_altezza_tabella()

        self.label_totale.setText(f"Totale capi registrati: {format_number(totale_capi, 0)}")

        self.table_animali.selectRow(0)
        self._on_selection_changed()

    def aggiungi_animale(self):
        import uuid # <--- Aggiunto per le stringhe univoche
        group_name = self.input_add_group_name.text().strip()
        if not group_name:
            QMessageBox.critical(self, "Errore", "Inserisci un nome gruppo.")
            return

        tipo_label = self.combo_add_tipo.currentText().strip()
        tipo_db = self.ANIMAL_TYPE_TO_DB.get(tipo_label, "")
        if not tipo_db:
            QMessageBox.critical(self, "Errore", "Seleziona un tipo animale valido.")
            return

        capi = int(self.spin_capi_nuovo_gruppo.value() or 0)
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
            nuovo_gruppo_id = add_azienda_animale_entry(
                user_id=self.user_id,
                tipo_animale=tipo_db,
                capi=capi,
                finalita=finalita_db,
                altro_label=altro_label,
                group_name=group_name,
                riproduzione=bool(self.check_add_riproduzione.isChecked()),
            )
            
            # --- AUTO TAGGING: Generazione dei singoli capi ---
            from models import CapoAnimale, db
            with db.atomic():
                now_date = datetime.now().strftime("%Y-%m-%d")
                capi_da_inserire = [{
                    'user': self.user_id, 'gruppo': nuovo_gruppo_id, 
                    'marca_auricolare': f"AUTO-{nuovo_gruppo_id}-{i+1}", 
                    'data_ingresso': now_date
                } for i in range(capi)]
                CapoAnimale.insert_many(capi_da_inserire).execute()
                
        except (Exception, ValueError) as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return

        self.label_stato.setText("Animale registrato correttamente e singoli capi auto-generati.")
        self.carica_report_animali(show_errors=False)
        self._reset_add_form()


    def rimuovi_capi_selezionati(self):
        entry = self._selected_entry()
        if not entry:
            QMessageBox.warning(self, "Selezione richiesta", "Seleziona una categoria dal report animali.")
            return

        entry_id = int(entry.get("id", 0) or 0)
        capi_da_rimuovere = int(self.spin_remove_capi.value() or 0)

        # --- Finestra di selezione capi da eliminare ---
        dialog = SelezioneCapiDaRimuovereDialog(self.user_id, entry_id, capi_da_rimuovere, self)
        if dialog.exec() != QDialog.Accepted:
            return # L'utente ha annullato
            
        capi_selezionati = dialog.capi_selezionati_ids

        try:
            with db.atomic():
                # ELIMINAZIONE FISICA DEI CAPI SELEZIONATI
                CapoAnimale.delete().where(CapoAnimale.id << capi_selezionati).execute()
                # Riduciamo il contatore del gruppo
                categoria_azzerata = remove_azienda_animale_capi(self.user_id, entry_id, capi_da_rimuovere)
        except (Exception, ValueError) as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return

        if categoria_azzerata:
            self.label_stato.setText("Rimozione completata: categoria azzerata e rimossa.")
        else:
            self.label_stato.setText(
                f"Rimozione completata: eliminati {format_number(capi_da_rimuovere, 0)} capi e i loro dati."
            )

        self.carica_report_animali(show_errors=False)

    def aggiungi_capi_selezionati(self):
        import uuid # <--- Aggiunto per le stringhe univoche
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
            
            # --- AUTO TAGGING DEI NUOVI CAPI ---
            from models import CapoAnimale, db
            with db.atomic():
                now_date = datetime.now().strftime("%Y-%m-%d")
                capi_da_inserire = [{
                    'user': self.user_id, 'gruppo': entry_id, 
                    'marca_auricolare': f"AUTO-ADD-{uuid.uuid4().hex[:5].upper()}", 
                    'data_ingresso': now_date
                } for i in range(capi_da_aggiungere)]
                CapoAnimale.insert_many(capi_da_inserire).execute()
                
        except (Exception, ValueError) as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return

        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
        self.label_stato.setText(f"Aggiunta completata: +{format_number(capi_da_aggiungere, 0)} capi (auto-generati).")
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
        capi_attivi = int(entry.get("capi", 0) or 0)

        # SE IL GRUPPO CONTIENE ANIMALI
        if capi_attivi > 0:
            scelta = QMessageBox.question(
                self,
                "Gruppo non vuoto",
                f"Il gruppo '{group_name}' contiene ancora {capi_attivi} capi attivi.\n"
                "Vuoi spostare questi capi in un altro gruppo prima di eliminare?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes
            )
            
            if scelta == QMessageBox.Cancel:
                return
                
            if scelta == QMessageBox.Yes:
                # Cerca gruppi compatibili per lo spostamento
                tipo_animale = entry.get("tipo_animale", "")
                gruppi_compatibili = list(AziendaAnimaliDettaglio.select().where(
                    (AziendaAnimaliDettaglio.user == self.user_id) &
                    (AziendaAnimaliDettaglio.tipo_animale == tipo_animale) &
                    (AziendaAnimaliDettaglio.id != entry_id)
                ))
                
                if not gruppi_compatibili:
                    QMessageBox.warning(self, "Nessun gruppo", "Non ci sono altri gruppi compatibili per questo tipo di animale.\nCrea prima un nuovo gruppo o procedi con l'eliminazione definitiva.")
                    return
                
                # Finestra di dialogo rapida per la scelta del gruppo di destinazione
                dialog = QDialog(self)
                dialog.setWindowTitle("Seleziona gruppo di destinazione")
                layout = QVBoxLayout(dialog)
                layout.addWidget(QLabel("Seleziona in quale gruppo salvare i capi prima di eliminare:"))
                combo = QComboBox()
                for g in gruppi_compatibili:
                    nome = g.group_name or f"Gruppo {g.id}"
                    combo.addItem(f"{nome} ({g.finalita})", g.id)
                layout.addWidget(combo)
                
                btn_box = QHBoxLayout()
                btn_ok = QPushButton("Sposta ed Elimina Gruppo")
                btn_ok.setStyleSheet("background-color: #e67e22; color: white; font-weight: bold; padding: 5px;")
                btn_ok.clicked.connect(dialog.accept)
                btn_annulla = QPushButton("Annulla")
                btn_annulla.clicked.connect(dialog.reject)
                btn_box.addWidget(btn_ok)
                btn_box.addWidget(btn_annulla)
                layout.addLayout(btn_box)
                
                if dialog.exec() == QDialog.Accepted:
                    dest_id = combo.currentData()
                    # Sposta tutti i capi attivi uno ad uno salvando i loro dati
                    capi_da_spostare = CapoAnimale.select().where((CapoAnimale.gruppo == entry_id) & (CapoAnimale.stato == 'ATTIVO'))
                    for capo in capi_da_spostare:
                        sposta_capo_animale(self.user_id, capo.id, dest_id)
                    
                    # Ora che è vuoto, elimina il gruppo
                    delete_azienda_animale_entry(self.user_id, entry_id)
                    self.label_stato.setText(f"Capi messi in salvo ed eliminata categoria: {group_name}.")
                    self.carica_report_animali(show_errors=False)
                return
            
            elif scelta == QMessageBox.No:
                # Vuole cancellare tutto senza salvare gli animali
                conferma_finale = QMessageBox.question(
                    self,
                    "Conferma eliminazione definitiva",
                    f"ATTENZIONE: Stai per eliminare IRRIMEDIABILMENTE il gruppo '{group_name}' "
                    f"e tutti i {capi_attivi} capi al suo interno (inclusi i loro dati di latte, carne e costi).\n\nSei assolutamente sicuro di voler procedere?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if conferma_finale != QMessageBox.Yes: return
                
        else:
            # GRUPPO GIA' VUOTO, conferma semplice
            conferma = QMessageBox.question(
                self,
                "Conferma rimozione",
                f"Vuoi eliminare il gruppo vuoto '{group_name}'?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if conferma != QMessageBox.Yes: return

        # Esecuzione eliminazione
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
            QMessageBox.critical(self, "Errore", "Il gruppo secondario non è più disponibile.")
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

    # ----------------------------------------------------
    # METODO APERTURA GESTIONE SINGOLI CAPI
    # ----------------------------------------------------
    def apri_gestione_singoli(self):
        riga = self.table_animali.currentRow()
        if riga < 0: 
            return QMessageBox.warning(self, "Attenzione", "Seleziona un gruppo dalla tabella.")
        
        gruppo_id = int(self.table_animali.item(riga, 0).text())
        nome_gruppo = self.table_animali.item(riga, 1).text()
        
        try:
            dialog = GestioneCapiDialog(self.user_id, gruppo_id, nome_gruppo, self)
            dialog.exec()
            # Ricarica dopo la chiusura
            self.carica_report_animali(show_errors=False)
        except Exception as e:
            import traceback
            QMessageBox.critical(self, "Errore di Sistema", f"Impossibile aprire la finestra:\n{e}\n\n{traceback.format_exc()}")


class SelezioneCapiDaRimuovereDialog(QDialog):
    def __init__(self, user_id, gruppo_id, capi_da_rimuovere, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.gruppo_id = gruppo_id
        self.capi_da_rimuovere = capi_da_rimuovere
        self.capi_selezionati_ids = []
        
        self.setWindowTitle(f"Seleziona i {capi_da_rimuovere} capi da eliminare")
        self.resize(500, 600)
        self.setModal(True)
        self._build_ui()
        self.carica_capi()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        info = QLabel(
            f"Hai indicato la rimozione di <b>{self.capi_da_rimuovere} capi</b>.<br>"
            "Seleziona esattamente quali animali eliminare.<br><br>"
            "<b style='color:#dc3545;'>ATTENZIONE: L'eliminazione cancellerà "
            "irrimediabilmente tutti i dati produttivi e finanziari di questi animali!</b>"
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        
        self.list_capi = QListWidget()
        self.list_capi.setSelectionMode(QAbstractItemView.MultiSelection)
        self.list_capi.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self.list_capi)
        
        self.btn_conferma = QPushButton(f"Conferma Eliminazione Definitiva (0/{self.capi_da_rimuovere})")
        self.btn_conferma.setStyleSheet("background-color: #dc3545; color: white; font-weight: bold; padding: 10px;")
        self.btn_conferma.setEnabled(False)
        self.btn_conferma.clicked.connect(self._conferma)
        layout.addWidget(self.btn_conferma)

    def carica_capi(self):
        from models import CapoAnimale
        capi = CapoAnimale.select().where((CapoAnimale.gruppo == self.gruppo_id) & (CapoAnimale.stato == 'ATTIVO'))
        for capo in capi:
            item = QListWidgetItem(f"ID: {capo.marca_auricolare}")
            item.setData(Qt.UserRole, capo.id)
            self.list_capi.addItem(item)

    def _on_selection(self):
        count = len(self.list_capi.selectedItems())
        self.btn_conferma.setText(f"Conferma Eliminazione Definitiva ({count}/{self.capi_da_rimuovere})")
        self.btn_conferma.setEnabled(count == self.capi_da_rimuovere)

    def _conferma(self):
        self.capi_selezionati_ids = [item.data(Qt.UserRole) for item in self.list_capi.selectedItems()]
        self.accept()

# ==========================================================
# CLASSE DIALOGO PER GESTIONE SINGOLI CAPI (CON SPOSTAMENTO)
# ==========================================================

class GestioneCapiDialog(QDialog):
    def __init__(self, user_id, gruppo_id, nome_gruppo, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.gruppo_id = gruppo_id
        self.setWindowTitle(f"Gestione Capi: {nome_gruppo}")
        self.resize(700, 550)
        self.setModal(True)
        
        self._build_ui()
        self.carica_capi()
        self.carica_gruppi_destinazione()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        
        row_inserimento = QHBoxLayout()
        self.input_marca = QLineEdit(self)
        self.input_marca.setPlaceholderText("Marca Auricolare (es. IT00123...)")
        row_inserimento.addWidget(self.input_marca)
        
        btn_aggiungi = QPushButton("➕ Aggiungi Singolo")
        btn_aggiungi.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold;")
        btn_aggiungi.clicked.connect(self.aggiungi_capo_singolo)
        row_inserimento.addWidget(btn_aggiungi)
        
        btn_importa = QPushButton("📄 Importa da TXT")
        btn_importa.setStyleSheet("background-color: #3498db; color: white; font-weight: bold;")
        btn_importa.clicked.connect(self.importa_da_txt)
        row_inserimento.addWidget(btn_importa)
        layout.addLayout(row_inserimento)
        
        self.table_capi = QTableWidget(0, 6)
        self.table_capi.setHorizontalHeaderLabels(["ID (Marca)", "Stato", "Data Ingresso", "Media Latte", "Costi", "Ricavi"])
        self.table_capi.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_capi.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_capi.setSelectionMode(QAbstractItemView.ExtendedSelection) 
        self.table_capi.setAlternatingRowColors(True)
        
        # --- NUOVO: Abilita il salvataggio automatico quando modifichi l'ID ---
        self.table_capi.itemChanged.connect(self.salva_modifica_marca)
        
        layout.addWidget(self.table_capi)
        
        row_azioni = QHBoxLayout()
        row_azioni.addWidget(QLabel("Imposta stato capo/i selezionato/i:"))
        self.combo_stati = QComboBox()
        self.combo_stati.addItems(['ATTIVO', 'VENDUTO_VIVO', 'VENDUTO_CARNE', 'DECEDUTO'])
        row_azioni.addWidget(self.combo_stati)
        
        btn_aggiorna_stato = QPushButton("Aggiorna Stato")
        btn_aggiorna_stato.clicked.connect(self.aggiorna_stato_capo)
        row_azioni.addWidget(btn_aggiorna_stato)
        layout.addLayout(row_azioni)
        
        row_sposta = QHBoxLayout()
        row_sposta.addWidget(QLabel("Sposta capo/i in:"))
        self.combo_destinazione = QComboBox()
        row_sposta.addWidget(self.combo_destinazione, stretch=1)
        
        btn_sposta = QPushButton("➡️ Sposta")
        btn_sposta.setStyleSheet("background-color: #e67e22; color: white; font-weight: bold;")
        btn_sposta.clicked.connect(self.esegui_spostamento)
        row_sposta.addWidget(btn_sposta)
        layout.addLayout(row_sposta)

    def carica_gruppi_destinazione(self):
        gruppo_attuale = AziendaAnimaliDettaglio.get_or_none(id=self.gruppo_id)
        if not gruppo_attuale: return
        
        # Carica solo i gruppi dello STESSO TIPO animale ed escludi quello corrente
        gruppi = list(AziendaAnimaliDettaglio.select().where(
            (AziendaAnimaliDettaglio.user == self.user_id) &
            (AziendaAnimaliDettaglio.tipo_animale == gruppo_attuale.tipo_animale) &
            (AziendaAnimaliDettaglio.id != self.gruppo_id)
        ).order_by(AziendaAnimaliDettaglio.group_name))
        
        self.combo_destinazione.clear()
        for g in gruppi:
            nome = g.group_name or f"Gruppo {g.id}"
            self.combo_destinazione.addItem(f"{nome} ({g.finalita})", g.id)

    def carica_capi(self):
        # Blocca i segnali mentre popola la tabella per evitare finti salvataggi
        self.table_capi.blockSignals(True)
        self.table_capi.setRowCount(0)
        
        from models import CapoAnimale
        capi = list(CapoAnimale.select().where(
            (CapoAnimale.gruppo == self.gruppo_id) & (CapoAnimale.user == self.user_id)
        ).order_by(CapoAnimale.stato, CapoAnimale.id.desc()))
        
        for row_idx, capo in enumerate(capi):
            self.table_capi.insertRow(row_idx)
            
            # COLONNA 0: ID Marca (L'UNICA CHE L'UTENTE PUÒ MODIFICARE A MANO)
            item_marca = QTableWidgetItem(capo.marca_auricolare)
            item_marca.setData(Qt.UserRole, capo.id) 
            self.table_capi.setItem(row_idx, 0, item_marca)
            
            # COLONNA 1: Stato (Sola Lettura)
            item_stato = QTableWidgetItem(capo.stato)
            item_stato.setFlags(item_stato.flags() & ~Qt.ItemIsEditable)
            self.table_capi.setItem(row_idx, 1, item_stato)
            
            # COLONNA 2: Data Ingresso (Sola Lettura)
            item_data = QTableWidgetItem(capo.data_ingresso or "-")
            item_data.setFlags(item_data.flags() & ~Qt.ItemIsEditable)
            self.table_capi.setItem(row_idx, 2, item_data)
            
            # --- VALORI ECONOMICI E PRODUTTIVI ---
            media_latte = getattr(capo, 'media_litri_latte', 0.0) or 0.0
            costi = getattr(capo, 'costi_accumulati', 0.0) or 0.0
            ricavi = getattr(capo, 'ricavi_accumulati', 0.0) or 0.0
            
            # COLONNA 3: Media Latte (Sola Lettura)
            item_latte = QTableWidgetItem(f"{media_latte:.2f} L/g" if media_latte > 0 else "-")
            item_latte.setFlags(item_latte.flags() & ~Qt.ItemIsEditable)
            self.table_capi.setItem(row_idx, 3, item_latte)
            
            # COLONNA 4: Costi (Sola Lettura)
            item_costi = QTableWidgetItem(f"€ {costi:.2f}" if costi > 0 else "-")
            item_costi.setFlags(item_costi.flags() & ~Qt.ItemIsEditable)
            self.table_capi.setItem(row_idx, 4, item_costi)
            
            # COLONNA 5: Ricavi (Sola Lettura)
            item_ricavi = QTableWidgetItem(f"€ {ricavi:.2f}" if ricavi > 0 else "-")
            item_ricavi.setFlags(item_ricavi.flags() & ~Qt.ItemIsEditable)
            self.table_capi.setItem(row_idx, 5, item_ricavi)
            
            # Colora di grigio i capi non attivi
            if capo.stato != 'ATTIVO':
                from PySide6.QtGui import QColor
                for col in range(6):
                    item = self.table_capi.item(row_idx, col)
                    if item:
                        item.setForeground(QColor("#7f8c8d"))
                        
        # Riattiva i segnali terminato il caricamento
        self.table_capi.blockSignals(False)


    def salva_modifica_marca(self, item):
        # Controlla se la cella modificata è quella dell'ID (colonna 0)
        if item.column() == 0:
            capo_id = item.data(Qt.UserRole)
            nuova_marca = item.text().strip().upper()
            
            if not nuova_marca: return
            
            try:
                from models import CapoAnimale
                # Salva il nuovo nome sul database
                CapoAnimale.update(marca_auricolare=nuova_marca).where(CapoAnimale.id == capo_id).execute()
                
                # Forza il testo in maiuscolo sulla tabella visivamente
                self.table_capi.blockSignals(True)
                item.setText(nuova_marca)
                self.table_capi.blockSignals(False)
            except Exception as e:
                print(f"Errore salvataggio marca: {e}")



    def aggiungi_capo_singolo(self):
        marca = self.input_marca.text().strip().upper()
        if not marca: return
        try:
            CapoAnimale.create(
                user=self.user_id, gruppo=self.gruppo_id, marca_auricolare=marca,
                data_ingresso=datetime.now().strftime("%Y-%m-%d")
            )
            self.input_marca.clear()
            self.carica_capi()
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile salvare: {e}")

    def importa_da_txt(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Seleziona file TXT", "", "Testo (*.txt)")
        if not file_path: return
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            marche = [line.strip().upper() for line in lines if line.strip()]
            if not marche: return QMessageBox.warning(self, "Attenzione", "Il file è vuoto.")
            
            data_oggi = datetime.now().strftime("%Y-%m-%d")
            with db.atomic():
                dati_da_inserire = [{'user': self.user_id, 'gruppo': self.gruppo_id, 'marca_auricolare': m, 'data_ingresso': data_oggi} for m in set(marche)]
                for idx in range(0, len(dati_da_inserire), 100):
                    CapoAnimale.insert_many(dati_da_inserire[idx:idx+100]).execute()
            
            QMessageBox.information(self, "Successo", f"Importati {len(dati_da_inserire)} capi con successo!")
            self.carica_capi()
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile importare: {e}")

    def aggiorna_stato_capo(self):
        selected_items = self.table_capi.selectedItems()
        if not selected_items: return QMessageBox.warning(self, "Attenzione", "Seleziona uno o più capi dalla tabella.")
        
        selected_rows = set(item.row() for item in selected_items)
        nuovo_stato = self.combo_stati.currentText()
        
        # Capiamo in quale archivio mandarlo
        dest_id = None
        if nuovo_stato in ['VENDUTO_VIVO', 'VENDUTO_CARNE']:
            dest_id = self.parent().archivio_venduti_id
        elif nuovo_stato == 'DECEDUTO':
            dest_id = self.parent().archivio_deceduti_id

        try:
            successi = 0
            with db.atomic():
                for riga in selected_rows:
                    capo_id = self.table_capi.item(riga, 0).data(Qt.UserRole)
                    capo = CapoAnimale.get_by_id(capo_id)
                    
                    if capo.stato != nuovo_stato:
                        capo.stato = nuovo_stato
                        capo.data_uscita = datetime.now().strftime("%Y-%m-%d") if nuovo_stato != 'ATTIVO' else None
                        capo.save()
                        
                        # Magia: Se è venduto o deceduto, lo teletrasportiamo nell'archivio protetto!
                        if dest_id and capo.gruppo_id != dest_id:
                            from database import sposta_capo_animale
                            sposta_capo_animale(self.user_id, capo.id, dest_id)
                        successi += 1
                        
            self.carica_capi()
            if hasattr(self.parent(), 'carica_report_animali'):
                self.parent().carica_report_animali(show_errors=False)
                
            QMessageBox.information(self, "Successo", f"Stato aggiornato per {successi} capi.\nGli animali non attivi sono stati trasferiti in Archivio.")
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Aggiornamento fallito: {e}")
            

    def esegui_spostamento(self):
        selected_items = self.table_capi.selectedItems()
        if not selected_items: return QMessageBox.warning(self, "Attenzione", "Seleziona uno o più capi dalla tabella da spostare.")
        
        selected_rows = set(item.row() for item in selected_items)
        destinazione_id = self.combo_destinazione.currentData()
        if not destinazione_id:
            return QMessageBox.warning(self, "Attenzione", "Non ci sono altri gruppi compatibili in cui spostare i capi.")
            
        conferma = QMessageBox.question(self, "Conferma Spostamento", f"Vuoi spostare i {len(selected_rows)} capi selezionati nel gruppo di destinazione?", QMessageBox.Yes | QMessageBox.No)
        if conferma != QMessageBox.Yes: return
        
        try:
            successi = 0
            for riga in selected_rows:
                capo_id = self.table_capi.item(riga, 0).data(Qt.UserRole)
                successo = sposta_capo_animale(self.user_id, capo_id, destinazione_id)
                if successo: successi += 1
                
            QMessageBox.information(self, "Successo", f"{successi} animali spostati correttamente!")
            self.carica_capi() 
            
            # --- NUOVO: CONTROLLO GRUPPO VUOTO DOPO LO SPOSTAMENTO ---
            from models import CapoAnimale
            rimasti = CapoAnimale.select().where((CapoAnimale.gruppo == self.gruppo_id) & (CapoAnimale.stato == 'ATTIVO')).count()
            if rimasti == 0:
                chiedi_elimina = QMessageBox.question(
                    self, 
                    "Gruppo vuoto", 
                    "Hai spostato tutti i capi e questo gruppo è ora vuoto.\nVuoi eliminarlo definitivamente per mantenere ordine?", 
                    QMessageBox.Yes | QMessageBox.No
                )
                if chiedi_elimina == QMessageBox.Yes:
                    from database import delete_azienda_animale_entry
                    delete_azienda_animale_entry(self.user_id, self.gruppo_id)
                    self.accept() # Chiude automaticamente la finestra

        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Spostamento fallito: {e}")