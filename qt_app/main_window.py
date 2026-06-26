import os
import shutil
import csv
from PySide6.QtCore import Qt, Signal, QTimer, QDate
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QFileDialog
)
from database import get_db_path, Movimento


class MainWindow(QMainWindow):
    change_user_requested = Signal()

    CATEGORIA_DASHBOARD = "Dashboard"
    CATEGORIA_AZIENDA = "Azienda"
    CATEGORIA_AGRICOLTURA = "Agricoltura"
    CATEGORIA_ATTREZZATURE = "Attrezzature"
    CATEGORIA_MACCHINARI = "Macchinari"
    CATEGORIA_ZOOTECNIA = "Zootecnia"
    CATEGORIA_ANAGRAFICA = "Anagrafica"

    CATEGORIES = (
        CATEGORIA_DASHBOARD,
        CATEGORIA_AZIENDA,
        CATEGORIA_AGRICOLTURA,
        CATEGORIA_ATTREZZATURE,
        CATEGORIA_MACCHINARI,
        CATEGORIA_ZOOTECNIA,
        CATEGORIA_ANAGRAFICA,
    )

    def __init__(self, user_id: int, username: str):
        super().__init__()
        self.user_id = int(user_id)
        self.username = username

        self.setWindowTitle(f"Gestione Azienda Agricola - {self.username}")
        self.resize(1200, 800)

        # Stile globale per correggere l'invisibilità di mese e anno nei calendari
        self.setStyleSheet("""
            QCalendarWidget QWidget#qt_calendar_navigationbar {
                background-color: #f8f9fa;
                border-bottom: 1px solid #ddd;
            }
            QCalendarWidget QToolButton {
                color: #2c3e50;
                font-weight: bold;
                background-color: transparent;
                padding: 4px;
            }
            QCalendarWidget QToolButton:hover {
                background-color: #e2e6ea;
                border-radius: 4px;
            }
            QCalendarWidget QMenu {
                background-color: white;
                color: #2c3e50;
                border: 1px solid #ccc;
            }
            QCalendarWidget QSpinBox {
                color: #2c3e50;
                background-color: white;
                border: 1px solid #ccc;
                border-radius: 3px;
                padding: 2px;
            }
        """)

        self.stack = QStackedWidget(self)
        self.stack.currentChanged.connect(self._adatta_altezza_dinamica)
        self.pages = {}
        self.page_containers = {}

        # ---> RIMOSSO IL CICLO FOR CHE CARICAVA TUTTO ALL'AVVIO <---

        self.setCentralWidget(self.stack)
        self._build_menu()
        self.statusBar().showMessage(f"Accesso effettuato come: {self.username}")
        
        # Questa riga chiamerà la nuova logica e caricherà in memoria SOLO la dashboard
        self.show_category(self.CATEGORIA_DASHBOARD)

    def _build_menu(self):
        menu_bar = self.menuBar()
        
        # --- MENU NAVIGAZIONE ---
        for category in self.CATEGORIES:
            action = QAction(category, self)
            action.triggered.connect(lambda _checked=False, name=category: self.show_category(name))
            menu_bar.addAction(action)

        # --- MENU DATI E BACKUP (NUOVO) ---
        menu_dati = menu_bar.addMenu("💾 Gestione Dati")
        
        action_backup = QAction("📦 Crea Backup Database", self)
        action_backup.triggered.connect(self._esegui_backup)
        menu_dati.addAction(action_backup)
        
        action_ripristina = QAction("🔄 Ripristina Backup", self)
        action_ripristina.triggered.connect(self._ripristina_backup)
        menu_dati.addAction(action_ripristina)
        menu_dati.addSeparator()
        
        action_esporta_csv = QAction("📊 Esporta Movimenti (Excel / Fogli Google)", self)
        action_esporta_csv.triggered.connect(self._esporta_csv)
        menu_dati.addAction(action_esporta_csv)

        # --- MENU ACCOUNT ---
        account_menu = menu_bar.addMenu("👤 Account")
        change_user_action = QAction("Cambia utente / Esci", self)
        change_user_action.triggered.connect(self._request_change_user)
        account_menu.addAction(change_user_action)

    # ==========================================
    # LOGICA DI BACKUP, RIPRISTINO ED EXPORT
    # ==========================================
    def _get_db_path(self):
        """Metodo pulito: usa la funzione centralizzata invece del cursore SQL."""
        return str(get_db_path())

    def _esporta_csv(self):
        percorso_salvataggio, _ = QFileDialog.getSaveFileName(
            self, "Esporta per Excel / Fogli Google",
            f"Export_Movimenti_{self.username}_{QDate.currentDate().toString('yyyy_MM_dd')}.csv",
            "File CSV (*.csv)"
        )
        if not percorso_salvataggio: return

        try:
            # Una riga per estrarre tutti i movimenti grazie all'ORM!
            movimenti = Movimento.select().where(Movimento.user == self.user_id).order_by(Movimento.data_op.desc()).dicts()

            with open(percorso_salvataggio, mode='w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';') 
                writer.writerow(["ID Movimento", "Data", "Tipo", "Categoria", "Descrizione", "Imponibile EUR", "IVA EUR", "Stato"])
                
                for r in movimenti:
                    imp = str(r['importo']).replace('.', ',') if r['importo'] is not None else "0,00"
                    iva = str(r['iva_importo']).replace('.', ',') if r['iva_importo'] is not None else "0,00"
                    writer.writerow([r['id'], r['data_op'], r['tipo'], r['categoria'], r['descrizione'], imp, iva, r['stato_pagamento']])

            QMessageBox.information(self, "Completato", "Dati esportati con successo!\nApri il file con Excel o Fogli Google.")
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Errore durante l'esportazione:\n{e}")

    def _esegui_backup(self):
        db_path = self._get_db_path()
        if not db_path or not os.path.exists(db_path):
            QMessageBox.critical(self, "Errore", "Impossibile localizzare il database attuale.")
            return

        dest_path, _ = QFileDialog.getSaveFileName(
            self, 
            "Salva Backup Database",
            f"Backup_Azienda_{QDate.currentDate().toString('yyyy_MM_dd')}.db",
            "Database SQLite (*.db)"
        )
        
        if not dest_path:
            return

        try:
            shutil.copy2(db_path, dest_path)
            QMessageBox.information(self, "Successo", "Backup salvato correttamente in:\n" + dest_path)
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Errore durante il backup:\n{e}")

    def _ripristina_backup(self):
        db_path = self._get_db_path()
        src_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Seleziona file di Backup da ripristinare", 
            "", 
            "Database SQLite (*.db)"
        )
        
        if not src_path:
            return

        risposta = QMessageBox.warning(
            self, 
            "Attenzione Pericolo Sovrascrittura",
            "Il ripristino SOVRASCRIVERÀ tutti i dati attuali con quelli del backup selezionato.\n\n"
            "Sei sicuro di voler procedere?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if risposta == QMessageBox.Yes:
            try:
                shutil.copy2(src_path, db_path)
                QMessageBox.information(self, "Ripristino Completato", "Backup ripristinato con successo!\n\nL'applicazione verrà ora chiusa per applicare le modifiche in sicurezza. Riaprila per continuare.")
                self.close() # Chiudiamo l'app per forzare il ricaricamento del DB
            except Exception as e:
                QMessageBox.critical(self, "Errore", f"Errore durante il ripristino:\n{e}")

    

    # ==========================================
    # LOGICA DI NAVIGAZIONE E UI
    # ==========================================
    def _create_category_page(self, category: str) -> QWidget:
        if category == self.CATEGORIA_DASHBOARD:    
            from qt_app.pages.dashboard_page import DashboardPage     
            page = DashboardPage(self.user_id, self)
            page.richiesta_navigazione.connect(self._gestisci_navigazione_dashboard)
            return page
        elif category == self.CATEGORIA_AZIENDA:
            from qt_app.pages.azienda_page import AziendaPage
            return AziendaPage(user_id=self.user_id, parent=self)
        if category == self.CATEGORIA_AGRICOLTURA:
            from qt_app.pages.agricoltura_page import AgricolturaPage
            return AgricolturaPage(user_id=self.user_id, parent=self)
        if category == self.CATEGORIA_ATTREZZATURE:
            from qt_app.pages.attrezzature_page import AttrezzaturePage
            return AttrezzaturePage(user_id=self.user_id, parent=self)
        if category == self.CATEGORIA_MACCHINARI:
            from qt_app.pages.macchinari_page import MacchinariPage
            return MacchinariPage(user_id=self.user_id, parent=self)
        if category == self.CATEGORIA_ZOOTECNIA:
            from qt_app.pages.zootecnia_page import ZootecniaPage
            return ZootecniaPage(user_id=self.user_id, parent=self)
        if category == self.CATEGORIA_ANAGRAFICA:
            from qt_app.pages.anagrafica_page import AnagraficaPage
            return AnagraficaPage(user_id=self.user_id, parent=self)
            
        return self._create_placeholder_page(category)

    def _gestisci_navigazione_dashboard(self, destinazione: str):
        mappa_destinazioni = {
            "agricoltura": self.CATEGORIA_AGRICOLTURA,
            "fatture": self.CATEGORIA_AZIENDA,
            "macchinari": self.CATEGORIA_MACCHINARI,
            "zootecnia": self.CATEGORIA_ZOOTECNIA
        }
        categoria_target = mappa_destinazioni.get(destinazione)
        if categoria_target:
            self.show_category(categoria_target)

    def _create_placeholder_page(self, category: str) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel(f"Area {category}")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        title.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        subtitle = QLabel(
            "Migrazione in corso: questa pagina verra portata da Tkinter a PySide6 passo passo."
        )
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)
        return page

    def _create_scrollable_container(self, page: QWidget) -> QScrollArea:
        container = QScrollArea(self)
        container.setWidgetResizable(True)
        container.setFrameShape(QFrame.NoFrame)
        container.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        container.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        container.setWidget(page)
        return container

    def show_category(self, category: str):
        # LAZY LOADING: Crea la pagina la primissima volta che l'utente ci clicca
        if category not in self.pages:
            # Imposta il cursore di "Attesa/Caricamento"
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            try:
                page = self._create_category_page(category)
                self.pages[category] = page
                container = self._create_scrollable_container(page)
                self.page_containers[category] = container
                self.stack.addWidget(container)
            finally:
                # Ripristina il cursore normale anche se ci sono stati errori
                QApplication.restoreOverrideCursor()

        # Ora la pagina esiste di sicuro, la recuperiamo e la mostriamo
        page_container = self.page_containers.get(category)
        if page_container is None:
            return
            
        self.stack.setCurrentWidget(page_container)
        self.statusBar().showMessage(f"Categoria attiva: {category}")

    def _request_change_user(self):
        conferma = QMessageBox.question(
            self,
            "Conferma",
            "Vuoi uscire e cambiare utente?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if conferma == QMessageBox.Yes:
            self.change_user_requested.emit()
            
    def _adatta_altezza_dinamica(self, index):
        current_widget = self.stack.widget(index)
        if not current_widget:
            return

        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        QTimer.singleShot(0, lambda: self._finalize_layout(current_widget))

    def _finalize_layout(self, widget):
        if not widget:
            return
        
        widget.updateGeometry()
        if widget.layout():
            widget.layout().activate()
            widget.layout().update()
        
        self.stack.adjustSize()
        self.update()