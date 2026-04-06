import tkinter as tk
import importlib
import re
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

from app_utils import format_number, is_blank
from database import get_conn, get_fatture_user_dir, to_storage_fattura_path


class MovimentiTabMixin:
    def setup_tab_movimenti(self):
        ttk.Label(self.tab_movimenti, text="Registra Movimento", font=("Arial", 14, "bold")).pack(pady=10)

        self.var_data = tk.StringVar(value=datetime.now().strftime("%d/%m/%Y"))
        self.var_tipo = tk.StringVar(value="ENTRATA")
        self.var_cat = tk.StringVar()
        self.var_desc = tk.StringVar()
        self.var_imp = tk.StringVar()
        self.var_iva = tk.StringVar(value="0,00")

        self.crea_campo_data(self.tab_movimenti, "Data:", self.var_data)

        frame_tipo = ttk.Frame(self.tab_movimenti)
        frame_tipo.pack(fill="x", padx=20, pady=5)
        ttk.Label(frame_tipo, text="Tipo:", width=20).pack(side="left")
        frame_radio = ttk.Frame(frame_tipo)
        frame_radio.pack(side="left", fill="x", expand=True)

        ttk.Radiobutton(frame_radio, text="Entrata", value="ENTRATA", variable=self.var_tipo).pack(side="left", padx=(0, 15))
        ttk.Radiobutton(frame_radio, text="Uscita", value="USCITA", variable=self.var_tipo).pack(side="left")

        self.crea_campo_categoria(self.tab_movimenti, "Categoria:", self.var_cat)
        self.crea_campo(self.tab_movimenti, "Descrizione:", self.var_desc)
        self.crea_campo(self.tab_movimenti, "Importo (EUR):", self.var_imp)
        self.crea_campo(self.tab_movimenti, "IVA (EUR):", self.var_iva)

        frame_actions = ttk.Frame(self.tab_movimenti)
        frame_actions.pack(pady=20)

        self.btn_salva_movimento = ttk.Button(frame_actions, text="Salva nel DB", command=self.salva_movimento)
        self.btn_salva_movimento.pack(side="left", padx=6)

        self.btn_annulla_modifica = ttk.Button(
            frame_actions,
            text="Annulla modifica",
            command=self.annulla_modifica_movimento,
            state="disabled",
        )
        self.btn_annulla_modifica.pack(side="left", padx=6)

        ttk.Button(frame_actions, text="Importa fattura PDF", command=self.importa_fattura_pdf).pack(side="left", padx=6)

        self.var_nome_fattura_mov = tk.StringVar(value="Nessuna fattura caricata")
        frame_fattura = ttk.Frame(self.tab_movimenti)
        frame_fattura.pack(fill="x", padx=20, pady=(0, 6))

        ttk.Label(frame_fattura, text="Fattura caricata:", width=20).pack(side="left")
        ttk.Label(frame_fattura, textvariable=self.var_nome_fattura_mov).pack(side="left", fill="x", expand=True)
        ttk.Button(frame_fattura, text="Rimuovi", command=self.rimuovi_fattura_movimento).pack(side="right")

    def salva_movimento(self):
        if is_blank(self.var_data.get()):
            messagebox.showerror("Errore", "Inserisci la data.")
            return
        if is_blank(self.var_imp.get()):
            messagebox.showerror("Errore", "Inserisci l'importo.")
            return

        try:
            data_obj = datetime.strptime(self.var_data.get().strip(), "%d/%m/%Y")
            data_db = data_obj.strftime("%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Errore", "Formato data non valido (Usa GG/MM/AAAA)")
            return

        importo_val = self._normalizza_importo(self.var_imp.get(), allow_zero=False)
        if importo_val is None:
            messagebox.showerror("Errore", "Importo non valido.")
            return

        iva_text = self.var_iva.get().strip()
        if is_blank(iva_text):
            iva_val = 0.0
        else:
            iva_val = self._normalizza_importo(iva_text, allow_zero=True)
            if iva_val is None:
                messagebox.showerror("Errore", "Valore IVA non valido.")
                return

        try:
            with get_conn() as conn:
                c = conn.cursor()
                movimento_salvato_id = None
                parser_data = getattr(self, "pending_parser_movimento_data", None)

                parser_invoice_number = None
                parser_invoice_date = None
                parser_due_date = None
                parser_supplier_name = None
                parser_supplier_vat = None
                parser_customer_name = None
                parser_customer_vat = None
                parser_total_amount = None
                parser_taxable_total = None
                parser_vat_total = None
                parser_payment_terms = None
                parser_warnings = None
                parser_products = None
                parser_fields_view = None

                if isinstance(parser_data, dict):
                    parser_invoice_number = parser_data.get("invoice_number")
                    parser_invoice_date = parser_data.get("invoice_date")
                    parser_due_date = parser_data.get("due_date")
                    parser_supplier_name = parser_data.get("supplier_name")
                    parser_supplier_vat = parser_data.get("supplier_vat")
                    parser_customer_name = parser_data.get("customer_name")
                    parser_customer_vat = parser_data.get("customer_vat")
                    parser_total_amount = parser_data.get("total_amount")
                    parser_taxable_total = parser_data.get("taxable_total")
                    parser_vat_total = parser_data.get("vat_total")
                    parser_payment_terms = parser_data.get("payment_terms")
                    parser_warnings = parser_data.get("warnings")
                    parser_products = parser_data.get("products")
                    parser_fields_view = parser_data.get("fields_view")

                if self.movimento_in_modifica_id is None:
                    c.execute(
                        '''
                        INSERT INTO movimenti (
                            user_id, data_op, tipo, categoria, descrizione, importo, iva_importo,
                            parser_invoice_number, parser_invoice_date, parser_due_date,
                            parser_supplier_name, parser_supplier_vat,
                            parser_customer_name, parser_customer_vat,
                            parser_total_amount, parser_taxable_total, parser_vat_total,
                            parser_payment_terms, parser_warnings, parser_products, parser_fields_view
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                        (
                            self.user_id,
                            data_db,
                            self.var_tipo.get(),
                            self.var_cat.get().strip(),
                            self.var_desc.get().strip(),
                            importo_val,
                            iva_val,
                            parser_invoice_number,
                            parser_invoice_date,
                            parser_due_date,
                            parser_supplier_name,
                            parser_supplier_vat,
                            parser_customer_name,
                            parser_customer_vat,
                            parser_total_amount,
                            parser_taxable_total,
                            parser_vat_total,
                            parser_payment_terms,
                            parser_warnings,
                            parser_products,
                            parser_fields_view,
                        ),
                    )
                    movimento_salvato_id = c.lastrowid
                    msg_ok = "Movimento salvato nel database!"
                else:
                    if parser_data is not None:
                        c.execute(
                            '''
                            UPDATE movimenti
                            SET data_op=?, tipo=?, categoria=?, descrizione=?, importo=?, iva_importo=?,
                                parser_invoice_number=?, parser_invoice_date=?, parser_due_date=?,
                                parser_supplier_name=?, parser_supplier_vat=?,
                                parser_customer_name=?, parser_customer_vat=?,
                                parser_total_amount=?, parser_taxable_total=?, parser_vat_total=?,
                                parser_payment_terms=?, parser_warnings=?, parser_products=?, parser_fields_view=?
                            WHERE id=? AND user_id=?
                        ''',
                            (
                                data_db,
                                self.var_tipo.get(),
                                self.var_cat.get().strip(),
                                self.var_desc.get().strip(),
                                importo_val,
                                iva_val,
                                parser_invoice_number,
                                parser_invoice_date,
                                parser_due_date,
                                parser_supplier_name,
                                parser_supplier_vat,
                                parser_customer_name,
                                parser_customer_vat,
                                parser_total_amount,
                                parser_taxable_total,
                                parser_vat_total,
                                parser_payment_terms,
                                parser_warnings,
                                parser_products,
                                parser_fields_view,
                                self.movimento_in_modifica_id,
                                self.user_id,
                            ),
                        )
                    else:
                        c.execute(
                            '''
                            UPDATE movimenti
                            SET data_op=?, tipo=?, categoria=?, descrizione=?, importo=?, iva_importo=?
                            WHERE id=? AND user_id=?
                        ''',
                            (
                                data_db,
                                self.var_tipo.get(),
                                self.var_cat.get().strip(),
                                self.var_desc.get().strip(),
                                importo_val,
                                iva_val,
                                self.movimento_in_modifica_id,
                                self.user_id,
                            ),
                        )

                    if c.rowcount == 0:
                        messagebox.showerror("Errore", "Movimento non trovato o non modificabile.")
                        return
                    movimento_salvato_id = self.movimento_in_modifica_id
                    msg_ok = "Movimento aggiornato nel database!"

                if self.pending_fattura_movimento_id is not None and movimento_salvato_id is not None:
                    c.execute(
                        '''
                        UPDATE fatture
                        SET movimento_id=?
                        WHERE id=? AND user_id=?
                    ''',
                        (movimento_salvato_id, self.pending_fattura_movimento_id, self.user_id),
                    )

            messagebox.showinfo("Successo", msg_ok)
            self.annulla_modifica_movimento()
            self.rimuovi_fattura_movimento()
            self.carica_movimenti()
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")

    def importa_fattura_pdf(self):
        if self.movimento_in_modifica_id is not None:
            self.annulla_modifica_movimento()

        file_path = filedialog.askopenfilename(title="Seleziona fattura PDF", filetypes=[("PDF", "*.pdf")])
        if not file_path:
            return

        try:
            fattura_id, percorso_archiviato = self.archivia_fattura_caricata(file_path, "MOVIMENTO")
        except Exception as e:
            messagebox.showerror("Importazione fallita", f"Impossibile salvare la fattura: {e}")
            return

        self.pending_fattura_movimento_id = fattura_id
        self.pending_fattura_movimento_path = percorso_archiviato
        self.pending_parser_movimento_data = None
        self.var_nome_fattura_mov.set(Path(percorso_archiviato).name)

        try:
            dati = self.analizza_fattura_con_parser_fatture(percorso_archiviato, file_path)
        except Exception as e:
            messagebox.showwarning(
                "Analisi non completata",
                f"Fattura salvata correttamente, ma analisi automatica non disponibile: {e}",
            )
            return

        if dati.get("data"):
            self.var_data.set(dati["data"])
        if dati.get("tipo"):
            self.var_tipo.set(dati["tipo"])
        if dati.get("categoria"):
            self.var_cat.set(dati["categoria"])
        if dati.get("descrizione"):
            self.var_desc.set(dati["descrizione"])
        if dati.get("importo"):
            self.var_imp.set(dati["importo"])
        if dati.get("iva"):
            self.var_iva.set(dati["iva"])
        self.pending_parser_movimento_data = dati.get("parser_data")

        if is_blank(self.var_imp.get()):
            messagebox.showwarning("Attenzione", "Importo non trovato automaticamente. Verificalo manualmente.")
            return

        if messagebox.askyesno("Conferma", "Fattura analizzata. Vuoi salvare subito il movimento nel DB?"):
            self.salva_movimento()

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
                '''
                INSERT INTO fatture (user_id, origine, movimento_id, produzione_id, nome_originale, percorso_file, data_caricamento)
                VALUES (?, ?, NULL, NULL, ?, ?, ?)
            ''',
                (
                    self.user_id,
                    origine,
                    src.name,
                    percorso_db,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            fattura_id = c.lastrowid

        return fattura_id, str(dest)

    def rimuovi_fattura_movimento(self):
        self.pending_fattura_movimento_id = None
        self.pending_fattura_movimento_path = None
        self.pending_parser_movimento_data = None
        if hasattr(self, "var_nome_fattura_mov"):
            self.var_nome_fattura_mov.set("Nessuna fattura caricata")

    def seleziona_fattura_latte(self):
        file_path = filedialog.askopenfilename(title="Seleziona fattura PDF (Latte)", filetypes=[("PDF", "*.pdf")])
        if not file_path:
            return

        try:
            fattura_id, percorso_archiviato = self.archivia_fattura_caricata(file_path, "LATTE")
        except Exception as e:
            messagebox.showerror("Caricamento fattura", f"Impossibile salvare la fattura: {e}")
            return

        self.pending_fattura_latte_id = fattura_id
        self.pending_fattura_latte_path = percorso_archiviato
        if hasattr(self, "var_nome_fattura_latte"):
            self.var_nome_fattura_latte.set(Path(percorso_archiviato).name)

    def rimuovi_fattura_latte(self):
        self.pending_fattura_latte_id = None
        self.pending_fattura_latte_path = None
        if hasattr(self, "var_nome_fattura_latte"):
            self.var_nome_fattura_latte.set("Nessuna fattura caricata")

    def estrai_testo_pdf(self, file_path):
        try:
            from pypdf import PdfReader
        except ImportError:
            raise RuntimeError("Manca la libreria pypdf. Installa con: pip install pypdf")

        reader = PdfReader(file_path)
        chunks = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")

        testo = "\n".join(chunks).strip()
        if not testo:
            raise RuntimeError("Il PDF non contiene testo estraibile (probabile scansione).")
        return testo

    def analizza_testo_fattura(self, testo, file_path):
        # Manteniamo la firma per compatibilita con vecchi call site.
        return self.analizza_fattura_con_parser_fatture(file_path, file_path)

    def analizza_fattura_con_parser_fatture(self, pdf_path, file_path):
        parse_invoice_pdf = self._get_parser_fatture_function()
        risultato = parse_invoice_pdf(str(pdf_path))
        fields = getattr(risultato, "fields", {}) or {}
        parser_data = self._costruisci_dati_parser_movimento(risultato, fields)

        data_raw = self._estrai_valore_campo_parser(fields, "invoice_date")
        data_out = self._normalizza_data_fattura(data_raw)

        importo = self._estrai_importo_parser(fields, "total_amount", allow_zero=False)
        iva = self._estrai_importo_parser(fields, "vat_total", allow_zero=True)

        if importo is None:
            imponibile = self._estrai_importo_parser(fields, "taxable_total", allow_zero=True)
            if imponibile is not None and iva is not None:
                importo = imponibile + iva
            elif imponibile is not None:
                importo = imponibile

        if iva is None:
            iva = 0.0

        testo_struttura = self._testo_da_struttura_parser(getattr(risultato, "structure", {}))
        testo_struttura_lower = testo_struttura.lower()

        tipo = "USCITA"
        if "nota di credito" in testo_struttura_lower or "rimborso" in testo_struttura_lower:
            tipo = "ENTRATA"

        descrizione = self._estrai_valore_campo_parser(fields, "supplier_name")
        if not descrizione and testo_struttura:
            descrizione = self._estrai_intestazione_fattura(testo_struttura, file_path)

        if not descrizione:
            numero_fattura = self._estrai_valore_campo_parser(fields, "invoice_number")
            if numero_fattura:
                descrizione = f"Fattura {numero_fattura}"
            else:
                descrizione = f"Fattura importata: {Path(file_path).name}"

        return {
            "data": data_out or datetime.now().strftime("%d/%m/%Y"),
            "tipo": tipo,
            "categoria": "Fattura",
            "descrizione": descrizione,
            "importo": format_number(importo, 2) if importo is not None else "",
            "iva": format_number(iva, 2),
            "parser_data": parser_data,
        }

    def _get_parser_fatture_function(self):
        parse_invoice_pdf = getattr(self, "_parser_fatture_parse_fn", None)
        if parse_invoice_pdf is not None:
            return parse_invoice_pdf

        parser_src = Path(__file__).resolve().parents[1] / "parserFatture" / "src"
        if parser_src.exists():
            parser_src_str = str(parser_src)
            if parser_src_str not in sys.path:
                sys.path.insert(0, parser_src_str)

        try:
            parser_module = importlib.import_module("parser")
            parse_invoice_pdf = getattr(parser_module, "parse_invoice_pdf")
        except Exception as exc:
            raise RuntimeError(
                "parserFatture non disponibile. Installa dipendenze con: pip install -e parserFatture"
            ) from exc

        self._parser_fatture_parse_fn = parse_invoice_pdf
        return parse_invoice_pdf

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

    def _testo_da_struttura_parser(self, struttura):
        if not isinstance(struttura, dict):
            return ""

        righe = []
        for blocco in struttura.values():
            if not isinstance(blocco, list):
                continue
            for riga in blocco:
                testo_riga = str(riga).strip()
                if testo_riga:
                    righe.append(testo_riga)

        return "\n".join(righe)

    def _costruisci_dati_parser_movimento(self, risultato, fields):
        warnings = getattr(risultato, "warnings", []) or []
        line_items = getattr(risultato, "line_items", []) or []

        prodotti = []
        for line in line_items:
            descrizione = str(getattr(line, "description", "") or "").strip()
            quantita = getattr(line, "quantity", None)
            totale = getattr(line, "line_total", None)

            if not descrizione or quantita is None or totale is None:
                continue
            if quantita <= 0 or totale <= 0:
                continue

            parti = [descrizione, f"qta {quantita}", f"tot {totale}"]
            prodotti.append(" - ".join(parti))

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
            "products": " | ".join(prodotti),
            "fields_view": " | ".join(campi_riepilogo),
        }

    def _estrai_data_emissione_fattura(self, testo):
        pattern_data = r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2}"
        parole_chiave = (
            "data emissione",
            "data di emissione",
            "emessa il",
            "data fattura",
            "data documento",
            "invoice date",
            "issue date",
        )

        # Formato richiesto: "n. <numero_fattura> del GG Mese YYYY".
        match_fattura = re.search(
            r"\bn\.?\s*[^\n]{0,60}?\bdel\b\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b",
            testo,
            flags=re.IGNORECASE,
        )
        if match_fattura:
            giorno = int(match_fattura.group(1))
            mese = self._mese_italiano_to_numero(match_fattura.group(2))
            anno = int(match_fattura.group(3))
            if mese is not None:
                try:
                    return datetime(anno, mese, giorno).strftime("%d/%m/%Y")
                except ValueError:
                    pass

        # Priorita: date presenti su righe che contengono indicatori di emissione.
        for riga in testo.splitlines():
            riga_pulita = re.sub(r"\s+", " ", riga).strip()
            if not riga_pulita:
                continue
            riga_lower = riga_pulita.lower()
            if not any(k in riga_lower for k in parole_chiave):
                continue

            for candidato in re.findall(rf"\b({pattern_data})\b", riga_pulita):
                data_norm = self._normalizza_data_fattura(candidato)
                if data_norm:
                    return data_norm

        pattern_con_etichetta = [
            rf"(?:data\s*(?:di\s*)?emissione|emessa\s*il|data\s*fattura|data\s*documento|invoice\s*date|issue\s*date)\D{{0,30}}({pattern_data})",
        ]
        for pattern in pattern_con_etichetta:
            match = re.search(pattern, testo, flags=re.IGNORECASE)
            if match:
                data_norm = self._normalizza_data_fattura(match.group(1))
                if data_norm:
                    return data_norm

        for candidato in re.findall(rf"\b({pattern_data})\b", testo):
            data_norm = self._normalizza_data_fattura(candidato)
            if data_norm:
                return data_norm

        return ""

    def _normalizza_data_fattura(self, raw_data):
        if not raw_data:
            return ""

        testo_data = raw_data.strip().replace(".", "/").replace("-", "/")
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

    def _mese_italiano_to_numero(self, mese_raw):
        if not mese_raw:
            return None

        mese = re.sub(r"[^A-Za-z]", "", mese_raw).lower()
        mapping = {
            "gennaio": 1,
            "gen": 1,
            "febbraio": 2,
            "feb": 2,
            "marzo": 3,
            "mar": 3,
            "aprile": 4,
            "apr": 4,
            "maggio": 5,
            "mag": 5,
            "giugno": 6,
            "giu": 6,
            "luglio": 7,
            "lug": 7,
            "agosto": 8,
            "ago": 8,
            "settembre": 9,
            "set": 9,
            "ottobre": 10,
            "ott": 10,
            "novembre": 11,
            "nov": 11,
            "dicembre": 12,
            "dic": 12,
        }
        return mapping.get(mese)

    def _estrai_intestazione_fattura(self, testo, file_path):
        righe = []
        for riga in testo.splitlines():
            pulita = re.sub(r"\s+", " ", riga).strip()
            if pulita:
                righe.append(pulita)

        if not righe:
            return f"Fattura importata: {Path(file_path).name}"

        parole_escluse = (
            "fattura",
            "invoice",
            "numero",
            "data",
            "date",
            "totale",
            "iva",
            "imponibile",
            "pagamento",
            "scadenza",
            "iban",
            "banca",
            "documento",
            "cliente",
            "fornitore",
        )

        for riga in righe[:40]:
            testo_riga = riga.lower()
            if len(riga) < 3:
                continue
            if not re.search(r"[A-Za-z]", riga):
                continue
            if re.fullmatch(r"[0-9€.,/\\\-\s]+", riga):
                continue
            if any(parola in testo_riga for parola in parole_escluse):
                continue
            return riga[:120]

        for riga in righe[:15]:
            if re.search(r"[A-Za-z]", riga):
                return riga[:120]

        return f"Fattura importata: {Path(file_path).name}"

    def _normalizza_importo(self, raw, allow_zero=False):
        if not raw:
            return None
        s = raw.strip()
        s = s.replace("€", "").replace(" ", "").replace("'", "").replace("’", "")

        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")

        try:
            val = float(s)
            if val < 0:
                return None
            if not allow_zero and val <= 0:
                return None
            return val
        except ValueError:
            return None
