import sqlite3
from datetime import datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QFormLayout,
    QFrame,
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
)

from app_utils import format_eur, is_blank, TabellaIsolata
from database import get_azienda_info, get_conn, save_azienda_info


class AziendaInfoPage(QWidget):
    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = int(user_id)

        self._build_ui()
        self.load_data(show_errors=False)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(12)

        title = QLabel("Azienda - Informazioni")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        main_layout.addWidget(title)

        subtitle = QLabel("Anagrafica aziendale e andamento economico annuale.")
        subtitle.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        main_layout.addWidget(subtitle)

        card_anagrafica = QFrame(self)
        card_anagrafica.setFrameShape(QFrame.StyledPanel)
        form_layout = QFormLayout(card_anagrafica)
        form_layout.setLabelAlignment(Qt.AlignLeft)
        form_layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)

        self.value_nome = self._create_info_label()
        self.value_piva = self._create_info_label()
        self.value_occupazione = self._create_info_label()
        self.value_data_creazione = self._create_info_label()

        form_layout.addRow("Nome azienda:", self.value_nome)
        form_layout.addRow("P.IVA:", self.value_piva)
        form_layout.addRow("Occupazione:", self.value_occupazione)
        form_layout.addRow("Data creazione:", self.value_data_creazione)
        main_layout.addWidget(card_anagrafica)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        button_edit = QPushButton("Modifica informazioni", self)
        button_edit.clicked.connect(self.open_edit_dialog)
        action_row.addWidget(button_edit)

        button_reload = QPushButton("Aggiorna", self)
        button_reload.clicked.connect(lambda: self.load_data(show_errors=True))
        action_row.addWidget(button_reload)

        action_row.addStretch(1)
        main_layout.addLayout(action_row)

        self.table_andamento = TabellaIsolata(0, 2, self)
        self.table_andamento.setHorizontalHeaderLabels(["Metrica", "Valore"])
        self.table_andamento.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_andamento.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_andamento.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_andamento.setAlternatingRowColors(True)
        self.table_andamento.verticalHeader().setVisible(False)

        header = self.table_andamento.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)

        main_layout.addWidget(self.table_andamento, 1)

    def _create_info_label(self) -> QLabel:
        label = QLabel("-")
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    def _normalizza_piva(self, raw_value: str) -> str:
        value = (raw_value or "").strip().upper()
        if value.startswith("IT"):
            value = value[2:]

        cleaned = []
        for ch in value:
            if ch.isdigit():
                cleaned.append(ch)
            elif ch in (" ", ".", "-"):
                continue
            else:
                return ""

        return "".join(cleaned)

    def _piva_is_valid(self, piva_value: str) -> bool:
        if len(piva_value) != 11 or not piva_value.isdigit():
            return False

        checksum = 0
        for idx, char in enumerate(piva_value[:10]):
            digit = int(char)
            if idx % 2 == 0:
                checksum += digit
            else:
                doubled = digit * 2
                checksum += doubled - 9 if doubled > 9 else doubled

        control = (10 - (checksum % 10)) % 10
        return control == int(piva_value[10])

    def _format_data_info_azienda(self, raw_value, fallback: str = "-") -> str:
        testo = (raw_value or "").strip()
        if not testo:
            return fallback

        for fmt in (
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%d/%m/%Y",
            "%d-%m-%Y",
        ):
            try:
                return datetime.strptime(testo, fmt).strftime("%d/%m/%Y")
            except ValueError:
                continue

        return testo

    def _parse_qdate(self, raw_value: str) -> QDate:
        text = (raw_value or "").strip()
        if not text:
            return QDate.currentDate()

        for fmt in (
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%d/%m/%Y",
            "%d-%m-%Y",
        ):
            try:
                dt = datetime.strptime(text, fmt)
                return QDate(dt.year, dt.month, dt.day)
            except ValueError:
                continue

        return QDate.currentDate()

    def _calcola_totali_manutenzioni_azienda(
        self,
        data_da_db: str | None = None,
        data_a_db: str | None = None,
        show_errors: bool = True,
    ):
        params = [self.user_id]
        where_clause = "WHERE user_id=?"

        if data_da_db and data_a_db:
            where_clause += " AND data_manutenzione BETWEEN ? AND ?"
            params.extend([data_da_db, data_a_db])

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    f"""
                    SELECT
                        COALESCE(SUM(COALESCE(costo, 0)), 0),
                        COUNT(id)
                    FROM manutenzioni_macchinari
                    {where_clause}
                """,
                    tuple(params),
                )
                row = c.fetchone()
        except sqlite3.Error as exc:
            if show_errors:
                QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return 0.0, 0

        totale = float((row[0] if row else 0) or 0)
        numero = int((row[1] if row else 0) or 0)
        return totale, numero

    def _calcola_totali_annuali_azienda_info(self, anno: int, show_errors: bool = True):
        data_da = f"{anno:04d}-01-01"
        data_a = f"{anno:04d}-12-31"

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    """
                    SELECT
                        COUNT(id),
                        COALESCE(SUM(CASE WHEN tipo='ENTRATA' THEN importo ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN tipo='USCITA' THEN importo ELSE 0 END), 0)
                    FROM movimenti
                    WHERE user_id=? AND data_op BETWEEN ? AND ?
                """,
                    (self.user_id, data_da, data_a),
                )
                row = c.fetchone()
        except sqlite3.Error as exc:
            if show_errors:
                QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return None

        movimenti = int((row[0] if row else 0) or 0)
        entrate = float((row[1] if row else 0) or 0)
        uscite_movimenti = float((row[2] if row else 0) or 0)

        uscite_manutenzioni, _ = self._calcola_totali_manutenzioni_azienda(
            data_da_db=data_da,
            data_a_db=data_a,
            show_errors=show_errors,
        )
        uscite = uscite_movimenti + uscite_manutenzioni

        return {
            "movimenti": movimenti,
            "entrate": entrate,
            "uscite": uscite,
            "utile": entrate - uscite,
        }

    def _fill_andamento_table(self, righe: list[tuple[str, str]]):
        self.table_andamento.setRowCount(len(righe))

        for row_index, (metrica, valore) in enumerate(righe):
            metrica_item = QTableWidgetItem(metrica)
            metrica_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

            valore_item = QTableWidgetItem(valore)
            valore_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            self.table_andamento.setItem(row_index, 0, metrica_item)
            self.table_andamento.setItem(row_index, 1, valore_item)

    def load_data(self, show_errors: bool = True):
        try:
            info = get_azienda_info(self.user_id)
        except sqlite3.Error as exc:
            if show_errors:
                QMessageBox.critical(self, "Errore DB", f"Errore database: {exc}")
            return

        nome = (info.get("nome_azienda") or "").strip()
        piva = (info.get("piva") or "").strip()
        occupazione = (info.get("occupazione") or "").strip()
        data_creazione = info.get("data_creazione") or ""

        self.value_nome.setText(nome if nome else "-")
        self.value_piva.setText(piva if piva else "-")
        self.value_occupazione.setText(occupazione if occupazione else "-")
        self.value_data_creazione.setText(self._format_data_info_azienda(data_creazione, fallback="-"))

        anno_corrente = datetime.now().year
        anno_precedente = anno_corrente - 1

        stats_precedente = self._calcola_totali_annuali_azienda_info(anno_precedente, show_errors=show_errors)
        stats_corrente = self._calcola_totali_annuali_azienda_info(anno_corrente, show_errors=show_errors)
        if stats_precedente is None or stats_corrente is None:
            return

        righe: list[tuple[str, str]] = []
        if stats_precedente["movimenti"] > 0:
            righe.extend(
                [
                    (f"Entrate {anno_precedente}", format_eur(stats_precedente["entrate"])),
                    (f"Uscite {anno_precedente}", format_eur(stats_precedente["uscite"])),
                    (f"Utile {anno_precedente}", format_eur(stats_precedente["utile"])),
                ]
            )

        righe.extend(
            [
                (f"Entrate {anno_corrente}", format_eur(stats_corrente["entrate"])),
                (f"Uscite {anno_corrente}", format_eur(stats_corrente["uscite"])),
                (f"Utile {anno_corrente}", format_eur(stats_corrente["utile"])),
            ]
        )

        self._fill_andamento_table(righe)

    def open_edit_dialog(self):
        info = get_azienda_info(self.user_id)

        dialog = QDialog(self)
        dialog.setWindowTitle("Modifica informazioni azienda")
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        input_nome = QLineEdit((info.get("nome_azienda") or "").strip(), dialog)
        input_piva = QLineEdit((info.get("piva") or "").strip(), dialog)
        input_occupazione = QLineEdit((info.get("occupazione") or "").strip(), dialog)

        data_value = info.get("data_creazione") or ""
        input_data = QDateEdit(dialog)
        input_data.setDisplayFormat("dd/MM/yyyy")
        input_data.setCalendarPopup(True)
        input_data.setDate(self._parse_qdate(data_value))

        form.addRow("Nome azienda:", input_nome)
        form.addRow("P.IVA:", input_piva)
        form.addRow("Occupazione:", input_occupazione)
        form.addRow("Data creazione:", input_data)

        layout.addLayout(form)

        row_buttons = QHBoxLayout()
        row_buttons.addStretch(1)

        button_cancel = QPushButton("Annulla", dialog)
        button_cancel.clicked.connect(dialog.reject)
        row_buttons.addWidget(button_cancel)

        button_save = QPushButton("Salva", dialog)
        button_save.clicked.connect(
            lambda: self._salva_modifica_info_azienda(
                dialog,
                input_nome,
                input_piva,
                input_occupazione,
                input_data,
            )
        )
        row_buttons.addWidget(button_save)

        layout.addLayout(row_buttons)
        dialog.exec()

    def _salva_modifica_info_azienda(
        self,
        dialog: QDialog,
        input_nome: QLineEdit,
        input_piva: QLineEdit,
        input_occupazione: QLineEdit,
        input_data: QDateEdit,
    ):
        piva_raw = input_piva.text().strip()
        piva_clean = ""

        if not is_blank(piva_raw):
            piva_clean = self._normalizza_piva(piva_raw)
            if len(piva_clean) != 11:
                QMessageBox.critical(
                    dialog,
                    "Errore",
                    "P.IVA non valida. Inserisci 11 cifre (puoi usare anche prefisso IT).",
                )
                return

            if not self._piva_is_valid(piva_clean):
                QMessageBox.critical(dialog, "Errore", "P.IVA non valida (checksum errato).")
                return

        data_iso = input_data.date().toString("yyyy-MM-dd")
        if is_blank(data_iso):
            QMessageBox.critical(dialog, "Errore", "Inserisci la data di creazione.")
            return

        try:
            save_azienda_info(
                self.user_id,
                input_nome.text().strip(),
                piva_clean,
                input_occupazione.text().strip(),
                data_iso,
            )
        except sqlite3.Error as exc:
            QMessageBox.critical(dialog, "Errore DB", f"Errore database: {exc}")
            return

        dialog.accept()
        self.load_data(show_errors=False)
        QMessageBox.information(self, "Successo", "Informazioni azienda aggiornate.")
