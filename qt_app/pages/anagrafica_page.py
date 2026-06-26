from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QFormLayout,
    QLineEdit, QPushButton, QComboBox, QMessageBox, QHeaderView, 
    QAbstractItemView, QGridLayout, QSplitter, QTableWidgetItem
)

from app_utils import TabellaIsolata
from models import Anagrafica # Importiamo direttamente il modello!

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
        header_layout.addWidget(titolo)
        header_layout.addWidget(QLabel("Gestisci i contatti della tua azienda per velocizzare la fatturazione."))
        main_layout.addLayout(header_layout)

        main_splitter = QSplitter(Qt.Horizontal)

        # --- SINISTRA: Form ---
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
        form.addRow("Ragione Sociale:", self.input_ragione_sociale)
        form.addRow("Partita IVA:", self.input_piva)
        form.addRow("Codice Fiscale:", self.input_cf)
        form.addRow("Email:", self.input_email)
        form.addRow("Telefono:", self.input_telefono)
        form.addRow("Indirizzo:", self.input_indirizzo)
        layout_form.addLayout(form)

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

        # --- DESTRA: Tabella ---
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
        self.table.itemDoubleClicked.connect(self.prepara_modifica)
        layout_tab.addWidget(self.table)

        main_splitter.addWidget(frame_tab)
        main_splitter.setSizes([350, 650])
        main_layout.addWidget(main_splitter, 1)

    def pulisci_form(self):
        self.soggetto_in_modifica_id = None
        for inpt in (self.input_ragione_sociale, self.input_piva, self.input_cf, self.input_email, self.input_telefono, self.input_indirizzo): inpt.clear()
        self.lbl_stato.setText("")
        self.btn_salva.setText("Salva Contatto")

    def carica_soggetti(self):
        self.table.setRowCount(0)
        ricerca = self.input_ricerca.text().lower()
        
        try:
            # Una singola chiamata ORM per prendere i soggetti
            soggetti = list(Anagrafica.select().where(Anagrafica.user == self.user_id).order_by(Anagrafica.ragione_sociale).dicts())
            for s in soggetti:
                if ricerca and ricerca not in f"{s['ragione_sociale']} {s['partita_iva']} {s['email']}".lower(): continue
                
                riga = self.table.rowCount()
                self.table.insertRow(riga)
                self.table.setItem(riga, 0, QTableWidgetItem(str(s['id'])))
                
                item_tipo = QTableWidgetItem(s['tipo'])
                item_tipo.setForeground(Qt.red if s['tipo'] == "Fornitore" else Qt.darkGreen)
                self.table.setItem(riga, 1, item_tipo)
                
                self.table.setItem(riga, 2, QTableWidgetItem(s['ragione_sociale']))
                self.table.setItem(riga, 3, QTableWidgetItem(s['partita_iva'] or s['codice_fiscale'] or ""))
                self.table.setItem(riga, 4, QTableWidgetItem(s['email'] or ""))
                self.table.setItem(riga, 5, QTableWidgetItem(s['telefono'] or ""))
        except Exception as e:
            print(f"Errore caricamento anagrafica: {e}")

    def salva_soggetto(self):
        ragione = self.input_ragione_sociale.text().strip()
        if not ragione: return QMessageBox.warning(self, "Attenzione", "La Ragione Sociale è obbligatoria.")

        dati = {
            "tipo": self.combo_tipo.currentText(), "ragione_sociale": ragione, "partita_iva": self.input_piva.text().strip(),
            "codice_fiscale": self.input_cf.text().strip(), "indirizzo": self.input_indirizzo.text().strip(),
            "email": self.input_email.text().strip(), "telefono": self.input_telefono.text().strip()
        }

        try:
            if self.soggetto_in_modifica_id:
                Anagrafica.update(**dati).where(Anagrafica.id == self.soggetto_in_modifica_id, Anagrafica.user == self.user_id).execute()
                self.lbl_stato.setText("✅ Contatto aggiornato!")
            else:
                Anagrafica.create(user=self.user_id, **dati)
                self.lbl_stato.setText("✅ Contatto salvato!")
            
            self.pulisci_form()
            self.carica_soggetti()
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile salvare il contatto: {e}")

    def prepara_modifica(self):
        riga = self.table.currentRow()
        if riga < 0: return
        
        self.soggetto_in_modifica_id = int(self.table.item(riga, 0).text())
        s = Anagrafica.get_or_none(Anagrafica.id == self.soggetto_in_modifica_id, Anagrafica.user == self.user_id)
        if s:
            self.combo_tipo.setCurrentText(s.tipo)
            self.input_ragione_sociale.setText(s.ragione_sociale)
            self.input_piva.setText(s.partita_iva or "")
            self.input_cf.setText(s.codice_fiscale or "")
            self.input_email.setText(s.email or "")
            self.input_telefono.setText(s.telefono or "")
            self.input_indirizzo.setText(s.indirizzo or "")
                
        self.btn_salva.setText("Aggiorna Contatto")
        self.lbl_stato.setText(f"✍️ Modifica contatto ID {self.soggetto_in_modifica_id}")

    def elimina_soggetto_selezionato(self):
        riga = self.table.currentRow()
        if riga < 0: return QMessageBox.warning(self, "Attenzione", "Seleziona un contatto.")
            
        soggetto_id = int(self.table.item(riga, 0).text())
        
        if QMessageBox.question(self, "Conferma", "Vuoi davvero eliminare questo contatto?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            try:
                Anagrafica.delete().where(Anagrafica.id == soggetto_id, Anagrafica.user == self.user_id).execute()
                self.pulisci_form()
                self.carica_soggetti()
            except Exception as e:
                QMessageBox.critical(self, "Errore", f"Impossibile eliminare: {e}")