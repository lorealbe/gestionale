import re
import shutil
import uuid
import importlib
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal, Slot, QRunnable, QThreadPool

from app_utils import format_number, parse_decimal
from database import get_conn, get_fatture_user_dir, resolve_fattura_path, to_storage_fattura_path
from services.product_parser_utils import (
    build_basic_product_storage_line, normalize_cost_type, normalize_product_category, serialize_product_storage_lines
)

# 1. Definizione Segnali per il Runnable (I QRunnable non possono avere segnali nativi)
class ParserSignals(QObject):
    success = Signal(object)
    error = Signal(str)
    progress = Signal(str)
    finished = Signal()

# 2. Il Task snello gestito dal Pool
class InvoiceParserTask(QRunnable):
    def __init__(self, parse_fn, file_path: str, on_success, on_error, on_done, on_progress):
        super().__init__()
        self._parse_fn = parse_fn
        self._file_path = str(file_path)
        self.signals = ParserSignals()
        
        # Colleghiamo direttamente i callback passati dalla GUI ai segnali thread-safe
        if on_success: self.signals.success.connect(on_success)
        if on_error: self.signals.error.connect(on_error)
        if on_progress: self.signals.progress.connect(on_progress)
        if on_done: self.signals.finished.connect(on_done)

    @Slot()
    def run(self):
        try:
            try:
                result = self._parse_fn(self._file_path, progress_cb=self.signals.progress.emit)
            except TypeError:
                result = self._parse_fn(self._file_path)
            self.signals.success.emit(result)
        except Exception as exc:
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()

class ZootecniaParserSupport:
    _PARSER_DB_FIELDS = (
        "invoice_number",
        "invoice_date",
        "due_date",
        "supplier_name",
        "supplier_vat",
        "customer_name",
        "customer_vat",
        "total_amount",
        "taxable_total",
        "vat_total",
        "payment_terms",
        "warnings",
        "products",
        "fields_view",
    )

    def _normalizza_importo(self, raw, allow_zero=False):
        return parse_decimal(raw, allow_zero=allow_zero, allow_negative=False)

    def _valore_parser_to_float(self, value, allow_zero=False):
        if value is None:
            return None

        if isinstance(value, (int, float)):
            number = float(value)
        else:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return self._normalizza_importo(str(value), allow_zero=allow_zero)

        if number < 0:
            return None
        if number == 0 and not allow_zero:
            return None
        return number

    def _valore_parser_to_text(self, value, decimals=2):
        number = self._valore_parser_to_float(value, allow_zero=True)
        if number is not None:
            return format_number(number, decimals)

        if value in (None, ""):
            return "-"
        return str(value).strip()

    def _get_parser_fatture_function(self):
        parse_invoice_pdf = getattr(self, "_parser_fatture_parse_fn", None)
        if parse_invoice_pdf is not None:
            return parse_invoice_pdf

        project_root = None
        current_file = Path(__file__).resolve()
        for parent in current_file.parents:
            candidate = parent / "parserFatture" / "parserFatture.py"
            if candidate.exists():
                project_root = parent
                break

        if project_root is not None:
            project_root_str = str(project_root)
            if project_root_str not in sys.path:
                sys.path.insert(0, project_root_str)

        try:
            parser_module = importlib.import_module("parserFatture.parserFatture")
            parse_invoice_pdf = getattr(parser_module, "parse_invoice_pdf")
        except Exception as exc:
            raise RuntimeError(
                "parserFatture non disponibile. Verifica il modulo parserFatture/parserFatture.py e le dipendenze del parser."
            ) from exc

        self._parser_fatture_parse_fn = parse_invoice_pdf
        return parse_invoice_pdf

    def avvia_parser_fattura_async(self, file_path, on_success, on_error, on_done=None, on_progress=None):
        """Avvia il parsing in modo asincrono usando il ThreadPool globale nativo di Qt."""
        parse_fn = self._get_parser_fatture_function()
        task = InvoiceParserTask(parse_fn, file_path, on_success, on_error, on_done, on_progress)
        
        # QThreadPool prende in carico il task, lo esegue e lo distrugge appena ha finito. Zero Memory Leaks.
        QThreadPool.globalInstance().start(task)

    def _estrai_valore_campo_parser(self, fields, field_name):
        field = fields.get(field_name)
        if field is None:
            return ""

        valore = getattr(field, "normalized_value", None)
        if valore in (None, ""):
            valore = getattr(field, "raw_value", None)

        return str(valore).strip() if valore is not None else ""

    def _estrai_importo_parser(self, fields, field_name, allow_zero):
        field = fields.get(field_name)
        if field is None:
            return None

        valore = getattr(field, "normalized_value", None)
        if valore in (None, ""):
            valore = getattr(field, "raw_value", None)
        if valore in (None, ""):
            return None

        if isinstance(valore, (int, float)):
            numero = float(valore)
            if numero < 0:
                return None
            if not allow_zero and numero <= 0:
                return None
            return numero

        return self._normalizza_importo(str(valore), allow_zero=allow_zero)

    def _normalizza_data_fattura(self, raw_data):
        if not raw_data:
            return ""

        testo_data = str(raw_data).strip().replace(".", "/").replace("-", "/")
        formati = []

        if re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", testo_data):
            formati = ["%Y/%m/%d"]
        elif re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", testo_data):
            formati = ["%d/%m/%Y", "%d/%m/%y"]

        for formato in formati:
            try:
                data = datetime.strptime(testo_data, formato)
                return data.strftime("%d/%m/%Y")
            except ValueError:
                continue

        return ""

    def _normalizza_risultato_parser(self, risultato):
        if not isinstance(risultato, dict):
            return risultato

        fields = {}
        for key in (
            "invoice_number",
            "invoice_date",
            "due_date",
            "supplier_name",
            "supplier_vat",
            "customer_name",
            "customer_vat",
            "total_amount",
            "taxable_total",
            "vat_total",
            "payment_terms",
            "invoice_header",
        ):
            value = risultato.get(key)
            if value not in (None, ""):
                fields[key] = SimpleNamespace(raw_value=value, normalized_value=value)

        raw_items = risultato.get("line_items", []) or []
        normalized_items = []
        for item in raw_items:
            if isinstance(item, dict):
                normalized_items.append(
                    SimpleNamespace(
                        description=item.get("description"),
                        quantity=item.get("quantity"),
                        price=item.get("price"),
                        unit_price=item.get("unit_price", item.get("price")),
                        line_total=item.get("line_total"),
                        vat_rate=item.get("vat_rate", item.get("vat")),
                        category=item.get("category"),
                        cost_type=item.get("cost_type"),
                    )
                )
            else:
                normalized_items.append(item)

        return SimpleNamespace(
            fields=fields,
            line_items=normalized_items,
            warnings=risultato.get("warnings", []) or [],
            structure=risultato.get("structure", {}) or {},
        )

    def _costruisci_dati_parser_movimento(self, risultato, fields):
        warnings = getattr(risultato, "warnings", []) or []
        line_items = getattr(risultato, "line_items", []) or []

        prodotti = []
        prodotti_rows = []

        for line in line_items:
            descrizione = str(getattr(line, "description", "") or "").strip()
            categoria_raw = getattr(line, "category", None)
            quantita_raw = getattr(line, "quantity", None)
            prezzo_unit_raw = getattr(line, "unit_price", None)
            totale_raw = getattr(line, "line_total", None)
            iva_raw = getattr(line, "vat_rate", None)
            tipo_costo_raw = getattr(line, "cost_type", None)

            quantita = self._valore_parser_to_float(quantita_raw, allow_zero=True)
            totale = self._valore_parser_to_float(totale_raw, allow_zero=True)

            if not descrizione and quantita is None and totale is None and prezzo_unit_raw in (None, ""):
                continue

            prodotti_rows.append(
                {
                    "description": descrizione or "-",
                    "category": normalize_product_category(categoria_raw),
                    "quantity": self._valore_parser_to_text(quantita_raw, 3),
                    "unit_price": self._valore_parser_to_text(prezzo_unit_raw, 4),
                    "vat_rate": self._valore_parser_to_text(iva_raw, 2),
                    "line_total": self._valore_parser_to_text(totale_raw, 2),
                    "cost_type": normalize_cost_type(tipo_costo_raw),
                }
            )

            if not descrizione or quantita is None or totale is None:
                continue
            if quantita <= 0 or totale <= 0:
                continue

            prodotti.append(
                build_basic_product_storage_line(
                    descrizione,
                    format_number(quantita, 3),
                    format_number(totale, 2),
                )
            )

        campi_riepilogo = []
        for field_name in sorted(fields):
            field = fields.get(field_name)
            if field is None:
                continue

            valore = getattr(field, "normalized_value", None)
            if valore in (None, ""):
                valore = getattr(field, "raw_value", None)

            valore_text = str(valore).strip() if valore not in (None, "") else "-"
            conf = getattr(field, "confidence", 0.0) or 0.0
            try:
                conf_pct = int(round(float(conf) * 100))
            except (TypeError, ValueError):
                conf_pct = 0

            needs_review = bool(getattr(field, "requires_confirmation", False))
            suffisso = " [Conferma]" if needs_review else ""
            label = field_name.replace("_", " ").title()
            campi_riepilogo.append(f"{label}: {valore_text} ({conf_pct}%){suffisso}")

        return {
            "invoice_number": self._estrai_valore_campo_parser(fields, "invoice_number"),
            "invoice_date": self._estrai_valore_campo_parser(fields, "invoice_date"),
            "due_date": self._estrai_valore_campo_parser(fields, "due_date"),
            "supplier_name": self._estrai_valore_campo_parser(fields, "supplier_name"),
            "supplier_vat": self._estrai_valore_campo_parser(fields, "supplier_vat"),
            "customer_name": self._estrai_valore_campo_parser(fields, "customer_name"),
            "customer_vat": self._estrai_valore_campo_parser(fields, "customer_vat"),
            "total_amount": self._estrai_valore_campo_parser(fields, "total_amount"),
            "taxable_total": self._estrai_valore_campo_parser(fields, "taxable_total"),
            "vat_total": self._estrai_valore_campo_parser(fields, "vat_total"),
            "payment_terms": self._estrai_valore_campo_parser(fields, "payment_terms"),
            "warnings": " | ".join(str(w).strip() for w in warnings if str(w).strip()),
            "products": serialize_product_storage_lines(prodotti, separator="\n"),
            "products_rows": prodotti_rows,
            "fields_view": " | ".join(campi_riepilogo),
        }

    def _estrai_valori_parser_db(self, parser_data):
        if not isinstance(parser_data, dict):
            return (None,) * len(self._PARSER_DB_FIELDS)
        return tuple(parser_data.get(field_name) for field_name in self._PARSER_DB_FIELDS)

    def _calcola_aliquota_iva_parser(self, fields, risultato=None):
        vat_rows = getattr(risultato, "vat_breakdown", []) or []
        for row in vat_rows:
            vat_rate = self._valore_parser_to_float(getattr(row, "vat_rate", None), allow_zero=False)
            if vat_rate is not None and vat_rate > 0:
                return vat_rate

        vat_total = self._estrai_importo_parser(fields, "vat_total", allow_zero=True)
        taxable_total = self._estrai_importo_parser(fields, "taxable_total", allow_zero=False)

        if vat_total is None or taxable_total is None or taxable_total <= 0:
            total_amount = self._estrai_importo_parser(fields, "total_amount", allow_zero=False)
            if total_amount is None or total_amount <= 0:
                return None
            taxable_total = total_amount - (vat_total or 0.0)
            if taxable_total <= 0:
                return None

        return max((vat_total or 0.0) * 100.0 / taxable_total, 0.0)

    def archivia_fattura_caricata(self, file_path, origine):
        src = Path(file_path)
        if not src.exists():
            raise RuntimeError("File fattura non trovato.")

        archivio_dir = get_fatture_user_dir(self.user_id)

        nome_pulito = re.sub(r"[^A-Za-z0-9._-]", "_", src.name)
        nome_dest = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{nome_pulito}"
        dest = archivio_dir / nome_dest
        shutil.copy2(src, dest)
        percorso_db = to_storage_fattura_path(dest)

        with get_conn() as conn:
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO fatture (user_id, origine, movimento_id, produzione_id, nome_originale, percorso_file, data_caricamento)
                VALUES (?, ?, NULL, NULL, ?, ?, ?)
            """,
                (
                    self.user_id,
                    origine,
                    src.name,
                    percorso_db,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            fattura_id = c.lastrowid

        return int(fattura_id or 0), str(dest)

    def elimina_fatture_collegate_db(self, cursor, movimento_id):
        cursor.execute(
            "SELECT percorso_file FROM fatture WHERE user_id=? AND movimento_id=?",
            (self.user_id, movimento_id),
        )
        percorsi = [row[0] for row in cursor.fetchall() if row and row[0]]

        cursor.execute("DELETE FROM fatture WHERE user_id=? AND movimento_id=?", (self.user_id, movimento_id))
        fatture_eliminate = max(cursor.rowcount, 0)
        return fatture_eliminate, percorsi

    def elimina_file_fatture(self, percorsi):
        file_eliminati = 0
        file_non_trovati = 0
        errori = []

        for percorso in sorted(set(p for p in percorsi if p)):
            file_path = resolve_fattura_path(percorso)
            try:
                if file_path.exists():
                    file_path.unlink()
                    file_eliminati += 1
                else:
                    file_non_trovati += 1
            except Exception as exc:
                errori.append(f"{file_path} ({exc})")

        return file_eliminati, file_non_trovati, errori
