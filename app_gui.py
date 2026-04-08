import calendar
import sqlite3
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app_utils import is_blank
from database import get_conn
from tabs import (
    AgricolturaTabMixin,
    AziendaTabMixin,
    AttrezzatureTabMixin,
    CarneTabMixin,
    FormHelpersMixin,
    LatteTabMixin,
    MacchinariTabMixin,
    MovimentiTabMixin,
    StoricoTabMixin,
    ZootecniaTabMixin,
)

ph = PasswordHasher()  # Argon2 (consigliato)


def _invoke_button_on_enter(event):
    widget = event.widget
    if isinstance(widget, (ttk.Button, tk.Button)):
        try:
            widget.invoke()
            return "break"
        except tk.TclError:
            return None
    return None


def _enable_enter_on_buttons(root_widget):
    # Consente di attivare un pulsante con Invio quando ha il focus.
    root_widget.bind_class("TButton", "<Return>", _invoke_button_on_enter)
    root_widget.bind_class("TButton", "<KP_Enter>", _invoke_button_on_enter)
    root_widget.bind_class("Button", "<Return>", _invoke_button_on_enter)
    root_widget.bind_class("Button", "<KP_Enter>", _invoke_button_on_enter)


def _enable_tab_focus_on_buttons(container):
    for child in container.winfo_children():
        if isinstance(child, (ttk.Button, tk.Button)):
            try:
                child.configure(takefocus=True)
            except tk.TclError:
                pass
        _enable_tab_focus_on_buttons(child)


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

        _enable_enter_on_buttons(self.top)

        main = ttk.Frame(self.top, padding=10)
        main.pack(fill="both", expand=True)

        header = ttk.Frame(main)
        header.pack(fill="x", pady=(0, 10))

        ttk.Button(header, text="<", width=3, command=self.prev_month, takefocus=True).pack(side="left")
        self.lbl_month = ttk.Label(header, text="", anchor="center", font=("Arial", 11, "bold"))
        self.lbl_month.pack(side="left", fill="x", expand=True)
        ttk.Button(header, text=">", width=3, command=self.next_month, takefocus=True).pack(side="right")

        days = ttk.Frame(main)
        days.pack(fill="x")
        for idx in range(7):
            days.grid_columnconfigure(idx, weight=1, uniform="giorni")
        for idx, name in enumerate(["Lu", "Ma", "Me", "Gi", "Ve", "Sa", "Do"]):
            ttk.Label(days, text=name, anchor="center").grid(row=0, column=idx, padx=1, pady=1, sticky="ew")

        self.calendar_frame = ttk.Frame(main)
        self.calendar_frame.pack()

        footer = ttk.Frame(main)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Button(footer, text="Oggi", command=self.select_today, takefocus=True).pack(side="left")
        ttk.Button(footer, text="Annulla", command=self._close, takefocus=True).pack(side="right")

        self.render_calendar()
        _enable_tab_focus_on_buttons(self.top)

    def render_calendar(self):
        for widget in self.calendar_frame.winfo_children():
            widget.destroy()

        for idx in range(7):
            self.calendar_frame.grid_columnconfigure(idx, weight=1, uniform="celle")

        self.lbl_month.config(text=f"{calendar.month_name[self.month]} {self.year}")

        month_days = calendar.monthcalendar(self.year, self.month)
        for row_idx, week in enumerate(month_days):
            for col_idx, day in enumerate(week):
                if day == 0:
                    ttk.Label(self.calendar_frame, text="").grid(
                        row=row_idx,
                        column=col_idx,
                        padx=1,
                        pady=1,
                        sticky="nsew",
                    )
                else:
                    ttk.Button(
                        self.calendar_frame,
                        text=str(day),
                        command=lambda d=day: self.select_day(d),
                        takefocus=True,
                    ).grid(row=row_idx, column=col_idx, padx=1, pady=1, sticky="nsew")

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


class FinestraLogin:
    def __init__(self, root):
        self.root = root
        self.root.title("Login Gestionale")
        self.root.geometry("300x250")

        _enable_enter_on_buttons(self.root)

        ttk.Label(root, text="Autenticazione", font=("Arial", 14, "bold")).pack(pady=10)

        ttk.Label(root, text="Username:").pack(pady=5)
        self.entry_user = ttk.Entry(root)
        self.entry_user.pack()

        ttk.Label(root, text="Password:").pack(pady=5)
        self.entry_pass = ttk.Entry(root, show="*")
        self.entry_pass.pack()

        frame_btn = ttk.Frame(root)
        frame_btn.pack(pady=20)

        self.btn_login = ttk.Button(frame_btn, text="Accedi", command=self.login, takefocus=True)
        self.btn_login.pack(side="left", padx=5)
        self.btn_registra = ttk.Button(frame_btn, text="Registrati", command=self.registra, takefocus=True)
        self.btn_registra.pack(side="left", padx=5)

        _enable_tab_focus_on_buttons(self.root)
        self.root.bind("<Return>", self._on_login_enter)
        self.root.bind("<KP_Enter>", self._on_login_enter)

        self.entry_user.focus_set()

    def _on_login_enter(self, _event=None):
        focused = self.root.focus_get()
        if focused == self.btn_registra:
            self.registra()
        else:
            self.login()
        return "break"

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
            messagebox.showerror("Errore", "Nome utente gia esistente.")
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

            self.root.unbind("<Return>")
            self.root.unbind("<KP_Enter>")
            for widget in self.root.winfo_children():
                widget.destroy()
            AppGestionaleGUI(self.root, user_id)
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")


class AppGestionaleGUI(
    FormHelpersMixin,
    AgricolturaTabMixin,
    AziendaTabMixin,
    AttrezzatureTabMixin,
    CarneTabMixin,
    MacchinariTabMixin,
    MovimentiTabMixin,
    LatteTabMixin,
    StoricoTabMixin,
    ZootecniaTabMixin,
):
    CATEGORIA_AZIENDA = "Azienda"
    CATEGORIA_AGRICOLTURA = "Agricoltura"
    CATEGORIA_ATTREZZATURE = "Attrezzature"
    CATEGORIA_MACCHINARI = "Macchinari"
    CATEGORIA_ZOOTECNIA = "Zootecnia"

    def __init__(self, root, user_id):
        self.root = root
        self.user_id = user_id
        self.calendar_dialog_cls = CalendarDialog

        self.root.unbind("<Return>")
        self.root.unbind("<KP_Enter>")
        _enable_enter_on_buttons(self.root)

        self.movimento_in_modifica_id = None
        self.pending_fattura_movimento_id = None
        self.pending_fattura_movimento_path = None
        self.pending_parser_movimento_data = None
        self.pending_fattura_latte_id = None
        self.pending_fattura_latte_path = None
        self.pending_parser_latte_data = None
        self.pending_fattura_carne_id = None
        self.pending_fattura_carne_path = None
        self.pending_parser_carne_data = None
        self.produzione_carne_in_modifica_id = None

        self.root.title("Gestione Fatture")
        self.root.geometry("980x700")
        self._apri_a_schermo_intero()

        self._setup_menu_bar()

        self.main_container = ttk.Frame(self.root)
        self.main_container.pack(pady=10, padx=10, expand=True, fill="both")
        self.main_container.grid_rowconfigure(0, weight=1)
        self.main_container.grid_columnconfigure(0, weight=1)

        self.frame_azienda = ttk.Frame(self.main_container)
        self.frame_agricoltura = ttk.Frame(self.main_container)
        self.frame_attrezzature = ttk.Frame(self.main_container)
        self.frame_macchinari = ttk.Frame(self.main_container)
        self.frame_zootecnia = ttk.Frame(self.main_container)

        self._categoria_frames = {
            self.CATEGORIA_AZIENDA: self.frame_azienda,
            self.CATEGORIA_AGRICOLTURA: self.frame_agricoltura,
            self.CATEGORIA_ATTREZZATURE: self.frame_attrezzature,
            self.CATEGORIA_MACCHINARI: self.frame_macchinari,
            self.CATEGORIA_ZOOTECNIA: self.frame_zootecnia,
        }
        for frame in self._categoria_frames.values():
            frame.grid(row=0, column=0, sticky="nsew")

        self.setup_categoria_azienda()
        self._setup_categoria_agricoltura()
        self._setup_categoria_attrezzature()
        self._setup_categoria_macchinari()
        self._setup_categoria_zootecnia()

        if hasattr(self, "abilita_a_capo_tutte_treeview"):
            self.abilita_a_capo_tutte_treeview()

        _enable_tab_focus_on_buttons(self.root)

        self.carica_movimenti()
        self.carica_produzioni_latte(mostra_errori=False)
        self.aggiorna_categoria_zootecnia()
        self.mostra_categoria(self.CATEGORIA_AZIENDA)

    def _apri_a_schermo_intero(self):
        # Preferiamo una finestra massimizzata (non kiosk fullscreen) per mantenere la UI standard.
        self.root.update_idletasks()

        try:
            self.root.state("zoomed")
            return
        except tk.TclError:
            pass

        try:
            self.root.attributes("-zoomed", True)
            return
        except tk.TclError:
            pass

        larghezza = self.root.winfo_screenwidth()
        altezza = self.root.winfo_screenheight()
        self.root.geometry(f"{larghezza}x{altezza}+0+0")

    def _setup_menu_bar(self):
        menu_bar = tk.Menu(self.root)
        menu_bar.add_command(
            label=self.CATEGORIA_AZIENDA,
            command=lambda: self.mostra_categoria(self.CATEGORIA_AZIENDA),
        )
        menu_bar.add_command(
            label=self.CATEGORIA_AGRICOLTURA,
            command=lambda: self.mostra_categoria(self.CATEGORIA_AGRICOLTURA),
        )
        menu_bar.add_command(
            label=self.CATEGORIA_ATTREZZATURE,
            command=lambda: self.mostra_categoria(self.CATEGORIA_ATTREZZATURE),
        )
        menu_bar.add_command(
            label=self.CATEGORIA_MACCHINARI,
            command=lambda: self.mostra_categoria(self.CATEGORIA_MACCHINARI),
        )
        menu_bar.add_command(
            label=self.CATEGORIA_ZOOTECNIA,
            command=lambda: self.mostra_categoria(self.CATEGORIA_ZOOTECNIA),
        )

        account_menu = tk.Menu(menu_bar, tearoff=False)
        account_menu.add_command(label="Cambia utente", command=self.cambia_utente)
        menu_bar.add_cascade(label="Account", menu=account_menu)

        self.root.config(menu=menu_bar)
        self.menu_bar = menu_bar

    def _setup_categoria_placeholder(self, frame, titolo, descrizione):
        container = self.crea_container_scorribile(frame, padding=18)
        ttk.Label(container, text=titolo, font=("Arial", 14, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(container, text=descrizione, wraplength=860, justify="left").pack(anchor="w")

    def mostra_categoria(self, nome_categoria):
        frame = self._categoria_frames.get(nome_categoria)
        if frame is None:
            return

        frame.tkraise()

        if nome_categoria == self.CATEGORIA_AZIENDA and hasattr(self, "genera_report_azienda"):
            self.genera_report_azienda(mostra_errori=False)
            if hasattr(self, "carica_dati_azienda_info"):
                self.carica_dati_azienda_info(mostra_errori=False)
            if hasattr(self, "carica_movimenti_azienda_storico"):
                self.carica_movimenti_azienda_storico(mostra_errori=False)

        if nome_categoria == self.CATEGORIA_ZOOTECNIA:
            self.aggiorna_categoria_zootecnia()

    def cambia_utente(self):
        conferma = messagebox.askyesno("Conferma", "Vuoi uscire e cambiare utente?")
        if not conferma:
            return

        self.root.config(menu="")
        for widget in self.root.winfo_children():
            widget.destroy()
        FinestraLogin(self.root)

