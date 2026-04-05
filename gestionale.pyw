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
                      FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE)''')

        # Indice utile per velocizzare i report per periodo
        c.execute('''CREATE INDEX IF NOT EXISTS idx_mov_user_date
                     ON movimenti(user_id, data_op)''')

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
        self.root.title(f"Gestione Fatture - Utente ID: {self.user_id}")
        self.root.geometry("700x520")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(pady=10, expand=True, fill="both")

        self.tab_profilo = ttk.Frame(self.notebook)
        self.tab_movimenti = ttk.Frame(self.notebook)
        self.tab_report = ttk.Frame(self.notebook)
        self.tab_storico = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_profilo, text="Profilo Utente")
        self.notebook.add(self.tab_movimenti, text="Nuovo Movimento")
        self.notebook.add(self.tab_report, text="Report Periodo")
        self.notebook.add(self.tab_storico, text="Storico Movimenti")

        self.setup_tab_profilo()
        self.setup_tab_movimenti()
        self.setup_tab_report()
        self.setup_tab_storico()

        self.carica_profilo()
        self.carica_movimenti()

    # --- SCHEDA PROFILO ---
    def setup_tab_profilo(self):
        ttk.Label(self.tab_profilo, text="I tuoi dati (Salvati nel DB):", font=("Arial", 14, "bold")).pack(pady=10)

        self.var_nome = tk.StringVar()
        self.var_piva = tk.StringVar()
        self.var_prof = tk.StringVar()

        self.crea_campo(self.tab_profilo, "Nome Completo:", self.var_nome)
        self.crea_campo(self.tab_profilo, "Partita IVA / CF:", self.var_piva)
        self.crea_campo(self.tab_profilo, "Professione:", self.var_prof)

        ttk.Button(self.tab_profilo, text="Salva/Aggiorna Profilo", command=self.salva_profilo).pack(pady=20)

    def carica_profilo(self):
        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT nome, piva, professione FROM profili WHERE user_id=?", (self.user_id,))
                row = c.fetchone()

            if row:
                self.var_nome.set(row[0] or "")
                self.var_piva.set(row[1] or "")
                self.var_prof.set(row[2] or "")
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")

    def salva_profilo(self):
        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute('''
                    INSERT INTO profili (user_id, nome, piva, professione)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        nome=excluded.nome,
                        piva=excluded.piva,
                        professione=excluded.professione
                ''', (self.user_id,
                      self.var_nome.get().strip(),
                      self.var_piva.get().strip(),
                      self.var_prof.get().strip()))
            messagebox.showinfo("Successo", "Dati del profilo aggiornati nel database!")
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")

    # --- SCHEDA MOVIMENTI ---
    def setup_tab_movimenti(self):
        ttk.Label(self.tab_movimenti, text="Registra Movimento", font=("Arial", 14, "bold")).pack(pady=10)

        self.var_data = tk.StringVar(value=datetime.now().strftime("%d/%m/%Y"))
        self.var_tipo = tk.StringVar(value="ENTRATA")
        self.var_cat = tk.StringVar()
        self.var_desc = tk.StringVar()
        self.var_imp = tk.StringVar()

        self.crea_campo_data(self.tab_movimenti, "Data:", self.var_data)

        frame_tipo = ttk.Frame(self.tab_movimenti)
        frame_tipo.pack(fill="x", padx=20, pady=5)
        ttk.Label(frame_tipo, text="Tipo:", width=20).pack(side="left")
        frame_radio = ttk.Frame(frame_tipo)
        frame_radio.pack(side="left", fill="x", expand=True)

        ttk.Radiobutton(frame_radio, text="Entrata", value="ENTRATA", variable=self.var_tipo).pack(side="left", padx=(0, 15))
        ttk.Radiobutton(frame_radio, text="Uscita", value="USCITA", variable=self.var_tipo).pack(side="left")

        self.crea_campo(self.tab_movimenti, "Categoria:", self.var_cat)
        self.crea_campo(self.tab_movimenti, "Descrizione:", self.var_desc)
        self.crea_campo(self.tab_movimenti, "Importo (€):", self.var_imp)

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

        try:
            importo_val = float(self.var_imp.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Errore", "Importo non valido.")
            return

        if importo_val <= 0:
            messagebox.showerror("Errore", "L'importo deve essere maggiore di 0.")
            return

        try:
            with get_conn() as conn:
                c = conn.cursor()

                if self.movimento_in_modifica_id is None:
                    c.execute('''
                        INSERT INTO movimenti (user_id, data_op, tipo, categoria, descrizione, importo)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (self.user_id,
                          data_db,
                          self.var_tipo.get(),
                          self.var_cat.get().strip(),
                          self.var_desc.get().strip(),
                          importo_val))
                    msg_ok = "Movimento salvato nel database!"
                else:
                    c.execute('''
                        UPDATE movimenti
                        SET data_op=?, tipo=?, categoria=?, descrizione=?, importo=?
                        WHERE id=? AND user_id=?
                    ''', (data_db,
                          self.var_tipo.get(),
                          self.var_cat.get().strip(),
                          self.var_desc.get().strip(),
                          importo_val,
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

        # Fallback: prende il massimo importo trovato
        if importo is None:
            candidati = re.findall(r"[€\s]*\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|[€\s]*\d+(?:[.,]\d{2})", testo)
            valori = [self._normalizza_importo(c) for c in candidati]
            valori = [v for v in valori if v is not None]
            if valori:
                importo = max(valori)

        tipo = "USCITA"
        if "nota di credito" in t or "rimborso" in t:
            tipo = "ENTRATA"

        return {
            "data": data_out or datetime.now().strftime("%d/%m/%Y"),
            "tipo": tipo,
            "categoria": "Fattura",
            "descrizione": f"Fattura importata: {Path(file_path).name}",
            "importo": f"{importo:.2f}" if importo is not None else "",
        }

    def _normalizza_importo(self, raw):
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
            return val if val > 0 else None
        except ValueError:
            return None

    # --- SCHEDA STORICO ---
    def setup_tab_storico(self):
        ttk.Label(self.tab_storico, text="Movimenti inseriti", font=("Arial", 14, "bold")).pack(pady=10)

        frame_table = ttk.Frame(self.tab_storico)
        frame_table.pack(fill="both", expand=True, padx=12, pady=6)

        cols = ("id", "data", "tipo", "categoria", "descrizione", "importo")
        self.tree_movimenti = ttk.Treeview(frame_table, columns=cols, show="headings", height=14)

        self.tree_movimenti.heading("id", text="ID")
        self.tree_movimenti.heading("data", text="Data")
        self.tree_movimenti.heading("tipo", text="Tipo")
        self.tree_movimenti.heading("categoria", text="Categoria")
        self.tree_movimenti.heading("descrizione", text="Descrizione")
        self.tree_movimenti.heading("importo", text="Importo")

        self.tree_movimenti.column("id", width=60, anchor="center")
        self.tree_movimenti.column("data", width=100, anchor="center")
        self.tree_movimenti.column("tipo", width=90, anchor="center")
        self.tree_movimenti.column("categoria", width=130, anchor="w")
        self.tree_movimenti.column("descrizione", width=220, anchor="w")
        self.tree_movimenti.column("importo", width=100, anchor="e")

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
                    SELECT id, data_op, tipo, categoria, descrizione, importo
                    FROM movimenti
                    WHERE user_id=?
                    ORDER BY data_op DESC, id DESC
                ''', (self.user_id,))
                rows = c.fetchall()
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        for mov_id, data_op, tipo, categoria, descrizione, importo in rows:
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
                    f"{float(importo):.2f}"
                )
            )

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

    # --- SCHEDA REPORT ---
    def setup_tab_report(self):
        ttk.Label(self.tab_report, text="Genera Report tramite DB", font=("Arial", 14, "bold")).pack(pady=10)

        self.var_data_inizio = tk.StringVar()
        self.var_data_fine = tk.StringVar()

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

        report_text = f"Movimenti estratti dal DB: {conteggio}\n"
        report_text += "-" * 30 + "\n"
        report_text += f"Totale Entrate: EUR {tot_entrate:.2f}\n"
        report_text += f"Totale Uscite:  EUR {tot_uscite:.2f}\n"
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