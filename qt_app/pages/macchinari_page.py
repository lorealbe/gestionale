import sqlite3
from datetime import datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
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

from app_utils import format_eur, parse_decimal, TabellaIsolata
from database import (
    add_macchinario_entry,
    add_manutenzione_macchinario_entry,
    delete_macchinario_entry,
    delete_manutenzione_macchinario_entry,
    list_macchinari_entries,
    list_manutenzioni_macchinari_entries,
    update_macchinario_entry,
    update_manutenzione_macchinario_entry,
)


class MacchinariPage(QWidget):
    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = int(user_id)

        self.macchinario_in_modifica_id = None
        self.manutenzione_in_modifica_id = None
        self._macchinari_by_id = {}

        self._build_ui()
        self.carica_macchinari(show_errors=False)

    def _build_ui(self):
        # Stili ricorrenti per i pulsanti
        STYLE_BTN_SALVA = "background-color: #28a745; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_MODIFICA = "background-color: #ffc107; color: black; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_ELIMINA = "background-color: #dc3545; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_SECONDARIO = "background-color: #6c757d; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_INFO = "background-color: #17a2b8; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # HEADER
        header_layout = QVBoxLayout()
        titolo = QLabel("🚜 Gestione Macchinari e Manutenzioni")
        titolo.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        sottotitolo = QLabel("Registra i tuoi mezzi agricoli, tieni traccia degli interventi e dei costi.")
        sottotitolo.setStyleSheet("font-size: 14px; color: #7f8c8d;")
        header_layout.addWidget(titolo)
        header_layout.addWidget(sottotitolo)
        main_layout.addLayout(header_layout)

        # SPLITTER PRINCIPALE VERTICALE (Sopra Macchine, Sotto Manutenzioni)
        main_splitter = QSplitter(Qt.Vertical)
        
        # ==========================================
        # PARTE 1: MACCHINARI
        # ==========================================
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        lbl_titolo_macch = QLabel("📋 Parco Macchine")
        lbl_titolo_macch.setStyleSheet("font-size: 18px; font-weight: bold; color: #34495e; padding-top: 5px;")
        top_layout.addWidget(lbl_titolo_macch)

        h_split_macch = QSplitter(Qt.Horizontal)

        # --- Pannello Inserimento Macchinari (Sinistra) ---
        frame_form_m = QFrame()
        frame_form_m.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        layout_form_m = QVBoxLayout(frame_form_m)
        layout_form_m.setContentsMargins(15, 15, 15, 15)

        form_m = QFormLayout()
        self.input_nome = QLineEdit(self)
        self.input_marca = QLineEdit(self)
        self.input_modello = QLineEdit(self)
        self.input_identificativo = QLineEdit(self)
        self.input_anno = QLineEdit(self)
        self.input_anno.setPlaceholderText("Es: 2015")
        self.input_note = QLineEdit(self)

        form_m.addRow("Nome/Tipo:", self.input_nome)
        form_m.addRow("Marca:", self.input_marca)
        form_m.addRow("Modello:", self.input_modello)
        form_m.addRow("Targa/Telaio:", self.input_identificativo)
        form_m.addRow("Anno:", self.input_anno)
        form_m.addRow("Note:", self.input_note)
        layout_form_m.addLayout(form_m)

        # Pulsanti Macchinari in griglia per risparmiare spazio
        grid_btn_m = QGridLayout()
        grid_btn_m.setSpacing(8)
        
        btn_salva_m = QPushButton("Salva")
        btn_salva_m.setStyleSheet(STYLE_BTN_SALVA)
        btn_salva_m.clicked.connect(self.salva_macchinario)
        
        btn_pulisci_m = QPushButton("Pulisci")
        btn_pulisci_m.setStyleSheet(STYLE_BTN_SECONDARIO)
        btn_pulisci_m.clicked.connect(self._reset_form_macchinario)
        
        btn_modifica_m = QPushButton("Modifica Selezionato")
        btn_modifica_m.setStyleSheet(STYLE_BTN_MODIFICA)
        btn_modifica_m.clicked.connect(self.prepara_modifica_macchinario)
        
        self.button_annulla_modifica_macchinario = QPushButton("Annulla Mod.")
        self.button_annulla_modifica_macchinario.setStyleSheet(STYLE_BTN_SECONDARIO)
        self.button_annulla_modifica_macchinario.setEnabled(False)
        self.button_annulla_modifica_macchinario.clicked.connect(lambda: self.annulla_modifica_macchinario(reset_fields=True))
        
        btn_elimina_m = QPushButton("Elimina")
        btn_elimina_m.setStyleSheet(STYLE_BTN_ELIMINA)
        btn_elimina_m.clicked.connect(self.elimina_macchinario_selezionato)

        btn_ricarica_m = QPushButton("Aggiorna")
        btn_ricarica_m.setStyleSheet(STYLE_BTN_INFO)
        btn_ricarica_m.clicked.connect(lambda: self.carica_macchinari(show_errors=True))

        grid_btn_m.addWidget(btn_salva_m, 0, 0)
        grid_btn_m.addWidget(btn_modifica_m, 0, 1)
        grid_btn_m.addWidget(btn_elimina_m, 0, 2)
        grid_btn_m.addWidget(btn_pulisci_m, 1, 0)
        grid_btn_m.addWidget(self.button_annulla_modifica_macchinario, 1, 1)
        grid_btn_m.addWidget(btn_ricarica_m, 1, 2)
        
        layout_form_m.addLayout(grid_btn_m)

        self.label_stato_macchinario = QLabel("")
        self.label_stato_macchinario.setStyleSheet("color: #e67e22; font-weight: bold; border: none; background: transparent;")
        self.label_stato_macchinario.setWordWrap(True)
        layout_form_m.addWidget(self.label_stato_macchinario)
        layout_form_m.addStretch()

        h_split_macch.addWidget(frame_form_m)

        # --- Tabella Macchinari (Destra) ---
        frame_tab_m = QFrame()
        frame_tab_m.setStyleSheet("background-color: white; border: 1px solid #ddd; border-radius: 8px;")
        layout_tab_m = QVBoxLayout(frame_tab_m)
        layout_tab_m.setContentsMargins(10, 10, 10, 10)

        row_filtri_m = QHBoxLayout()
        row_filtri_m.addWidget(QLabel("🔍 Ricerca:"))
        self.input_ricerca_macchinari = QLineEdit(self)
        self.input_ricerca_macchinari.setPlaceholderText("Cerca...")
        self.input_ricerca_macchinari.textChanged.connect(lambda _v: self.carica_macchinari(show_errors=False))
        row_filtri_m.addWidget(self.input_ricerca_macchinari, 1)

        row_filtri_m.addWidget(QLabel("📅 Anno:"))
        self.input_filtro_anno = QLineEdit(self)
        self.input_filtro_anno.setPlaceholderText("YYYY")
        self.input_filtro_anno.setFixedWidth(80)
        self.input_filtro_anno.textChanged.connect(lambda _v: self.carica_macchinari(show_errors=False))
        row_filtri_m.addWidget(self.input_filtro_anno)

        btn_reset_filtri_m = QPushButton("Reset Filtri")
        btn_reset_filtri_m.setStyleSheet(STYLE_BTN_SECONDARIO)
        btn_reset_filtri_m.clicked.connect(self._reset_filtri_macchinari)
        row_filtri_m.addWidget(btn_reset_filtri_m)

        layout_tab_m.addLayout(row_filtri_m)

        self.table_macchinari = TabellaIsolata(0, 7, self)
        self.table_macchinari.setHorizontalHeaderLabels(["ID", "Nome", "Marca", "Modello", "Targa/Telaio", "Anno", "Note"])
        self.table_macchinari.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_macchinari.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_macchinari.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_macchinari.setAlternatingRowColors(True)
        self.table_macchinari.verticalHeader().setVisible(False)
        self.table_macchinari.setStyleSheet("QTableWidget { border: none; } QHeaderView::section { background-color: #f8f9fa; font-weight: bold; border: 1px solid #ddd; }")
        self.table_macchinari.itemSelectionChanged.connect(self._on_macchinario_selection_changed)

        header_m = self.table_macchinari.horizontalHeader()
        header_m.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_m.setSectionResizeMode(1, QHeaderView.Stretch)
        header_m.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_m.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header_m.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header_m.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header_m.setSectionResizeMode(6, QHeaderView.Stretch)

        layout_tab_m.addWidget(self.table_macchinari)
        h_split_macch.addWidget(frame_tab_m)
        
        # Imposta proporzioni splitter 35% sx, 65% dx
        h_split_macch.setSizes([350, 650])
        top_layout.addWidget(h_split_macch)

        main_splitter.addWidget(top_widget)

        # ==========================================
        # PARTE 2: MANUTENZIONI
        # ==========================================
        self.frame_manutenzione = QWidget(self)
        manut_layout = QVBoxLayout(self.frame_manutenzione)
        manut_layout.setContentsMargins(0, 0, 0, 0)
        manut_layout.setSpacing(10)

        lbl_titolo_manut = QLabel("🔧 Registro Manutenzioni")
        lbl_titolo_manut.setStyleSheet("font-size: 18px; font-weight: bold; color: #34495e; padding-top: 10px;")
        manut_layout.addWidget(lbl_titolo_manut)

        # Riquadro di avviso se non ci sono macchine
        self.label_manutenzione_non_disponibile = QLabel("ℹ️ Manutenzione disponibile dopo aver registrato almeno 1 macchinario.")
        self.label_manutenzione_non_disponibile.setStyleSheet("color: #e67e22; font-size: 14px; font-style: italic; font-weight: bold;")
        self.label_manutenzione_non_disponibile.setWordWrap(True)
        manut_layout.addWidget(self.label_manutenzione_non_disponibile)

        h_split_manut = QSplitter(Qt.Horizontal)

        # --- Form Manutenzioni (Sinistra) ---
        frame_form_manut = QFrame()
        frame_form_manut.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        layout_form_manut = QVBoxLayout(frame_form_manut)
        layout_form_manut.setContentsMargins(15, 15, 15, 15)

        form_manut = QFormLayout()
        self.combo_macchinario_manutenzione = QComboBox(self)
        self.combo_macchinario_manutenzione.setStyleSheet("padding: 5px;")
        self.combo_macchinario_manutenzione.currentIndexChanged.connect(lambda _i: self.carica_manutenzioni(show_errors=False))

        self.input_manut_data = QDateEdit(self)
        self.input_manut_data.setDisplayFormat("dd/MM/yyyy")
        self.input_manut_data.setCalendarPopup(True)
        self.input_manut_data.setDate(QDate.currentDate())

        self.combo_manut_tipo = QComboBox(self)
        self.combo_manut_tipo.setStyleSheet("padding: 5px;")
        self.combo_manut_tipo.addItems(["Ordinaria", "Straordinaria"])

        self.input_manut_descrizione = QLineEdit(self)
        self.input_manut_fornitore = QLineEdit(self)
        self.input_manut_costo = QLineEdit(self)
        self.input_manut_costo.setPlaceholderText("Es: 150.50")
        self.input_manut_note = QLineEdit(self)

        form_manut.addRow("Macchinario:", self.combo_macchinario_manutenzione)
        form_manut.addRow("Data:", self.input_manut_data)
        form_manut.addRow("Tipo:", self.combo_manut_tipo)
        form_manut.addRow("Descrizione:", self.input_manut_descrizione)
        form_manut.addRow("Officina:", self.input_manut_fornitore)
        form_manut.addRow("Costo (€):", self.input_manut_costo)
        form_manut.addRow("Note:", self.input_manut_note)
        layout_form_manut.addLayout(form_manut)

        # Pulsanti Manutenzione
        grid_btn_manut = QGridLayout()
        grid_btn_manut.setSpacing(8)
        
        btn_salva_manut = QPushButton("Salva")
        btn_salva_manut.setStyleSheet(STYLE_BTN_SALVA)
        btn_salva_manut.clicked.connect(self.salva_manutenzione)

        btn_pulisci_manut = QPushButton("Pulisci")
        btn_pulisci_manut.setStyleSheet(STYLE_BTN_SECONDARIO)
        btn_pulisci_manut.clicked.connect(self._reset_form_manutenzione)

        btn_modifica_manut = QPushButton("Modifica Selez.")
        btn_modifica_manut.setStyleSheet(STYLE_BTN_MODIFICA)
        btn_modifica_manut.clicked.connect(self.prepara_modifica_manutenzione)

        self.button_annulla_modifica_manutenzione = QPushButton("Annulla Mod.")
        self.button_annulla_modifica_manutenzione.setStyleSheet(STYLE_BTN_SECONDARIO)
        self.button_annulla_modifica_manutenzione.setEnabled(False)
        self.button_annulla_modifica_manutenzione.clicked.connect(lambda: self.annulla_modifica_manutenzione(reset_fields=True))

        btn_elimina_manut = QPushButton("Elimina")
        btn_elimina_manut.setStyleSheet(STYLE_BTN_ELIMINA)
        btn_elimina_manut.clicked.connect(self.elimina_manutenzione_selezionata)

        btn_aggiorna_manut = QPushButton("Aggiorna")
        btn_aggiorna_manut.setStyleSheet(STYLE_BTN_INFO)
        btn_aggiorna_manut.clicked.connect(lambda: self.carica_manutenzioni(show_errors=True))

        grid_btn_manut.addWidget(btn_salva_manut, 0, 0)
        grid_btn_manut.addWidget(btn_modifica_manut, 0, 1)
        grid_btn_manut.addWidget(btn_elimina_manut, 0, 2)
        grid_btn_manut.addWidget(btn_pulisci_manut, 1, 0)
        grid_btn_manut.addWidget(self.button_annulla_modifica_manutenzione, 1, 1)
        grid_btn_manut.addWidget(btn_aggiorna_manut, 1, 2)
        
        layout_form_manut.addLayout(grid_btn_manut)

        self.label_stato_manutenzione = QLabel("")
        self.label_stato_manutenzione.setStyleSheet("color: #e67e22; font-weight: bold; border: none; background: transparent;")
        self.label_stato_manutenzione.setWordWrap(True)
        layout_form_manut.addWidget(self.label_stato_manutenzione)
        layout_form_manut.addStretch()

        h_split_manut.addWidget(frame_form_manut)

        # --- Tabella Manutenzioni (Destra) ---
        frame_tab_manut = QFrame(self)
        frame_tab_manut.setStyleSheet("background-color: white; border: 1px solid #ddd; border-radius: 8px;")
        layout_tab_manut = QVBoxLayout(frame_tab_manut)
        layout_tab_manut.setContentsMargins(10, 10, 10, 10)

        filters_layout = QHBoxLayout()
        filters_layout.addWidget(QLabel("🔍 Cerca:"))
        self.input_ricerca_manut = QLineEdit(self)
        self.input_ricerca_manut.setPlaceholderText("Fornitore, note...")
        self.input_ricerca_manut.textChanged.connect(lambda _v: self.carica_manutenzioni(show_errors=False))
        filters_layout.addWidget(self.input_ricerca_manut, 1)

        filters_layout.addWidget(QLabel("Tipo:"))
        self.combo_filtro_tipo_manut = QComboBox(self)
        self.combo_filtro_tipo_manut.addItems(["Tutte", "Ordinaria", "Straordinaria"])
        self.combo_filtro_tipo_manut.currentIndexChanged.connect(lambda _i: self.carica_manutenzioni(show_errors=False))
        filters_layout.addWidget(self.combo_filtro_tipo_manut)

        self.check_data_da = QCheckBox("Da:", self)
        self.check_data_da.toggled.connect(self._on_toggle_filtri_data_manutenzione)
        filters_layout.addWidget(self.check_data_da)

        self.filtro_data_da = QDateEdit(self)
        self.filtro_data_da.setDisplayFormat("dd/MM/yyyy")
        self.filtro_data_da.setCalendarPopup(True)
        self.filtro_data_da.setDate(QDate.currentDate())
        self.filtro_data_da.setEnabled(False)
        self.filtro_data_da.dateChanged.connect(lambda _d: self.carica_manutenzioni(show_errors=False))
        filters_layout.addWidget(self.filtro_data_da)

        self.check_data_a = QCheckBox("A:", self)
        self.check_data_a.toggled.connect(self._on_toggle_filtri_data_manutenzione)
        filters_layout.addWidget(self.check_data_a)

        self.filtro_data_a = QDateEdit(self)
        self.filtro_data_a.setDisplayFormat("dd/MM/yyyy")
        self.filtro_data_a.setCalendarPopup(True)
        self.filtro_data_a.setDate(QDate.currentDate())
        self.filtro_data_a.setEnabled(False)
        self.filtro_data_a.dateChanged.connect(lambda _d: self.carica_manutenzioni(show_errors=False))
        filters_layout.addWidget(self.filtro_data_a)

        btn_reset_filtri_manut = QPushButton("Reset Filtri")
        btn_reset_filtri_manut.setStyleSheet(STYLE_BTN_SECONDARIO)
        btn_reset_filtri_manut.clicked.connect(self._reset_filtri_manutenzioni)
        filters_layout.addWidget(btn_reset_filtri_manut)

        layout_tab_manut.addLayout(filters_layout)

        self.table_manutenzioni = TabellaIsolata(0, 7, self)
        self.table_manutenzioni.setHorizontalHeaderLabels(["ID", "Data", "Tipo", "Descrizione", "Officina", "Costo", "Note"])
        self.table_manutenzioni.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_manutenzioni.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_manutenzioni.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_manutenzioni.setAlternatingRowColors(True)
        self.table_manutenzioni.verticalHeader().setVisible(False)
        self.table_manutenzioni.setStyleSheet("QTableWidget { border: none; } QHeaderView::section { background-color: #f8f9fa; font-weight: bold; border: 1px solid #ddd; }")

        header_manut = self.table_manutenzioni.horizontalHeader()
        header_manut.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_manut.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header_manut.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_manut.setSectionResizeMode(3, QHeaderView.Stretch)
        header_manut.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header_manut.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header_manut.setSectionResizeMode(6, QHeaderView.Stretch)

        layout_tab_manut.addWidget(self.table_manutenzioni)
        h_split_manut.addWidget(frame_tab_manut)
        
        # Imposta proporzioni splitter 35% sx, 65% dx
        h_split_manut.setSizes([350, 650])
        manut_layout.addWidget(h_split_manut)

        main_splitter.addWidget(self.frame_manutenzione)
        
        # Split 50% e 50% tra macchine e manutenzioni
        main_splitter.setSizes([400, 400])
        main_layout.addWidget(main_splitter, 1)


    # =========================================================================
    # LE LOGICHE DI FUNZIONAMENTO RESTANO INVARIATE DA QUI IN GIÙ
    # =========================================================================

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

    def _selected_id_from_table(self, table: QTableWidget):
        row = table.currentRow()
        if row < 0:
            return None
        item = table.item(row, 0)
        if item is None:
            return None
        try:
            value = int(item.text().strip())
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def _format_macchinario_label(self, entry: dict) -> str:
        entry_id = int(entry.get("id") or 0)
        nome = (entry.get("nome") or "").strip() or "Macchinario"
        identificativo = (entry.get("identificativo") or "").strip()
        if identificativo:
            return f"{nome} - {identificativo}"
        return f"{nome} (ID {entry_id})"

    def _set_combo_macchinario_selected_id(self, macchinario_id: int):
        target_id = int(macchinario_id or 0)
        if target_id <= 0:
            return

        for idx in range(self.combo_macchinario_manutenzione.count()):
            data = int(self.combo_macchinario_manutenzione.itemData(idx) or 0)
            if data == target_id:
                self.combo_macchinario_manutenzione.setCurrentIndex(idx)
                return

    def _selected_macchinario_combo_id(self) -> int:
        try:
            return int(self.combo_macchinario_manutenzione.currentData() or 0)
        except (TypeError, ValueError):
            return 0

    def _data_iso_to_it(self, data_iso: str) -> str:
        value = (data_iso or "").strip()
        if not value:
            return ""
        try:
            return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return value

    def _it_to_qdate(self, text: str) -> QDate:
        date = QDate.fromString((text or "").strip(), "dd/MM/yyyy")
        if date.isValid():
            return date
        return QDate.currentDate()

    def _qdate_to_iso(self, date: QDate) -> str:
        if not date.isValid():
            raise ValueError("Inserisci una data valida.")
        return date.toString("yyyy-MM-dd")

    def _reset_form_macchinario(self):
        self.input_nome.clear()
        self.input_marca.clear()
        self.input_modello.clear()
        self.input_identificativo.clear()
        self.input_anno.clear()
        self.input_note.clear()

    def _reset_form_manutenzione(self):
        self.input_manut_data.setDate(QDate.currentDate())
        self.combo_manut_tipo.setCurrentText("Ordinaria")
        self.input_manut_descrizione.clear()
        self.input_manut_fornitore.clear()
        self.input_manut_costo.clear()
        self.input_manut_note.clear()

    def _reset_filtri_macchinari(self):
        self.input_ricerca_macchinari.clear()
        self.input_filtro_anno.clear()
        self.carica_macchinari(show_errors=False)

    def _reset_filtri_manutenzioni(self):
        self.input_ricerca_manut.clear()
        self.combo_filtro_tipo_manut.setCurrentText("Tutte")
        self.check_data_da.setChecked(False)
        self.check_data_a.setChecked(False)
        self.filtro_data_da.setDate(QDate.currentDate())
        self.filtro_data_a.setDate(QDate.currentDate())
        self.carica_manutenzioni(show_errors=False)

    def _on_toggle_filtri_data_manutenzione(self):
        self.filtro_data_da.setEnabled(self.check_data_da.isChecked())
        self.filtro_data_a.setEnabled(self.check_data_a.isChecked())
        self.carica_manutenzioni(show_errors=False)

    def _filtra_macchinari_entries(self, entries: list[dict]) -> list[dict]:
        ricerca = self.input_ricerca_macchinari.text().strip().lower()
        anno_filtro = self.input_filtro_anno.text().strip()

        if not ricerca and not anno_filtro:
            return list(entries)

        filtrati = []
        for entry in entries:
            anno_value = entry.get("anno")
            anno_display = str(int(anno_value)) if isinstance(anno_value, int) else ""

            if anno_filtro and anno_filtro not in anno_display:
                continue

            searchable = " ".join(
                [
                    str(entry.get("nome") or ""),
                    str(entry.get("marca") or ""),
                    str(entry.get("modello") or ""),
                    str(entry.get("identificativo") or ""),
                    anno_display,
                    str(entry.get("note") or ""),
                ]
            ).lower()
            if ricerca and ricerca not in searchable:
                continue

            filtrati.append(entry)

        return filtrati

    def _filtra_manutenzioni_entries(self, entries: list[dict]) -> list[dict]:
        ricerca = self.input_ricerca_manut.text().strip().lower()
        tipo_filtro = self.combo_filtro_tipo_manut.currentText().strip().lower()

        data_da = self.filtro_data_da.date().toString("yyyy-MM-dd") if self.check_data_da.isChecked() else ""
        data_a = self.filtro_data_a.date().toString("yyyy-MM-dd") if self.check_data_a.isChecked() else ""
        if data_da and data_a and data_da > data_a:
            data_da, data_a = data_a, data_da

        if not ricerca and tipo_filtro in ("", "tutte") and not data_da and not data_a:
            return list(entries)

        filtrati = []
        for entry in entries:
            tipo = (entry.get("tipo_manutenzione") or "").strip().upper()
            tipo_display = "Straordinaria" if tipo == "STRAORDINARIA" else "Ordinaria"

            if tipo_filtro == "ordinaria" and tipo != "ORDINARIA":
                continue
            if tipo_filtro == "straordinaria" and tipo != "STRAORDINARIA":
                continue

            data_entry = (entry.get("data_manutenzione") or "").strip()
            if data_da and (not data_entry or data_entry < data_da):
                continue
            if data_a and (not data_entry or data_entry > data_a):
                continue

            searchable = " ".join(
                [
                    self._data_iso_to_it(data_entry),
                    tipo_display,
                    str(entry.get("descrizione") or ""),
                    str(entry.get("fornitore") or ""),
                    format_eur(entry.get("costo")) if entry.get("costo") is not None else "",
                    str(entry.get("note") or ""),
                ]
            ).lower()
            if ricerca and ricerca not in searchable:
                continue

            filtrati.append(entry)

        return filtrati

    def annulla_modifica_macchinario(self, reset_fields=False):
        self.macchinario_in_modifica_id = None
        self.button_annulla_modifica_macchinario.setEnabled(False)
        if reset_fields:
            self._reset_form_macchinario()
        self.label_stato_macchinario.setText("")

    def annulla_modifica_manutenzione(self, reset_fields=False):
        self.manutenzione_in_modifica_id = None
        self.button_annulla_modifica_manutenzione.setEnabled(False)
        if reset_fields:
            self._reset_form_manutenzione()
        self.label_stato_manutenzione.setText("")

    def _set_manutenzione_visibility(self, has_macchinari: bool):
        self.frame_manutenzione.setVisible(has_macchinari)
        self.label_manutenzione_non_disponibile.setVisible(not has_macchinari)

        if not has_macchinari:
            self.combo_macchinario_manutenzione.clear()
            self.table_manutenzioni.setRowCount(0)
            self.annulla_modifica_manutenzione(reset_fields=True)

    def _on_macchinario_selection_changed(self):
        macchinario_id = self._selected_id_from_table(self.table_macchinari)
        if macchinario_id is None:
            return

        self._set_combo_macchinario_selected_id(macchinario_id)
        self.carica_manutenzioni(show_errors=False)

    def _populate_macchinari_selector(self, entries: list[dict], preferred_id: int | None = None):
        selected_before = self._selected_macchinario_combo_id()

        self.combo_macchinario_manutenzione.blockSignals(True)
        self.combo_macchinario_manutenzione.clear()

        for entry in entries:
            entry_id = int(entry.get("id") or 0)
            if entry_id <= 0:
                continue
            self.combo_macchinario_manutenzione.addItem(self._format_macchinario_label(entry), entry_id)

        target_id = int(preferred_id or 0) if preferred_id else 0
        if target_id <= 0:
            target_id = int(selected_before or 0)

        if self.combo_macchinario_manutenzione.count() > 0:
            if target_id > 0:
                found = False
                for idx in range(self.combo_macchinario_manutenzione.count()):
                    data = int(self.combo_macchinario_manutenzione.itemData(idx) or 0)
                    if data == target_id:
                        self.combo_macchinario_manutenzione.setCurrentIndex(idx)
                        found = True
                        break
                if not found:
                    self.combo_macchinario_manutenzione.setCurrentIndex(0)
            else:
                self.combo_macchinario_manutenzione.setCurrentIndex(0)

        self.combo_macchinario_manutenzione.blockSignals(False)

    def prepara_modifica_macchinario(self):
        row = self.table_macchinari.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Attenzione", "Seleziona prima un macchinario da modificare.")
            return

        macchinario_id = self._selected_id_from_table(self.table_macchinari)
        if macchinario_id is None:
            QMessageBox.warning(self, "Attenzione", "Macchinario selezionato non valido.")
            return

        self.macchinario_in_modifica_id = macchinario_id
        self.input_nome.setText(self.table_macchinari.item(row, 1).text() if self.table_macchinari.item(row, 1) else "")
        self.input_marca.setText(self.table_macchinari.item(row, 2).text() if self.table_macchinari.item(row, 2) else "")
        self.input_modello.setText(self.table_macchinari.item(row, 3).text() if self.table_macchinari.item(row, 3) else "")
        self.input_identificativo.setText(
            self.table_macchinari.item(row, 4).text() if self.table_macchinari.item(row, 4) else ""
        )
        self.input_anno.setText(self.table_macchinari.item(row, 5).text() if self.table_macchinari.item(row, 5) else "")
        self.input_note.setText(self.table_macchinari.item(row, 6).text() if self.table_macchinari.item(row, 6) else "")

        self.button_annulla_modifica_macchinario.setEnabled(True)
        self.label_stato_macchinario.setText(
            f"✍️ Modifica ID {macchinario_id} attiva."
        )

    def elimina_macchinario_selezionato(self):
        row = self.table_macchinari.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Attenzione", "Seleziona prima un macchinario da eliminare.")
            return

        macchinario_id = self._selected_id_from_table(self.table_macchinari)
        if macchinario_id is None:
            QMessageBox.warning(self, "Attenzione", "Macchinario selezionato non valido.")
            return

        nome = self.table_macchinari.item(row, 1).text().strip() if self.table_macchinari.item(row, 1) else "(senza nome)"
        identificativo = self.table_macchinari.item(row, 4).text().strip() if self.table_macchinari.item(row, 4) else ""

        dettaglio = f"Nome: {nome}"
        if identificativo:
            dettaglio += f"\nIdentificativo: {identificativo}"

        conferma = QMessageBox.question(
            self,
            "Conferma eliminazione",
            "Vuoi eliminare il macchinario selezionato?\n\n"
            + dettaglio
            + "\n\n🚨 Le manutenzioni collegate saranno eliminate definitivamente.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if conferma != QMessageBox.Yes:
            return

        try:
            manutenzioni_eliminate = delete_macchinario_entry(self.user_id, macchinario_id)
        except ValueError as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        if self.macchinario_in_modifica_id == macchinario_id:
            self.annulla_modifica_macchinario(reset_fields=True)

        self.carica_macchinari(show_errors=False)
        msg = "Macchinario eliminato correttamente."
        if manutenzioni_eliminate > 0:
            msg += f" Manutenzioni collegate eliminate: {manutenzioni_eliminate}."
        QMessageBox.information(self, "Eliminazione completata", msg)

    def prepara_modifica_manutenzione(self):
        row = self.table_manutenzioni.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Attenzione", "Seleziona prima una manutenzione da modificare.")
            return

        manutenzione_id = self._selected_id_from_table(self.table_manutenzioni)
        if manutenzione_id is None:
            QMessageBox.warning(self, "Attenzione", "Manutenzione selezionata non valida.")
            return

        data_it = self.table_manutenzioni.item(row, 1).text().strip() if self.table_manutenzioni.item(row, 1) else ""
        tipo = self.table_manutenzioni.item(row, 2).text().strip() if self.table_manutenzioni.item(row, 2) else "Ordinaria"
        descrizione = self.table_manutenzioni.item(row, 3).text() if self.table_manutenzioni.item(row, 3) else ""
        fornitore = self.table_manutenzioni.item(row, 4).text() if self.table_manutenzioni.item(row, 4) else ""
        costo_text = self.table_manutenzioni.item(row, 5).text() if self.table_manutenzioni.item(row, 5) else ""
        note = self.table_manutenzioni.item(row, 6).text() if self.table_manutenzioni.item(row, 6) else ""

        self.manutenzione_in_modifica_id = manutenzione_id
        self.input_manut_data.setDate(self._it_to_qdate(data_it))
        self.combo_manut_tipo.setCurrentText("Straordinaria" if tipo.lower().startswith("straord") else "Ordinaria")
        self.input_manut_descrizione.setText(descrizione)
        self.input_manut_fornitore.setText(fornitore)

        costo_clean = costo_text.replace("EUR", "").strip()
        costo_val = parse_decimal(costo_clean, allow_zero=True, allow_negative=False)
        self.input_manut_costo.setText("" if costo_val is None else f"{costo_val:.2f}".replace(".", ","))
        self.input_manut_note.setText(note)

        self.button_annulla_modifica_manutenzione.setEnabled(True)
        self.label_stato_manutenzione.setText(
            f"✍️ Modifica ID {manutenzione_id} attiva."
        )

    def elimina_manutenzione_selezionata(self):
        row = self.table_manutenzioni.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Attenzione", "Seleziona prima una manutenzione da eliminare.")
            return

        manutenzione_id = self._selected_id_from_table(self.table_manutenzioni)
        if manutenzione_id is None:
            QMessageBox.warning(self, "Attenzione", "Manutenzione selezionata non valida.")
            return

        data = self.table_manutenzioni.item(row, 1).text().strip() if self.table_manutenzioni.item(row, 1) else ""
        descrizione = self.table_manutenzioni.item(row, 3).text().strip() if self.table_manutenzioni.item(row, 3) else ""

        conferma = QMessageBox.question(
            self,
            "Conferma eliminazione",
            "Vuoi eliminare la manutenzione selezionata?\n\n"
            f"Data: {data}\n"
            f"Descrizione: {descrizione or '(senza descrizione)'}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if conferma != QMessageBox.Yes:
            return

        try:
            deleted = delete_manutenzione_macchinario_entry(self.user_id, manutenzione_id)
            if not deleted:
                QMessageBox.critical(self, "Errore", "Manutenzione non trovata o non eliminabile.")
                return
        except ValueError as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        if self.manutenzione_in_modifica_id == manutenzione_id:
            self.annulla_modifica_manutenzione(reset_fields=True)

        self.carica_manutenzioni(show_errors=False)
        QMessageBox.information(self, "Eliminazione completata", "Manutenzione eliminata correttamente.")

    def salva_macchinario(self):
        nome = self.input_nome.text().strip()
        if not nome:
            QMessageBox.warning(self, "Dati mancanti", "Inserisci il nome del macchinario.")
            return

        in_modifica = self.macchinario_in_modifica_id is not None
        macchinario_id = int(self.macchinario_in_modifica_id or 0)

        try:
            if not in_modifica:
                new_id = add_macchinario_entry(
                    self.user_id,
                    nome=nome,
                    marca=self.input_marca.text(),
                    modello=self.input_modello.text(),
                    identificativo=self.input_identificativo.text(),
                    anno=self.input_anno.text(),
                    note=self.input_note.text(),
                )
                self._reset_form_macchinario()
                self.label_stato_macchinario.setText("✅ Macchinario salvato correttamente.")
                self.carica_macchinari(show_errors=False, select_macchinario_id=new_id)
                return

            updated = update_macchinario_entry(
                self.user_id,
                macchinario_id=macchinario_id,
                nome=nome,
                marca=self.input_marca.text(),
                modello=self.input_modello.text(),
                identificativo=self.input_identificativo.text(),
                anno=self.input_anno.text(),
                note=self.input_note.text(),
            )
            if not updated:
                QMessageBox.critical(self, "Errore", "Macchinario non trovato o non modificabile.")
                return
        except ValueError as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        self.annulla_modifica_macchinario(reset_fields=True)
        self.label_stato_macchinario.setText(f"✅ Macchinario ID {macchinario_id} aggiornato.")
        self.carica_macchinari(show_errors=False, select_macchinario_id=macchinario_id)

    def salva_manutenzione(self):
        macchinario_id = self._selected_macchinario_combo_id()
        if macchinario_id <= 0:
            QMessageBox.warning(self, "Dati mancanti", "Seleziona il macchinario da manutenere.")
            return

        descrizione = self.input_manut_descrizione.text().strip()
        if not descrizione:
            QMessageBox.warning(self, "Dati mancanti", "Inserisci una descrizione della manutenzione.")
            return

        costo_value = None
        costo_text = self.input_manut_costo.text().strip()
        if costo_text:
            costo_value = parse_decimal(costo_text, allow_zero=True, allow_negative=False)
            if costo_value is None:
                QMessageBox.warning(self, "Costo non valido", "Inserisci un costo numerico valido (es. 1200,50).")
                return

        data_iso = self._qdate_to_iso(self.input_manut_data.date())
        tipo_label = self.combo_manut_tipo.currentText().strip().lower()
        tipo_db = "STRAORDINARIA" if tipo_label.startswith("straord") else "ORDINARIA"

        in_modifica = self.manutenzione_in_modifica_id is not None
        manutenzione_id = int(self.manutenzione_in_modifica_id or 0)

        try:
            if not in_modifica:
                new_id = add_manutenzione_macchinario_entry(
                    self.user_id,
                    macchinario_id=macchinario_id,
                    data_manutenzione=data_iso,
                    tipo_manutenzione=tipo_db,
                    descrizione=descrizione,
                    costo=costo_value,
                    fornitore=self.input_manut_fornitore.text(),
                    note=self.input_manut_note.text(),
                )
                self._reset_form_manutenzione()
                self.label_stato_manutenzione.setText("✅ Manutenzione salvata correttamente.")
                self.carica_manutenzioni(show_errors=False, select_manutenzione_id=new_id)
                return

            updated = update_manutenzione_macchinario_entry(
                self.user_id,
                manutenzione_id=manutenzione_id,
                macchinario_id=macchinario_id,
                data_manutenzione=data_iso,
                tipo_manutenzione=tipo_db,
                descrizione=descrizione,
                costo=costo_value,
                fornitore=self.input_manut_fornitore.text(),
                note=self.input_manut_note.text(),
            )
            if not updated:
                QMessageBox.critical(self, "Errore", "Manutenzione non trovata o non modificabile.")
                return
        except ValueError as exc:
            QMessageBox.critical(self, "Errore", str(exc))
            return
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        self.annulla_modifica_manutenzione(reset_fields=True)
        self.label_stato_manutenzione.setText(f"✅ Manutenzione ID {manutenzione_id} aggiornata.")
        self.carica_manutenzioni(show_errors=False, select_manutenzione_id=manutenzione_id)

    def carica_macchinari(self, show_errors=True, select_macchinario_id=None):
        selected_id = self._selected_id_from_table(self.table_macchinari)

        try:
            entries = list_macchinari_entries(self.user_id)
        except sqlite3.Error as exc:
            if show_errors:
                QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        self._macchinari_by_id = {int(entry.get("id") or 0): entry for entry in entries}
        self._populate_macchinari_selector(entries, preferred_id=select_macchinario_id or selected_id)
        self._set_manutenzione_visibility(bool(entries))

        if self.macchinario_in_modifica_id is not None:
            if int(self.macchinario_in_modifica_id) not in self._macchinari_by_id:
                self.annulla_modifica_macchinario(reset_fields=True)

        filtered = self._filtra_macchinari_entries(entries)

        self.table_macchinari.setRowCount(0)
        target_id = int(select_macchinario_id or 0) if select_macchinario_id else int(selected_id or 0)
        target_row = None

        for idx, entry in enumerate(filtered):
            entry_id = int(entry.get("id") or 0)
            anno_value = entry.get("anno")
            anno_display = str(int(anno_value)) if isinstance(anno_value, int) else ""

            self._append_row(
                self.table_macchinari,
                idx,
                [
                    str(entry_id),
                    str(entry.get("nome") or ""),
                    str(entry.get("marca") or ""),
                    str(entry.get("modello") or ""),
                    str(entry.get("identificativo") or ""),
                    anno_display,
                    str(entry.get("note") or ""),
                ],
            )

            if target_id > 0 and entry_id == target_id:
                target_row = idx

        if self.table_macchinari.rowCount() > 0:
            if target_row is None:
                target_row = 0
            self.table_macchinari.selectRow(target_row)

        if entries:
            self.carica_manutenzioni(show_errors=False)

    def carica_manutenzioni(self, show_errors=True, select_manutenzione_id=None):
        self.table_manutenzioni.setRowCount(0)

        macchinario_id = self._selected_macchinario_combo_id()
        if macchinario_id <= 0:
            return

        try:
            entries = list_manutenzioni_macchinari_entries(self.user_id, macchinario_id=macchinario_id)
        except sqlite3.Error as exc:
            if show_errors:
                QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        if self.manutenzione_in_modifica_id is not None:
            in_lista = any(int(entry.get("id") or 0) == int(self.manutenzione_in_modifica_id) for entry in entries)
            if not in_lista:
                self.annulla_modifica_manutenzione(reset_fields=True)

        filtered = self._filtra_manutenzioni_entries(entries)

        selected_before = self._selected_id_from_table(self.table_manutenzioni)
        target_id = int(select_manutenzione_id or 0) if select_manutenzione_id else int(selected_before or 0)
        target_row = None

        for idx, entry in enumerate(filtered):
            entry_id = int(entry.get("id") or 0)
            tipo = (entry.get("tipo_manutenzione") or "").strip().upper()
            tipo_display = "Straordinaria" if tipo == "STRAORDINARIA" else "Ordinaria"
            costo = entry.get("costo")
            costo_display = format_eur(costo) if costo is not None else ""

            self._append_row(
                self.table_manutenzioni,
                idx,
                [
                    str(entry_id),
                    self._data_iso_to_it(entry.get("data_manutenzione") or ""),
                    tipo_display,
                    str(entry.get("descrizione") or ""),
                    str(entry.get("fornitore") or ""),
                    costo_display,
                    str(entry.get("note") or ""),
                ],
                right_align_indexes=[5],
            )

            if target_id > 0 and entry_id == target_id:
                target_row = idx

        if self.table_manutenzioni.rowCount() > 0:
            if target_row is None:
                target_row = 0
            self.table_manutenzioni.selectRow(target_row)