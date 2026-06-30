import re
import shutil
import uuid
import importlib
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from PySide6.QtCore import QObject, Signal, Slot, QRunnable, QThreadPool

from app_utils import format_number, parse_decimal
from database import get_fatture_user_dir, resolve_fattura_path, to_storage_fattura_path
from services.product_parser_utils import (
    build_basic_product_storage_line, normalize_cost_type, normalize_product_category, serialize_product_storage_lines
)
from models import Fattura # <-- Il nostro modello ORM!

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

        # PEEWEE ORM
        fattura = Fattura.create(
            user=self.user_id,
            origine=origine,
            nome_originale=src.name,
            percorso_file=percorso_db,
            data_caricamento=datetime.now().isoformat(timespec="seconds")
        )

        return int(fattura.id), str(dest)

    def elimina_fatture_collegate_db(self, movimento_id):
        # Usiamo ORM Peewee senza bisogno di passare cursori dal blocco transazionale
        percorsi = [f.percorso_file for f in Fattura.select().where((Fattura.user == self.user_id) & (Fattura.movimento == movimento_id))]
        Fattura.delete().where((Fattura.user == self.user_id) & (Fattura.movimento == movimento_id)).execute()
        return len(percorsi), percorsi

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
            except Exception as e:
                errori.append(f"{file_path} ({e})")

        return file_eliminati, file_non_trovati, errori

    def _get_parser_fatture_function(self):
        parse_invoice_pdf = getattr(self, "_parser_fatture_parse_fn", None)
        if parse_invoice_pdf is not None: return parse_invoice_pdf

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
            raise RuntimeError("Modulo parserFatture non trovato.") from exc

        self._parser_fatture_parse_fn = parse_invoice_pdf
        return parse_invoice_pdf

    def avvia_parser_fattura_async(self, file_path, on_success, on_error, on_done=None, on_progress=None):
        parse_fn = self._get_parser_fatture_function()
        task = InvoiceParserTask(parse_fn, file_path, on_success, on_error, on_done, on_progress)
        task.setAutoDelete(True)
        QThreadPool.globalInstance().start(task)

    def _normalizza_importo(self, raw, allow_zero=False):
        return parse_decimal(raw, allow_zero=allow_zero, allow_negative=False)

    def _valore_parser_to_float(self, value, allow_zero=False):
        if value is None: return None
        if isinstance(value, (int, float)): number = float(value)
        else:
            try: number = float(value)
            except (TypeError, ValueError): return self._normalizza_importo(str(value), allow_zero=allow_zero)
        if number < 0: return None
        if number == 0 and not allow_zero: return None
        return number

    def _valore_parser_to_text(self, value, decimals=2):
        number = self._valore_parser_to_float(value, allow_zero=True)
        if number is not None: return format_number(number, decimals)
        if value in (None, ""): return "-"
        return str(value).strip()

    def _estrai_valore_campo_parser(self, fields, field_name):
        field = fields.get(field_name)
        if field is None: return ""
        valore = getattr(field, "normalized_value", None)
        if valore in (None, ""): valore = getattr(field, "raw_value", None)
        return str(valore).strip() if valore is not None else ""

    def _normalizza_data_fattura(self, raw_data):
        if not raw_data: return ""
        testo_data = str(raw_data).strip().replace(".", "/").replace("-", "/")
        formati = []
        if re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", testo_data): formati = ["%Y/%m/%d"]
        elif re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", testo_data): formati = ["%d/%m/%Y", "%d/%m/%y"]
        for formato in formati:
            try:
                data = datetime.strptime(testo_data, formato)
                return data.strftime("%d/%m/%Y")
            except ValueError: continue
        return ""

    def _calcola_aliquota_iva_parser(self, fields, risultato):
        taxable_raw = self._estrai_valore_campo_parser(fields, "taxable_total")
        vat_raw = self._estrai_valore_campo_parser(fields, "vat_total")
        
        taxable = self._normalizza_importo(taxable_raw, allow_zero=False)
        vat = self._normalizza_importo(vat_raw, allow_zero=True)
        
        if taxable is not None and taxable > 0 and vat is not None:
            aliquota_calcolata = (vat / taxable) * 100.0
            aliquote_standard = [4.0, 5.0, 10.0, 22.0]
            for std in aliquote_standard:
                if abs(aliquota_calcolata - std) < 1.0: return std
            return round(aliquota_calcolata, 1)
        return 0.0

    def _normalizza_risultato_parser(self, risultato):
        if not isinstance(risultato, dict): return risultato
        
        fields = {}
        for key in ("invoice_number", "invoice_date", "due_date", "supplier_name", "supplier_vat", "customer_name", "customer_vat", "total_amount", "taxable_total", "vat_total", "payment_terms"):
            value = risultato.get(key)
            if value not in (None, ""):
                fields[key] = SimpleNamespace(raw_value=value, normalized_value=value)
                
        raw_items = risultato.get("line_items", []) or []
        normalized_items = []
        for item in raw_items:
            if isinstance(item, dict):
                normalized_items.append(SimpleNamespace(
                    description=item.get("description"), quantity=item.get("quantity"), price=item.get("price"),
                    unit_price=item.get("unit_price", item.get("price")), line_total=item.get("line_total"),
                    vat_rate=item.get("vat_rate", item.get("vat")), category=item.get("category"), cost_type=item.get("cost_type")
                ))
            else: normalized_items.append(item)
            
        return SimpleNamespace(fields=fields, line_items=normalized_items, warnings=risultato.get("warnings", []) or [])

    def _costruisci_dati_parser_movimento(self, risultato, fields):
        warnings = getattr(risultato, "warnings", []) or []
        line_items = getattr(risultato, "line_items", []) or []

        prodotti = []
        for line in line_items:
            descrizione = str(getattr(line, "description", "") or "").strip()
            categoria_raw = getattr(line, "category", None)
            quantita_raw = getattr(line, "quantity", None)
            prezzo_raw = getattr(line, "price", None)
            prezzo_unit_raw = getattr(line, "unit_price", None)
            if prezzo_raw in (None, ""): prezzo_raw = prezzo_unit_raw
            totale_raw = getattr(line, "line_total", None)
            iva_raw = getattr(line, "vat_rate", None)
            tipo_costo_raw = getattr(line, "cost_type", None)

            quantita = self._valore_parser_to_float(quantita_raw, allow_zero=True)
            totale = self._valore_parser_to_float(totale_raw, allow_zero=True)

            if not descrizione or quantita is None or totale is None or quantita <= 0 or totale <= 0: continue
            
            prodotti.append(build_basic_product_storage_line(descrizione, format_number(quantita, 3), format_number(totale, 2)))

        campi_riepilogo = []
        for field_name in sorted(fields):
            field = fields.get(field_name)
            if field is None: continue
            valore = getattr(field, "normalized_value", None)
            if valore in (None, ""): valore = getattr(field, "raw_value", None)
            valore_text = str(valore).strip() if valore not in (None, "") else "-"
            
            conf = getattr(field, "confidence", 0.0) or 0.0
            try: conf_pct = int(round(float(conf) * 100))
            except (TypeError, ValueError): conf_pct = 0
            
            needs_review = bool(getattr(field, "requires_confirmation", False))
            campi_riepilogo.append(f"{field_name.replace('_', ' ').title()}: {valore_text} ({conf_pct}%){' [Conferma]' if needs_review else ''}")

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
            "fields_view": " | ".join(campi_riepilogo),
        }

    def _estrai_valori_parser_db(self, parser_data):
        _PARSER_DB_FIELDS = (
            "invoice_number", "invoice_date", "due_date", "supplier_name",
            "supplier_vat", "customer_name", "customer_vat", "total_amount",
            "taxable_total", "vat_total", "payment_terms", "warnings",
            "products", "fields_view",
        )
        if not isinstance(parser_data, dict): return (None,) * len(_PARSER_DB_FIELDS)
        return tuple(parser_data.get(field_name) for field_name in _PARSER_DB_FIELDS)

    def parse_xml_fattura_standard(self, file_path):
        """Metodo unificato per leggere i dati da XML e P7M in tutto il gestionale."""
        with open(file_path, 'rb') as f: content = f.read()
        xml_string = b""
        start_idx = content.find(b'<?xml')
        if start_idx == -1: start_idx = content.find(b'<FatturaElettronica')
        if start_idx == -1: start_idx = content.find(b'<p:FatturaElettronica')
        
        if start_idx != -1:
            end_idx = content.rfind(b'</FatturaElettronica>')
            if end_idx == -1: end_idx = content.rfind(b'</p:FatturaElettronica>')
            
            if end_idx != -1:
                end_tag = content[end_idx:].split(b'>')[0] + b'>'
                xml_string = content[start_idx:end_idx + len(end_tag)]
            else: xml_string = content[start_idx:]
        else: xml_string = content

        xml_string = re.sub(b' xmlns="[^"]+"', b'', xml_string, count=1)
        xml_string = re.sub(b'<[a-zA-Z0-9]+:', b'<', xml_string)
        xml_string = re.sub(b'</[a-zA-Z0-9]+:', b'</', xml_string)
        
        try: root = ET.fromstring(xml_string)
        except Exception as e: raise ValueError(f"Formato file XML/P7M danneggiato o non standard: {e}")

        supplier_name = "-"
        cedente = root.find('.//CedentePrestatore/DatiAnagrafici/Anagrafica/Denominazione')
        if cedente is not None and cedente.text: supplier_name = cedente.text
        else:
            nome = root.find('.//CedentePrestatore/DatiAnagrafici/Anagrafica/Nome')
            cognome = root.find('.//CedentePrestatore/DatiAnagrafici/Anagrafica/Cognome')
            if nome is not None and cognome is not None: supplier_name = f"{nome.text} {cognome.text}"

        invoice_number = root.findtext('.//DatiGeneraliDocumento/Numero', "")
        invoice_date = root.findtext('.//DatiGeneraliDocumento/Data', "")
        
        taxable_total, vat_total = 0.0, 0.0
        for riepilogo in root.findall('.//DatiRiepilogo'):
            imp = riepilogo.find('ImponibileImporto')
            iva = riepilogo.find('Imposta')
            if imp is not None: taxable_total += float(imp.text)
            if iva is not None: vat_total += float(iva.text)
            
        products_rows = []
        for dettaglio in root.findall('.//DettaglioLinee'):
            products_rows.append({
                "description": dettaglio.findtext('Descrizione', "Prodotto da XML"),
                "quantity": dettaglio.findtext('Quantita', "1"),
                "price": dettaglio.findtext('PrezzoUnitario', dettaglio.findtext('PrezzoTotale', "0")),
                "unit_price": dettaglio.findtext('PrezzoUnitario', dettaglio.findtext('PrezzoTotale', "0")),
                "line_total": dettaglio.findtext('PrezzoTotale', "0"),
                "vat_rate": dettaglio.findtext('AliquotaIVA', "0"),
                "category": "Da categorizzare",
                "cost_type": "Variabili"
            })

        return {
            "invoice_number": invoice_number, "invoice_date": invoice_date, "supplier_name": supplier_name, 
            "taxable_total": taxable_total, "vat_total": vat_total, "total_amount": taxable_total + vat_total, "line_items": products_rows
        }