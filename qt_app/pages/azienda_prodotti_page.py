from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app_utils import TabellaIsolata
from models import Movimento # Usiamo Peewee!
from services.product_parser_utils import (
    PRODUCT_CATEGORY_OPTIONS,
    extract_products_rows_from_parser_text
)

class AziendaProdottiPage(QWidget):
    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = int(user_id)
        self._build_ui()
        self.carica_storico_prodotti(show_errors=False)

    def _build_ui(self):
        STYLE_BTN_INFO = "background-color: #17a2b8; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_SECONDARIO = "background-color: #6c757d; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)

        header = QVBoxLayout()
        titolo = QLabel("📦 Archivio Prodotti Acquistati")
        titolo.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        header.addWidget(titolo)
        header.addWidget(QLabel("Cerca e analizza i singoli articoli (es. concimi, sementi) estratti dalle fatture."))
        main_layout.addLayout(header)

        frame_filtri = QFrame()
        frame_filtri.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        layout_filtri = QGridLayout(frame_filtri)

        self.check_data_da = QCheckBox("Data da:")
        self.check_data_da.toggled.connect(lambda on: self.date_data_da.setEnabled(on))
        self.date_data_da = QDateEdit(QDate.currentDate())
        self.date_data_da.setDisplayFormat("dd/MM/yyyy")
        self.date_data_da.setEnabled(False)

        self.check_data_a = QCheckBox("Data a:")
        self.check_data_a.toggled.connect(lambda on: self.date_data_a.setEnabled(on))
        self.date_data_a = QDateEdit(QDate.currentDate())
        self.date_data_a.setDisplayFormat("dd/MM/yyyy")
        self.date_data_a.setEnabled(False)

        self.combo_tipo_costo = QComboBox()
        self.combo_tipo_costo.addItems(["Tutti", "Variabili", "Fissi"])

        layout_filtri.addWidget(self.check_data_da, 0, 0)
        layout_filtri.addWidget(self.date_data_da, 0, 1)
        layout_filtri.addWidget(self.check_data_a, 0, 2)
        layout_filtri.addWidget(self.date_data_a, 0, 3)
        layout_filtri.addWidget(QLabel("<b>Costo:</b>"), 0, 4)
        layout_filtri.addWidget(self.combo_tipo_costo, 0, 5)

        self.input_fattura = QLineEdit(placeholderText="N. fattura")
        self.input_fornitore = QLineEdit(placeholderText="Fornitore")
        self.input_prodotto = QLineEdit(placeholderText="Nome prodotto")
        self.combo_categoria = QComboBox()
        self.combo_categoria.addItems(["Tutte", *PRODUCT_CATEGORY_OPTIONS])
        
        layout_filtri.addWidget(QLabel("<b>N. fattura:</b>"), 1, 0)
        layout_filtri.addWidget(self.input_fattura, 1, 1)
        layout_filtri.addWidget(QLabel("<b>Fornitore:</b>"), 1, 2)
        layout_filtri.addWidget(self.input_fornitore, 1, 3, 1, 3)
        layout_filtri.addWidget(QLabel("<b>Prodotto:</b>"), 2, 0)
        layout_filtri.addWidget(self.input_prodotto, 2, 1)
        layout_filtri.addWidget(QLabel("<b>Categoria:</b>"), 2, 2)
        layout_filtri.addWidget(self.combo_categoria, 2, 3)

        row_buttons = QHBoxLayout()
        btn_cerca = QPushButton("Cerca Prodotti")
        btn_cerca.setStyleSheet(STYLE_BTN_INFO)
        btn_cerca.clicked.connect(lambda: self.carica_storico_prodotti(True))
        
        btn_reset = QPushButton("Reset Filtri")
        btn_reset.setStyleSheet(STYLE_BTN_SECONDARIO)
        btn_reset.clicked.connect(self.pulisci_filtri)

        self.label_stato = QLabel("Nessun prodotto caricato.")
        self.label_stato.setStyleSheet("color: #e67e22; font-weight: bold;")
        
        row_buttons.addWidget(btn_cerca)
        row_buttons.addWidget(btn_reset)
        row_buttons.addWidget(self.label_stato)
        row_buttons.addStretch()
        layout_filtri.addLayout(row_buttons, 3, 0, 1, 6)

        main_layout.addWidget(frame_filtri)

        self.table_prodotti = TabellaIsolata(0, 9)
        self.table_prodotti.setHorizontalHeaderLabels([
            "Data", "N. fattura", "Fornitore", "Prodotto", "Categoria", 
            "Qta", "Totale (€)", "Tipo costo", "Gruppi"
        ])
        self.table_prodotti.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_prodotti.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        main_layout.addWidget(self.table_prodotti, 1)

    def pulisci_filtri(self):
        self.check_data_da.setChecked(False)
        self.check_data_a.setChecked(False)
        for i in (self.input_fattura, self.input_fornitore, self.input_prodotto): i.clear()
        self.combo_categoria.setCurrentIndex(0)
        self.combo_tipo_costo.setCurrentIndex(0)
        self.carica_storico_prodotti()

    def carica_storico_prodotti(self, show_errors=True):
        query = Movimento.select().where(Movimento.user == self.user_id)
        if self.check_data_da.isChecked():
            query = query.where(Movimento.data_op >= self.date_data_da.date().toString("yyyy-MM-dd"))
        if self.check_data_a.isChecked():
            query = query.where(Movimento.data_op <= self.date_data_a.date().toString("yyyy-MM-dd"))

        try:
            movimenti = list(query.order_by(Movimento.data_op.desc()).dicts())
            self.table_prodotti.setRowCount(0)
            righe_inserite = 0
            
            f_fatt = self.input_fattura.text().lower()
            f_forn = self.input_fornitore.text().lower()
            f_prod = self.input_prodotto.text().lower()
            f_cat = self.combo_categoria.currentText()
            f_costo = self.combo_tipo_costo.currentText()

            for mov in movimenti:
                # Controlla campi fattura in python (velocissimo)
                if f_fatt and f_fatt not in str(mov.get('parser_invoice_number') or "").lower(): continue
                if f_forn and f_forn not in str(mov.get('parser_supplier_name') or "").lower(): continue

                testo_prodotti = mov.get('parser_products')
                if not testo_prodotti: continue

                # Parsa il testo testuale salvato dal PDF
                lista_prodotti = extract_products_rows_from_parser_text(testo_prodotti)
                for p in lista_prodotti:
                    if f_prod and f_prod not in p['description'].lower(): continue
                    if f_cat != "Tutte" and p['category'] != f_cat: continue
                    if f_costo != "Tutti" and p['cost_type'] != f_costo: continue

                    self.table_prodotti.insertRow(righe_inserite)
                    self.table_prodotti.setItem(righe_inserite, 0, QTableWidgetItem(mov['data_op']))
                    self.table_prodotti.setItem(righe_inserite, 1, QTableWidgetItem(mov.get('parser_invoice_number') or "-"))
                    self.table_prodotti.setItem(righe_inserite, 2, QTableWidgetItem(mov.get('parser_supplier_name') or "-"))
                    self.table_prodotti.setItem(righe_inserite, 3, QTableWidgetItem(p['description']))
                    self.table_prodotti.setItem(righe_inserite, 4, QTableWidgetItem(p['category']))
                    self.table_prodotti.setItem(righe_inserite, 5, QTableWidgetItem(str(p['quantity'])))
                    self.table_prodotti.setItem(righe_inserite, 6, QTableWidgetItem(str(p['line_total'])))
                    self.table_prodotti.setItem(righe_inserite, 7, QTableWidgetItem(p['cost_type']))
                    self.table_prodotti.setItem(righe_inserite, 8, QTableWidgetItem(p['groups']))
                    righe_inserite += 1

            self.label_stato.setText(f"Mostrando {righe_inserite} prodotti.")
        except Exception as e:
            if show_errors: QMessageBox.critical(self, "Errore", str(e))