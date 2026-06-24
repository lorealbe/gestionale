import sqlite3
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QFormLayout,
    QLineEdit, QPushButton, QComboBox, QMessageBox, QHeaderView, QAbstractItemView, QGridLayout, QSplitter, QTableWidgetItem
)

from app_utils import TabellaIsolata
from database import add_soggetto, update_soggetto, delete_soggetto, list_soggetti

class AnagraficaPage(QWidget):
    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.soggetto_in_modifica_id = None
        self._build_ui()
        self.carica_soggetti()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        header_layout = QVBoxLayout()
        titolo = QLabel("👥 Anagrafica Clienti e Fornitori")
        titolo.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        sottotitolo = QLabel("Gestisci i contatti della tua azienda per velocizzare la fatturazione.")
        sottotitolo.setStyleSheet("font-size: 14px; color: #7f8c8d;")
        header_layout.addWidget(titolo)
        header_layout.addWidget(sottotitolo)
        main_layout.addLayout(header_layout)

        main_splitter = QSplitter(Qt.Horizontal)

        # --- SINISTRA: Form di Inserimento ---
        frame_form = QFrame()
        frame_form.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        layout_form = QVBoxLayout(frame_form)
        layout_form.setContentsMargins(15, 15, 15, 15)

        lbl_form = QLabel("Nuovo Contatto")
        lbl_form.setStyleSheet("font-size: 18px; font-weight: bold; color: #34495e; margin-bottom: 10px; border: none;")
        layout_form.addWidget(lbl_form)

        form = QFormLayout()
        self.combo_tipo = QComboBox()
        self.combo_tipo.addItems(["Fornitore", "Cliente", "Entrambi", "Consulente/Commercialista"])
        self.input_ragione_sociale = QLineEdit()
        self.input_piva = QLineEdit()
        self.input_cf = QLineEdit()
        self.input_email = QLineEdit()
        self.input_telefono = QLineEdit()
        self.input_indirizzo = QLineEdit()
        
        form.addRow("Tipo:", self.combo_tipo)
        form.addRow("Ragione Sociale/Nome:", self.input_ragione_sociale)
        form.addRow("Partita IVA:", self.input_piva)
        form.addRow("Codice Fiscale:", self.input_cf)
        form.addRow("Email:", self.input_email)
        form.addRow("Telefono:", self.input_telefono)
        form.addRow("Indirizzo:", self.input_indirizzo)
        layout_form.addLayout(form)

        # Pulsanti
        grid_btn = QGridLayout()
        self.btn_salva = QPushButton("Salva Contatto")
        self.btn_salva.setStyleSheet("background-color: #28a745; color: white; font-weight: bold; padding: 8px; border-radius: 5px;")
        self.btn_salva.clicked.connect(self.salva_soggetto)
        
        self.btn_pulisci = QPushButton("Annulla")
        self.btn_pulisci.setStyleSheet("background-color: #6c757d; color: white; font-weight: bold; padding: 8px; border-radius: 5px;")
        self.btn_pulisci.clicked.connect(self.pulisci_form)

        self.btn_elimina = QPushButton("Elimina Selezionato")
        self.btn_elimina.setStyleSheet("background-color: #dc3545; color: white; font-weight: bold; padding: 8px; border-radius: 5px;")
        self.btn_elimina.clicked.connect(self.elimina_soggetto_selezionato)

        grid_btn.addWidget(self.btn_salva, 0, 0)
        grid_btn.addWidget(self.btn_pulisci, 0, 1)
        grid_btn.addWidget(self.btn_elimina, 1, 0, 1, 2)
        layout_form.addLayout(grid_btn)
        
        self.lbl_stato = QLabel("")
        self.lbl_stato.setStyleSheet("color: #e67e22; font-weight: bold; margin-top: 10px; border: none;")
        layout_form.addWidget(self.lbl_stato)
        layout_form.addStretch()

        main_splitter.addWidget(frame_form)

        # --- DESTRA: Tabella Contatti ---
        frame_tab = QFrame()
        frame_tab.setStyleSheet("background-color: white; border: 1px solid #ddd; border-radius: 8px;")
        layout_tab = QVBoxLayout(frame_tab)
        
        self.input_ricerca = QLineEdit()
        self.input_ricerca.setPlaceholderText("Cerca per nome, P.IVA o email...")
        self.input_ricerca.textChanged.connect(self.carica_soggetti)
        layout_tab.addWidget(self.input_ricerca)

        self.table = TabellaIsolata(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "Tipo", "Ragione Sociale", "P.IVA/CF", "Email", "Telefono"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        # Doppio clic per modificare
        self.table.itemDoubleClicked.connect(self.prepara_modifica)
        layout_tab.addWidget(self.table)

        main_splitter.addWidget(frame_tab)
        main_splitter.setSizes([350, 650])
        main_layout.addWidget(main_splitter, 1)

    def pulisci_form(self):
        self.soggetto_in_modifica_id = None
        self.input_ragione_sociale.clear()
        self.input_piva.clear()
        self.input_cf.clear()
        self.input_email.clear()
        self.input_telefono.clear()
        self.input_indirizzo.clear()
        self.lbl_stato.setText("")
        self.btn_salva.setText("Salva Contatto")

    def carica_soggetti(self):
        self.table.setRowCount(0)
        ricerca = self.input_ricerca.text().lower()
        
        try:
            soggetti = list_soggetti(self.user_id)
            riga = 0
            for s in soggetti:
                # Filtro ricerca veloce
                search_str = f"{s['ragione_sociale']} {s['partita_iva']} {s['email']}".lower()
                if ricerca and ricerca not in search_str:
                    continue
                    
                self.table.insertRow(riga)
                self.table.setItem(riga, 0, QTableWidgetItem(str(s['id'])))
                
                item_tipo = QTableWidgetItem(s['tipo'])
                if s['tipo'] == "Fornitore": item_tipo.setForeground(Qt.red)
                elif s['tipo'] == "Cliente": item_tipo.setForeground(Qt.darkGreen)
                self.table.setItem(riga, 1, item_tipo)
                
                self.table.setItem(riga, 2, QTableWidgetItem(s['ragione_sociale']))
                piva_cf = s['partita_iva'] if s['partita_iva'] else s['codice_fiscale']
                self.table.setItem(riga, 3, QTableWidgetItem(piva_cf or ""))
                self.table.setItem(riga, 4, QTableWidgetItem(s['email'] or ""))
                self.table.setItem(riga, 5, QTableWidgetItem(s['telefono'] or ""))
                riga += 1
        except Exception as e:
            print(f"Errore caricamento anagrafica: {e}")

    def salva_soggetto(self):
        ragione = self.input_ragione_sociale.text().strip()
        if not ragione:
            QMessageBox.warning(self, "Attenzione", "La Ragione Sociale / Nome è obbligatoria.")
            return

        tipo = self.combo_tipo.currentText()
        piva = self.input_piva.text().strip()
        cf = self.input_cf.text().strip()
        email = self.input_email.text().strip()
        tel = self.input_telefono.text().strip()
        ind = self.input_indirizzo.text().strip()

        try:
            if self.soggetto_in_modifica_id:
                update_soggetto(self.user_id, self.soggetto_in_modifica_id, tipo, ragione, piva, cf, ind, email, tel)
                self.lbl_stato.setText("✅ Contatto aggiornato!")
            else:
                add_soggetto(self.user_id, tipo, ragione, piva, cf, ind, email, tel)
                self.lbl_stato.setText("✅ Contatto salvato!")
            
            self.pulisci_form()
            self.carica_soggetti()
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile salvare il contatto: {e}")

    def prepara_modifica(self):
        riga = self.table.currentRow()
        if riga < 0: return
        
        soggetto_id = int(self.table.item(riga, 0).text())
        self.soggetto_in_modifica_id = soggetto_id
        
        soggetti = list_soggetti(self.user_id)
        for s in soggetti:
            if s['id'] == soggetto_id:
                self.combo_tipo.setCurrentText(s['tipo'])
                self.input_ragione_sociale.setText(s['ragione_sociale'])
                self.input_piva.setText(s['partita_iva'] or "")
                self.input_cf.setText(s['codice_fiscale'] or "")
                self.input_email.setText(s['email'] or "")
                self.input_telefono.setText(s['telefono'] or "")
                self.input_indirizzo.setText(s['indirizzo'] or "")
                break
                
        self.btn_salva.setText("Aggiorna Contatto")
        self.lbl_stato.setText(f"✍️ Modifica contatto ID {soggetto_id}")

    def elimina_soggetto_selezionato(self):
        riga = self.table.currentRow()
        if riga < 0:
            QMessageBox.warning(self, "Attenzione", "Seleziona un contatto dalla tabella per eliminarlo.")
            return
            
        soggetto_id = int(self.table.item(riga, 0).text())
        nome = self.table.item(riga, 2).text()
        
        risp = QMessageBox.question(self, "Conferma Eliminazione", f"Vuoi davvero eliminare '{nome}'?", QMessageBox.Yes | QMessageBox.No)
        if risp == QMessageBox.Yes:
            try:
                delete_soggetto(self.user_id, soggetto_id)
                self.pulisci_form()
                self.carica_soggetti()
            except Exception as e:
                QMessageBox.critical(self, "Errore", f"Impossibile eliminare: {e}")