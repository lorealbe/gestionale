import tkinter as tk
import re
import shutil
import sqlite3
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

                if self.movimento_in_modifica_id is None:
                    c.execute(
                        '''
                        INSERT INTO movimenti (user_id, data_op, tipo, categoria, descrizione, importo, iva_importo)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''',
                        (
                            self.user_id,
                            data_db,
                            self.var_tipo.get(),
                            self.var_cat.get().strip(),
                            self.var_desc.get().strip(),
                            importo_val,
                            iva_val,
                        ),
                    )
                    movimento_salvato_id = c.lastrowid
                    msg_ok = "Movimento salvato nel database!"
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
        self.var_nome_fattura_mov.set(Path(percorso_archiviato).name)

        try:
            testo = self.estrai_testo_pdf(percorso_archiviato)
            dati = self.analizza_testo_fattura(testo, file_path)
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
        t = testo.lower()
        intestazione = self._estrai_intestazione_fattura(testo, file_path)

        data_match = re.search(r"\b(\d{2}[/-]\d{2}[/-]\d{4})\b", testo)
        data_out = ""
        if data_match:
            raw = data_match.group(1).replace("-", "/")
            try:
                data_out = datetime.strptime(raw, "%d/%m/%Y").strftime("%d/%m/%Y")
            except ValueError:
                data_out = ""

        patterns = [
            r"(?:totale\s+da\s+pagare|importo\s+totale|totale\s+fattura|totale)\D{0,25}([€\s]*\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|[€\s]*\d+(?:[.,]\d{2}))",
            r"(?:da\s+pagare)\D{0,25}([€\s]*\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|[€\s]*\d+(?:[.,]\d{2}))",
        ]

        importo = None
        for p in patterns:
            m = re.search(p, t, flags=re.IGNORECASE)
            if m:
                importo = self._normalizza_importo(m.group(1))
                if importo is not None:
                    break

        iva = None
        iva_patterns = [
            r"(?:imposta\s*iva|iva(?:\s*imposta)?)\D{0,20}([€\s]*\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|[€\s]*\d+(?:[.,]\d{2}))",
        ]

        for p in iva_patterns:
            m = re.search(p, t, flags=re.IGNORECASE)
            if m:
                iva = self._normalizza_importo(m.group(1), allow_zero=True)
                if iva is not None:
                    break

        if importo is None:
            candidati = re.findall(r"[€\s]*\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|[€\s]*\d+(?:[.,]\d{2})", testo)
            valori = [self._normalizza_importo(c) for c in candidati]
            valori = [v for v in valori if v is not None]
            if valori:
                importo = max(valori)

        if iva is None:
            iva = 0.0

        tipo = "USCITA"
        if "nota di credito" in t or "rimborso" in t:
            tipo = "ENTRATA"

        return {
            "data": data_out or datetime.now().strftime("%d/%m/%Y"),
            "tipo": tipo,
            "categoria": "Fattura",
            "descrizione": intestazione,
            "importo": format_number(importo, 2) if importo is not None else "",
            "iva": format_number(iva, 2),
        }

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
