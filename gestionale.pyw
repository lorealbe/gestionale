import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
import calendar
import re
from pathlib import Path
from datetime import datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# --- GESTIONE DATABASE ---
DB_NAME = "gestionale.db"
ph = PasswordHasher()  # Argon2 (consigliato)
LITRI_PER_QUINTALE = 100.0

def get_conn():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    """Inizializza le tabelle del database se non esistono."""
    with get_conn() as conn:
        c = conn.cursor()

        # Tabella Utenti (login)
        c.execute('''CREATE TABLE IF NOT EXISTS utenti
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      username TEXT UNIQUE NOT NULL,
                      password_hash TEXT NOT NULL)''')

        # Tabella Profilo (anagrafica collegata all'utente)
        c.execute('''CREATE TABLE IF NOT EXISTS profili
                     (user_id INTEGER PRIMARY KEY,
                      nome TEXT,
                      piva TEXT,
                      professione TEXT,
                      FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE)''')

        # Tabella Movimenti (entrate/uscite collegate all'utente)
        c.execute('''CREATE TABLE IF NOT EXISTS movimenti
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER NOT NULL,
                      data_op TEXT NOT NULL, -- ISO: YYYY-MM-DD
                      tipo TEXT NOT NULL CHECK(tipo IN ('ENTRATA','USCITA')),
                      categoria TEXT,
                      descrizione TEXT,
                      importo REAL NOT NULL,
                      iva_importo REAL NOT NULL DEFAULT 0,
                      FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE)''')

        # Migrazione per database gia esistenti: aggiunge colonna IVA se manca.
        c.execute("PRAGMA table_info(movimenti)")
        colonne_movimenti = {row[1] for row in c.fetchall()}
        if "iva_importo" not in colonne_movimenti:
            c.execute("ALTER TABLE movimenti ADD COLUMN iva_importo REAL NOT NULL DEFAULT 0")

        # Indice utile per velocizzare i report per periodo
        c.execute('''CREATE INDEX IF NOT EXISTS idx_mov_user_date
                     ON movimenti(user_id, data_op)''')

        # Tabella Produzione Latte (quantita salvata in litri, input in quintali)
        c.execute('''CREATE TABLE IF NOT EXISTS produzione_latte
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER NOT NULL,
                      data_op TEXT NOT NULL, -- ISO: YYYY-MM-DD
                      litri REAL NOT NULL CHECK(litri > 0),
                      prezzo_litro REAL NOT NULL DEFAULT 0,
                      movimento_id INTEGER,
                      FOREIGN KEY(movimento_id) REFERENCES movimenti(id) ON DELETE SET NULL,
                      FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE)''')

        # Migrazione per database gia esistenti: aggiunge prezzo_litro se manca.
        c.execute("PRAGMA table_info(produzione_latte)")
        colonne_produzione = {row[1] for row in c.fetchall()}
        if colonne_produzione and "prezzo_litro" not in colonne_produzione:
            c.execute("ALTER TABLE produzione_latte ADD COLUMN prezzo_litro REAL NOT NULL DEFAULT 0")
        if colonne_produzione and "movimento_id" not in colonne_produzione:
            c.execute("ALTER TABLE produzione_latte ADD COLUMN movimento_id INTEGER")

        c.execute('''CREATE INDEX IF NOT EXISTS idx_prod_user_date
                     ON produzione_latte(user_id, data_op)''')

def is_blank(s: str) -> bool:
    return s is None or s.strip() == ""


class CalendarDialog:
    def __init__(self, parent, initial_date=None):
        self.parent = parent
        self.selected_date = None
        self.current_date = initial_date or datetime.now().date()
        self.year = self.current_date.year
        self.month = self.current_date.month

        self.top = tk.Toplevel(parent)
        self.top.title("Seleziona data")
        self.top.resizable(False, False)
        self.top.transient(parent)
        self.top.grab_set()
        self.top.protocol("WM_DELETE_WINDOW", self._close)

        main = ttk.Frame(self.top, padding=10)
        main.pack(fill="both", expand=True)

        header = ttk.Frame(main)
        header.pack(fill="x", pady=(0, 10))

        ttk.Button(header, text="◀", width=3, command=self.prev_month).pack(side="left")
        self.lbl_month = ttk.Label(header, text="", anchor="center", font=("Arial", 11, "bold"))
        self.lbl_month.pack(side="left", fill="x", expand=True)
        ttk.Button(header, text="▶", width=3, command=self.next_month).pack(side="right")

        days = ttk.Frame(main)
        days.pack(fill="x")
        for idx, name in enumerate(["Lu", "Ma", "Me", "Gi", "Ve", "Sa", "Do"]):
            ttk.Label(days, text=name, width=4, anchor="center").grid(row=0, column=idx, padx=1, pady=1)

        self.calendar_frame = ttk.Frame(main)
        self.calendar_frame.pack()

        footer = ttk.Frame(main)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Button(footer, text="Oggi", command=self.select_today).pack(side="left")
        ttk.Button(footer, text="Annulla", command=self._close).pack(side="right")

        self.render_calendar()

    def render_calendar(self):
        for widget in self.calendar_frame.winfo_children():
            widget.destroy()

        self.lbl_month.config(text=f"{calendar.month_name[self.month]} {self.year}")

        month_days = calendar.monthcalendar(self.year, self.month)
        for row_idx, week in enumerate(month_days):
            for col_idx, day in enumerate(week):
                if day == 0:
                    ttk.Label(self.calendar_frame, text="", width=4).grid(row=row_idx, column=col_idx, padx=1, pady=1)
                else:
                    ttk.Button(
                        self.calendar_frame,
                        text=str(day),
                        width=4,
                        command=lambda d=day: self.select_day(d)
                    ).grid(row=row_idx, column=col_idx, padx=1, pady=1)

    def prev_month(self):
        if self.month == 1:
            self.month = 12
            self.year -= 1
        else:
            self.month -= 1
        self.render_calendar()

    def next_month(self):
        if self.month == 12:
            self.month = 1
            self.year += 1
        else:
            self.month += 1
        self.render_calendar()

    def select_day(self, day):
        self.selected_date = datetime(self.year, self.month, day).date()
        self.top.destroy()

    def select_today(self):
        self.selected_date = datetime.now().date()
        self.top.destroy()

    def _close(self):
        self.top.destroy()

    def show(self):
        self.top.wait_window()
        return self.selected_date


# --- FINESTRA DI LOGIN E REGISTRAZIONE ---
class FinestraLogin:
    def __init__(self, root):
        self.root = root
        self.root.title("Login Gestionale")
        self.root.geometry("300x250")

        ttk.Label(root, text="Autenticazione", font=("Arial", 14, "bold")).pack(pady=10)

        ttk.Label(root, text="Username:").pack(pady=5)
        self.entry_user = ttk.Entry(root)
        self.entry_user.pack()

        ttk.Label(root, text="Password:").pack(pady=5)
        self.entry_pass = ttk.Entry(root, show="*")
        self.entry_pass.pack()

        frame_btn = ttk.Frame(root)
        frame_btn.pack(pady=20)

        ttk.Button(frame_btn, text="Accedi", command=self.login).pack(side="left", padx=5)
        ttk.Button(frame_btn, text="Registrati", command=self.registra).pack(side="left", padx=5)

    def registra(self):
        user = self.entry_user.get().strip()
        pwd = self.entry_pass.get()

        if is_blank(user) or is_blank(pwd):
            messagebox.showwarning("Errore", "Inserisci Username e Password")
            return

        try:
            pwd_hash = ph.hash(pwd)
            with get_conn() as conn:
                c = conn.cursor()
                c.execute("INSERT INTO utenti (username, password_hash) VALUES (?, ?)", (user, pwd_hash))
            messagebox.showinfo("Successo", "Registrazione completata! Ora puoi accedere.")
        except sqlite3.IntegrityError:
            messagebox.showerror("Errore", "Nome utente già esistente.")
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")

    def login(self):
        user = self.entry_user.get().strip()
        pwd = self.entry_pass.get()

        if is_blank(user) or is_blank(pwd):
            messagebox.showwarning("Errore", "Inserisci Username e Password")
            return

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT id, password_hash FROM utenti WHERE username=?", (user,))
                row = c.fetchone()

            if not row:
                messagebox.showerror("Accesso Negato", "Username o Password errati.")
                return

            user_id, stored_hash = row[0], row[1]
            try:
                ph.verify(stored_hash, pwd)
            except VerifyMismatchError:
                messagebox.showerror("Accesso Negato", "Username o Password errati.")
                return

            # Svuota la finestra attuale e carica l'app principale
            for widget in self.root.winfo_children():
                widget.destroy()
            AppGestionaleGUI(self.root, user_id)

        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")


# --- APPLICAZIONE PRINCIPALE ---
class AppGestionaleGUI:
    def __init__(self, root, user_id):
        self.root = root
        self.user_id = user_id
        self.movimento_in_modifica_id = None
        self.root.title(f"Gestione Fatture - Utente: {self.user_id}")
        self.root.geometry("700x520")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(pady=10, expand=True, fill="both")

        self.tab_situazione = ttk.Frame(self.notebook)
        self.tab_movimenti = ttk.Frame(self.notebook)
        self.tab_latte = ttk.Frame(self.notebook)
        self.tab_report = ttk.Frame(self.notebook)
        self.tab_storico = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_situazione, text="Situazione Attuale")
        self.notebook.add(self.tab_movimenti, text="Nuovo Movimento")
        self.notebook.add(self.tab_latte, text="Produzione Latte")
        self.notebook.add(self.tab_report, text="Report Periodo")
        self.notebook.add(self.tab_storico, text="Storico Movimenti")

        self.setup_tab_situazione()
        self.setup_tab_movimenti()
        self.setup_tab_latte()
        self.setup_tab_report()
        self.setup_tab_storico()

        self.carica_movimenti()
        self.carica_produzioni_latte(mostra_errori=False)
        self.aggiorna_situazione_attuale(mostra_errori=False)
        self.imposta_periodo_report_default(mostra_errori=False)
        self.genera_report()

    # --- SCHEDA SITUAZIONE ---
    def setup_tab_situazione(self):
        ttk.Label(self.tab_situazione, text="Situazione Attuale", font=("Arial", 14, "bold")).pack(pady=12)

        frame_stats = ttk.Frame(self.tab_situazione, padding=12)
        frame_stats.pack(fill="x", padx=20, pady=10)

        self.var_tot_movimenti = tk.StringVar(value="0")
        self.var_tot_entrate = tk.StringVar(value="EUR 0.00")
        self.var_tot_uscite = tk.StringVar(value="EUR 0.00")
        self.var_tot_utile = tk.StringVar(value="EUR 0.00")

        righe = [
            ("Numero di movimenti:", self.var_tot_movimenti),
            ("Entrate:", self.var_tot_entrate),
            ("Uscite:", self.var_tot_uscite),
            ("Utile:", self.var_tot_utile),
        ]

        for idx, (testo, valore) in enumerate(righe):
            ttk.Label(frame_stats, text=testo, width=22).grid(row=idx, column=0, sticky="w", pady=4)
            ttk.Label(frame_stats, textvariable=valore, font=("Arial", 11, "bold")).grid(row=idx, column=1, sticky="w", pady=4)

        ttk.Button(self.tab_situazione, text="Aggiorna situazione", command=self.aggiorna_situazione_attuale).pack(pady=8)

    def aggiorna_situazione_attuale(self, mostra_errori=True):
        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute('''
                    SELECT COUNT(id),
                           COALESCE(SUM(CASE WHEN tipo='ENTRATA' THEN importo ELSE 0 END), 0),
                           COALESCE(SUM(CASE WHEN tipo='USCITA' THEN importo ELSE 0 END), 0)
                    FROM movimenti
                    WHERE user_id=?
                ''', (self.user_id,))
                row = c.fetchone()
        except sqlite3.Error as e:
            if mostra_errori:
                messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        num_movimenti = int((row[0] if row else 0) or 0)
        tot_entrate = float((row[1] if row else 0) or 0)
        tot_uscite = float((row[2] if row else 0) or 0)
        utile = tot_entrate - tot_uscite

        self.var_tot_movimenti.set(str(num_movimenti))
        self.var_tot_entrate.set(f"EUR {tot_entrate:.2f}")
        self.var_tot_uscite.set(f"EUR {tot_uscite:.2f}")
        self.var_tot_utile.set(f"EUR {utile:.2f}")

    # --- SCHEDA MOVIMENTI ---
    def setup_tab_movimenti(self):
        ttk.Label(self.tab_movimenti, text="Registra Movimento", font=("Arial", 14, "bold")).pack(pady=10)

        self.var_data = tk.StringVar(value=datetime.now().strftime("%d/%m/%Y"))
        self.var_tipo = tk.StringVar(value="ENTRATA")
        self.var_cat = tk.StringVar()
        self.var_desc = tk.StringVar()
        self.var_imp = tk.StringVar()
        self.var_iva = tk.StringVar(value="0.00")

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
        self.crea_campo(self.tab_movimenti, "Importo (€):", self.var_imp)
        self.crea_campo(self.tab_movimenti, "IVA (€):", self.var_iva)

        frame_actions = ttk.Frame(self.tab_movimenti)
        frame_actions.pack(pady=20)

        self.btn_salva_movimento = ttk.Button(frame_actions, text="Salva nel DB", command=self.salva_movimento)
        self.btn_salva_movimento.pack(side="left", padx=6)

        self.btn_annulla_modifica = ttk.Button(
            frame_actions,
            text="Annulla modifica",
            command=self.annulla_modifica_movimento,
            state="disabled"
        )
        self.btn_annulla_modifica.pack(side="left", padx=6)

        ttk.Button(frame_actions, text="Importa fattura PDF", command=self.importa_fattura_pdf).pack(side="left", padx=6)

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

                if self.movimento_in_modifica_id is None:
                    c.execute('''
                        INSERT INTO movimenti (user_id, data_op, tipo, categoria, descrizione, importo, iva_importo)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (self.user_id,
                          data_db,
                          self.var_tipo.get(),
                          self.var_cat.get().strip(),
                          self.var_desc.get().strip(),
                          importo_val,
                          iva_val))
                    msg_ok = "Movimento salvato nel database!"
                else:
                    c.execute('''
                        UPDATE movimenti
                        SET data_op=?, tipo=?, categoria=?, descrizione=?, importo=?, iva_importo=?
                        WHERE id=? AND user_id=?
                    ''', (data_db,
                          self.var_tipo.get(),
                          self.var_cat.get().strip(),
                          self.var_desc.get().strip(),
                          importo_val,
                          iva_val,
                          self.movimento_in_modifica_id,
                          self.user_id))

                    if c.rowcount == 0:
                        messagebox.showerror("Errore", "Movimento non trovato o non modificabile.")
                        return
                    msg_ok = "Movimento aggiornato nel database!"

            messagebox.showinfo("Successo", msg_ok)
            self.annulla_modifica_movimento()
            self.carica_movimenti()
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")

    def importa_fattura_pdf(self):
        if self.movimento_in_modifica_id is not None:
            self.annulla_modifica_movimento()

        file_path = filedialog.askopenfilename(
            title="Seleziona fattura PDF",
            filetypes=[("PDF", "*.pdf")]
        )
        if not file_path:
            return

        try:
            testo = self.estrai_testo_pdf(file_path)
            dati = self.analizza_testo_fattura(testo, file_path)
        except Exception as e:
            messagebox.showerror("Importazione fallita", str(e))
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

        # Data (dd/mm/yyyy o dd-mm-yyyy)
        data_match = re.search(r"\b(\d{2}[/-]\d{2}[/-]\d{4})\b", testo)
        data_out = ""
        if data_match:
            raw = data_match.group(1).replace("-", "/")
            try:
                data_out = datetime.strptime(raw, "%d/%m/%Y").strftime("%d/%m/%Y")
            except ValueError:
                data_out = ""

        # Importo: prima cerca vicino a parole chiave
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

        # Fallback: prende il massimo importo trovato
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
            "descrizione": f"Fattura importata: {Path(file_path).name}",
            "importo": f"{importo:.2f}" if importo is not None else "",
            "iva": f"{iva:.2f}",
        }

    def _normalizza_importo(self, raw, allow_zero=False):
        if not raw:
            return None
        s = raw.strip()
        s = s.replace("€", "").replace(" ", "")

        # Gestione separatori IT/EN
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

    # --- SCHEDA LATTE ---
    def setup_tab_latte(self):
        ttk.Label(self.tab_latte, text="Produzione Latte", font=("Arial", 14, "bold")).pack(pady=10)

        self.var_latte_data = tk.StringVar(value=datetime.now().strftime("%d/%m/%Y"))
        self.var_latte_quintali = tk.StringVar()
        self.var_latte_prezzo = tk.StringVar(value="0.00")

        self.crea_campo_data(self.tab_latte, "Data produzione:", self.var_latte_data)
        self.crea_campo(self.tab_latte, "Quintali prodotti:", self.var_latte_quintali)
        self.crea_campo(self.tab_latte, "Prezzo al litro (EUR):", self.var_latte_prezzo)

        ttk.Label(self.tab_latte, text="Conversione automatica: 1 quintale = 100 litri").pack(pady=(0, 6))

        frame_actions = ttk.Frame(self.tab_latte)
        frame_actions.pack(pady=10)

        ttk.Button(frame_actions, text="Salva Produzione", command=self.salva_produzione_latte).pack(side="left", padx=6)
        ttk.Button(frame_actions, text="Ricarica Storico", command=self.carica_produzioni_latte).pack(side="left", padx=6)
        ttk.Button(frame_actions, text="Elimina selezionata", command=self.elimina_produzione_latte_selezionata).pack(side="left", padx=6)

        frame_table = ttk.Frame(self.tab_latte)
        frame_table.pack(fill="both", expand=True, padx=12, pady=8)

        cols = ("id", "data", "quintali", "prezzo")
        self.tree_produzione = ttk.Treeview(frame_table, columns=cols, show="headings", height=10)

        self.tree_produzione.heading("id", text="ID")
        self.tree_produzione.heading("data", text="Data")
        self.tree_produzione.heading("quintali", text="Quintali")
        self.tree_produzione.heading("prezzo", text="Prezzo / L")

        self.tree_produzione.column("id", width=60, anchor="center")
        self.tree_produzione.column("data", width=120, anchor="center")
        self.tree_produzione.column("quintali", width=140, anchor="e")
        self.tree_produzione.column("prezzo", width=140, anchor="e")

        scroll = ttk.Scrollbar(frame_table, orient="vertical", command=self.tree_produzione.yview)
        self.tree_produzione.configure(yscrollcommand=scroll.set)

        self.tree_produzione.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tree_produzione.bind("<Delete>", lambda _event: self.elimina_produzione_latte_selezionata())

    def salva_produzione_latte(self):
        if is_blank(self.var_latte_data.get()):
            messagebox.showerror("Errore", "Inserisci la data di produzione.")
            return
        if is_blank(self.var_latte_quintali.get()):
            messagebox.showerror("Errore", "Inserisci i quintali prodotti.")
            return

        try:
            data_obj = datetime.strptime(self.var_latte_data.get().strip(), "%d/%m/%Y")
            data_db = data_obj.strftime("%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Errore", "Formato data non valido (Usa GG/MM/AAAA)")
            return

        quintali_val = self._normalizza_importo(self.var_latte_quintali.get(), allow_zero=False)
        if quintali_val is None:
            messagebox.showerror("Errore", "Quintali non validi.")
            return

        litri_val = quintali_val * LITRI_PER_QUINTALE

        prezzo_text = self.var_latte_prezzo.get().strip()
        if is_blank(prezzo_text):
            prezzo_val = 0.0
        else:
            prezzo_val = self._normalizza_importo(prezzo_text, allow_zero=True)
            if prezzo_val is None:
                messagebox.showerror("Errore", "Prezzo al litro non valido.")
                return

        importo_entrata = litri_val * prezzo_val
        descrizione_mov = f"Produzione latte: {quintali_val:.2f} q ({litri_val:.2f} L) x EUR {prezzo_val:.4f}/L"

        try:
            with get_conn() as conn:
                c = conn.cursor()

                c.execute('''
                    INSERT INTO movimenti (user_id, data_op, tipo, categoria, descrizione, importo, iva_importo)
                    VALUES (?, ?, 'ENTRATA', ?, ?, ?, 0)
                ''', (
                    self.user_id,
                    data_db,
                    "Latte",
                    descrizione_mov,
                    importo_entrata,
                ))
                movimento_id = c.lastrowid

                c.execute('''
                    INSERT INTO produzione_latte (user_id, data_op, litri, prezzo_litro, movimento_id)
                    VALUES (?, ?, ?, ?, ?)
                ''', (self.user_id, data_db, litri_val, prezzo_val, movimento_id))
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        self.var_latte_quintali.set("")
        self.carica_produzioni_latte(mostra_errori=False)
        self.carica_movimenti()
        messagebox.showinfo("Successo", f"Produzione latte salvata ({quintali_val:.2f} q)! Entrata automatica: EUR {importo_entrata:.2f}")

    def carica_produzioni_latte(self, mostra_errori=True):
        if not hasattr(self, "tree_produzione"):
            return

        for item in self.tree_produzione.get_children():
            self.tree_produzione.delete(item)

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute('''
                    SELECT id, data_op, litri, prezzo_litro, movimento_id
                    FROM produzione_latte
                    WHERE user_id=?
                    ORDER BY data_op DESC, id DESC
                ''', (self.user_id,))
                rows = c.fetchall()
        except sqlite3.Error as e:
            if mostra_errori:
                messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        for prod_id, data_op, litri, prezzo_litro, _movimento_id in rows:
            try:
                data_view = datetime.strptime(data_op, "%Y-%m-%d").strftime("%d/%m/%Y")
            except ValueError:
                data_view = data_op

            quintali = float(litri) / LITRI_PER_QUINTALE

            self.tree_produzione.insert(
                "",
                "end",
                values=(
                    prod_id,
                    data_view,
                    f"{quintali:.2f}",
                    f"{float(prezzo_litro):.4f}"
                )
            )

    def elimina_produzione_latte_selezionata(self):
        selezione = self.tree_produzione.selection()
        if not selezione:
            messagebox.showwarning("Attenzione", "Seleziona prima una riga di produzione da eliminare.")
            return

        valori = self.tree_produzione.item(selezione[0], "values")
        if not valori:
            messagebox.showerror("Errore", "Impossibile leggere la produzione selezionata.")
            return

        prod_id = int(valori[0])
        conferma = messagebox.askyesno(
            "Conferma eliminazione",
            f"Vuoi eliminare la produzione selezionata?\n\nData: {valori[1]} - Quintali: {valori[2]}"
        )
        if not conferma:
            return

        try:
            with get_conn() as conn:
                c = conn.cursor()

                c.execute("SELECT movimento_id FROM produzione_latte WHERE id=? AND user_id=?", (prod_id, self.user_id))
                row = c.fetchone()
                if not row:
                    messagebox.showerror("Errore", "Produzione non trovata o non eliminabile.")
                    return

                movimento_id = row[0]

                c.execute("DELETE FROM produzione_latte WHERE id=? AND user_id=?", (prod_id, self.user_id))
                if c.rowcount == 0:
                    messagebox.showerror("Errore", "Produzione non trovata o non eliminabile.")
                    return

                if movimento_id is not None:
                    c.execute("DELETE FROM movimenti WHERE id=? AND user_id=?", (movimento_id, self.user_id))
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        self.carica_produzioni_latte(mostra_errori=False)
        self.carica_movimenti()
        messagebox.showinfo("Successo", "Produzione eliminata dal database!")

    # --- SCHEDA STORICO ---
    def setup_tab_storico(self):
        ttk.Label(self.tab_storico, text="Movimenti inseriti", font=("Arial", 14, "bold")).pack(pady=10)

        frame_table = ttk.Frame(self.tab_storico)
        frame_table.pack(fill="both", expand=True, padx=12, pady=6)

        cols = ("id", "data", "tipo", "categoria", "descrizione", "importo", "iva")
        self.tree_movimenti = ttk.Treeview(frame_table, columns=cols, show="headings", height=14)

        self.tree_movimenti.heading("id", text="ID")
        self.tree_movimenti.heading("data", text="Data")
        self.tree_movimenti.heading("tipo", text="Tipo")
        self.tree_movimenti.heading("categoria", text="Categoria")
        self.tree_movimenti.heading("descrizione", text="Descrizione")
        self.tree_movimenti.heading("importo", text="Importo")
        self.tree_movimenti.heading("iva", text="IVA")

        self.tree_movimenti.column("id", width=60, anchor="center")
        self.tree_movimenti.column("data", width=100, anchor="center")
        self.tree_movimenti.column("tipo", width=90, anchor="center")
        self.tree_movimenti.column("categoria", width=130, anchor="w")
        self.tree_movimenti.column("descrizione", width=180, anchor="w")
        self.tree_movimenti.column("importo", width=90, anchor="e")
        self.tree_movimenti.column("iva", width=90, anchor="e")

        scroll = ttk.Scrollbar(frame_table, orient="vertical", command=self.tree_movimenti.yview)
        self.tree_movimenti.configure(yscrollcommand=scroll.set)

        self.tree_movimenti.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tree_movimenti.bind("<Double-1>", lambda _event: self.prepara_modifica_movimento())
        self.tree_movimenti.bind("<Delete>", lambda _event: self.elimina_movimento_selezionato())

        frame_btn = ttk.Frame(self.tab_storico)
        frame_btn.pack(pady=10)

        ttk.Button(frame_btn, text="Ricarica", command=self.carica_movimenti).pack(side="left", padx=6)
        ttk.Button(frame_btn, text="Modifica selezionato", command=self.prepara_modifica_movimento).pack(side="left", padx=6)
        ttk.Button(frame_btn, text="Elimina selezionato", command=self.elimina_movimento_selezionato).pack(side="left", padx=6)

    def carica_movimenti(self):
        if not hasattr(self, "tree_movimenti"):
            return

        for item in self.tree_movimenti.get_children():
            self.tree_movimenti.delete(item)

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute('''
                    SELECT id, data_op, tipo, categoria, descrizione, importo, iva_importo
                    FROM movimenti
                    WHERE user_id=?
                    ORDER BY data_op DESC, id DESC
                ''', (self.user_id,))
                rows = c.fetchall()
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        for mov_id, data_op, tipo, categoria, descrizione, importo, iva_importo in rows:
            try:
                data_view = datetime.strptime(data_op, "%Y-%m-%d").strftime("%d/%m/%Y")
            except ValueError:
                data_view = data_op

            self.tree_movimenti.insert(
                "",
                "end",
                values=(
                    mov_id,
                    data_view,
                    tipo,
                    categoria or "",
                    descrizione or "",
                    f"{float(importo):.2f}",
                    f"{float(iva_importo):.2f}"
                )
            )

        self.carica_categorie_salvate(mostra_errori=False)
        self.aggiorna_situazione_attuale(mostra_errori=False)

    def carica_categorie_salvate(self, mostra_errori=True):
        if not hasattr(self, "combo_categoria"):
            return

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute('''
                    SELECT DISTINCT TRIM(categoria) AS cat
                    FROM movimenti
                    WHERE user_id=?
                      AND categoria IS NOT NULL
                      AND TRIM(categoria) <> ''
                    ORDER BY cat COLLATE NOCASE
                ''', (self.user_id,))
                rows = c.fetchall()
        except sqlite3.Error as e:
            if mostra_errori:
                messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        categorie = [row[0] for row in rows if row[0]]
        self.combo_categoria["values"] = categorie

    def prepara_modifica_movimento(self):
        selezione = self.tree_movimenti.selection()
        if not selezione:
            messagebox.showwarning("Attenzione", "Seleziona prima un movimento da modificare.")
            return

        valori = self.tree_movimenti.item(selezione[0], "values")
        if not valori:
            messagebox.showerror("Errore", "Impossibile leggere il movimento selezionato.")
            return

        self.movimento_in_modifica_id = int(valori[0])
        self.var_data.set(valori[1] or datetime.now().strftime("%d/%m/%Y"))
        self.var_tipo.set(valori[2] or "ENTRATA")
        self.var_cat.set(valori[3] or "")
        self.var_desc.set(valori[4] or "")
        self.var_imp.set((valori[5] or "").replace(",", "."))
        self.var_iva.set((valori[6] or "0.00").replace(",", "."))

        self.btn_salva_movimento.config(text="Aggiorna nel DB")
        self.btn_annulla_modifica.config(state="normal")
        self.notebook.select(self.tab_movimenti)

    def elimina_movimento_selezionato(self):
        selezione = self.tree_movimenti.selection()
        if not selezione:
            messagebox.showwarning("Attenzione", "Seleziona prima un movimento da eliminare.")
            return

        valori = self.tree_movimenti.item(selezione[0], "values")
        if not valori:
            messagebox.showerror("Errore", "Impossibile leggere il movimento selezionato.")
            return

        mov_id = int(valori[0])
        descrizione = valori[4] or f"ID {mov_id}"
        conferma = messagebox.askyesno(
            "Conferma eliminazione",
            f"Vuoi eliminare il movimento selezionato?\n\n{descrizione}"
        )
        if not conferma:
            return

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM movimenti WHERE id=? AND user_id=?", (mov_id, self.user_id))

                if c.rowcount == 0:
                    messagebox.showerror("Errore", "Movimento non trovato o non eliminabile.")
                    return
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        if self.movimento_in_modifica_id == mov_id:
            self.annulla_modifica_movimento()

        self.carica_movimenti()
        messagebox.showinfo("Successo", "Movimento eliminato dal database!")

    def annulla_modifica_movimento(self):
        self.movimento_in_modifica_id = None
        self.btn_salva_movimento.config(text="Salva nel DB")
        self.btn_annulla_modifica.config(state="disabled")

        self.var_data.set(datetime.now().strftime("%d/%m/%Y"))
        self.var_tipo.set("ENTRATA")
        self.var_cat.set("")
        self.var_desc.set("")
        self.var_imp.set("")
        self.var_iva.set("0.00")

    # --- SCHEDA REPORT ---
    def setup_tab_report(self):
        ttk.Label(self.tab_report, text="Genera Report tramite DB", font=("Arial", 14, "bold")).pack(pady=10)

        self.var_data_inizio = tk.StringVar()
        self.var_data_fine = tk.StringVar()
        self.var_data_inizio.trace_add("write", self._auto_compila_data_fine)

        self.crea_campo_data(self.tab_report, "Data INIZIO:", self.var_data_inizio)
        self.crea_campo_data(self.tab_report, "Data FINE:", self.var_data_fine)

        ttk.Button(self.tab_report, text="Interroga DB e Calcola", command=self.genera_report).pack(pady=15)

        frame_report = ttk.Frame(self.tab_report)
        frame_report.pack(padx=20, pady=10, fill="both", expand=True)

        scroll = ttk.Scrollbar(frame_report, orient="vertical")
        scroll.pack(side="right", fill="y")

        self.txt_risultato = tk.Text(
            frame_report,
            height=12,
            width=60,
            state="disabled",
            wrap="word",
            yscrollcommand=scroll.set
        )
        self.txt_risultato.pack(side="left", fill="both", expand=True)

        scroll.config(command=self.txt_risultato.yview)

    def _auto_compila_data_fine(self, *_args):
        if is_blank(self.var_data_fine.get()) and not is_blank(self.var_data_inizio.get()):
            self.var_data_fine.set(self.var_data_inizio.get())

    def imposta_periodo_report_default(self, mostra_errori=True):
        oggi = datetime.now().strftime("%d/%m/%Y")
        data_inizio = oggi
        data_fine = oggi

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT MIN(data_op), MAX(data_op) FROM movimenti WHERE user_id=?", (self.user_id,))
                row = c.fetchone()

            if row and row[0]:
                data_inizio = datetime.strptime(row[0], "%Y-%m-%d").strftime("%d/%m/%Y")
                data_fine_iso = row[1] or row[0]
                data_fine = datetime.strptime(data_fine_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
        except (sqlite3.Error, ValueError) as e:
            if mostra_errori:
                messagebox.showerror("Errore DB", f"Errore database: {e}")

        self.var_data_inizio.set(data_inizio)
        self.var_data_fine.set(data_fine)

    def genera_report(self):
        try:
            inizio = datetime.strptime(self.var_data_inizio.get().strip(), "%d/%m/%Y")
            fine = datetime.strptime(self.var_data_fine.get().strip(), "%d/%m/%Y")
        except ValueError:
            messagebox.showerror("Errore", "Formato date non valido (Usa GG/MM/AAAA).")
            return

        if inizio > fine:
            messagebox.showerror("Errore", "La data INIZIO non puo essere successiva alla data FINE.")
            return

        inizio_db = inizio.strftime("%Y-%m-%d")
        fine_db = fine.strftime("%Y-%m-%d")

        try:
            with get_conn() as conn:
                c = conn.cursor()

                c.execute('''
                    SELECT tipo, COALESCE(SUM(importo), 0) AS totale, COUNT(id) AS qta
                    FROM movimenti
                    WHERE user_id=? AND data_op BETWEEN ? AND ?
                    GROUP BY tipo
                ''', (self.user_id, inizio_db, fine_db))
                risultati = c.fetchall()

                c.execute('''
                    SELECT COALESCE(SUM(iva_importo), 0)
                    FROM movimenti
                    WHERE user_id=? AND data_op BETWEEN ? AND ?
                ''', (self.user_id, inizio_db, fine_db))
                row_iva = c.fetchone()
                totale_iva = float(row_iva[0] or 0)

                c.execute('''
                    SELECT COALESCE(SUM(litri), 0),
                           COUNT(id),
                           COALESCE(SUM(litri * prezzo_litro), 0)
                    FROM produzione_latte
                    WHERE user_id=? AND data_op BETWEEN ? AND ?
                ''', (self.user_id, inizio_db, fine_db))
                row_latte = c.fetchone()
                tot_litri = float(row_latte[0] or 0)
                qta_produzioni = int(row_latte[1] or 0)
                totale_valore_latte = float(row_latte[2] or 0)

                c.execute('''
                    SELECT tipo,
                           COALESCE(NULLIF(TRIM(categoria), ''), '(Senza categoria)') AS cat,
                           COALESCE(SUM(importo), 0) AS totale,
                           COUNT(id) AS qta
                    FROM movimenti
                    WHERE user_id=? AND data_op BETWEEN ? AND ?
                    GROUP BY tipo, cat
                    ORDER BY tipo, totale DESC
                ''', (self.user_id, inizio_db, fine_db))
                righe_cat = c.fetchall()

        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        tot_entrate = 0.0
        tot_uscite = 0.0
        conteggio = 0

        for tipo, totale, qta in risultati:
            conteggio += qta
            if tipo == "ENTRATA":
                tot_entrate = float(totale or 0)
            elif tipo == "USCITA":
                tot_uscite = float(totale or 0)

        saldo = tot_entrate - tot_uscite
        giorni_periodo = (fine - inizio).days + 1
        media_litri_giorno = (tot_litri / giorni_periodo) if giorni_periodo > 0 else 0.0
        media_litri_registrazione = (tot_litri / qta_produzioni) if qta_produzioni > 0 else 0.0
        tot_quintali = tot_litri / LITRI_PER_QUINTALE
        media_quintali_giorno = media_litri_giorno / LITRI_PER_QUINTALE
        media_quintali_registrazione = media_litri_registrazione / LITRI_PER_QUINTALE
        prezzo_medio_litro = (totale_valore_latte / tot_litri) if tot_litri > 0 else 0.0
        costo_produzione_litro = (tot_uscite / tot_litri) if tot_litri > 0 else 0.0
        utile_litro = (saldo / tot_litri) if tot_litri > 0 else 0.0

        report_text = f"Movimenti estratti dal DB: {conteggio}\n"
        report_text += f"Produzioni latte nel periodo: {qta_produzioni}\n"
        report_text += "-" * 30 + "\n"
        report_text += f"Totale Entrate: EUR {tot_entrate:.2f}\n"
        report_text += f"Totale Uscite:  EUR {tot_uscite:.2f}\n"
        report_text += f"Totale IVA:     EUR {totale_iva:.2f}\n"
        report_text += f"Totale Quintali: {tot_quintali:.2f} q ({tot_litri:.2f} L)\n"
        report_text += f"Media Quintali/Giorno: {media_quintali_giorno:.2f} q\n"
        report_text += f"Media Quintali/Registrazione: {media_quintali_registrazione:.2f} q\n"
        report_text += f"Prezzo Medio/Litro: EUR {prezzo_medio_litro:.4f}\n"
        report_text += f"Costo Produzione/Litro: EUR {costo_produzione_litro:.4f}\n"
        report_text += f"Utile/Litro: EUR {utile_litro:.4f}\n"
        report_text += "-" * 30 + "\n"
        report_text += f"SALDO NETTO:   EUR {saldo:.2f}\n\n"

        report_text += "DETTAGLIO PER CATEGORIA\n"
        report_text += "-" * 30 + "\n"

        tipo_corrente = None
        for tipo, cat, totale, qta in righe_cat:
            if tipo != tipo_corrente:
                tipo_corrente = tipo
                report_text += f"\n[{tipo}]\n"
            report_text += f"- {cat}: EUR {float(totale):.2f} ({qta} mov.)\n"

        self.txt_risultato.config(state="normal")
        self.txt_risultato.delete(1.0, tk.END)
        self.txt_risultato.insert(tk.END, report_text)
        self.txt_risultato.config(state="disabled")

    def crea_campo(self, parent, label_text, text_var):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", padx=20, pady=5)
        ttk.Label(frame, text=label_text, width=20).pack(side="left")
        ttk.Entry(frame, textvariable=text_var).pack(side="left", fill="x", expand=True)

    def crea_campo_categoria(self, parent, label_text, text_var):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", padx=20, pady=5)
        ttk.Label(frame, text=label_text, width=20).pack(side="left")

        self.combo_categoria = ttk.Combobox(
            frame,
            textvariable=text_var,
            state="normal",
            postcommand=self.carica_categorie_salvate
        )
        self.combo_categoria.pack(side="left", fill="x", expand=True)

        ttk.Button(frame, text="Aggiorna", command=self.carica_categorie_salvate).pack(side="left", padx=(5, 0))

    def crea_campo_data(self, parent, label_text, text_var):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", padx=20, pady=5)
        ttk.Label(frame, text=label_text, width=20).pack(side="left")

        entry = ttk.Entry(frame, textvariable=text_var, state="readonly")
        entry.pack(side="left", fill="x", expand=True)

        def apri_calendario():
            date_text = text_var.get().strip()
            if date_text:
                try:
                    initial_date = datetime.strptime(date_text, "%d/%m/%Y").date()
                except ValueError:
                    initial_date = datetime.now().date()
            else:
                initial_date = datetime.now().date()

            scelta = CalendarDialog(self.root, initial_date).show()
            if scelta is not None:
                text_var.set(scelta.strftime("%d/%m/%Y"))

        ttk.Button(frame, text="...", width=3, command=apri_calendario).pack(side="left", padx=(5, 0))
        entry.bind("<Button-1>", lambda _event: apri_calendario())
# --- AVVIO DEL PROGRAMMA ---
if __name__ == "__main__":
    init_db()
    root_window = tk.Tk()
    app = FinestraLogin(root_window)
    root_window.mainloop()