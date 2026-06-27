import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QSplitter
)

from app_utils import format_number, parse_decimal, TabellaIsolata
from database import (
    get_movimento_animali_group_labels,
    list_azienda_animali_entries,
    resolve_fattura_path,
)
from models import Movimento, Fattura, ProduzioneLatte, ProduzioneCarne, MovimentiAnimaliLink
from services.product_parser_utils import normalize_multiline_display_text


class AziendaMovimentiPage(QWidget):
    edit_movimento_requested = Signal(int)
    movimenti_changed = Signal()

    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = int(user_id)

        self._filtro_gruppi_animali_map: dict[str, int] = {}
        self._fattura_dettaglio_corrente = None

        self._build_ui()
        self.carica_movimenti(show_errors=False)

    def _build_ui(self):
        STYLE_BTN_MODIFICA = "background-color: #ffc107; color: black; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_ELIMINA = "background-color: #dc3545; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_SECONDARIO = "background-color: #6c757d; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"
        STYLE_BTN_INFO = "background-color: #17a2b8; color: white; font-weight: bold; padding: 8px; border-radius: 5px;"

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # HEADER
        header_layout = QVBoxLayout()
        titolo = QLabel("📜 Storico Movimenti e Fatture")
        titolo.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        sottotitolo = QLabel("Consulta le entrate, le uscite e apri rapidamente i documenti PDF.")
        sottotitolo.setStyleSheet("font-size: 14px; color: #7f8c8d;")
        header_layout.addWidget(titolo)
        header_layout.addWidget(sottotitolo)
        main_layout.addLayout(header_layout)

        # FILTRI
        frame_filtri = QFrame(self)
        frame_filtri.setStyleSheet("background-color: #f8f9fa; border: 1px solid #ddd; border-radius: 8px;")
        layout_filtri = QGridLayout(frame_filtri)
        layout_filtri.setContentsMargins(15, 15, 15, 15)

        self.combo_categoria = QComboBox(self)
        self.combo_categoria.addItem("Tutte")
        self.combo_categoria.currentIndexChanged.connect(self._on_filter_changed)

        self.combo_gruppo_animale = QComboBox(self)
        self.combo_gruppo_animale.addItem("Tutti")
        self.combo_gruppo_animale.currentIndexChanged.connect(self._on_filter_changed)

        self.input_descrizione = QLineEdit(self)
        self.input_descrizione.setPlaceholderText("Filtro descrizione")
        self.input_descrizione.returnPressed.connect(lambda: self.carica_movimenti(show_errors=True))

        layout_filtri.addWidget(QLabel("<b>Categoria:</b>"), 0, 0)
        layout_filtri.addWidget(self.combo_categoria, 0, 1)
        layout_filtri.addWidget(QLabel("<b>Gruppo animale:</b>"), 0, 2)
        layout_filtri.addWidget(self.combo_gruppo_animale, 0, 3)
        layout_filtri.addWidget(QLabel("<b>Descrizione:</b>"), 0, 4)
        layout_filtri.addWidget(self.input_descrizione, 0, 5)

        self.check_data_da = QCheckBox("Data da", self)
        self.check_data_da.toggled.connect(lambda on: self.date_data_da.setEnabled(on))
        self.date_data_da = QDateEdit(QDate.currentDate())
        self.date_data_da.setDisplayFormat("dd/MM/yyyy")
        self.date_data_da.setEnabled(False)

        self.check_data_a = QCheckBox("Data a", self)
        self.check_data_a.toggled.connect(lambda on: self.date_data_a.setEnabled(on))
        self.date_data_a = QDateEdit(QDate.currentDate())
        self.date_data_a.setDisplayFormat("dd/MM/yyyy")
        self.date_data_a.setEnabled(False)

        button_applica = QPushButton("Applica filtri")
        button_applica.setStyleSheet(STYLE_BTN_INFO)
        button_applica.clicked.connect(lambda: self.carica_movimenti(show_errors=True))

        button_pulisci = QPushButton("Pulisci")
        button_pulisci.setStyleSheet(STYLE_BTN_SECONDARIO)
        button_pulisci.clicked.connect(self.pulisci_filtri)

        layout_filtri.addWidget(self.check_data_da, 1, 0)
        layout_filtri.addWidget(self.date_data_da, 1, 1)
        layout_filtri.addWidget(self.check_data_a, 1, 2)
        layout_filtri.addWidget(self.date_data_a, 1, 3)
        layout_filtri.addWidget(button_applica, 1, 4)
        layout_filtri.addWidget(button_pulisci, 1, 5)

        main_layout.addWidget(frame_filtri)

        # SPLITTER PRINCIPALE VERTICALE
        main_splitter = QSplitter(Qt.Vertical)

        # WIDGET SUPERIORE (Tabella)
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        self.table_movimenti = TabellaIsolata(0, 7, self)
        self.table_movimenti.setHorizontalHeaderLabels(["ID", "Data", "Tipo", "Categoria", "Descrizione", "Importo", "IVA"])
        self.table_movimenti.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_movimenti.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_movimenti.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_movimenti.itemSelectionChanged.connect(self.carica_dettagli_fattura_movimento_selezionato)
        self.table_movimenti.cellDoubleClicked.connect(lambda _row, _col: self.richiedi_modifica_movimento())
        self.table_movimenti.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        top_layout.addWidget(self.table_movimenti)

        row_actions = QHBoxLayout()
        button_ricarica = QPushButton("Ricarica")
        button_ricarica.setStyleSheet(STYLE_BTN_SECONDARIO)
        button_ricarica.clicked.connect(lambda: self.carica_movimenti(show_errors=True))
        
        button_modifica = QPushButton("Modifica Selezionato")
        button_modifica.setStyleSheet(STYLE_BTN_MODIFICA)
        button_modifica.clicked.connect(self.richiedi_modifica_movimento)
        
        button_apri_fattura = QPushButton("Apri PDF Fattura")
        button_apri_fattura.setStyleSheet(STYLE_BTN_INFO)
        button_apri_fattura.clicked.connect(self.apri_fattura_movimento_selezionato)
        
        button_elimina = QPushButton("Elimina Selezionato")
        button_elimina.setStyleSheet(STYLE_BTN_ELIMINA)
        button_elimina.clicked.connect(self.elimina_movimento_selezionato)
        
        row_actions.addWidget(button_ricarica)
        row_actions.addWidget(button_modifica)
        row_actions.addWidget(button_apri_fattura)
        row_actions.addWidget(button_elimina)
        row_actions.addStretch()
        top_layout.addLayout(row_actions)
        main_splitter.addWidget(top_widget)

        # WIDGET INFERIORE (Dettagli)
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        dettagli_title = QLabel("📄 Dati della Fattura collegata")
        dettagli_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #34495e; padding-top: 10px;")
        bottom_layout.addWidget(dettagli_title)

        self.table_dettagli = TabellaIsolata(0, 2, self)
        self.table_dettagli.setHorizontalHeaderLabels(["Campo", "Valore Letto da PDF"])
        self.table_dettagli.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_dettagli.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        bottom_layout.addWidget(self.table_dettagli)
        
        main_splitter.addWidget(bottom_widget)
        main_layout.addWidget(main_splitter, 1)

        self._azzera_dettagli_fattura()

    def _on_filter_changed(self):
        self.carica_movimenti(show_errors=False)

    def _set_combo_items(self, combo: QComboBox, values: list[str], fallback_value: str):
        current = combo.currentText().strip()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(values)
        combo.setCurrentText(current if current in values else fallback_value)
        combo.blockSignals(False)

    def _carica_categorie_filtro(self, show_errors=True):
        try:
            categorie = [m.categoria for m in Movimento.select(Movimento.categoria).where((Movimento.user == self.user_id) & Movimento.categoria.is_null(False)).distinct()]
            categorie = sorted([c.strip() for c in categorie if c.strip()], key=str.lower)
            self._set_combo_items(self.combo_categoria, ["Tutte", *categorie], "Tutte")
        except Exception as exc:
            if show_errors: QMessageBox.critical(self, "Errore DB", str(exc))

    def _carica_gruppi_filtro(self, show_errors=True):
        try:
            entries = list_azienda_animali_entries(self.user_id)
            mapping, labels = {}, []
            for entry in entries:
                if entry.get("id", 0) <= 0: continue
                label = f"{entry.get('group_name', '')} | {entry.get('tipo_animale', '')} | {entry.get('finalita', '')} | {entry.get('capi', 0)} capi"
                mapping[label] = entry['id']
                labels.append(label)
            self._filtro_gruppi_animali_map = mapping
            self._set_combo_items(self.combo_gruppo_animale, ["Tutti", *labels], "Tutti")
        except Exception as exc:
            if show_errors: QMessageBox.critical(self, "Errore DB", str(exc))

    def pulisci_filtri(self):
        self.combo_categoria.setCurrentText("Tutte")
        self.combo_gruppo_animale.setCurrentText("Tutti")
        self.input_descrizione.clear()
        self.check_data_da.setChecked(False)
        self.check_data_a.setChecked(False)
        self.carica_movimenti(show_errors=False)

    def carica_movimenti(self, show_errors=True):
        self._carica_categorie_filtro(show_errors)
        self._carica_gruppi_filtro(show_errors)

        filtro_categoria = self.combo_categoria.currentText().strip()
        filtro_gruppo = self.combo_gruppo_animale.currentText().strip()
        filtro_desc = self.input_descrizione.text().strip()
        d_da = self.date_data_da.date().toString("yyyy-MM-dd") if self.check_data_da.isChecked() else None
        d_a = self.date_data_a.date().toString("yyyy-MM-dd") if self.check_data_a.isChecked() else None

        if d_da and d_a and d_da > d_a:
            if show_errors: QMessageBox.critical(self, "Errore", "La Data DA non può essere successiva alla Data A.")
            return

        query = Movimento.select().where(Movimento.user == self.user_id)

        if filtro_categoria and filtro_categoria != "Tutte":
            query = query.where(Movimento.categoria == filtro_categoria)
        if filtro_gruppo and filtro_gruppo != "Tutti":
            entry_id = self._filtro_gruppi_animali_map.get(filtro_gruppo)
            if entry_id:
                query = query.join(MovimentiAnimaliLink, on=(Movimento.id == MovimentiAnimaliLink.movimento)).where(MovimentiAnimaliLink.animale_entry == entry_id)
        if filtro_desc:
            query = query.where(Movimento.descrizione.contains(filtro_desc))
        if d_da: query = query.where(Movimento.data_op >= d_da)
        if d_a: query = query.where(Movimento.data_op <= d_a)

        try:
            rows = list(query.order_by(Movimento.data_op.desc(), Movimento.id.desc()).dicts())
        except Exception as exc:
            if show_errors: QMessageBox.critical(self, "Errore DB", str(exc))
            return

        self.table_movimenti.setRowCount(0)
        for idx, m in enumerate(rows):
            try: d_view = datetime.strptime(m['data_op'], "%Y-%m-%d").strftime("%d/%m/%Y")
            except: d_view = m['data_op']
            
            imp_view = m['importo'] or 0.0
            iva_view = m['iva_importo'] or 0.0

            if iva_view <= 0 and (m['categoria'] or "").upper() == "LATTE":
                p_iva = parse_decimal(m['parser_vat_total'], allow_zero=True)
                p_imp = parse_decimal(m['parser_taxable_total'], allow_zero=True)
                p_tot = parse_decimal(m['parser_total_amount'])
                if p_iva and p_iva > 0:
                    iva_view = p_iva
                    if p_imp and p_imp >= 0: imp_view = p_imp
                    elif p_tot and p_tot >= iva_view: imp_view = p_tot - iva_view

            self.table_movimenti.insertRow(idx)
            self.table_movimenti.setItem(idx, 0, QTableWidgetItem(str(m['id'])))
            self.table_movimenti.setItem(idx, 1, QTableWidgetItem(d_view))
            self.table_movimenti.setItem(idx, 2, QTableWidgetItem(m['tipo']))
            self.table_movimenti.setItem(idx, 3, QTableWidgetItem(m['categoria'] or ""))
            self.table_movimenti.setItem(idx, 4, QTableWidgetItem(m['descrizione'] or ""))
            
            it_imp = QTableWidgetItem(format_number(imp_view, 2))
            it_imp.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table_movimenti.setItem(idx, 5, it_imp)
            
            it_iva = QTableWidgetItem(format_number(iva_view, 2))
            it_iva.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table_movimenti.setItem(idx, 6, it_iva)

        self._azzera_dettagli_fattura()

    def _selected_movimento_id(self):
        row = self.table_movimenti.currentRow()
        if row < 0: return None
        return int(self.table_movimenti.item(row, 0).text())

    def _azzera_dettagli_fattura(self, text="Seleziona un movimento per vedere la fattura collegata."):
        self._fattura_dettaglio_corrente = None
        self.table_dettagli.setRowCount(1)
        self.table_dettagli.setItem(0, 0, QTableWidgetItem("Info"))
        self.table_dettagli.setItem(0, 1, QTableWidgetItem(text))

    def _format_data_parser(self, raw_value):
        if not raw_value: return ""
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try: return datetime.strptime(raw_value, fmt).strftime("%d/%m/%Y")
            except: continue
        return raw_value

    def carica_dettagli_fattura_movimento_selezionato(self):
        mov_id = self._selected_movimento_id()
        if mov_id is None:
            return self._azzera_dettagli_fattura()

        try:
            prod_ids = [p.id for p in ProduzioneLatte.select(ProduzioneLatte.id).where(ProduzioneLatte.movimento == mov_id)]
            fattura = Fattura.select().where((Fattura.user == self.user_id) & ((Fattura.movimento == mov_id) | (Fattura.produzione << prod_ids))).order_by(Fattura.data_caricamento.desc()).first()
            movimento = Movimento.get_by_id(mov_id)
        except Exception as e:
            return self._azzera_dettagli_fattura(f"Errore DB: {e}")

        if not fattura:
            return self._azzera_dettagli_fattura("Nessuna fattura collegata al movimento selezionato.")

        labels = get_movimento_animali_group_labels(self.user_id, mov_id)
        
        self._fattura_dettaglio_corrente = {
            "id": fattura.id,
            "data_caricamento": fattura.data_caricamento,
            "origine": fattura.origine or "",
            "nome_originale": fattura.nome_originale or "",
            "percorso_file": fattura.percorso_file or "",
            "invoice_number": movimento.parser_invoice_number or "",
            "invoice_date": self._format_data_parser(movimento.parser_invoice_date),
            "due_date": self._format_data_parser(movimento.parser_due_date),
            "supplier_name": movimento.parser_supplier_name or "",
            "supplier_vat": movimento.parser_supplier_vat or "",
            "customer_name": movimento.parser_customer_name or "",
            "customer_vat": movimento.parser_customer_vat or "",
            "total_amount": format_number(parse_decimal(movimento.parser_total_amount), 2) if parse_decimal(movimento.parser_total_amount) else "",
            "taxable_total": format_number(parse_decimal(movimento.parser_taxable_total), 2) if parse_decimal(movimento.parser_taxable_total) else "",
            "vat_total": format_number(parse_decimal(movimento.parser_vat_total), 2) if parse_decimal(movimento.parser_vat_total) else "",
            "payment_terms": movimento.parser_payment_terms or "",
            "gruppi_animali": normalize_multiline_display_text("\n".join(labels) if labels else "Nessun gruppo collegato"),
            "products": normalize_multiline_display_text(movimento.parser_products),
        }
        
        self.table_dettagli.setRowCount(0)
        righe = [
            ("ID Fattura", self._fattura_dettaglio_corrente["id"]),
            ("Nome file", self._fattura_dettaglio_corrente["nome_originale"]),
            ("Numero fattura", self._fattura_dettaglio_corrente["invoice_number"]),
            ("Data fattura", self._fattura_dettaglio_corrente["invoice_date"]),
            ("Fornitore", self._fattura_dettaglio_corrente["supplier_name"]),
            ("Totale documento", self._fattura_dettaglio_corrente["total_amount"]),
            ("Totale IVA", self._fattura_dettaglio_corrente["vat_total"]),
            ("Gruppi animali", self._fattura_dettaglio_corrente["gruppi_animali"]),
            ("Prodotti", self._fattura_dettaglio_corrente["products"]),
        ]
        for i, (k, v) in enumerate(righe):
            self.table_dettagli.insertRow(i)
            self.table_dettagli.setItem(i, 0, QTableWidgetItem(str(k)))
            self.table_dettagli.setItem(i, 1, QTableWidgetItem(str(v)))

    def apri_fattura_movimento_selezionato(self):
        if not self._fattura_dettaglio_corrente:
            return QMessageBox.warning(self, "Attenzione", "Seleziona un movimento con fattura.")
        
        path = resolve_fattura_path(self._fattura_dettaglio_corrente["percorso_file"])
        if not path.exists():
            return QMessageBox.critical(self, "Errore", "La fattura non esiste più nel percorso salvato.")
            
        try:
            if hasattr(os, "startfile"): os.startfile(str(path))
            elif sys.platform == "darwin": subprocess.run(["open", str(path)])
            else: subprocess.run(["xdg-open", str(path)])
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile aprire il file:\n{e}")

    def richiedi_modifica_movimento(self):
        mov_id = self._selected_movimento_id()
        if mov_id: self.edit_movimento_requested.emit(mov_id)

    def _elimina_file_fatture(self, percorsi):
        eliminati, non_trovati, errori = 0, 0, []
        for p in set(p for p in percorsi if p):
            path = resolve_fattura_path(p)
            try:
                if path.exists():
                    path.unlink()
                    eliminati += 1
                else: non_trovati += 1
            except Exception as e: errori.append(f"{path} ({e})")
        return eliminati, non_trovati, errori

    def elimina_movimento_selezionato(self):
        mov_id = self._selected_movimento_id()
        if not mov_id: return
        
        desc = self.table_movimenti.item(self.table_movimenti.currentRow(), 4).text()
        if QMessageBox.question(self, "Conferma", f"Vuoi eliminare il movimento:\n{desc}?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        try:
            with Movimento._meta.database.atomic():
                ProduzioneLatte.delete().where((ProduzioneLatte.movimento == mov_id) & (ProduzioneLatte.user == self.user_id)).execute()
                ProduzioneCarne.delete().where((ProduzioneCarne.movimento == mov_id) & (ProduzioneCarne.user == self.user_id)).execute()
                
                fatture = list(Fattura.select().where((Fattura.movimento == mov_id) & (Fattura.user == self.user_id)))
                percorsi = [f.percorso_file for f in fatture]
                fatture_eliminate = Fattura.delete().where((Fattura.movimento == mov_id) & (Fattura.user == self.user_id)).execute()
                
                Movimento.delete().where((Movimento.id == mov_id) & (Movimento.user == self.user_id)).execute()
        except Exception as e:
            return QMessageBox.critical(self, "Errore DB", str(e))

        el, no, err = self._elimina_file_fatture(percorsi)
        self.carica_movimenti(False)
        self.movimenti_changed.emit()
        
        if err: QMessageBox.warning(self, "Avviso", f"Movimento eliminato, ma i file PDF non sono stati cancellati:\n{err[0]}")
        else: QMessageBox.information(self, "Successo", "Movimento eliminato con successo!")