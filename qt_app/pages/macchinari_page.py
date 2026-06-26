from datetime import datetime
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QSplitter
)

from app_utils import format_eur, parse_decimal, TabellaIsolata
from models import Macchinario, ManutenzioneMacchinario # ORM Diretto

class MacchinariPage(QWidget):
    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = int(user_id)
        self.macchinario_in_modifica_id = None
        self.manutenzione_in_modifica_id = None
        self._build_ui()
        self.carica_macchinari()

    def _build_ui(self):
        STYLE_BTN_SALVA = "background-color: #28a745; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_MODIFICA = "background-color: #ffc107; color: black; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_ELIMINA = "background-color: #dc3545; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_SECONDARIO = "background-color: #6c757d; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        header_layout = QVBoxLayout()
        titolo = QLabel("🚜 Gestione Macchinari e Manutenzioni")
        titolo.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        header_layout.addWidget(titolo)
        header_layout.addWidget(QLabel("Registra i mezzi agricoli e tieni traccia degli interventi."))
        main_layout.addLayout(header_layout)

        main_splitter = QSplitter(Qt.Vertical)
        
        # --- PARTE 1: MACCHINARI ---
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0,0,0,0)
        lbl_titolo_macch = QLabel("📋 Parco Macchine")
        lbl_titolo_macch.setStyleSheet("font-size: 18px; font-weight: bold; color: #34495e;")
        top_layout.addWidget(lbl_titolo_macch)

        h_split_macch = QSplitter(Qt.Horizontal)

        frame_form_m = QFrame()
        frame_form_m.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        layout_form_m = QVBoxLayout(frame_form_m)

        form_m = QFormLayout()
        self.input_nome = QLineEdit()
        self.input_marca = QLineEdit()
        self.input_modello = QLineEdit()
        self.input_identificativo = QLineEdit()
        self.input_anno = QLineEdit()
        self.input_note = QLineEdit()

        form_m.addRow("Nome/Tipo:", self.input_nome)
        form_m.addRow("Marca:", self.input_marca)
        form_m.addRow("Modello:", self.input_modello)
        form_m.addRow("Targa/Telaio:", self.input_identificativo)
        form_m.addRow("Anno:", self.input_anno)
        form_m.addRow("Note:", self.input_note)
        layout_form_m.addLayout(form_m)

        grid_btn_m = QGridLayout()
        btn_salva_m = QPushButton("Salva")
        btn_salva_m.setStyleSheet(STYLE_BTN_SALVA)
        btn_salva_m.clicked.connect(self.salva_macchinario)
        
        btn_modifica_m = QPushButton("Modifica")
        btn_modifica_m.setStyleSheet(STYLE_BTN_MODIFICA)
        btn_modifica_m.clicked.connect(self.prepara_modifica_macchinario)
        
        btn_elimina_m = QPushButton("Elimina")
        btn_elimina_m.setStyleSheet(STYLE_BTN_ELIMINA)
        btn_elimina_m.clicked.connect(self.elimina_macchinario_selezionato)

        btn_pulisci_m = QPushButton("Pulisci Form")
        btn_pulisci_m.setStyleSheet(STYLE_BTN_SECONDARIO)
        btn_pulisci_m.clicked.connect(self._reset_form_macchinario)

        grid_btn_m.addWidget(btn_salva_m, 0, 0); grid_btn_m.addWidget(btn_modifica_m, 0, 1)
        grid_btn_m.addWidget(btn_elimina_m, 1, 0); grid_btn_m.addWidget(btn_pulisci_m, 1, 1)
        layout_form_m.addLayout(grid_btn_m)

        h_split_macch.addWidget(frame_form_m)

        frame_tab_m = QFrame()
        frame_tab_m.setStyleSheet("background-color: white; border: 1px solid #ddd; border-radius: 8px;")
        layout_tab_m = QVBoxLayout(frame_tab_m)

        row_filtri_m = QHBoxLayout()
        self.input_ricerca_macchinari = QLineEdit()
        self.input_ricerca_macchinari.setPlaceholderText("Cerca...")
        self.input_ricerca_macchinari.textChanged.connect(self.carica_macchinari)
        row_filtri_m.addWidget(self.input_ricerca_macchinari)
        layout_tab_m.addLayout(row_filtri_m)

        self.table_macchinari = TabellaIsolata(0, 7)
        self.table_macchinari.setHorizontalHeaderLabels(["ID", "Nome", "Marca", "Modello", "Targa/Telaio", "Anno", "Note"])
        self.table_macchinari.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_macchinari.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_macchinari.verticalHeader().setVisible(False)
        self.table_macchinari.itemSelectionChanged.connect(self.carica_manutenzioni)
        layout_tab_m.addWidget(self.table_macchinari)

        h_split_macch.addWidget(frame_tab_m)
        h_split_macch.setSizes([350, 650])
        top_layout.addWidget(h_split_macch)
        main_splitter.addWidget(top_widget)

        # --- PARTE 2: MANUTENZIONI ---
        self.frame_manutenzione = QWidget()
        manut_layout = QVBoxLayout(self.frame_manutenzione)
        manut_layout.setContentsMargins(0,0,0,0)
        lbl_titolo_manut = QLabel("🔧 Registro Manutenzioni")
        lbl_titolo_manut.setStyleSheet("font-size: 18px; font-weight: bold; color: #34495e;")
        manut_layout.addWidget(lbl_titolo_manut)

        self.h_split_manut = QSplitter(Qt.Horizontal)

        frame_form_manut = QFrame()
        frame_form_manut.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        layout_form_manut = QVBoxLayout(frame_form_manut)

        form_manut = QFormLayout()
        self.input_manut_data = QDateEdit()
        self.input_manut_data.setDisplayFormat("dd/MM/yyyy")
        self.input_manut_data.setDate(QDate.currentDate())
        self.combo_manut_tipo = QComboBox()
        self.combo_manut_tipo.addItems(["ORDINARIA", "STRAORDINARIA"])
        self.input_manut_descrizione = QLineEdit()
        self.input_manut_fornitore = QLineEdit()
        self.input_manut_costo = QLineEdit()
        self.input_manut_note = QLineEdit()

        form_manut.addRow("Data:", self.input_manut_data)
        form_manut.addRow("Tipo:", self.combo_manut_tipo)
        form_manut.addRow("Descrizione:", self.input_manut_descrizione)
        form_manut.addRow("Officina:", self.input_manut_fornitore)
        form_manut.addRow("Costo (€):", self.input_manut_costo)
        form_manut.addRow("Note:", self.input_manut_note)
        layout_form_manut.addLayout(form_manut)

        grid_btn_manut = QGridLayout()
        btn_salva_manut = QPushButton("Salva")
        btn_salva_manut.setStyleSheet(STYLE_BTN_SALVA)
        btn_salva_manut.clicked.connect(self.salva_manutenzione)

        btn_modifica_manut = QPushButton("Modifica")
        btn_modifica_manut.setStyleSheet(STYLE_BTN_MODIFICA)
        btn_modifica_manut.clicked.connect(self.prepara_modifica_manutenzione)

        btn_elimina_manut = QPushButton("Elimina")
        btn_elimina_manut.setStyleSheet(STYLE_BTN_ELIMINA)
        btn_elimina_manut.clicked.connect(self.elimina_manutenzione_selezionata)
        
        btn_pulisci_manut = QPushButton("Pulisci Form")
        btn_pulisci_manut.setStyleSheet(STYLE_BTN_SECONDARIO)
        btn_pulisci_manut.clicked.connect(self._reset_form_manutenzione)

        grid_btn_manut.addWidget(btn_salva_manut, 0, 0); grid_btn_manut.addWidget(btn_modifica_manut, 0, 1)
        grid_btn_manut.addWidget(btn_elimina_manut, 1, 0); grid_btn_manut.addWidget(btn_pulisci_manut, 1, 1)
        layout_form_manut.addLayout(grid_btn_manut)

        self.h_split_manut.addWidget(frame_form_manut)

        frame_tab_manut = QFrame()
        frame_tab_manut.setStyleSheet("background-color: white; border: 1px solid #ddd; border-radius: 8px;")
        layout_tab_manut = QVBoxLayout(frame_tab_manut)

        self.table_manutenzioni = TabellaIsolata(0, 7)
        self.table_manutenzioni.setHorizontalHeaderLabels(["ID", "Data", "Tipo", "Descrizione", "Officina", "Costo", "Note"])
        self.table_manutenzioni.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_manutenzioni.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_manutenzioni.verticalHeader().setVisible(False)
        layout_tab_manut.addWidget(self.table_manutenzioni)

        self.h_split_manut.addWidget(frame_tab_manut)
        self.h_split_manut.setSizes([350, 650])
        manut_layout.addWidget(self.h_split_manut)

        main_splitter.addWidget(self.frame_manutenzione)
        main_splitter.setSizes([400, 400])
        main_layout.addWidget(main_splitter)

    # --- LOGICA MACCHINARI ---
    def _reset_form_macchinario(self):
        self.macchinario_in_modifica_id = None
        for i in (self.input_nome, self.input_marca, self.input_modello, self.input_identificativo, self.input_anno, self.input_note): i.clear()

    def carica_macchinari(self):
        self.table_macchinari.setRowCount(0)
        ricerca = self.input_ricerca_macchinari.text().lower()
        
        macchinari = list(Macchinario.select().where(Macchinario.user == self.user_id).order_by(Macchinario.nome).dicts())
        for m in macchinari:
            if ricerca and ricerca not in f"{m['nome']} {m['marca']} {m['modello']} {m['identificativo']}".lower(): continue
            r = self.table_macchinari.rowCount()
            self.table_macchinari.insertRow(r)
            self.table_macchinari.setItem(r, 0, QTableWidgetItem(str(m['id'])))
            self.table_macchinari.setItem(r, 1, QTableWidgetItem(m['nome']))
            self.table_macchinari.setItem(r, 2, QTableWidgetItem(m['marca'] or ""))
            self.table_macchinari.setItem(r, 3, QTableWidgetItem(m['modello'] or ""))
            self.table_macchinari.setItem(r, 4, QTableWidgetItem(m['identificativo'] or ""))
            self.table_macchinari.setItem(r, 5, QTableWidgetItem(str(m['anno']) if m['anno'] else ""))
            self.table_macchinari.setItem(r, 6, QTableWidgetItem(m['note'] or ""))

    def salva_macchinario(self):
        nome = self.input_nome.text().strip()
        if not nome: return QMessageBox.warning(self, "Attenzione", "Il nome è obbligatorio.")

        anno_txt = self.input_anno.text().strip()
        anno_val = int(anno_txt) if anno_txt.isdigit() else None

        dati = {
            "nome": nome, "marca": self.input_marca.text(), "modello": self.input_modello.text(),
            "identificativo": self.input_identificativo.text(), "anno": anno_val, "note": self.input_note.text()
        }

        try:
            if self.macchinario_in_modifica_id:
                Macchinario.update(**dati).where(Macchinario.id == self.macchinario_in_modifica_id, Macchinario.user == self.user_id).execute()
            else:
                Macchinario.create(user=self.user_id, **dati)
            self._reset_form_macchinario()
            self.carica_macchinari()
        except Exception as e: QMessageBox.critical(self, "Errore", str(e))

    def prepara_modifica_macchinario(self):
        riga = self.table_macchinari.currentRow()
        if riga < 0: return
        self.macchinario_in_modifica_id = int(self.table_macchinari.item(riga, 0).text())
        
        m = Macchinario.get_or_none(Macchinario.id == self.macchinario_in_modifica_id, Macchinario.user == self.user_id)
        if m:
            self.input_nome.setText(m.nome)
            self.input_marca.setText(m.marca or "")
            self.input_modello.setText(m.modello or "")
            self.input_identificativo.setText(m.identificativo or "")
            self.input_anno.setText(str(m.anno) if m.anno else "")
            self.input_note.setText(m.note or "")

    def elimina_macchinario_selezionato(self):
        riga = self.table_macchinari.currentRow()
        if riga < 0: return
        m_id = int(self.table_macchinari.item(riga, 0).text())
        if QMessageBox.question(self, "Conferma", "Eliminare il macchinario (e le sue manutenzioni)?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            Macchinario.delete().where(Macchinario.id == m_id, Macchinario.user == self.user_id).execute()
            self._reset_form_macchinario()
            self.carica_macchinari()
            self.table_manutenzioni.setRowCount(0)

    # --- LOGICA MANUTENZIONI ---
    def _reset_form_manutenzione(self):
        self.manutenzione_in_modifica_id = None
        self.input_manut_data.setDate(QDate.currentDate())
        for i in (self.input_manut_descrizione, self.input_manut_fornitore, self.input_manut_costo, self.input_manut_note): i.clear()

    def carica_manutenzioni(self):
        riga = self.table_macchinari.currentRow()
        if riga < 0: return
        m_id = int(self.table_macchinari.item(riga, 0).text())
        
        self.table_manutenzioni.setRowCount(0)
        manutenzioni = list(ManutenzioneMacchinario.select().where(ManutenzioneMacchinario.macchinario == m_id, ManutenzioneMacchinario.user == self.user_id).order_by(ManutenzioneMacchinario.data_manutenzione.desc()).dicts())
        
        for m in manutenzioni:
            r = self.table_manutenzioni.rowCount()
            self.table_manutenzioni.insertRow(r)
            self.table_manutenzioni.setItem(r, 0, QTableWidgetItem(str(m['id'])))
            data_it = datetime.strptime(m['data_manutenzione'], "%Y-%m-%d").strftime("%d/%m/%Y") if m['data_manutenzione'] else ""
            self.table_manutenzioni.setItem(r, 1, QTableWidgetItem(data_it))
            self.table_manutenzioni.setItem(r, 2, QTableWidgetItem(m['tipo_manutenzione']))
            self.table_manutenzioni.setItem(r, 3, QTableWidgetItem(m['descrizione'] or ""))
            self.table_manutenzioni.setItem(r, 4, QTableWidgetItem(m['fornitore'] or ""))
            self.table_manutenzioni.setItem(r, 5, QTableWidgetItem(f"{m['costo']:.2f} €" if m['costo'] else ""))
            self.table_manutenzioni.setItem(r, 6, QTableWidgetItem(m['note'] or ""))

    def salva_manutenzione(self):
        riga_m = self.table_macchinari.currentRow()
        if riga_m < 0: return QMessageBox.warning(self, "Errore", "Seleziona un macchinario dalla tabella in alto prima di salvare una manutenzione.")
        m_id = int(self.table_macchinari.item(riga_m, 0).text())

        descrizione = self.input_manut_descrizione.text().strip()
        if not descrizione: return QMessageBox.warning(self, "Attenzione", "Inserisci la descrizione.")
        
        costo_val = parse_decimal(self.input_manut_costo.text(), allow_zero=True)

        dati = {
            "macchinario": m_id,
            "data_manutenzione": self.input_manut_data.date().toString("yyyy-MM-dd"),
            "tipo_manutenzione": self.combo_manut_tipo.currentText(),
            "descrizione": descrizione,
            "fornitore": self.input_manut_fornitore.text(),
            "costo": costo_val,
            "note": self.input_manut_note.text()
        }

        try:
            if self.manutenzione_in_modifica_id:
                ManutenzioneMacchinario.update(**dati).where(ManutenzioneMacchinario.id == self.manutenzione_in_modifica_id, ManutenzioneMacchinario.user == self.user_id).execute()
            else:
                ManutenzioneMacchinario.create(user=self.user_id, **dati)
            self._reset_form_manutenzione()
            self.carica_manutenzioni()
        except Exception as e: QMessageBox.critical(self, "Errore", str(e))

    def prepara_modifica_manutenzione(self):
        riga = self.table_manutenzioni.currentRow()
        if riga < 0: return
        self.manutenzione_in_modifica_id = int(self.table_manutenzioni.item(riga, 0).text())
        
        m = ManutenzioneMacchinario.get_or_none(ManutenzioneMacchinario.id == self.manutenzione_in_modifica_id, ManutenzioneMacchinario.user == self.user_id)
        if m:
            self.input_manut_data.setDate(QDate.fromString(m.data_manutenzione, "yyyy-MM-dd"))
            self.combo_manut_tipo.setCurrentText(m.tipo_manutenzione)
            self.input_manut_descrizione.setText(m.descrizione or "")
            self.input_manut_fornitore.setText(m.fornitore or "")
            self.input_manut_costo.setText(str(m.costo) if m.costo else "")
            self.input_manut_note.setText(m.note or "")

    def elimina_manutenzione_selezionata(self):
        riga = self.table_manutenzioni.currentRow()
        if riga < 0: return
        m_id = int(self.table_manutenzioni.item(riga, 0).text())
        if QMessageBox.question(self, "Conferma", "Eliminare la manutenzione?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            ManutenzioneMacchinario.delete().where(ManutenzioneMacchinario.id == m_id, ManutenzioneMacchinario.user == self.user_id).execute()
            self._reset_form_manutenzione()
            self.carica_manutenzioni()