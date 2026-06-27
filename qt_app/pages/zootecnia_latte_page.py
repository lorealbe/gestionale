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
    QSplitter
)


from models import db, ProduzioneLatte, ProduzioneCarne, Movimento, Fattura
from app_utils import format_eur, format_number, is_blank, parse_decimal, TabellaIsolata
from database import (
    LITRI_PER_QUINTALE,
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
        
        lbl_form = QLabel("🥛 Dati Produzione Latte")
        lbl_form.setStyleSheet("font-size: 16px; font-weight: bold; color: #34495e; border: none;")
        form_layout.addWidget(lbl_form, 0, 0, 1, 3)

        self.input_data = QDateEdit(self)
        self.input_data.setStyleSheet("padding: 5px;")
        self.input_data.setDisplayFormat("dd/MM/yyyy")
        self.input_data.setCalendarPopup(True)
        self.input_data.setDate(QDate.currentDate())

        self.input_quantita = QLineEdit(self)
        self.input_quantita.setStyleSheet("padding: 5px;")
        self.input_quantita.setPlaceholderText("Quantita prodotta")

        self.combo_unita_quantita = QComboBox(self)
        self.combo_unita_quantita.setStyleSheet("padding: 5px;")
        self.combo_unita_quantita.addItems(self._UNITA_QTA_LATTE)

        self.input_prezzo = QLineEdit(self)
        self.input_prezzo.setStyleSheet("padding: 5px;")
        self.input_prezzo.setText("0,00")

        self.combo_unita_prezzo = QComboBox(self)
        self.combo_unita_prezzo.setStyleSheet("padding: 5px;")
        self.combo_unita_prezzo.addItems(self._UNITA_PREZZO_LATTE)

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
        self.button_importa_fattura.clicked.connect(self.seleziona_fattura_latte)
        
        self.button_rimuovi_fattura = QPushButton("Rimuovi")
        self.button_rimuovi_fattura.setStyleSheet(STYLE_BTN_SECONDARIO)
        self.button_rimuovi_fattura.clicked.connect(self.rimuovi_fattura_latte)
        
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
        
        lbl_gruppi = QLabel("🐄 Gruppi da Latte")
        lbl_gruppi.setStyleSheet("font-size: 16px; font-weight: bold; color: #34495e; border: none;")
        gruppi_layout.addWidget(lbl_gruppi)

        row_gruppi = QHBoxLayout()
        
        self.list_gruppi = QListWidget(self)
        self.list_gruppi.setStyleSheet("background-color: white; border: 1px solid #ccc; border-radius: 4px;")
        self.list_gruppi.setSelectionMode(QAbstractItemView.MultiSelection)
        self.list_gruppi.itemSelectionChanged.connect(self._on_selezione_gruppi_latte)
        row_gruppi.addWidget(self.list_gruppi, 1)

        col_buttons = QVBoxLayout()
        button_tutti = QPushButton("Seleziona tutti", self)
        button_tutti.setStyleSheet(STYLE_BTN_INFO)
        button_tutti.clicked.connect(self.seleziona_tutti_gruppi_latte)
        col_buttons.addWidget(button_tutti)

        button_nessuno = QPushButton("Deseleziona", self)
        button_nessuno.setStyleSheet(STYLE_BTN_SECONDARIO)
        button_nessuno.clicked.connect(self.deseleziona_gruppi_latte)
        col_buttons.addWidget(button_nessuno)
        
        self.button_quote = QPushButton("Litri per gruppo...", self)
        self.button_quote.setStyleSheet(STYLE_BTN_MODIFICA)
        self.button_quote.clicked.connect(self.apri_dialog_quote_litri_gruppi_latte)
        col_buttons.addWidget(self.button_quote)

        col_buttons.addStretch(1)
        row_gruppi.addLayout(col_buttons)

        gruppi_layout.addLayout(row_gruppi)

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
        self.button_salva.clicked.connect(self.salva_produzione_latte)
        row_actions.addWidget(self.button_salva)

        button_modifica = QPushButton("Modifica Selezionata")
        button_modifica.setStyleSheet(STYLE_BTN_MODIFICA)
        button_modifica.clicked.connect(self.modifica_produzione_latte_selezionata)
        row_actions.addWidget(button_modifica)

        self.button_annulla = QPushButton("Annulla Modifica")
        self.button_annulla.setStyleSheet(STYLE_BTN_SECONDARIO)
        self.button_annulla.setEnabled(False)
        self.button_annulla.clicked.connect(lambda: self.annulla_modifica_produzione_latte(reset_fields=True))
        row_actions.addWidget(self.button_annulla)

        button_ricarica = QPushButton("Ricarica")
        button_ricarica.setStyleSheet(STYLE_BTN_SECONDARIO)
        button_ricarica.clicked.connect(lambda: self.carica_produzioni_latte(show_errors=True))
        row_actions.addWidget(button_ricarica)

        button_elimina = QPushButton("Elimina Selezionata")
        button_elimina.setStyleSheet(STYLE_BTN_ELIMINA)
        button_elimina.clicked.connect(self.elimina_produzione_latte_selezionata)
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

        self.table_produzione = TabellaIsolata(0, 4, self)
        self.table_produzione.setHorizontalHeaderLabels(["ID", "Data", "Quintali", "Prezzo / L"])
        self.table_produzione.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_produzione.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_produzione.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_produzione.setAlternatingRowColors(True)
        self.table_produzione.verticalHeader().setVisible(False)
        self.table_produzione.setStyleSheet("QTableWidget { border: 1px solid #ccc; border-radius: 5px; } QHeaderView::section { background-color: #f8f9fa; font-weight: bold; border: 1px solid #ddd; padding: 4px; }")
        self.table_produzione.itemSelectionChanged.connect(self._on_selezione_produzione_latte)
        self.table_produzione.cellDoubleClicked.connect(lambda _r, _c: self.modifica_produzione_latte_selezionata())

        table_header = self.table_produzione.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.Stretch)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        bottom_layout.addWidget(self.table_produzione, 1)
        main_splitter.addWidget(bottom_widget)

        main_splitter.setSizes([500, 300])
        main_layout.addWidget(main_splitter, 1)

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
        except Exception:
            return []

        gruppi_attivi = []
        for entry in entries:
            entry_id = int(entry.get("id", 0) or 0)
            capi = int(entry.get("capi", 0) or 0)
            finalita = (entry.get("finalita") or "").strip().upper()
            if entry_id <= 0 or capi <= 0 or finalita != "LATTE": continue
            gruppi_attivi.append(entry)

        gruppi_attivi.sort(key=lambda item: ((item.get("group_name") or "").strip().lower(), int(item.get("id", 0) or 0)))
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
        mov_id_val = int(movimento_id or 0)
        try:
            fatt = Fattura.select().where(
                (Fattura.user == self.user_id) & 
                ((Fattura.produzione == produzione_id) | ((mov_id_val > 0) & (Fattura.movimento == mov_id_val)))
            ).order_by(Fattura.data_caricamento.desc()).first()
            if fatt and fatt.nome_originale:
                self.label_nome_fattura.setText(str(fatt.nome_originale))
        except Exception:
            pass


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
            if show_errors: QMessageBox.warning(self, "Attenzione", "Seleziona prima una produzione da modificare.")
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

        try:
            prod = ProduzioneLatte.get_by_id(self.produzione_in_modifica_id)
            movimento_id = prod.movimento.id if prod.movimento else 0
            linked_group_ids = get_movimento_animali_entry_ids(self.user_id, movimento_id) if movimento_id > 0 else []
            group_allocations = get_produzione_latte_group_allocations(self.user_id, self.produzione_in_modifica_id)
        except Exception:
            linked_group_ids = []
            group_allocations = {}
            movimento_id = 0

        self.imposta_gruppi_latte_selezionati(linked_group_ids)
        self._latte_litri_quote_by_group = {int(e_id): float(lt) for e_id, lt in group_allocations.items() if int(e_id) in set(linked_group_ids) and float(lt or 0) > 0}
        self.button_salva.setText("Aggiorna Produzione")
        self.button_annulla.setEnabled(True)
        self.label_modifica_stato.setText(f"Modifica produzione ID {self.produzione_in_modifica_id} attiva. Quote gruppi caricate: {len(self._latte_litri_quote_by_group)}.")
        self._aggiorna_stato_gruppi_latte()
        self._carica_fattura_collegata_produzione(self.produzione_in_modifica_id, movimento_id)


    def annulla_modifica_produzione_latte(self, reset_fields=False):
        self.produzione_in_modifica_id = None
        self.button_salva.setText("✅ Salva Produzione")
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
        try: data_db = self._parse_data_iso()
        except ValueError as exc: return QMessageBox.critical(self, "Errore", str(exc))

        if is_blank(self.input_quantita.text()): return QMessageBox.critical(self, "Errore", "Inserisci la quantita prodotta.")
        litri_val = self._parse_quantita_litri_latte(self.input_quantita.text(), self.combo_unita_quantita.currentText())
        if litri_val is None or litri_val <= 0: return QMessageBox.critical(self, "Errore", "Quantita non valida.")
        quintali_val = litri_val / LITRI_PER_QUINTALE

        prezzo_text = self.input_prezzo.text().strip()
        prezzo_val = 0.0 if is_blank(prezzo_text) else self._parse_prezzo_litro_latte(prezzo_text, self.combo_unita_prezzo.currentText())
        if prezzo_val is None: return QMessageBox.critical(self, "Errore", "Prezzo non valido.")

        gruppi_info = self._valida_gruppi_latte_selezionati()
        if gruppi_info is None: return
        gruppi_ids = gruppi_info["entry_ids"]
        quote_litri_gruppi = self._quote_litri_gruppi_per_salvataggio(gruppi_ids, litri_val)
        if quote_litri_gruppi is None: return

        importo_movimento = litri_val * prezzo_val
        iva_importo_movimento = 0.0
        descrizione_mov = f"Produzione latte: {format_number(quintali_val, 2)} q ({format_number(litri_val, 2)} L) x {format_eur(prezzo_val, 4)}/L | Gruppi: {', '.join(gruppi_info['group_names'])}"

        parser_data = self.pending_parser_latte_data if isinstance(self.pending_parser_latte_data, dict) else None
        parser_values = self._estrai_valori_parser_db(parser_data)
        parser_dict = dict(zip(self._PARSER_DB_FIELDS, parser_values)) if parser_values else {}

        if parser_data is not None:
            parser_vat = parse_decimal(parser_data.get("vat_total"), allow_zero=True, allow_negative=False)
            parser_total = parse_decimal(parser_data.get("total_amount"), allow_zero=False, allow_negative=False)
            if parser_vat is not None and parser_total is not None and parser_total >= parser_vat:
                iva_importo_movimento = max(parser_vat, 0.0)
                importo_movimento = max(parser_total - iva_importo_movimento, 0.0)

        try:
            with db.atomic(): # TRANSAZIONE PEEWEE INDISTRUTTIBILE
                if self.produzione_in_modifica_id is None:
                    mov = Movimento.create(
                        user=self.user_id, data_op=data_db, tipo='ENTRATA', categoria='Latte',
                        descrizione=descrizione_mov, importo=importo_movimento, iva_importo=iva_importo_movimento,
                        stato_pagamento='PAGATO', **{f"parser_{k}": v for k, v in parser_dict.items()}
                    )
                    prod = ProduzioneLatte.create(user=self.user_id, data_op=data_db, litri=litri_val, prezzo_litro=prezzo_val, movimento=mov.id)
                    produzione_id = prod.id
                    movimento_id = mov.id
                    msg_ok = "Produzione latte salvata"
                else:
                    produzione_id = int(self.produzione_in_modifica_id)
                    prod = ProduzioneLatte.get_by_id(produzione_id)
                    movimento_id = prod.movimento.id if prod.movimento else 0
                    
                    ProduzioneLatte.update(data_op=data_db, litri=litri_val, prezzo_litro=prezzo_val).where(ProduzioneLatte.id == produzione_id).execute()
                    if movimento_id > 0:
                        Movimento.update(data_op=data_db, descrizione=descrizione_mov, importo=importo_movimento, iva_importo=iva_importo_movimento, **{f"parser_{k}": v for k, v in parser_dict.items()}).where(Movimento.id == movimento_id).execute()
                    else:
                        mov = Movimento.create(user=self.user_id, data_op=data_db, tipo='ENTRATA', categoria='Latte', descrizione=descrizione_mov, importo=importo_movimento, iva_importo=iva_importo_movimento, stato_pagamento='PAGATO', **{f"parser_{k}": v for k, v in parser_dict.items()})
                        movimento_id = mov.id
                        ProduzioneLatte.update(movimento=movimento_id).where(ProduzioneLatte.id == produzione_id).execute()
                    msg_ok = "Produzione latte aggiornata"

                if movimento_id > 0: set_movimento_animali_links(self.user_id, movimento_id, gruppi_ids)
                if self.pending_fattura_latte_id is not None and movimento_id > 0:
                    Fattura.update(movimento=movimento_id, produzione=produzione_id).where(Fattura.id == self.pending_fattura_latte_id).execute()
                if produzione_id is not None:
                    set_produzione_latte_group_allocations(self.user_id, produzione_id, movimento_id, quote_litri_gruppi)
        except Exception as exc:
            return QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")

        self.annulla_modifica_produzione_latte(reset_fields=True)
        self.rimuovi_fattura_latte()
        self.carica_produzioni_latte(show_errors=False)
        self.produzione_changed.emit()
        QMessageBox.information(self, "Successo", f"{msg_ok} ({format_number(quintali_val, 2)} q)!")


    def carica_produzioni_latte(self, show_errors=True):
        self.table_produzione.setRowCount(0)
        try:
            rows = list(ProduzioneLatte.select().where(ProduzioneLatte.user == self.user_id).order_by(ProduzioneLatte.data_op.desc(), ProduzioneLatte.id.desc()).dicts())
        except Exception as exc:
            if show_errors: QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        for row_index, row in enumerate(rows):
            quintali = float(row['litri'] or 0) / LITRI_PER_QUINTALE
            self._append_row(row_index, [str(row['id']), self._format_data_table(str(row['data_op'] or "")), format_number(quintali, 2), format_number(float(row['prezzo_litro'] or 0), 4)], right_align_indexes=[2, 3])

    def elimina_produzione_latte_selezionata(self):
        produzione_id = self._selected_produzione_id()
        if produzione_id is None: return QMessageBox.warning(self, "Attenzione", "Seleziona prima una riga di produzione da eliminare.")

        row = self.table_produzione.currentRow()
        if QMessageBox.question(self, "Conferma", f"Vuoi eliminare la produzione selezionata?\n\nData: {self.table_produzione.item(row, 1).text()}", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return

        era_in_modifica = self.produzione_in_modifica_id == produzione_id
        try:
            with db.atomic():
                prod = ProduzioneLatte.get_or_none((ProduzioneLatte.id == produzione_id) & (ProduzioneLatte.user == self.user_id))
                if not prod: return QMessageBox.critical(self, "Errore", "Produzione non trovata.")
                mov_id = prod.movimento.id if prod.movimento else None
                prod.delete_instance()
                
                if mov_id:
                    for f in Fattura.select().where(Fattura.movimento == mov_id):
                        try: Path(f.percorso_file).unlink(missing_ok=True)
                        except Exception: pass
                    Movimento.delete().where(Movimento.id == mov_id).execute()
        except Exception as exc:
            return QMessageBox.critical(self, "Errore DB", f"Errore: {exc}")

        self.carica_produzioni_latte(show_errors=False)
        if era_in_modifica: self.annulla_modifica_produzione_latte(reset_fields=True)
        self.produzione_changed.emit()
        QMessageBox.information(self, "Successo", "Produzione eliminata dal database!")

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