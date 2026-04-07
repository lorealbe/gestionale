import calendar
import re
import sqlite3
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app_utils import format_eur, format_number, is_blank, parse_decimal
from database import get_conn, list_azienda_animali_entries
from services.latte_group_metrics import (
    calcola_metriche_latte_da_totali as svc_calcola_metriche_latte_da_totali,
    costruisci_quote_litri_produzioni as svc_costruisci_quote_litri_produzioni,
    ripartizione_litri_produzione_per_gruppo as svc_ripartizione_litri_produzione_per_gruppo,
)
from tabs import (
    AziendaTabMixin,
    FormHelpersMixin,
    LatteTabMixin,
    MovimentiTabMixin,
    ReportTabMixin,
    StoricoTabMixin,
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
    AziendaTabMixin,
    MovimentiTabMixin,
    LatteTabMixin,
    ReportTabMixin,
    StoricoTabMixin,
):
    CATEGORIA_OPERATIVA = "Operativa"
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

        self.root.title("Gestione Fatture")
        self.root.geometry("980x700")
        self._apri_a_schermo_intero()

        self._setup_menu_bar()

        self.main_container = ttk.Frame(self.root)
        self.main_container.pack(pady=10, padx=10, expand=True, fill="both")
        self.main_container.grid_rowconfigure(0, weight=1)
        self.main_container.grid_columnconfigure(0, weight=1)

        self.frame_operativa = ttk.Frame(self.main_container)
        self.frame_azienda = ttk.Frame(self.main_container)
        self.frame_agricoltura = ttk.Frame(self.main_container)
        self.frame_attrezzature = ttk.Frame(self.main_container)
        self.frame_macchinari = ttk.Frame(self.main_container)
        self.frame_zootecnia = ttk.Frame(self.main_container)

        self._categoria_frames = {
            self.CATEGORIA_OPERATIVA: self.frame_operativa,
            self.CATEGORIA_AZIENDA: self.frame_azienda,
            self.CATEGORIA_AGRICOLTURA: self.frame_agricoltura,
            self.CATEGORIA_ATTREZZATURE: self.frame_attrezzature,
            self.CATEGORIA_MACCHINARI: self.frame_macchinari,
            self.CATEGORIA_ZOOTECNIA: self.frame_zootecnia,
        }
        for frame in self._categoria_frames.values():
            frame.grid(row=0, column=0, sticky="nsew")

        self._setup_area_operativa()
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
        self.imposta_periodo_report_default(mostra_errori=False)
        self.genera_report()
        self.aggiorna_categoria_zootecnia()
        self.mostra_categoria(self.CATEGORIA_OPERATIVA)

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
            label=self.CATEGORIA_OPERATIVA,
            command=lambda: self.mostra_categoria(self.CATEGORIA_OPERATIVA),
        )
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

    def _setup_area_operativa(self):
        self.notebook = ttk.Notebook(self.frame_operativa)
        self.notebook.pack(pady=4, padx=4, expand=True, fill="both")

        self.tab_report = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_report, text="Report Periodo")

        self.setup_tab_report()

    def _setup_categoria_attrezzature(self):
        self._setup_categoria_placeholder(
            self.frame_attrezzature,
            "Attrezzature",
            "Sezione pronta per inventario, manutenzione e scadenze delle attrezzature.",
        )

    def _setup_categoria_agricoltura(self):
        self._setup_categoria_placeholder(
            self.frame_agricoltura,
            "Agricoltura",
            "Sezione pronta per colture, trattamenti e operazioni agricole.",
        )

    def _setup_categoria_macchinari(self):
        self._setup_categoria_placeholder(
            self.frame_macchinari,
            "Macchinari",
            "Sezione pronta per gestione macchinari, ore lavoro e manutenzioni.",
        )

    def _setup_categoria_zootecnia(self):
        container = self.crea_container_scorribile(self.frame_zootecnia, padding=18, stretch_to_viewport=True)

        ttk.Label(container, text="Zootecnia", font=("Arial", 14, "bold")).pack(anchor="w", pady=(0, 8))

        self.var_zootecnia_stato = tk.StringVar(value="")

        ttk.Label(container, textvariable=self.var_zootecnia_stato, wraplength=860, justify="left").pack(
            anchor="w", pady=(0, 8)
        )

        frame_btn = ttk.Frame(container)
        frame_btn.pack(anchor="w", pady=(0, 8))
        ttk.Button(
            frame_btn,
            text="Configura tipi allevamento",
            command=self.apri_configurazione_allevamento,
        ).pack(side="left", padx=(0, 6))
        ttk.Button(frame_btn, text="Aggiorna", command=self.aggiorna_categoria_zootecnia).pack(side="left")

        self.frame_zootecnia_pagine = ttk.Frame(container)
        self.frame_zootecnia_pagine.pack(fill="both", expand=True)

        self.zootecnia_notebook = ttk.Notebook(self.frame_zootecnia_pagine)
        self.zootecnia_notebook.pack(fill="both", expand=True)
        self.tab_zootecnia_latte = None
        self.tab_zootecnia_info_generali = None

        self.lbl_zootecnia_vuoto = ttk.Label(
            self.frame_zootecnia_pagine,
            text="Nessun tipo allevamento impostato.",
            justify="left",
            wraplength=860,
        )

    def _zootecnia_label_tipo(self, entry):
        tipo = (entry.get("tipo_animale") or "").strip().upper()
        altro_label = (entry.get("altro_label") or "").strip()

        if tipo == "ALTRO":
            return f"Altro ({altro_label})" if altro_label else "Altro"
        return tipo.title() if tipo else "Tipo sconosciuto"

    def _zootecnia_label_destinazione(self, entry):
        finalita = (entry.get("finalita") or "").strip().upper()
        if finalita == "LATTE":
            return "Da Latte"
        if finalita == "CARNE":
            return "Da Carne"
        return "-"

    def _is_entry_latte_attiva(self, entry):
        finalita = (entry.get("finalita") or "").strip().upper()
        capi = int(entry.get("capi") or 0)
        return finalita == "LATTE" and capi > 0

    def _periodo_report_corrente_db(self):
        oggi = datetime.now()
        data_inizio = oggi
        data_fine = oggi

        data_inizio_text = ""
        data_fine_text = ""
        if hasattr(self, "var_data_inizio"):
            data_inizio_text = self.var_data_inizio.get().strip()
        if hasattr(self, "var_data_fine"):
            data_fine_text = self.var_data_fine.get().strip()

        if data_inizio_text:
            try:
                data_inizio = datetime.strptime(data_inizio_text, "%d/%m/%Y")
            except ValueError:
                pass

        if data_fine_text:
            try:
                data_fine = datetime.strptime(data_fine_text, "%d/%m/%Y")
            except ValueError:
                pass

        if data_inizio > data_fine:
            data_inizio, data_fine = data_fine, data_inizio

        return {
            "inizio": data_inizio,
            "fine": data_fine,
            "inizio_db": data_inizio.strftime("%Y-%m-%d"),
            "fine_db": data_fine.strftime("%Y-%m-%d"),
        }

    @staticmethod
    def _normalizza_token_gruppo_parser(raw_value):
        testo = str(raw_value or "").strip().lower()
        return re.sub(r"\s+", " ", testo)

    def _costruisci_lookup_gruppi_parser(self):
        try:
            entries = list_azienda_animali_entries(self.user_id)
        except sqlite3.Error:
            entries = []

        lookup = {}
        token_ambigui = set()

        def registra(token, entry_id):
            norm = self._normalizza_token_gruppo_parser(token)
            if not norm:
                return
            if norm in token_ambigui:
                return

            corrente = lookup.get(norm)
            if corrente is None:
                lookup[norm] = entry_id
                return

            if corrente != entry_id:
                lookup.pop(norm, None)
                token_ambigui.add(norm)

        for entry in entries:
            try:
                entry_id = int(entry.get("id") or 0)
            except (TypeError, ValueError):
                continue

            if entry_id <= 0:
                continue

            group_name = (entry.get("group_name") or "").strip()
            label_movimento = ""
            if hasattr(self, "_label_gruppo_animale_movimento"):
                try:
                    label_movimento = self._label_gruppo_animale_movimento(entry)
                except Exception:
                    label_movimento = ""

            registra(group_name, entry_id)
            registra(label_movimento, entry_id)
            registra(f"Gruppo {entry_id}", entry_id)
            registra(f"ID {entry_id}", entry_id)

            if label_movimento:
                parti = [part.strip() for part in str(label_movimento).split("|")]
                if len(parti) >= 3:
                    registra(" | ".join(parti[:3]), entry_id)

        return lookup

    def _risolvi_ids_gruppo_da_testo_parser(self, groups_text, movimento_link_ids, lookup_gruppi):
        testo = str(groups_text or "").strip()
        if not testo:
            return []

        norm_completo = self._normalizza_token_gruppo_parser(testo)
        if not norm_completo or norm_completo in {"-", "nessun gruppo"}:
            return []

        linked_ids = []
        linked_ids_seen = set()
        for raw_id in movimento_link_ids or []:
            try:
                entry_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if entry_id <= 0 or entry_id in linked_ids_seen:
                continue
            linked_ids.append(entry_id)
            linked_ids_seen.add(entry_id)

        if "tutti i gruppi" in norm_completo:
            return linked_ids

        resolved_ids = []
        resolved_seen = set()
        blocchi = [blocco.strip() for blocco in testo.split(",") if blocco and blocco.strip()]
        for blocco in blocchi:
            norm_blocco = self._normalizza_token_gruppo_parser(blocco)
            if not norm_blocco:
                continue

            entry_id = lookup_gruppi.get(norm_blocco)
            if entry_id is None:
                match = re.search(r"\bid\s*(\d+)\b", norm_blocco)
                if match:
                    entry_id = int(match.group(1))

            if entry_id is None:
                continue
            if entry_id <= 0 or entry_id in resolved_seen:
                continue

            resolved_ids.append(entry_id)
            resolved_seen.add(entry_id)

        if resolved_ids:
            return resolved_ids

        return linked_ids

    def _mappa_capi_gruppi_animali(self):
        try:
            entries = list_azienda_animali_entries(self.user_id)
        except sqlite3.Error:
            entries = []

        capi_map = {}
        for entry in entries:
            try:
                entry_id = int(entry.get("id") or 0)
                capi = int(entry.get("capi") or 0)
            except (TypeError, ValueError):
                continue

            if entry_id <= 0:
                continue
            capi_map[entry_id] = max(capi, 0)

        return capi_map

    def _ripartizione_litri_produzione_per_gruppo(self, litri_totali, linked_ids, allocazioni_esplicite, capi_map):
        return svc_ripartizione_litri_produzione_per_gruppo(
            litri_totali,
            linked_ids,
            allocazioni_esplicite,
            capi_map,
        )

    def _costruisci_quote_litri_produzioni(self, produzione_rows, link_map, allocazioni_esplicite_map, capi_map):
        return svc_costruisci_quote_litri_produzioni(
            produzione_rows,
            link_map,
            allocazioni_esplicite_map,
            capi_map,
        )

    def _prepara_dati_metriche_latte_per_gruppi(self, capi_overrides=None):
        periodo = self._periodo_report_corrente_db()
        inizio_db = periodo["inizio_db"]
        fine_db = periodo["fine_db"]

        lookup_gruppi = self._costruisci_lookup_gruppi_parser()

        with get_conn() as conn:
            c = conn.cursor()

            c.execute(
                '''
                SELECT id,
                       tipo,
                       COALESCE(importo, 0),
                       COALESCE(iva_importo, 0),
                       COALESCE(parser_products, '')
                FROM movimenti
                WHERE user_id=? AND data_op BETWEEN ? AND ?
            ''',
                (self.user_id, inizio_db, fine_db),
            )
            movimenti_rows = c.fetchall()

            c.execute(
                '''
                SELECT l.movimento_id, l.animale_entry_id
                FROM movimenti_animali_link l
                JOIN movimenti m
                  ON m.user_id = l.user_id
                 AND m.id = l.movimento_id
                WHERE l.user_id=? AND m.data_op BETWEEN ? AND ?
            ''',
                (self.user_id, inizio_db, fine_db),
            )
            link_rows = c.fetchall()

            c.execute(
                '''
                SELECT id,
                       movimento_id,
                       COALESCE(litri, 0),
                       COALESCE(prezzo_litro, 0)
                FROM produzione_latte
                WHERE user_id=? AND data_op BETWEEN ? AND ?
            ''',
                (self.user_id, inizio_db, fine_db),
            )
            produzione_rows = c.fetchall()

            c.execute(
                '''
                SELECT g.produzione_id,
                       g.animale_entry_id,
                       COALESCE(g.litri, 0)
                FROM produzione_latte_gruppi g
                JOIN produzione_latte p
                  ON p.user_id = g.user_id
                 AND p.id = g.produzione_id
                WHERE g.user_id=? AND p.data_op BETWEEN ? AND ?
            ''',
                (self.user_id, inizio_db, fine_db),
            )
            allocazioni_rows = c.fetchall()

        link_map = {}
        for movimento_id_raw, entry_id_raw in link_rows:
            try:
                movimento_id = int(movimento_id_raw or 0)
                entry_id = int(entry_id_raw or 0)
            except (TypeError, ValueError):
                continue
            if movimento_id <= 0 or entry_id <= 0:
                continue

            current_ids = link_map.setdefault(movimento_id, [])
            if entry_id not in current_ids:
                current_ids.append(entry_id)

        allocazioni_esplicite_map = {}
        for produzione_id_raw, entry_id_raw, litri_raw in allocazioni_rows:
            try:
                produzione_id = int(produzione_id_raw or 0)
                entry_id = int(entry_id_raw or 0)
            except (TypeError, ValueError):
                continue
            if produzione_id <= 0 or entry_id <= 0:
                continue

            litri_value = parse_decimal(litri_raw, allow_zero=True, allow_negative=False)
            if litri_value is None or litri_value <= 0:
                continue

            quote_produzione = allocazioni_esplicite_map.setdefault(produzione_id, {})
            quote_produzione[entry_id] = float(litri_value)

        capi_map = self._mappa_capi_gruppi_animali()
        if isinstance(capi_overrides, dict):
            for raw_entry_id, raw_capi in capi_overrides.items():
                try:
                    entry_id = int(raw_entry_id)
                    capi = int(raw_capi)
                except (TypeError, ValueError):
                    continue
                if entry_id <= 0:
                    continue
                capi_map[entry_id] = max(capi, 0)

        quote_per_produzione, quote_ratio_per_movimento_entrate = self._costruisci_quote_litri_produzioni(
            produzione_rows,
            link_map,
            allocazioni_esplicite_map,
            capi_map,
        )

        return {
            "periodo": periodo,
            "lookup_gruppi": lookup_gruppi,
            "movimenti_rows": movimenti_rows,
            "link_map": link_map,
            "produzione_rows": produzione_rows,
            "quote_per_produzione": quote_per_produzione,
            "quote_ratio_per_movimento_entrate": quote_ratio_per_movimento_entrate,
        }

    def _quota_movimento_per_gruppo(
        self,
        movimento_row,
        animale_entry_id,
        movimento_link_ids,
        lookup_gruppi,
        quote_ratio_entrate_per_movimento=None,
    ):
        movimento_id, tipo, importo_raw, iva_raw, parser_products = movimento_row

        linked_ids = []
        linked_seen = set()
        for raw_id in movimento_link_ids or []:
            try:
                entry_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if entry_id <= 0 or entry_id in linked_seen:
                continue
            linked_ids.append(entry_id)
            linked_seen.add(entry_id)

        if animale_entry_id not in linked_ids:
            return 0.0, 0.0, 0.0, 0.0, False

        importo = float(importo_raw or 0)
        iva_importo = float(iva_raw or 0)
        tipo_mov = str(tipo or "").strip().upper()

        if tipo_mov == "ENTRATA" and quote_ratio_entrate_per_movimento:
            quote_mov = quote_ratio_entrate_per_movimento.get(int(movimento_id or 0), {})
            quota_ratio = float(quote_mov.get(animale_entry_id, 0) or 0)
            if quota_ratio <= 0:
                return 0.0, 0.0, 0.0, 0.0, False

            quota_ratio = max(0.0, min(1.0, quota_ratio))
            return importo * quota_ratio, iva_importo * quota_ratio, 0.0, 0.0, True

        if tipo_mov == "USCITA" and parser_products and hasattr(self, "_estrai_righe_prodotti_da_parser_text"):
            righe_prodotti = self._estrai_righe_prodotti_da_parser_text(parser_products)
            if righe_prodotti:
                quota_gruppo = 0.0
                totale_righe = 0.0
                righe_con_imputazione = 0
                quota_costi_fissi = 0.0
                quota_costi_variabili = 0.0

                for riga in righe_prodotti:
                    totale_riga = parse_decimal(riga.get("line_total"), allow_zero=True, allow_negative=False)
                    if totale_riga is None or totale_riga <= 0:
                        continue

                    totale_righe += totale_riga
                    ids_riga = self._risolvi_ids_gruppo_da_testo_parser(
                        riga.get("groups"),
                        linked_ids,
                        lookup_gruppi,
                    )
                    if not ids_riga:
                        ids_riga = linked_ids
                    if not ids_riga:
                        continue

                    righe_con_imputazione += 1
                    quota_riga = totale_riga / max(len(ids_riga), 1)
                    if animale_entry_id in ids_riga:
                        quota_gruppo += quota_riga

                        tipo_costo = str(riga.get("cost_type") or "").strip().lower()
                        if hasattr(self, "_normalizza_tipo_costo_storico_prodotti"):
                            try:
                                tipo_costo = self._normalizza_tipo_costo_storico_prodotti(riga.get("cost_type")).lower()
                            except Exception:
                                pass

                        if tipo_costo.startswith("fiss"):
                            quota_costi_fissi += quota_riga
                        else:
                            quota_costi_variabili += quota_riga

                if totale_righe > 0 and righe_con_imputazione > 0:
                    if quota_gruppo <= 0:
                        return 0.0, 0.0, 0.0, 0.0, False

                    ratio_iva = quota_gruppo / totale_righe
                    ratio_iva = max(0.0, min(1.0, ratio_iva))
                    return quota_gruppo, iva_importo * ratio_iva, quota_costi_fissi, quota_costi_variabili, True

        quota_base = 1.0 / len(linked_ids) if linked_ids else 0.0
        if quota_base <= 0:
            return 0.0, 0.0, 0.0, 0.0, False

        quota_importo = importo * quota_base
        quota_iva = iva_importo * quota_base
        quota_costi_fissi = 0.0
        quota_costi_variabili = quota_importo if tipo_mov == "USCITA" else 0.0
        return quota_importo, quota_iva, quota_costi_fissi, quota_costi_variabili, True

    def _calcola_metriche_latte_da_totali(
        self,
        *,
        periodo,
        movimenti_estratti,
        qta_produzioni,
        tot_entrate,
        tot_uscite,
        totale_iva,
        tot_litri,
        totale_valore_latte,
        totale_capi=0,
        totale_costi_fissi=0.0,
        totale_costi_variabili=0.0,
    ):
        return svc_calcola_metriche_latte_da_totali(
            periodo=periodo,
            movimenti_estratti=movimenti_estratti,
            qta_produzioni=qta_produzioni,
            tot_entrate=tot_entrate,
            tot_uscite=tot_uscite,
            totale_iva=totale_iva,
            tot_litri=tot_litri,
            totale_valore_latte=totale_valore_latte,
            totale_capi=totale_capi,
            totale_costi_fissi=totale_costi_fissi,
            totale_costi_variabili=totale_costi_variabili,
        )

    def _calcola_metriche_latte_report_operativa(self):
        periodo = self._periodo_report_corrente_db()
        inizio_db = periodo["inizio_db"]
        fine_db = periodo["fine_db"]

        with get_conn() as conn:
            c = conn.cursor()

            c.execute(
                '''
                SELECT tipo, COALESCE(SUM(importo), 0), COUNT(id)
                FROM movimenti
                WHERE user_id=? AND data_op BETWEEN ? AND ?
                GROUP BY tipo
            ''',
                (self.user_id, inizio_db, fine_db),
            )
            risultati_movimenti = c.fetchall()

            c.execute(
                '''
                SELECT COALESCE(SUM(iva_importo), 0)
                FROM movimenti
                WHERE user_id=? AND data_op BETWEEN ? AND ?
            ''',
                (self.user_id, inizio_db, fine_db),
            )
            row_iva = c.fetchone()

            c.execute(
                '''
                SELECT COALESCE(SUM(litri), 0),
                       COUNT(id),
                       COALESCE(SUM(litri * prezzo_litro), 0)
                FROM produzione_latte
                WHERE user_id=? AND data_op BETWEEN ? AND ?
            ''',
                (self.user_id, inizio_db, fine_db),
            )
            row_latte = c.fetchone()

        tot_entrate = 0.0
        tot_uscite = 0.0
        movimenti_estratti = 0
        for tipo, totale, qta in risultati_movimenti:
            movimenti_estratti += int(qta or 0)
            if tipo == "ENTRATA":
                tot_entrate = float(totale or 0)
            elif tipo == "USCITA":
                tot_uscite = float(totale or 0)

        totale_iva = float((row_iva[0] if row_iva else 0) or 0)
        tot_litri = float((row_latte[0] if row_latte else 0) or 0)
        qta_produzioni = int((row_latte[1] if row_latte else 0) or 0)
        totale_valore_latte = float((row_latte[2] if row_latte else 0) or 0)

        return self._calcola_metriche_latte_da_totali(
            periodo=periodo,
            movimenti_estratti=movimenti_estratti,
            qta_produzioni=qta_produzioni,
            tot_entrate=tot_entrate,
            tot_uscite=tot_uscite,
            totale_iva=totale_iva,
            tot_litri=tot_litri,
            totale_valore_latte=totale_valore_latte,
        )

    def _calcola_metriche_latte_report_operativa_per_gruppo(self, animale_entry_id, totale_capi=0, shared_data=None):
        if not isinstance(shared_data, dict):
            shared_data = self._prepara_dati_metriche_latte_per_gruppi()

        periodo = shared_data.get("periodo") or self._periodo_report_corrente_db()
        lookup_gruppi = shared_data.get("lookup_gruppi") or {}
        movimenti_rows = shared_data.get("movimenti_rows") or []
        link_map = shared_data.get("link_map") or {}
        produzione_rows = shared_data.get("produzione_rows") or []
        quote_per_produzione = shared_data.get("quote_per_produzione") or {}
        quote_ratio_per_movimento_entrate = shared_data.get("quote_ratio_per_movimento_entrate") or {}

        tot_entrate = 0.0
        tot_uscite = 0.0
        totale_iva = 0.0
        totale_costi_fissi = 0.0
        totale_costi_variabili = 0.0
        movimenti_estratti = set()

        for movimento_row in movimenti_rows:
            movimento_id = int(movimento_row[0] or 0)
            if movimento_id <= 0:
                continue

            linked_ids = link_map.get(movimento_id, [])
            quota_importo, quota_iva, quota_fissi, quota_variabili, contribuisce = self._quota_movimento_per_gruppo(
                movimento_row,
                animale_entry_id,
                linked_ids,
                lookup_gruppi,
                quote_ratio_entrate_per_movimento=quote_ratio_per_movimento_entrate,
            )
            if not contribuisce:
                continue

            movimenti_estratti.add(movimento_id)
            tipo = (movimento_row[1] or "").strip().upper()
            if tipo == "ENTRATA":
                tot_entrate += quota_importo
            elif tipo == "USCITA":
                tot_uscite += quota_importo
                totale_costi_fissi += quota_fissi
                totale_costi_variabili += quota_variabili
            totale_iva += quota_iva

        qta_produzioni = 0
        tot_litri = 0.0
        totale_valore_latte = 0.0
        for produzione_id_raw, _movimento_id_raw, _litri_raw, prezzo_raw in produzione_rows:
            try:
                produzione_id = int(produzione_id_raw or 0)
            except (TypeError, ValueError):
                continue

            if produzione_id <= 0:
                continue

            quote_produzione = quote_per_produzione.get(produzione_id, {})
            litri_quota = float(quote_produzione.get(animale_entry_id, 0) or 0)
            if litri_quota <= 0:
                continue

            qta_produzioni += 1
            prezzo_litro = float(prezzo_raw or 0)
            tot_litri += litri_quota
            totale_valore_latte += litri_quota * prezzo_litro

        return self._calcola_metriche_latte_da_totali(
            periodo=periodo,
            movimenti_estratti=len(movimenti_estratti),
            qta_produzioni=qta_produzioni,
            tot_entrate=tot_entrate,
            tot_uscite=tot_uscite,
            totale_iva=totale_iva,
            tot_litri=tot_litri,
            totale_valore_latte=totale_valore_latte,
            totale_capi=totale_capi,
            totale_costi_fissi=totale_costi_fissi,
            totale_costi_variabili=totale_costi_variabili,
        )

    def _righe_report_generale_gruppo(self, metriche):
        return [
            ("Periodo produzione", metriche["periodo"]),
            ("Movimenti", str(metriche["movimenti_estratti"])),
            ("Produzioni", str(metriche["qta_produzioni"])),
            ("Totale Entrate", format_eur(metriche["tot_entrate"])),
            ("Totale Uscite", format_eur(metriche["tot_uscite"])),
            ("Totale IVA", format_eur(metriche["totale_iva"])),
            (
                "Totale Quintali",
                f"{format_number(metriche['tot_quintali'], 2)} q ({format_number(metriche['tot_litri'], 2)} L)",
            ),
            ("Media Quintali/Produzione", f"{format_number(metriche['media_quintali_registrazione'], 2)} q"),
        ]

    def _righe_report_indici_gruppo(self, metriche):
        return [
            ("Totale Entrate Gruppo", format_eur(metriche["tot_entrate"])),
            ("Totale Uscite Gruppo", format_eur(metriche["tot_uscite"])),
            ("Media Prezzo/Litro", format_eur(metriche["prezzo_medio_litro"], 4)),
            ("Media Litri/Capo/Giorno", f"{format_number(metriche['media_litri_per_capo_giorno'], 2)} L"),
            ("Costo Produzione/Litro Gruppo", format_eur(metriche["costo_produzione_litro"], 4)),
            ("% Incidenza Costi Fissi", f"{format_number(metriche['incidenza_costi_fissi_pct'], 2)}%"),
            ("% Incidenza Costi Variabili", f"{format_number(metriche['incidenza_costi_variabili_pct'], 2)}%"),
            ("Utile/Litro", format_eur(metriche["utile_litro"], 4)),
            ("Saldo Netto", format_eur(metriche["saldo"])),
        ]

    def _crea_tabella_report_gruppo(
        self,
        parent,
        titolo,
        righe,
        *,
        side="top",
        padx=(0, 0),
        metrica_width=330,
        valore_width=280,
    ):
        frame_tabella = ttk.LabelFrame(parent, text=titolo)
        fill_mode = "x"
        expand_mode = False
        if side in ("left", "right"):
            fill_mode = "both"
            expand_mode = True

        frame_tabella.pack(side=side, fill=fill_mode, expand=expand_mode, padx=padx, pady=(10, 0))

        tree = ttk.Treeview(
            frame_tabella,
            columns=("metrica", "valore"),
            show="headings",
            height=max(1, len(righe)),
        )
        tree.heading("metrica", text="Metrica")
        tree.heading("valore", text="Valore")
        tree.column("metrica", width=metrica_width, anchor="w")
        tree.column("valore", width=valore_width, anchor="e")

        for metrica, valore in righe:
            tree.insert("", "end", values=(metrica, valore))

        tree.pack(fill="both", expand=True, padx=8, pady=8)

    def _ensure_tab_zootecnia_latte(self):
        pagina = getattr(self, "tab_zootecnia_latte", None)
        if pagina is not None and pagina.winfo_exists():
            return pagina

        self.tab_zootecnia_latte = ttk.Frame(self.zootecnia_notebook)
        self.tab_latte = self.tab_zootecnia_latte
        self.setup_tab_latte()
        return self.tab_zootecnia_latte

    def _ensure_tab_zootecnia_info_generali(self):
        pagina = getattr(self, "tab_zootecnia_info_generali", None)
        if pagina is not None and pagina.winfo_exists():
            return pagina

        self.tab_zootecnia_info_generali = ttk.Frame(self.zootecnia_notebook, padding=12)
        self.var_zootecnia_info_generali = tk.StringVar(value="")

        frame_info = ttk.LabelFrame(self.tab_zootecnia_info_generali, text="Riepilogo zootecnia")
        frame_info.pack(fill="x")
        ttk.Label(
            frame_info,
            textvariable=self.var_zootecnia_info_generali,
            justify="left",
            wraplength=780,
        ).pack(anchor="w", padx=12, pady=10)

        frame_azioni = ttk.Frame(self.tab_zootecnia_info_generali)
        frame_azioni.pack(anchor="w", pady=(10, 0))
        ttk.Button(
            frame_azioni,
            text="Configura tipi allevamento",
            command=self.apri_configurazione_allevamento,
        ).pack(side="left")

        return self.tab_zootecnia_info_generali

    def _aggiorna_tab_zootecnia_info_generali(self, gruppi_attivi, gruppi_latte_attivi):
        if not hasattr(self, "var_zootecnia_info_generali"):
            return

        totale_gruppi = len(gruppi_attivi)
        totale_gruppi_latte = len(gruppi_latte_attivi)
        totale_gruppi_carne = sum(1 for gruppo in gruppi_attivi if gruppo.get("destinazione") == "Da Carne")
        totale_capi = sum(int(gruppo.get("capi") or 0) for gruppo in gruppi_attivi)

        if totale_gruppi <= 0:
            testo = (
                "Nessun gruppo animale attivo.\n"
                "Configura i gruppi in Azienda > Tipi Allevamento per abilitare le sottopagine dedicate."
            )
        else:
            testo = (
                f"Gruppi attivi: {totale_gruppi}\n"
                f"Gruppi da latte attivi: {totale_gruppi_latte}\n"
                f"Gruppi da carne attivi: {totale_gruppi_carne}\n"
                f"Capi totali registrati: {totale_capi}"
            )

        try:
            metriche_latte = self._calcola_metriche_latte_report_operativa()
            testo += (
                "\n\nCalcoli latte (come Report Operativa)\n"
                f"Periodo: {metriche_latte['periodo']}\n"
                f"Produzioni latte nel periodo: {metriche_latte['qta_produzioni']}\n"
                f"Totale Quintali: {format_number(metriche_latte['tot_quintali'], 2)} q "
                f"({format_number(metriche_latte['tot_litri'], 2)} L)\n"
                f"Media Quintali/Giorno: {format_number(metriche_latte['media_quintali_giorno'], 2)} q\n"
                f"Media Quintali/Registrazione: {format_number(metriche_latte['media_quintali_registrazione'], 2)} q\n"
                f"Prezzo Medio/Litro: {format_eur(metriche_latte['prezzo_medio_litro'], 4)}\n"
                f"Costo Produzione/Litro: {format_eur(metriche_latte['costo_produzione_litro'], 4)}\n"
                f"Utile/Litro: {format_eur(metriche_latte['utile_litro'], 4)}"
            )
        except Exception:
            testo += "\n\nCalcoli latte non disponibili (errore durante il calcolo)."

        self.var_zootecnia_info_generali.set(testo)

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

    def apri_configurazione_allevamento(self):
        self.mostra_categoria(self.CATEGORIA_AZIENDA)
        if hasattr(self, "mostra_tab_azienda_animali"):
            self.mostra_tab_azienda_animali()

    def aggiorna_categoria_zootecnia(self):
        try:
            entries = list_azienda_animali_entries(self.user_id)
        except sqlite3.Error:
            entries = []

        if not hasattr(self, "zootecnia_notebook"):
            return

        for tab_id in self.zootecnia_notebook.tabs():
            self.zootecnia_notebook.forget(tab_id)

        gruppi_attivi = []
        gruppi_latte_attivi = []

        for entry in entries:
            try:
                entry_id = int(entry.get("id") or 0)
            except (TypeError, ValueError):
                continue

            if entry_id <= 0:
                continue

            capi = int(entry.get("capi") or 0)

            if capi <= 0:
                continue

            if self._is_entry_latte_attiva(entry):
                gruppi_latte_attivi.append(entry)

            group_name = (entry.get("group_name") or "").strip()
            if not group_name:
                group_name = self._zootecnia_label_tipo(entry)

            gruppi_attivi.append(
                {
                    "entry_id": entry_id,
                    "nome": group_name,
                    "tipo": self._zootecnia_label_tipo(entry),
                    "destinazione": self._zootecnia_label_destinazione(entry),
                    "capi": capi,
                }
            )

        if self.lbl_zootecnia_vuoto.winfo_manager() != "":
            self.lbl_zootecnia_vuoto.pack_forget()
        if self.zootecnia_notebook.winfo_manager() == "":
            self.zootecnia_notebook.pack(fill="both", expand=True)

        pagina_info_generali = self._ensure_tab_zootecnia_info_generali()
        self.zootecnia_notebook.add(pagina_info_generali, text="Informazioni Generali")
        self._aggiorna_tab_zootecnia_info_generali(gruppi_attivi, gruppi_latte_attivi)

        if gruppi_attivi:
            shared_metriche_gruppi = None
            try:
                capi_overrides = {
                    int(gruppo.get("entry_id") or 0): int(gruppo.get("capi") or 0) for gruppo in gruppi_attivi
                }
                shared_metriche_gruppi = self._prepara_dati_metriche_latte_per_gruppi(capi_overrides=capi_overrides)
            except Exception:
                shared_metriche_gruppi = None

            if gruppi_latte_attivi:
                pagina_latte = self._ensure_tab_zootecnia_latte()
                self.zootecnia_notebook.add(pagina_latte, text="Produzione Latte")
                if hasattr(self, "aggiorna_lista_gruppi_latte"):
                    self.aggiorna_lista_gruppi_latte()
                if hasattr(self, "carica_produzioni_latte"):
                    self.carica_produzioni_latte(mostra_errori=False)

            for gruppo in gruppi_attivi:
                pagina = ttk.Frame(self.zootecnia_notebook, padding=12)

                frame_info = ttk.LabelFrame(pagina, text=gruppo["nome"])
                frame_info.pack(fill="x")

                ttk.Label(frame_info, text=f"Tipo: {gruppo['tipo']}").pack(anchor="w", padx=12, pady=(10, 4))
                ttk.Label(frame_info, text=f"Destinazione: {gruppo['destinazione']}").pack(anchor="w", padx=12, pady=4)
                ttk.Label(frame_info, text=f"Capi registrati: {gruppo['capi']}").pack(anchor="w", padx=12, pady=(4, 10))

                try:
                    metriche_gruppo = self._calcola_metriche_latte_report_operativa_per_gruppo(
                        gruppo["entry_id"],
                        totale_capi=gruppo["capi"],
                        shared_data=shared_metriche_gruppi,
                    )

                    frame_report_affiancati = ttk.Frame(pagina)
                    frame_report_affiancati.pack(fill="both", expand=True)

                    self._crea_tabella_report_gruppo(
                        frame_report_affiancati,
                        "Report generale gruppo",
                        self._righe_report_generale_gruppo(metriche_gruppo),
                        side="left",
                        padx=(0, 6),
                        metrica_width=230,
                        valore_width=190,
                    )
                    self._crea_tabella_report_gruppo(
                        frame_report_affiancati,
                        "Report entrate/uscite e indici",
                        self._righe_report_indici_gruppo(metriche_gruppo),
                        side="left",
                        padx=(6, 0),
                        metrica_width=230,
                        valore_width=190,
                    )
                except Exception:
                    frame_metriche = ttk.LabelFrame(pagina, text="Report gruppo")
                    frame_metriche.pack(fill="x", pady=(10, 0))
                    ttk.Label(
                        frame_metriche,
                        text="Calcoli non disponibili per questo gruppo (errore durante il calcolo).",
                        justify="left",
                        wraplength=860,
                    ).pack(anchor="w", padx=12, pady=10)

                frame_azioni = ttk.Frame(pagina)
                frame_azioni.pack(anchor="w", pady=(10, 0))
                ttk.Button(
                    frame_azioni,
                    text="Apri configurazione gruppo",
                    command=self.apri_configurazione_allevamento,
                ).pack(side="left")

                self.zootecnia_notebook.add(pagina, text=gruppo["nome"])

            if gruppi_latte_attivi:
                self.var_zootecnia_stato.set(
                    f"Sono disponibili {len(gruppi_attivi)} sottopagine per i gruppi animali attivi "
                    "oltre alle pagine Informazioni Generali e Produzione Latte."
                )
            else:
                self.var_zootecnia_stato.set(
                    f"Sono disponibili {len(gruppi_attivi)} sottopagine: una per ogni gruppo animale attivo, "
                    "oltre alla pagina Informazioni Generali."
                )
        else:
            self.var_zootecnia_stato.set(
                "Nessun tipo allevamento impostato. E disponibile la pagina Informazioni Generali."
            )

        if hasattr(self, "abilita_a_capo_tutte_treeview"):
            self.abilita_a_capo_tutte_treeview()

    def cambia_utente(self):
        conferma = messagebox.askyesno("Conferma", "Vuoi uscire e cambiare utente?")
        if not conferma:
            return

        self.root.config(menu="")
        for widget in self.root.winfo_children():
            widget.destroy()
        FinestraLogin(self.root)
