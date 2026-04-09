import sqlite3
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from app_utils import clear_treeview, format_eur, format_number, is_blank, parse_decimal
from database import (
    add_azienda_animale_entry,
    delete_azienda_animale_entry,
    get_azienda_info,
    get_movimento_animali_entry_ids,
    get_movimento_animali_group_labels,
    get_conn,
    list_azienda_animali_entries,
    merge_azienda_animale_groups,
    remove_azienda_animale_capi,
    resolve_fattura_path,
    split_azienda_animale_group,
    set_azienda_animale_capi,
    set_azienda_animale_finalita,
    set_azienda_animale_group_name,
    set_azienda_animale_riproduzione,
    save_azienda_info,
)
from services.product_parser_utils import (
    extract_products_rows_from_parser_text,
    normalize_cost_type,
    normalize_multiline_display_text,
)


class AziendaTabMixin:
    ANIMAL_TYPE_OPTIONS = ("Bovini", "Ovini", "Caprini", "Suini", "Avicoli", "Equini", "Altro")
    ANIMAL_TYPE_TO_DB = {
        "Bovini": "BOVINI",
        "Ovini": "OVINI",
        "Caprini": "CAPRINI",
        "Suini": "SUINI",
        "Avicoli": "AVICOLI",
        "Equini": "EQUINI",
        "Altro": "ALTRO",
    }
    PURPOSE_OPTIONS = ("Da Latte", "Da Carne")
    PURPOSE_TO_DB = {"Da Latte": "LATTE", "Da Carne": "CARNE"}

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

    def setup_categoria_azienda(self):
        container = ttk.Frame(self.frame_azienda, padding=10)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="Area Azienda", font=("Arial", 14, "bold")).pack(anchor="w", pady=(0, 8))

        self.azienda_notebook = ttk.Notebook(container)
        self.azienda_notebook.pack(fill="both", expand=True)

        self.tab_azienda_report = ttk.Frame(self.azienda_notebook)
        self.tab_azienda_fatture = ttk.Frame(self.azienda_notebook)
        self.tab_azienda_dati = ttk.Frame(self.azienda_notebook)

        self.azienda_notebook.add(self.tab_azienda_report, text="Report Azienda")
        self.azienda_notebook.add(self.tab_azienda_fatture, text="Fatture")
        self.azienda_notebook.add(self.tab_azienda_dati, text="Dati Azienda")

        self.azienda_dati_notebook = ttk.Notebook(self.tab_azienda_dati)
        self.azienda_dati_notebook.pack(fill="both", expand=True, padx=12, pady=12)
        self.tab_azienda_info = ttk.Frame(self.azienda_dati_notebook)
        self.tab_azienda_animali = ttk.Frame(self.azienda_dati_notebook)
        self.azienda_dati_notebook.add(self.tab_azienda_info, text="Informazioni")
        self.azienda_dati_notebook.add(self.tab_azienda_animali, text="Tipi Allevamenti")

        self._setup_pagina_report_azienda()
        self._setup_pagina_fatture_azienda()
        self._setup_pagina_dati_azienda_informazioni(self.tab_azienda_info)
        self._setup_pagina_animali_azienda()

        self.imposta_periodo_report_azienda_default(mostra_errori=False)
        self.carica_report_animali_allevamento(mostra_errori=False)
        self.genera_report_azienda(mostra_errori=False)
        self.carica_dati_azienda_info(mostra_errori=False)

    def _setup_pagina_dati_azienda_informazioni(self, parent):
        content = self.crea_container_scorribile(parent, stretch_to_viewport=True)

        ttk.Label(content, text="Informazioni Azienda", font=("Arial", 14, "bold")).pack(anchor="w", padx=12, pady=(10, 8))

        self.var_azienda_info_nome = tk.StringVar(value="-")
        self.var_azienda_info_piva = tk.StringVar(value="-")
        self.var_azienda_info_occupazione = tk.StringVar(value="-")
        self.var_azienda_info_data_creazione = tk.StringVar(value="-")

        frame_anagrafica = ttk.LabelFrame(content, text="Dati anagrafici")
        frame_anagrafica.pack(fill="x", padx=12, pady=(0, 8))

        def _aggiungi_riga_info(label_text, text_var):
            riga = ttk.Frame(frame_anagrafica)
            riga.pack(fill="x", padx=12, pady=4)
            ttk.Label(riga, text=label_text, width=20).pack(side="left")
            ttk.Label(riga, textvariable=text_var, anchor="w").pack(side="left", fill="x", expand=True)

        _aggiungi_riga_info("Nome dell'Azienda:", self.var_azienda_info_nome)
        _aggiungi_riga_info("P.IVA:", self.var_azienda_info_piva)
        _aggiungi_riga_info("Occupazione:", self.var_azienda_info_occupazione)
        _aggiungi_riga_info("Data creazione:", self.var_azienda_info_data_creazione)

        frame_anagrafica_btn = ttk.Frame(frame_anagrafica)
        frame_anagrafica_btn.pack(fill="x", padx=12, pady=(6, 10))
        ttk.Button(
            frame_anagrafica_btn,
            text="Modifica informazioni",
            command=self.apri_dialog_modifica_info_azienda,
        ).pack(side="left")

        frame_andamento = ttk.LabelFrame(content, text="Andamento economico annuale")
        frame_andamento.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        self.tree_azienda_info_andamento = ttk.Treeview(
            frame_andamento,
            columns=("metrica", "valore"),
            show="headings",
            height=8,
        )
        self.tree_azienda_info_andamento.heading("metrica", text="Metrica")
        self.tree_azienda_info_andamento.heading("valore", text="Valore")
        self.tree_azienda_info_andamento.column("metrica", width=320, anchor="w")
        self.tree_azienda_info_andamento.column("valore", width=220, anchor="e")

        scroll_info = ttk.Scrollbar(frame_andamento, orient="vertical", command=self.tree_azienda_info_andamento.yview)
        self.tree_azienda_info_andamento.configure(yscrollcommand=scroll_info.set)

        self.tree_azienda_info_andamento.pack(side="left", fill="both", expand=True)
        scroll_info.pack(side="right", fill="y")

    def _format_data_info_azienda(self, raw_value, fallback="-"):
        testo = (raw_value or "").strip()
        if not testo:
            return fallback

        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(testo, fmt).strftime("%d/%m/%Y")
            except ValueError:
                continue

        return testo

    def _calcola_totali_manutenzioni_azienda(
        self,
        data_da_db: str | None = None,
        data_a_db: str | None = None,
        mostra_errori=True,
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
                    f'''
                    SELECT
                        COALESCE(SUM(COALESCE(costo, 0)), 0),
                        COUNT(id)
                    FROM manutenzioni_macchinari
                    {where_clause}
                ''',
                    tuple(params),
                )
                row = c.fetchone()
        except sqlite3.Error as e:
            if mostra_errori:
                messagebox.showerror("Errore DB", f"Errore database: {e}")
            return 0.0, 0

        totale = float((row[0] if row else 0) or 0)
        numero = int((row[1] if row else 0) or 0)
        return totale, numero

    def _calcola_totali_annuali_azienda_info(self, anno: int, mostra_errori=True):
        data_da = f"{anno:04d}-01-01"
        data_a = f"{anno:04d}-12-31"

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    '''
                    SELECT
                        COUNT(id),
                        COALESCE(SUM(CASE WHEN tipo='ENTRATA' THEN importo ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN tipo='USCITA' THEN importo ELSE 0 END), 0)
                    FROM movimenti
                    WHERE user_id=? AND data_op BETWEEN ? AND ?
                ''',
                    (self.user_id, data_da, data_a),
                )
                row = c.fetchone()
        except sqlite3.Error as e:
            if mostra_errori:
                messagebox.showerror("Errore DB", f"Errore database: {e}")
            return None

        movimenti = int((row[0] if row else 0) or 0)
        entrate = float((row[1] if row else 0) or 0)
        uscite_movimenti = float((row[2] if row else 0) or 0)
        uscite_manutenzioni, _ = self._calcola_totali_manutenzioni_azienda(
            data_da_db=data_da,
            data_a_db=data_a,
            mostra_errori=mostra_errori,
        )
        uscite = uscite_movimenti + uscite_manutenzioni
        return {
            "movimenti": movimenti,
            "entrate": entrate,
            "uscite": uscite,
            "utile": entrate - uscite,
        }

    def carica_dati_azienda_info(self, mostra_errori=True):
        if not hasattr(self, "var_azienda_info_nome") or not hasattr(self, "tree_azienda_info_andamento"):
            return

        try:
            info = get_azienda_info(self.user_id)
        except sqlite3.Error as e:
            if mostra_errori:
                messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        nome = (info.get("nome_azienda") or "").strip()
        piva = (info.get("piva") or "").strip()
        occupazione = (info.get("occupazione") or "").strip()
        data_creazione = info.get("data_creazione") or ""

        self.var_azienda_info_nome.set(nome if nome else "-")
        self.var_azienda_info_piva.set(piva if piva else "-")
        self.var_azienda_info_occupazione.set(occupazione if occupazione else "-")
        self.var_azienda_info_data_creazione.set(self._format_data_info_azienda(data_creazione, fallback="-"))

        anno_corrente = datetime.now().year
        anno_precedente = anno_corrente - 1

        stats_precedente = self._calcola_totali_annuali_azienda_info(anno_precedente, mostra_errori=mostra_errori)
        stats_corrente = self._calcola_totali_annuali_azienda_info(anno_corrente, mostra_errori=mostra_errori)
        if stats_precedente is None or stats_corrente is None:
            return

        clear_treeview(self.tree_azienda_info_andamento)

        righe = []
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

        for metrica, valore in righe:
            self.tree_azienda_info_andamento.insert("", "end", values=(metrica, valore))

    def apri_dialog_modifica_info_azienda(self):
        info = get_azienda_info(self.user_id)

        dialog = tk.Toplevel(self.root)
        dialog.title("Modifica informazioni azienda")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)

        var_nome = tk.StringVar(value=(info.get("nome_azienda") or "").strip())
        var_piva = tk.StringVar(value=(info.get("piva") or "").strip())
        var_occupazione = tk.StringVar(value=(info.get("occupazione") or "").strip())
        data_default = self._format_data_info_azienda(info.get("data_creazione") or "", fallback="")
        if is_blank(data_default):
            data_default = datetime.now().strftime("%d/%m/%Y")
        var_data = tk.StringVar(value=data_default)

        riga_nome = ttk.Frame(frame)
        riga_nome.pack(fill="x", pady=(0, 6))
        ttk.Label(riga_nome, text="Nome dell'Azienda:", width=20).pack(side="left")
        ttk.Entry(riga_nome, textvariable=var_nome).pack(side="left", fill="x", expand=True)

        riga_occupazione = ttk.Frame(frame)
        riga_occupazione.pack(fill="x", pady=6)
        ttk.Label(riga_occupazione, text="Occupazione:", width=20).pack(side="left")
        ttk.Entry(riga_occupazione, textvariable=var_occupazione).pack(side="left", fill="x", expand=True)

        riga_piva = ttk.Frame(frame)
        riga_piva.pack(fill="x", pady=6)
        ttk.Label(riga_piva, text="P.IVA:", width=20).pack(side="left")
        ttk.Entry(riga_piva, textvariable=var_piva).pack(side="left", fill="x", expand=True)

        riga_data = ttk.Frame(frame)
        riga_data.pack(fill="x", pady=6)
        ttk.Label(riga_data, text="Data creazione:", width=20).pack(side="left")
        entry_data = ttk.Entry(riga_data, textvariable=var_data, width=14, state="readonly")
        entry_data.pack(side="left")

        def _seleziona_data():
            testo_data = var_data.get().strip()
            if testo_data:
                try:
                    initial_date = datetime.strptime(testo_data, "%d/%m/%Y").date()
                except ValueError:
                    initial_date = datetime.now().date()
            else:
                initial_date = datetime.now().date()

            scelta = self.calendar_dialog_cls(dialog, initial_date).show()
            if scelta is not None:
                var_data.set(scelta.strftime("%d/%m/%Y"))

        ttk.Button(riga_data, text="...", width=3, command=_seleziona_data).pack(side="left", padx=(5, 0))
        entry_data.bind("<Button-1>", lambda _event: _seleziona_data())

        frame_btn = ttk.Frame(frame)
        frame_btn.pack(fill="x", pady=(12, 0))
        ttk.Button(
            frame_btn,
            text="Salva",
            command=lambda: self._salva_modifica_info_azienda(dialog, var_nome, var_piva, var_occupazione, var_data),
        ).pack(side="left")
        ttk.Button(frame_btn, text="Annulla", command=dialog.destroy).pack(side="left", padx=6)

    def _salva_modifica_info_azienda(self, dialog, var_nome, var_piva, var_occupazione, var_data):
        piva_raw = var_piva.get().strip()
        piva_clean = ""
        if not is_blank(piva_raw):
            piva_clean = self._normalizza_piva(piva_raw)
            if len(piva_clean) != 11:
                messagebox.showerror(
                    "Errore",
                    "P.IVA non valida. Inserisci 11 cifre (puoi usare anche prefisso IT).",
                )
                return
            if not self._piva_is_valid(piva_clean):
                messagebox.showerror("Errore", "P.IVA non valida (checksum errato).")
                return

        data_text = var_data.get().strip()
        if is_blank(data_text):
            messagebox.showerror("Errore", "Inserisci la data di creazione.")
            return

        try:
            data_iso = datetime.strptime(data_text, "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Errore", "Formato data non valido (Usa GG/MM/AAAA).")
            return

        try:
            save_azienda_info(
                self.user_id,
                var_nome.get().strip(),
                piva_clean,
                var_occupazione.get().strip(),
                data_iso,
            )
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        dialog.destroy()
        self.carica_dati_azienda_info(mostra_errori=False)
        messagebox.showinfo("Successo", "Informazioni azienda aggiornate.")

    def _setup_pagina_report_azienda(self):
        content = self.crea_container_scorribile(self.tab_azienda_report)

        self.var_azienda_report_usa_filtro = tk.BooleanVar(value=False)
        self.var_azienda_data_inizio = tk.StringVar()
        self.var_azienda_data_fine = tk.StringVar()
        self.var_azienda_data_inizio.trace_add("write", self._auto_compila_data_fine_azienda)

        frame_filtri = ttk.LabelFrame(content, text="Filtri report")
        frame_filtri.pack(fill="x", padx=12, pady=(10, 6))

        ttk.Checkbutton(
            frame_filtri,
            text="Usa filtro periodo",
            variable=self.var_azienda_report_usa_filtro,
        ).pack(anchor="w", padx=20, pady=(8, 2))

        self.crea_campo_data(frame_filtri, "Data INIZIO:", self.var_azienda_data_inizio)
        self.crea_campo_data(frame_filtri, "Data FINE:", self.var_azienda_data_fine)

        frame_btn = ttk.Frame(content)
        frame_btn.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Button(frame_btn, text="Aggiorna report azienda", command=self.genera_report_azienda).pack(side="left")

        frame_riepilogo = ttk.LabelFrame(content, text="Riepilogo azienda")
        frame_riepilogo.pack(fill="x", padx=12, pady=(0, 8))

        self.tree_azienda_report = ttk.Treeview(
            frame_riepilogo,
            columns=("metrica", "valore"),
            show="headings",
            height=7,
        )
        self.tree_azienda_report.heading("metrica", text="Metrica")
        self.tree_azienda_report.heading("valore", text="Valore")
        self.tree_azienda_report.column("metrica", width=300, anchor="w")
        self.tree_azienda_report.column("valore", width=240, anchor="e")

        scroll_report = ttk.Scrollbar(frame_riepilogo, orient="vertical", command=self.tree_azienda_report.yview)
        self.tree_azienda_report.configure(yscrollcommand=scroll_report.set)

        self.tree_azienda_report.pack(side="left", fill="x", expand=True)
        scroll_report.pack(side="right", fill="y")

        frame_categorie = ttk.LabelFrame(content, text="Dettaglio per categoria")
        frame_categorie.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        self.tree_azienda_categorie = ttk.Treeview(
            frame_categorie,
            columns=("tipo", "categoria", "totale", "movimenti"),
            show="headings",
            height=8,
        )
        self.tree_azienda_categorie.heading("tipo", text="Tipo")
        self.tree_azienda_categorie.heading("categoria", text="Categoria")
        self.tree_azienda_categorie.heading("totale", text="Totale")
        self.tree_azienda_categorie.heading("movimenti", text="N. Movimenti")

        self.tree_azienda_categorie.column("tipo", width=100, anchor="center")
        self.tree_azienda_categorie.column("categoria", width=250, anchor="w")
        self.tree_azienda_categorie.column("totale", width=150, anchor="e")
        self.tree_azienda_categorie.column("movimenti", width=120, anchor="e")

        scroll_categorie = ttk.Scrollbar(frame_categorie, orient="vertical", command=self.tree_azienda_categorie.yview)
        self.tree_azienda_categorie.configure(yscrollcommand=scroll_categorie.set)

        self.tree_azienda_categorie.pack(side="left", fill="both", expand=True)
        scroll_categorie.pack(side="right", fill="y")

    def _setup_pagina_fatture_azienda(self):
        content = self.crea_container_scorribile(self.tab_azienda_fatture)

        self.azienda_fatture_notebook = ttk.Notebook(content)
        self.azienda_fatture_notebook.pack(fill="both", expand=True, padx=12, pady=12)

        self.tab_azienda_fatture_inserimento = ttk.Frame(self.azienda_fatture_notebook)
        self.tab_azienda_fatture_storico = ttk.Frame(self.azienda_fatture_notebook)
        self.tab_azienda_fatture_storico_prodotti = ttk.Frame(self.azienda_fatture_notebook)

        self.azienda_fatture_notebook.add(self.tab_azienda_fatture_inserimento, text="Nuovo movimento")
        self.azienda_fatture_notebook.add(self.tab_azienda_fatture_storico, text="Storico movimenti")
        self.azienda_fatture_notebook.add(self.tab_azienda_fatture_storico_prodotti, text="Storico Prodotti")

        self._setup_pagina_fatture_azienda_inserimento(self.tab_azienda_fatture_inserimento)
        self._setup_pagina_fatture_azienda_storico(self.tab_azienda_fatture_storico)
        self._setup_pagina_fatture_azienda_storico_prodotti(self.tab_azienda_fatture_storico_prodotti)
        self.carica_movimenti_azienda_storico(mostra_errori=False)

    def _setup_pagina_fatture_azienda_inserimento(self, parent):
        content = self.crea_container_scorribile(parent)

        ttk.Label(content, text="Registra Movimento", font=("Arial", 14, "bold")).pack(pady=10)

        if not hasattr(self, "var_data"):
            self.var_data = tk.StringVar(value=datetime.now().strftime("%d/%m/%Y"))
        if not hasattr(self, "var_tipo"):
            self.var_tipo = tk.StringVar(value="ENTRATA")
        if not hasattr(self, "var_cat"):
            self.var_cat = tk.StringVar()
        if not hasattr(self, "var_desc"):
            self.var_desc = tk.StringVar()
        if not hasattr(self, "var_imp"):
            self.var_imp = tk.StringVar()
        if not hasattr(self, "var_iva"):
            self.var_iva = tk.StringVar(value="0,00")
        if not hasattr(self, "var_nome_fattura_mov"):
            self.var_nome_fattura_mov = tk.StringVar(value="Nessuna fattura caricata")

        self.crea_campo_data(content, "Data:", self.var_data)

        frame_tipo = ttk.Frame(content)
        frame_tipo.pack(fill="x", padx=20, pady=5)
        ttk.Label(frame_tipo, text="Tipo:", width=20).pack(side="left")
        frame_radio = ttk.Frame(frame_tipo)
        frame_radio.pack(side="left", fill="x", expand=True)

        ttk.Radiobutton(frame_radio, text="Entrata", value="ENTRATA", variable=self.var_tipo).pack(
            side="left", padx=(0, 15)
        )
        ttk.Radiobutton(frame_radio, text="Uscita", value="USCITA", variable=self.var_tipo).pack(side="left")

        self.crea_campo_categoria(content, "Categoria:", self.var_cat)
        self.crea_campo(content, "Descrizione:", self.var_desc)
        self.crea_campo(content, "Importo (EUR):", self.var_imp)
        self.crea_campo(content, "IVA (EUR):", self.var_iva)

        frame_fattura = ttk.Frame(content)
        frame_fattura.pack(fill="x", padx=20, pady=(0, 6))

        ttk.Label(frame_fattura, text="Fattura caricata:", width=20).pack(side="left")
        ttk.Label(frame_fattura, textvariable=self.var_nome_fattura_mov).pack(side="left", fill="x", expand=True)
        ttk.Button(frame_fattura, text="Rimuovi", command=self.rimuovi_fattura_movimento).pack(side="right")

        if hasattr(self, "_setup_tabella_prodotti_fattura_movimento"):
            self._setup_tabella_prodotti_fattura_movimento(content)

        frame_actions = ttk.Frame(content)
        frame_actions.pack(pady=20)

        self.btn_salva_movimento_azienda = ttk.Button(frame_actions, text="Salva nel DB", command=self.salva_movimento)
        self.btn_salva_movimento_azienda.pack(side="left", padx=6)

        self.btn_annulla_modifica_azienda = ttk.Button(
            frame_actions,
            text="Annulla modifica",
            command=self.annulla_modifica_movimento,
            state="disabled",
        )
        self.btn_annulla_modifica_azienda.pack(side="left", padx=6)

        ttk.Button(frame_actions, text="Importa fattura PDF", command=self.importa_fattura_pdf).pack(side="left", padx=6)

    def _label_gruppo_animale_movimento(self, entry):
        entry_id = int(entry.get("id", 0) or 0)
        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
        tipo_text = self._format_tipo_animale_report(entry.get("tipo_animale", ""), entry.get("altro_label", ""))
        finalita_text = self._format_finalita_report(entry.get("finalita", ""))
        capi = int(entry.get("capi", 0) or 0)
        return f"{group_name} | {tipo_text} | {finalita_text} | {format_number(capi, 0)} capi"

    def aggiorna_lista_gruppi_animali_movimento(self, selected_entry_ids=None):
        if not hasattr(self, "listbox_movimento_animali"):
            return

        if selected_entry_ids is None and hasattr(self, "get_gruppi_animali_movimento_selezionati_ids"):
            selected_entry_ids = self.get_gruppi_animali_movimento_selezionati_ids()

        selected_ids = set()
        for raw in selected_entry_ids or []:
            try:
                entry_id = int(raw)
            except (TypeError, ValueError):
                continue
            if entry_id > 0:
                selected_ids.add(entry_id)

        try:
            entries = list_azienda_animali_entries(self.user_id)
        except sqlite3.Error:
            entries = []

        attivi = [entry for entry in entries if int(entry.get("capi", 0) or 0) > 0]
        attivi.sort(key=lambda item: ((item.get("group_name") or "").strip().lower(), int(item.get("id", 0) or 0)))

        self.listbox_movimento_animali.delete(0, tk.END)
        self._movimento_animali_list_entry_ids = []

        labels_seen = set()
        listbox_idx = 0
        for entry in attivi:
            entry_id = int(entry.get("id", 0) or 0)
            if entry_id <= 0:
                continue

            label = self._label_gruppo_animale_movimento(entry)
            if label in labels_seen:
                label = f"{label} [ID {entry_id}]"
            labels_seen.add(label)

            self.listbox_movimento_animali.insert(tk.END, label)
            self._movimento_animali_list_entry_ids.append(entry_id)

            if entry_id in selected_ids:
                self.listbox_movimento_animali.selection_set(listbox_idx)

            listbox_idx += 1

        self._aggiorna_stato_gruppi_animali_movimento()

    def _on_selezione_gruppi_animali_movimento(self, _event=None):
        self._aggiorna_stato_gruppi_animali_movimento()

    def _aggiorna_stato_gruppi_animali_movimento(self):
        if not hasattr(self, "var_movimento_animali_link_stato") or not hasattr(self, "listbox_movimento_animali"):
            return

        totale = int(self.listbox_movimento_animali.size())
        if totale <= 0:
            self.var_movimento_animali_link_stato.set(
                "Nessun gruppo disponibile. Configurali in Azienda > Tipi Allevamento."
            )
            return

        selezionati = len(self.listbox_movimento_animali.curselection())
        if selezionati <= 0:
            self.var_movimento_animali_link_stato.set(f"Nessun gruppo selezionato (disponibili: {totale}).")
            return

        self.var_movimento_animali_link_stato.set(f"Gruppi selezionati: {selezionati} su {totale}.")

    def get_gruppi_animali_movimento_selezionati_ids(self):
        if not hasattr(self, "listbox_movimento_animali"):
            return []

        selected = []
        for idx in self.listbox_movimento_animali.curselection():
            if 0 <= idx < len(self._movimento_animali_list_entry_ids):
                entry_id = int(self._movimento_animali_list_entry_ids[idx] or 0)
                if entry_id > 0:
                    selected.append(entry_id)
        return selected

    def imposta_gruppi_animali_movimento_selezionati(self, entry_ids):
        self.aggiorna_lista_gruppi_animali_movimento(selected_entry_ids=entry_ids)

    def seleziona_tutti_gruppi_animali_movimento(self):
        if not hasattr(self, "listbox_movimento_animali"):
            return
        if self.listbox_movimento_animali.size() <= 0:
            return

        self.listbox_movimento_animali.selection_set(0, tk.END)
        self._aggiorna_stato_gruppi_animali_movimento()

    def deseleziona_gruppi_animali_movimento(self):
        if not hasattr(self, "listbox_movimento_animali"):
            return

        self.listbox_movimento_animali.selection_clear(0, tk.END)
        self._aggiorna_stato_gruppi_animali_movimento()

    def _gruppi_animali_collegati_movimento_testo(self, movimento_id: int):
        try:
            labels = get_movimento_animali_group_labels(self.user_id, movimento_id)
        except sqlite3.Error:
            return "-"

        if not labels:
            return "Nessun gruppo collegato"
        return "\n".join(labels)

    def _setup_pagina_fatture_azienda_storico(self, parent):
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)

        self.var_filtro_categoria_azienda_mov = tk.StringVar(value="Tutte")
        self.var_filtro_gruppo_animale_azienda_mov = tk.StringVar(value="Tutti")
        self.var_filtro_descrizione_azienda_mov = tk.StringVar()
        self.var_filtro_data_da_azienda_mov = tk.StringVar()
        self.var_filtro_data_a_azienda_mov = tk.StringVar()
        self._filtro_gruppi_animali_azienda_map = {}

        frame_filtri = ttk.LabelFrame(container, text="Filtri")
        frame_filtri.pack(fill="x", padx=12, pady=(10, 6))

        riga_filtri_1 = ttk.Frame(frame_filtri)
        riga_filtri_1.pack(fill="x", padx=8, pady=(8, 4))

        ttk.Label(riga_filtri_1, text="Categoria:").pack(side="left")
        self.combo_filtro_categoria_azienda_mov = ttk.Combobox(
            riga_filtri_1,
            textvariable=self.var_filtro_categoria_azienda_mov,
            state="readonly",
            width=24,
        )
        self.combo_filtro_categoria_azienda_mov.pack(side="left", padx=(6, 14))
        self.combo_filtro_categoria_azienda_mov["values"] = ["Tutte"]
        self.combo_filtro_categoria_azienda_mov.current(0)
        self.combo_filtro_categoria_azienda_mov.bind(
            "<<ComboboxSelected>>",
            lambda _event: self.carica_movimenti_azienda_storico(),
        )

        ttk.Label(riga_filtri_1, text="Gruppo animale:").pack(side="left")
        self.combo_filtro_gruppo_animale_azienda_mov = ttk.Combobox(
            riga_filtri_1,
            textvariable=self.var_filtro_gruppo_animale_azienda_mov,
            state="readonly",
            width=30,
        )
        self.combo_filtro_gruppo_animale_azienda_mov.pack(side="left", padx=(6, 14))
        self.combo_filtro_gruppo_animale_azienda_mov["values"] = ["Tutti"]
        self.combo_filtro_gruppo_animale_azienda_mov.current(0)
        self.combo_filtro_gruppo_animale_azienda_mov.bind(
            "<<ComboboxSelected>>",
            lambda _event: self.carica_movimenti_azienda_storico(),
        )

        ttk.Label(riga_filtri_1, text="Descrizione:").pack(side="left")
        entry_filtro_descrizione = ttk.Entry(riga_filtri_1, textvariable=self.var_filtro_descrizione_azienda_mov)
        entry_filtro_descrizione.pack(side="left", fill="x", expand=True, padx=(6, 0))
        entry_filtro_descrizione.bind("<Return>", lambda _event: self.carica_movimenti_azienda_storico())

        riga_filtri_2 = ttk.Frame(frame_filtri)
        riga_filtri_2.pack(fill="x", padx=8, pady=(0, 8))

        ttk.Label(riga_filtri_2, text="Data da:").pack(side="left")
        entry_data_da = ttk.Entry(riga_filtri_2, textvariable=self.var_filtro_data_da_azienda_mov, width=12, state="readonly")
        entry_data_da.pack(side="left", padx=(6, 0))
        ttk.Button(
            riga_filtri_2,
            text="...",
            width=3,
            command=lambda: self._apri_calendario_filtro_azienda_movimenti(self.var_filtro_data_da_azienda_mov),
        ).pack(side="left", padx=(4, 14))
        entry_data_da.bind(
            "<Button-1>",
            lambda _event: self._apri_calendario_filtro_azienda_movimenti(self.var_filtro_data_da_azienda_mov),
        )

        ttk.Label(riga_filtri_2, text="Data a:").pack(side="left")
        entry_data_a = ttk.Entry(riga_filtri_2, textvariable=self.var_filtro_data_a_azienda_mov, width=12, state="readonly")
        entry_data_a.pack(side="left", padx=(6, 0))
        ttk.Button(
            riga_filtri_2,
            text="...",
            width=3,
            command=lambda: self._apri_calendario_filtro_azienda_movimenti(self.var_filtro_data_a_azienda_mov),
        ).pack(side="left", padx=(4, 14))
        entry_data_a.bind(
            "<Button-1>",
            lambda _event: self._apri_calendario_filtro_azienda_movimenti(self.var_filtro_data_a_azienda_mov),
        )

        ttk.Button(riga_filtri_2, text="Applica filtri", command=self.carica_movimenti_azienda_storico).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(riga_filtri_2, text="Pulisci", command=self.pulisci_filtri_movimenti_azienda).pack(side="left")

        frame_table = ttk.Frame(container)
        frame_table.pack(fill="both", expand=True, padx=12, pady=6)

        cols = ("id", "data", "tipo", "categoria", "descrizione", "importo", "iva")
        self.tree_movimenti_azienda = ttk.Treeview(frame_table, columns=cols, show="headings", height=10)

        self.tree_movimenti_azienda.heading("id", text="ID")
        self.tree_movimenti_azienda.heading("data", text="Data")
        self.tree_movimenti_azienda.heading("tipo", text="Tipo")
        self.tree_movimenti_azienda.heading("categoria", text="Categoria")
        self.tree_movimenti_azienda.heading("descrizione", text="Descrizione")
        self.tree_movimenti_azienda.heading("importo", text="Importo")
        self.tree_movimenti_azienda.heading("iva", text="IVA")

        self.tree_movimenti_azienda.column("id", width=60, anchor="center")
        self.tree_movimenti_azienda.column("data", width=100, anchor="center")
        self.tree_movimenti_azienda.column("tipo", width=90, anchor="center")
        self.tree_movimenti_azienda.column("categoria", width=130, anchor="w")
        self.tree_movimenti_azienda.column("descrizione", width=300, anchor="w")
        self.tree_movimenti_azienda.column("importo", width=90, anchor="e")
        self.tree_movimenti_azienda.column("iva", width=90, anchor="e")

        scroll_y = ttk.Scrollbar(frame_table, orient="vertical", command=self.tree_movimenti_azienda.yview)
        scroll_x = ttk.Scrollbar(frame_table, orient="horizontal", command=self.tree_movimenti_azienda.xview)
        self.tree_movimenti_azienda.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        self.tree_movimenti_azienda.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        frame_table.grid_rowconfigure(0, weight=1)
        frame_table.grid_columnconfigure(0, weight=1)

        self.tree_movimenti_azienda.bind(
            "<Double-1>",
            lambda _event: self.prepara_modifica_movimento_da_storico_azienda(),
        )
        self.tree_movimenti_azienda.bind(
            "<<TreeviewSelect>>",
            self._on_selezione_movimento_storico_azienda,
        )
        self.tree_movimenti_azienda.bind(
            "<Delete>",
            lambda _event: self.elimina_movimento_selezionato_azienda(),
        )

        frame_btn = ttk.Frame(container)
        frame_btn.pack(fill="x", padx=12, pady=(0, 8))

        ttk.Button(frame_btn, text="Ricarica", command=self.carica_movimenti_azienda_storico).pack(side="left", padx=6)
        ttk.Button(
            frame_btn,
            text="Modifica selezionato",
            command=self.prepara_modifica_movimento_da_storico_azienda,
        ).pack(side="left", padx=6)
        ttk.Button(
            frame_btn,
            text="Apri fattura",
            command=self.apri_fattura_movimento_selezionato_azienda,
        ).pack(side="left", padx=6)
        ttk.Button(
            frame_btn,
            text="Elimina selezionato",
            command=self.elimina_movimento_selezionato_azienda,
        ).pack(side="left", padx=6)

        frame_dettagli = ttk.LabelFrame(container, text="Dati fattura del movimento selezionato")
        frame_dettagli.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        self.tree_fattura_dettagli_azienda = ttk.Treeview(
            frame_dettagli,
            columns=("campo", "valore"),
            show="headings",
            height=9,
        )
        self.tree_fattura_dettagli_azienda.heading("campo", text="Campo")
        self.tree_fattura_dettagli_azienda.heading("valore", text="Valore")
        self.tree_fattura_dettagli_azienda.column("campo", width=220, anchor="w")
        self.tree_fattura_dettagli_azienda.column("valore", width=620, anchor="w")

        dettagli_scroll_y = ttk.Scrollbar(
            frame_dettagli,
            orient="vertical",
            command=self.tree_fattura_dettagli_azienda.yview,
        )
        self.tree_fattura_dettagli_azienda.configure(yscrollcommand=dettagli_scroll_y.set)

        self.tree_fattura_dettagli_azienda.grid(row=0, column=0, sticky="nsew")
        dettagli_scroll_y.grid(row=0, column=1, sticky="ns")
        frame_dettagli.grid_rowconfigure(0, weight=1)
        frame_dettagli.grid_columnconfigure(0, weight=1)

        self._fattura_dettaglio_corrente_azienda = None
        self._azzera_dettagli_fattura_azienda()

    def _setup_pagina_fatture_azienda_storico_prodotti(self, parent):
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)

        self.var_filtro_storico_prodotti_data_da = tk.StringVar()
        self.var_filtro_storico_prodotti_data_a = tk.StringVar()
        self.var_filtro_storico_prodotti_numero_fattura = tk.StringVar()
        self.var_filtro_storico_prodotti_fornitore = tk.StringVar()
        self.var_filtro_storico_prodotti_prodotto = tk.StringVar()
        self.var_filtro_storico_prodotti_gruppo = tk.StringVar()
        self.var_filtro_storico_prodotti_tipo_costo = tk.StringVar(value="Tutti")

        frame_top = ttk.Frame(container)
        frame_top.pack(fill="x", padx=12, pady=(10, 6))

        self.var_storico_prodotti_azienda_stato = tk.StringVar(value="Nessun prodotto caricato.")
        ttk.Label(frame_top, textvariable=self.var_storico_prodotti_azienda_stato).pack(side="left")
        ttk.Button(
            frame_top,
            text="Ricarica",
            command=self.carica_storico_prodotti_fatture_azienda,
        ).pack(side="right")

        frame_filtri = ttk.LabelFrame(container, text="Filtri")
        frame_filtri.pack(fill="x", padx=12, pady=(0, 6))

        riga_filtri_1 = ttk.Frame(frame_filtri)
        riga_filtri_1.pack(fill="x", padx=8, pady=(8, 4))

        ttk.Label(riga_filtri_1, text="Data mov. da:").pack(side="left")
        entry_data_da = ttk.Entry(
            riga_filtri_1,
            textvariable=self.var_filtro_storico_prodotti_data_da,
            width=12,
            state="readonly",
        )
        entry_data_da.pack(side="left", padx=(6, 0))
        ttk.Button(
            riga_filtri_1,
            text="...",
            width=3,
            command=lambda: self._apri_calendario_filtro_azienda_prodotti(self.var_filtro_storico_prodotti_data_da),
        ).pack(side="left", padx=(4, 12))
        entry_data_da.bind(
            "<Button-1>",
            lambda _event: self._apri_calendario_filtro_azienda_prodotti(self.var_filtro_storico_prodotti_data_da),
        )

        ttk.Label(riga_filtri_1, text="a:").pack(side="left")
        entry_data_a = ttk.Entry(
            riga_filtri_1,
            textvariable=self.var_filtro_storico_prodotti_data_a,
            width=12,
            state="readonly",
        )
        entry_data_a.pack(side="left", padx=(6, 0))
        ttk.Button(
            riga_filtri_1,
            text="...",
            width=3,
            command=lambda: self._apri_calendario_filtro_azienda_prodotti(self.var_filtro_storico_prodotti_data_a),
        ).pack(side="left", padx=(4, 12))
        entry_data_a.bind(
            "<Button-1>",
            lambda _event: self._apri_calendario_filtro_azienda_prodotti(self.var_filtro_storico_prodotti_data_a),
        )

        ttk.Label(riga_filtri_1, text="Tipo costo:").pack(side="left")
        self.combo_filtro_storico_prodotti_tipo_costo = ttk.Combobox(
            riga_filtri_1,
            textvariable=self.var_filtro_storico_prodotti_tipo_costo,
            values=("Tutti", "Variabili", "Fissi"),
            state="readonly",
            width=14,
        )
        self.combo_filtro_storico_prodotti_tipo_costo.pack(side="left", padx=(6, 0))
        self.combo_filtro_storico_prodotti_tipo_costo.current(0)
        self.combo_filtro_storico_prodotti_tipo_costo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self.carica_storico_prodotti_fatture_azienda(),
        )

        riga_filtri_2 = ttk.Frame(frame_filtri)
        riga_filtri_2.pack(fill="x", padx=8, pady=(0, 4))

        ttk.Label(riga_filtri_2, text="N. fattura:").pack(side="left")
        entry_numero_fattura = ttk.Entry(riga_filtri_2, textvariable=self.var_filtro_storico_prodotti_numero_fattura, width=18)
        entry_numero_fattura.pack(side="left", padx=(6, 14))
        entry_numero_fattura.bind("<Return>", lambda _event: self.carica_storico_prodotti_fatture_azienda())

        ttk.Label(riga_filtri_2, text="Fornitore:").pack(side="left")
        entry_fornitore = ttk.Entry(riga_filtri_2, textvariable=self.var_filtro_storico_prodotti_fornitore)
        entry_fornitore.pack(side="left", fill="x", expand=True, padx=(6, 0))
        entry_fornitore.bind("<Return>", lambda _event: self.carica_storico_prodotti_fatture_azienda())

        riga_filtri_3 = ttk.Frame(frame_filtri)
        riga_filtri_3.pack(fill="x", padx=8, pady=(0, 8))

        ttk.Label(riga_filtri_3, text="Prodotto:").pack(side="left")
        entry_prodotto = ttk.Entry(riga_filtri_3, textvariable=self.var_filtro_storico_prodotti_prodotto)
        entry_prodotto.pack(side="left", fill="x", expand=True, padx=(6, 14))
        entry_prodotto.bind("<Return>", lambda _event: self.carica_storico_prodotti_fatture_azienda())

        ttk.Label(riga_filtri_3, text="Gruppo:").pack(side="left")
        entry_gruppo = ttk.Entry(riga_filtri_3, textvariable=self.var_filtro_storico_prodotti_gruppo, width=22)
        entry_gruppo.pack(side="left", padx=(6, 12))
        entry_gruppo.bind("<Return>", lambda _event: self.carica_storico_prodotti_fatture_azienda())

        ttk.Button(
            riga_filtri_3,
            text="Applica filtri",
            command=self.carica_storico_prodotti_fatture_azienda,
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            riga_filtri_3,
            text="Pulisci",
            command=self.pulisci_filtri_storico_prodotti_fatture_azienda,
        ).pack(side="left")

        frame_table = ttk.Frame(container)
        frame_table.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        cols = (
            "data",
            "numero_fattura",
            "fornitore",
            "prodotto",
            "quantita",
            "totale",
            "natura_costo",
            "gruppi",
            "movimento_id",
        )
        self.tree_storico_prodotti_azienda = ttk.Treeview(frame_table, columns=cols, show="headings", height=14)

        self.tree_storico_prodotti_azienda.heading("data", text="Data")
        self.tree_storico_prodotti_azienda.heading("numero_fattura", text="N. fattura")
        self.tree_storico_prodotti_azienda.heading("fornitore", text="Fornitore")
        self.tree_storico_prodotti_azienda.heading("prodotto", text="Prodotto")
        self.tree_storico_prodotti_azienda.heading("quantita", text="Qta")
        self.tree_storico_prodotti_azienda.heading("totale", text="Totale")
        self.tree_storico_prodotti_azienda.heading("natura_costo", text="Tipo costo")
        self.tree_storico_prodotti_azienda.heading("gruppi", text="Imputazione gruppi")
        self.tree_storico_prodotti_azienda.heading("movimento_id", text="ID movimento")

        self.tree_storico_prodotti_azienda.column("data", width=95, anchor="center")
        self.tree_storico_prodotti_azienda.column("numero_fattura", width=130, anchor="center")
        self.tree_storico_prodotti_azienda.column("fornitore", width=220, anchor="w")
        self.tree_storico_prodotti_azienda.column("prodotto", width=340, anchor="w")
        self.tree_storico_prodotti_azienda.column("quantita", width=90, anchor="e")
        self.tree_storico_prodotti_azienda.column("totale", width=110, anchor="e")
        self.tree_storico_prodotti_azienda.column("natura_costo", width=105, anchor="center")
        self.tree_storico_prodotti_azienda.column("gruppi", width=260, anchor="w")
        self.tree_storico_prodotti_azienda.column("movimento_id", width=95, anchor="center")

        scroll_y = ttk.Scrollbar(frame_table, orient="vertical", command=self.tree_storico_prodotti_azienda.yview)
        scroll_x = ttk.Scrollbar(frame_table, orient="horizontal", command=self.tree_storico_prodotti_azienda.xview)
        self.tree_storico_prodotti_azienda.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        self.tree_storico_prodotti_azienda.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        frame_table.grid_rowconfigure(0, weight=1)
        frame_table.grid_columnconfigure(0, weight=1)

    def _apri_calendario_filtro_azienda_prodotti(self, text_var):
        date_text = text_var.get().strip()
        if date_text:
            try:
                initial_date = datetime.strptime(date_text, "%d/%m/%Y").date()
            except ValueError:
                initial_date = datetime.now().date()
        else:
            initial_date = datetime.now().date()

        scelta = self.calendar_dialog_cls(self.root, initial_date).show()
        if scelta is not None:
            text_var.set(scelta.strftime("%d/%m/%Y"))
            self.carica_storico_prodotti_fatture_azienda()

    def pulisci_filtri_storico_prodotti_fatture_azienda(self):
        if hasattr(self, "var_filtro_storico_prodotti_data_da"):
            self.var_filtro_storico_prodotti_data_da.set("")
        if hasattr(self, "var_filtro_storico_prodotti_data_a"):
            self.var_filtro_storico_prodotti_data_a.set("")
        if hasattr(self, "var_filtro_storico_prodotti_numero_fattura"):
            self.var_filtro_storico_prodotti_numero_fattura.set("")
        if hasattr(self, "var_filtro_storico_prodotti_fornitore"):
            self.var_filtro_storico_prodotti_fornitore.set("")
        if hasattr(self, "var_filtro_storico_prodotti_prodotto"):
            self.var_filtro_storico_prodotti_prodotto.set("")
        if hasattr(self, "var_filtro_storico_prodotti_gruppo"):
            self.var_filtro_storico_prodotti_gruppo.set("")
        if hasattr(self, "var_filtro_storico_prodotti_tipo_costo"):
            self.var_filtro_storico_prodotti_tipo_costo.set("Tutti")

        self.carica_storico_prodotti_fatture_azienda()

    def _normalizza_tipo_costo_storico_prodotti(self, raw_value):
        return normalize_cost_type(raw_value)

    def _estrai_righe_prodotti_da_parser_text(self, products_text):
        return extract_products_rows_from_parser_text(products_text)

    def _format_data_storico_prodotti_azienda(self, raw_invoice_date, raw_movimento_date):
        invoice_date = (raw_invoice_date or "").strip()
        if invoice_date and hasattr(self, "_format_data_parser"):
            formatted_invoice_date = self._format_data_parser(invoice_date)
            if formatted_invoice_date:
                return formatted_invoice_date

        movimento_date = (raw_movimento_date or "").strip()
        if not movimento_date:
            return "-"

        try:
            return datetime.strptime(movimento_date, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return movimento_date

    def _format_numero_storico_prodotti_azienda(self, raw_value, decimals):
        testo = str(raw_value or "").strip()
        if not testo or testo == "-":
            return "-"

        numero = parse_decimal(testo, allow_zero=True, allow_negative=False)
        if numero is None:
            return testo
        return format_number(numero, decimals)

    def _normalizza_testo_prodotti_per_display(self, raw_text):
        return normalize_multiline_display_text(raw_text)

    def _normalizza_testo_gruppi_animali_per_display(self, raw_text):
        return normalize_multiline_display_text(raw_text)

    def carica_storico_prodotti_fatture_azienda(self, mostra_errori=True):
        if not hasattr(self, "tree_storico_prodotti_azienda"):
            return

        clear_treeview(self.tree_storico_prodotti_azienda)

        filtro_data_da = self.var_filtro_storico_prodotti_data_da.get().strip() if hasattr(
            self, "var_filtro_storico_prodotti_data_da"
        ) else ""
        filtro_data_a = self.var_filtro_storico_prodotti_data_a.get().strip() if hasattr(
            self, "var_filtro_storico_prodotti_data_a"
        ) else ""
        filtro_numero_fattura = self.var_filtro_storico_prodotti_numero_fattura.get().strip() if hasattr(
            self, "var_filtro_storico_prodotti_numero_fattura"
        ) else ""
        filtro_fornitore = self.var_filtro_storico_prodotti_fornitore.get().strip() if hasattr(
            self, "var_filtro_storico_prodotti_fornitore"
        ) else ""
        filtro_prodotto = self.var_filtro_storico_prodotti_prodotto.get().strip().lower() if hasattr(
            self, "var_filtro_storico_prodotti_prodotto"
        ) else ""
        filtro_gruppo = self.var_filtro_storico_prodotti_gruppo.get().strip().lower() if hasattr(
            self, "var_filtro_storico_prodotti_gruppo"
        ) else ""
        filtro_tipo_costo = self.var_filtro_storico_prodotti_tipo_costo.get().strip() if hasattr(
            self, "var_filtro_storico_prodotti_tipo_costo"
        ) else "Tutti"

        if filtro_tipo_costo not in ("Tutti", "Variabili", "Fissi"):
            filtro_tipo_costo = "Tutti"

        data_da_iso = None
        data_a_iso = None

        if filtro_data_da:
            try:
                data_da_iso = datetime.strptime(filtro_data_da, "%d/%m/%Y").strftime("%Y-%m-%d")
            except ValueError:
                if mostra_errori:
                    messagebox.showerror("Errore", "Data DA non valida (usa GG/MM/AAAA).")
                return

        if filtro_data_a:
            try:
                data_a_iso = datetime.strptime(filtro_data_a, "%d/%m/%Y").strftime("%Y-%m-%d")
            except ValueError:
                if mostra_errori:
                    messagebox.showerror("Errore", "Data A non valida (usa GG/MM/AAAA).")
                return

        if data_da_iso and data_a_iso and data_da_iso > data_a_iso:
            if mostra_errori:
                messagebox.showerror("Errore", "La Data DA non puo essere successiva alla Data A.")
            return

        query = (
            '''
                    SELECT
                        m.id,
                        m.data_op,
                        m.parser_invoice_number,
                        m.parser_invoice_date,
                        m.parser_supplier_name,
                        m.parser_products
                    FROM movimenti m
                    WHERE m.user_id=?
                      AND TRIM(COALESCE(m.parser_products, '')) <> ''
                      AND EXISTS (
                          SELECT 1
                          FROM fatture f
                          WHERE f.user_id = m.user_id
                            AND (
                                f.movimento_id = m.id
                                OR (
                                    f.produzione_id IS NOT NULL
                                    AND EXISTS (
                                        SELECT 1
                                        FROM produzione_latte p
                                        WHERE p.id = f.produzione_id
                                          AND p.user_id = f.user_id
                                          AND p.movimento_id = m.id
                                    )
                                )
                            )
                      )
                '''
        )
        params = [self.user_id]

        if data_da_iso:
            query += " AND m.data_op >= ?"
            params.append(data_da_iso)

        if data_a_iso:
            query += " AND m.data_op <= ?"
            params.append(data_a_iso)

        if filtro_numero_fattura:
            query += " AND LOWER(COALESCE(m.parser_invoice_number, '')) LIKE ?"
            params.append(f"%{filtro_numero_fattura.lower()}%")

        if filtro_fornitore:
            query += " AND LOWER(COALESCE(m.parser_supplier_name, '')) LIKE ?"
            params.append(f"%{filtro_fornitore.lower()}%")

        query += " ORDER BY m.data_op DESC, m.id DESC"

        filtri_attivi = any(
            (
                filtro_data_da,
                filtro_data_a,
                filtro_numero_fattura,
                filtro_fornitore,
                filtro_prodotto,
                filtro_gruppo,
                filtro_tipo_costo != "Tutti",
            )
        )

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(query, tuple(params))
                rows = c.fetchall()
        except sqlite3.Error as e:
            if mostra_errori:
                messagebox.showerror("Errore DB", f"Errore database: {e}")
            if hasattr(self, "var_storico_prodotti_azienda_stato"):
                self.var_storico_prodotti_azienda_stato.set("Errore caricamento storico prodotti.")
            return

        movimenti_con_prodotti = set()
        righe_prodotti = 0

        for mov_id, data_op, invoice_number, invoice_date, supplier_name, products_text in rows:
            prodotti = self._estrai_righe_prodotti_da_parser_text(products_text)
            if not prodotti:
                continue

            data_view = self._format_data_storico_prodotti_azienda(invoice_date, data_op)
            numero_fattura = (invoice_number or "").strip() or "-"
            fornitore = (supplier_name or "").strip() or "-"
            movimento_inserito = False

            for prodotto in prodotti:
                descrizione = str(prodotto.get("description", "-") or "-").strip() or "-"
                gruppi_text = str(prodotto.get("groups", "-") or "-").strip() or "-"
                tipo_costo = self._normalizza_tipo_costo_storico_prodotti(prodotto.get("cost_type"))

                if filtro_tipo_costo != "Tutti" and tipo_costo != filtro_tipo_costo:
                    continue
                if filtro_prodotto and filtro_prodotto not in descrizione.lower():
                    continue
                if filtro_gruppo and filtro_gruppo not in gruppi_text.lower():
                    continue

                self.tree_storico_prodotti_azienda.insert(
                    "",
                    "end",
                    values=(
                        data_view,
                        numero_fattura,
                        fornitore,
                        descrizione,
                        self._format_numero_storico_prodotti_azienda(prodotto.get("quantity"), 3),
                        self._format_numero_storico_prodotti_azienda(prodotto.get("line_total"), 2),
                        tipo_costo,
                        gruppi_text,
                        int(mov_id or 0),
                    ),
                )
                righe_prodotti += 1
                movimento_inserito = True

            if movimento_inserito:
                movimenti_con_prodotti.add(int(mov_id or 0))

        if hasattr(self, "var_storico_prodotti_azienda_stato"):
            if righe_prodotti <= 0:
                if filtri_attivi:
                    self.var_storico_prodotti_azienda_stato.set("Nessun prodotto trovato con i filtri impostati.")
                else:
                    self.var_storico_prodotti_azienda_stato.set("Nessun prodotto trovato nelle fatture archiviate.")
            else:
                suffix = " (filtri attivi)" if filtri_attivi else ""
                self.var_storico_prodotti_azienda_stato.set(
                    f"Prodotti trovati: {righe_prodotti} | Movimenti con fattura: {len(movimenti_con_prodotti)}{suffix}"
                )

    def _apri_calendario_filtro_azienda_movimenti(self, text_var):
        date_text = text_var.get().strip()
        if date_text:
            try:
                initial_date = datetime.strptime(date_text, "%d/%m/%Y").date()
            except ValueError:
                initial_date = datetime.now().date()
        else:
            initial_date = datetime.now().date()

        scelta = self.calendar_dialog_cls(self.root, initial_date).show()
        if scelta is not None:
            text_var.set(scelta.strftime("%d/%m/%Y"))
            self.carica_movimenti_azienda_storico()

    def _carica_categorie_filtro_azienda_movimenti(self, mostra_errori=True):
        if not hasattr(self, "combo_filtro_categoria_azienda_mov"):
            return

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    '''
                    SELECT DISTINCT TRIM(categoria) AS cat
                    FROM movimenti
                    WHERE user_id=?
                      AND categoria IS NOT NULL
                      AND TRIM(categoria) <> ''
                    ORDER BY cat COLLATE NOCASE
                ''',
                    (self.user_id,),
                )
                rows = c.fetchall()
        except sqlite3.Error as e:
            if mostra_errori:
                messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        categorie = [row[0] for row in rows if row[0]]
        valori_filtri = ["Tutte", *categorie]
        filtro_corrente = self.var_filtro_categoria_azienda_mov.get().strip()

        self.combo_filtro_categoria_azienda_mov["values"] = valori_filtri
        if filtro_corrente and filtro_corrente in valori_filtri:
            self.var_filtro_categoria_azienda_mov.set(filtro_corrente)
        else:
            self.var_filtro_categoria_azienda_mov.set("Tutte")

    def _carica_gruppi_filtro_azienda_movimenti(self, mostra_errori=True):
        if not hasattr(self, "combo_filtro_gruppo_animale_azienda_mov"):
            return

        try:
            entries = list_azienda_animali_entries(self.user_id)
        except sqlite3.Error as e:
            if mostra_errori:
                messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        candidati = [entry for entry in entries if int(entry.get("id", 0) or 0) > 0]
        candidati.sort(key=lambda item: ((item.get("group_name") or "").strip().lower(), int(item.get("id", 0) or 0)))

        mapping = {}
        labels = []
        labels_seen = set()
        for entry in candidati:
            entry_id = int(entry.get("id", 0) or 0)
            if entry_id <= 0:
                continue

            label = self._label_gruppo_animale_movimento(entry)
            if label in labels_seen:
                label = f"{label} [ID {entry_id}]"
            labels_seen.add(label)

            mapping[label] = entry_id
            labels.append(label)

        self._filtro_gruppi_animali_azienda_map = mapping

        valori_filtri = ["Tutti", *labels]
        filtro_corrente = self.var_filtro_gruppo_animale_azienda_mov.get().strip()

        self.combo_filtro_gruppo_animale_azienda_mov["values"] = valori_filtri
        if filtro_corrente and filtro_corrente in valori_filtri:
            self.var_filtro_gruppo_animale_azienda_mov.set(filtro_corrente)
        else:
            self.var_filtro_gruppo_animale_azienda_mov.set("Tutti")

    def pulisci_filtri_movimenti_azienda(self):
        if hasattr(self, "var_filtro_categoria_azienda_mov"):
            self.var_filtro_categoria_azienda_mov.set("Tutte")
        if hasattr(self, "var_filtro_gruppo_animale_azienda_mov"):
            self.var_filtro_gruppo_animale_azienda_mov.set("Tutti")
        if hasattr(self, "var_filtro_descrizione_azienda_mov"):
            self.var_filtro_descrizione_azienda_mov.set("")
        if hasattr(self, "var_filtro_data_da_azienda_mov"):
            self.var_filtro_data_da_azienda_mov.set("")
        if hasattr(self, "var_filtro_data_a_azienda_mov"):
            self.var_filtro_data_a_azienda_mov.set("")
        self.carica_movimenti_azienda_storico()

    def carica_movimenti_azienda_storico(self, mostra_errori=True):
        if not hasattr(self, "tree_movimenti_azienda"):
            return

        clear_treeview(self.tree_movimenti_azienda)

        filtro_categoria = self.var_filtro_categoria_azienda_mov.get().strip()
        filtro_gruppo_animale = self.var_filtro_gruppo_animale_azienda_mov.get().strip()
        filtro_descrizione = self.var_filtro_descrizione_azienda_mov.get().strip()
        filtro_data_da = self.var_filtro_data_da_azienda_mov.get().strip()
        filtro_data_a = self.var_filtro_data_a_azienda_mov.get().strip()

        data_da_iso = None
        data_a_iso = None

        if filtro_data_da:
            try:
                data_da_iso = datetime.strptime(filtro_data_da, "%d/%m/%Y").strftime("%Y-%m-%d")
            except ValueError:
                if mostra_errori:
                    messagebox.showerror("Errore", "Data DA non valida (usa GG/MM/AAAA).")
                return

        if filtro_data_a:
            try:
                data_a_iso = datetime.strptime(filtro_data_a, "%d/%m/%Y").strftime("%Y-%m-%d")
            except ValueError:
                if mostra_errori:
                    messagebox.showerror("Errore", "Data A non valida (usa GG/MM/AAAA).")
                return

        if data_da_iso and data_a_iso and data_da_iso > data_a_iso:
            if mostra_errori:
                messagebox.showerror("Errore", "La Data DA non puo essere successiva alla Data A.")
            return

        query = (
            '''
                    SELECT
                        id, data_op, tipo, categoria, descrizione, importo, iva_importo,
                        parser_taxable_total, parser_vat_total, parser_total_amount
                    FROM movimenti
                    WHERE user_id=?
                '''
        )
        params = [self.user_id]

        if filtro_categoria and filtro_categoria != "Tutte":
            query += " AND TRIM(COALESCE(categoria, '')) = ?"
            params.append(filtro_categoria)

        if filtro_gruppo_animale and filtro_gruppo_animale != "Tutti":
            entry_id = int((self._filtro_gruppi_animali_azienda_map or {}).get(filtro_gruppo_animale, 0) or 0)
            if entry_id > 0:
                query += (
                    """
                    AND EXISTS (
                        SELECT 1
                        FROM movimenti_animali_link mal
                        WHERE mal.user_id = movimenti.user_id
                          AND mal.movimento_id = movimenti.id
                          AND mal.animale_entry_id = ?
                    )
                """
                )
                params.append(entry_id)

        if filtro_descrizione:
            query += " AND LOWER(COALESCE(descrizione, '')) LIKE ?"
            params.append(f"%{filtro_descrizione.lower()}%")

        if data_da_iso:
            query += " AND data_op >= ?"
            params.append(data_da_iso)

        if data_a_iso:
            query += " AND data_op <= ?"
            params.append(data_a_iso)

        query += " ORDER BY data_op DESC, id DESC"

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(query, tuple(params))
                rows = c.fetchall()
        except sqlite3.Error as e:
            if mostra_errori:
                messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        for (
            mov_id,
            data_op,
            tipo,
            categoria,
            descrizione,
            importo,
            iva_importo,
            parser_taxable_total,
            parser_vat_total,
            parser_total_amount,
        ) in rows:
            try:
                data_view = datetime.strptime(data_op, "%Y-%m-%d").strftime("%d/%m/%Y")
            except ValueError:
                data_view = data_op

            importo_view = parse_decimal(importo, allow_zero=True, allow_negative=False)
            if importo_view is None:
                importo_view = 0.0

            iva_view = parse_decimal(iva_importo, allow_zero=True, allow_negative=False)
            if iva_view is None:
                iva_view = 0.0

            if iva_view <= 0 and (categoria or "").strip().upper() == "LATTE":
                iva_parser = parse_decimal(parser_vat_total, allow_zero=True, allow_negative=False)
                imponibile_parser = parse_decimal(parser_taxable_total, allow_zero=True, allow_negative=False)
                totale_parser = parse_decimal(parser_total_amount, allow_zero=False, allow_negative=False)

                if iva_parser is not None and iva_parser > 0:
                    iva_view = iva_parser
                    if imponibile_parser is not None and imponibile_parser >= 0:
                        importo_view = imponibile_parser
                    elif totale_parser is not None and totale_parser >= iva_view:
                        importo_view = totale_parser - iva_view

            self.tree_movimenti_azienda.insert(
                "",
                "end",
                values=(
                    mov_id,
                    data_view,
                    tipo,
                    categoria or "",
                    descrizione or "",
                    format_number(importo_view, 2),
                    format_number(iva_view, 2),
                ),
            )

        self._azzera_dettagli_fattura_azienda()
        self._carica_categorie_filtro_azienda_movimenti(mostra_errori=False)
        self._carica_gruppi_filtro_azienda_movimenti(mostra_errori=False)
        if hasattr(self, "carica_categorie_salvate"):
            self.carica_categorie_salvate(mostra_errori=False)
        if hasattr(self, "carica_storico_prodotti_fatture_azienda"):
            self.carica_storico_prodotti_fatture_azienda(mostra_errori=False)

    def _azzera_dettagli_fattura_azienda(self, testo="Seleziona un movimento per vedere la fattura collegata."):
        self._fattura_dettaglio_corrente_azienda = None
        if not hasattr(self, "tree_fattura_dettagli_azienda"):
            return

        clear_treeview(self.tree_fattura_dettagli_azienda)
        self.tree_fattura_dettagli_azienda.insert("", "end", values=("Info", testo))

    def _on_selezione_movimento_storico_azienda(self, _event=None):
        self.carica_dettagli_fattura_movimento_selezionato_azienda()

    def carica_dettagli_fattura_movimento_selezionato_azienda(self):
        if not hasattr(self, "tree_movimenti_azienda"):
            return

        selezione = self.tree_movimenti_azienda.selection()
        if not selezione:
            self._azzera_dettagli_fattura_azienda("Seleziona un movimento per vedere la fattura collegata.")
            return

        valori = self.tree_movimenti_azienda.item(selezione[0], "values")
        if not valori:
            self._azzera_dettagli_fattura_azienda("Movimento selezionato non valido.")
            return

        mov_id = int(valori[0])

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    '''
                    SELECT
                        f.id,
                        f.data_caricamento,
                        f.origine,
                        f.nome_originale,
                        f.percorso_file,
                        m.parser_invoice_number,
                        m.parser_invoice_date,
                        m.parser_due_date,
                        m.parser_supplier_name,
                        m.parser_supplier_vat,
                        m.parser_customer_name,
                        m.parser_customer_vat,
                        m.parser_total_amount,
                        m.parser_taxable_total,
                        m.parser_vat_total,
                        m.parser_payment_terms,
                        m.parser_warnings,
                        m.parser_products,
                        m.parser_fields_view
                    FROM fatture f
                    LEFT JOIN movimenti m
                      ON m.id = f.movimento_id
                     AND m.user_id = f.user_id
                                        WHERE f.user_id=?
                                            AND (
                                                        f.movimento_id=?
                                                        OR (
                                                                f.produzione_id IS NOT NULL
                                                                AND EXISTS (
                                                                        SELECT 1
                                                                        FROM produzione_latte p
                                                                        WHERE p.id = f.produzione_id
                                                                            AND p.user_id = f.user_id
                                                                            AND p.movimento_id = ?
                                                                )
                                                        )
                                            )
                    ORDER BY f.data_caricamento DESC, f.id DESC
                    LIMIT 1
                ''',
                                        (self.user_id, mov_id, mov_id),
                )
                row = c.fetchone()
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            self._azzera_dettagli_fattura_azienda("Errore durante il caricamento della fattura collegata.")
            return

        if not row:
            self._azzera_dettagli_fattura_azienda("Nessuna fattura collegata al movimento selezionato.")
            return

        (
            fattura_id,
            data_caricamento,
            origine,
            nome_originale,
            percorso_file,
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
        ) = row

        gruppi_animali_collegati = self._gruppi_animali_collegati_movimento_testo(mov_id)

        self._fattura_dettaglio_corrente_azienda = {
            "id": fattura_id,
            "data_caricamento": self._format_data_caricamento(data_caricamento),
            "origine": origine or "",
            "nome_originale": nome_originale or "",
            "percorso_file": percorso_file or "",
            "invoice_number": parser_invoice_number or "",
            "invoice_date": self._format_data_parser(parser_invoice_date),
            "due_date": self._format_data_parser(parser_due_date),
            "supplier_name": parser_supplier_name or "",
            "supplier_vat": parser_supplier_vat or "",
            "customer_name": parser_customer_name or "",
            "customer_vat": parser_customer_vat or "",
            "total_amount": self._format_importo_parser(parser_total_amount),
            "taxable_total": self._format_importo_parser(parser_taxable_total),
            "vat_total": self._format_importo_parser(parser_vat_total),
            "payment_terms": parser_payment_terms or "",
            "warnings": parser_warnings or "",
            "products": self._normalizza_testo_prodotti_per_display(parser_products),
            "fields_view": parser_fields_view or "",
            "gruppi_animali": self._normalizza_testo_gruppi_animali_per_display(gruppi_animali_collegati),
        }
        self._mostra_dettagli_fattura_azienda(self._fattura_dettaglio_corrente_azienda)

    def _mostra_dettagli_fattura_azienda(self, dettagli):
        clear_treeview(self.tree_fattura_dettagli_azienda)
        righe = [
            ("ID Fattura", dettagli.get("id", "")),
            ("Data caricamento", dettagli.get("data_caricamento", "")),
            ("Origine", dettagli.get("origine", "")),
            ("Nome file", dettagli.get("nome_originale", "")),
            ("Numero fattura", dettagli.get("invoice_number", "")),
            ("Data fattura", dettagli.get("invoice_date", "")),
            ("Scadenza", dettagli.get("due_date", "")),
            ("Fornitore", dettagli.get("supplier_name", "")),
            ("P.IVA Fornitore", dettagli.get("supplier_vat", "")),
            ("Cliente", dettagli.get("customer_name", "")),
            ("P.IVA Cliente", dettagli.get("customer_vat", "")),
            ("Totale documento", dettagli.get("total_amount", "")),
            ("Totale imponibile", dettagli.get("taxable_total", "")),
            ("Totale IVA", dettagli.get("vat_total", "")),
            ("Condizioni pagamento", dettagli.get("payment_terms", "")),
            ("Gruppi animali collegati", dettagli.get("gruppi_animali", "")),
            ("Prodotti", dettagli.get("products", "")),
        ]

        for campo, valore in righe:
            self.tree_fattura_dettagli_azienda.insert("", "end", values=(campo, valore or ""))

    def apri_fattura_movimento_selezionato_azienda(self):
        dettagli = getattr(self, "_fattura_dettaglio_corrente_azienda", None)
        if not dettagli:
            messagebox.showwarning("Attenzione", "Seleziona un movimento con fattura collegata.")
            return

        percorso = dettagli.get("percorso_file", "")
        if not percorso:
            messagebox.showerror("Errore", "La fattura selezionata non ha un percorso file valido.")
            return

        percorso_fattura = resolve_fattura_path(percorso)
        if not percorso_fattura.exists():
            messagebox.showerror("File non trovato", f"La fattura non esiste piu nel percorso salvato:\n{percorso_fattura}")
            return

        self.apri_file_locale(percorso_fattura)

    def elimina_movimento_selezionato_azienda(self):
        if not hasattr(self, "tree_movimenti_azienda"):
            return

        selezione = self.tree_movimenti_azienda.selection()
        if not selezione:
            messagebox.showwarning("Attenzione", "Seleziona prima un movimento da eliminare.")
            return

        valori = self.tree_movimenti_azienda.item(selezione[0], "values")
        if not valori:
            messagebox.showerror("Errore", "Impossibile leggere il movimento selezionato.")
            return

        mov_id = int(valori[0])
        descrizione = valori[4] or f"ID {mov_id}"
        conferma = messagebox.askyesno("Conferma eliminazione", f"Vuoi eliminare il movimento selezionato?\n\n{descrizione}")
        if not conferma:
            return

        fatture_eliminate = 0
        produzioni_eliminate = 0
        percorsi_fatture = []
        try:
            with get_conn() as conn:
                c = conn.cursor()

                c.execute("SELECT 1 FROM movimenti WHERE id=? AND user_id=?", (mov_id, self.user_id))
                if not c.fetchone():
                    messagebox.showerror("Errore", "Movimento non trovato o non eliminabile.")
                    return

                c.execute(
                    "SELECT COUNT(id) FROM produzione_latte WHERE user_id=? AND movimento_id=?",
                    (self.user_id, mov_id),
                )
                row_prod = c.fetchone()
                produzioni_eliminate = int((row_prod[0] if row_prod else 0) or 0)

                fatture_eliminate, percorsi_fatture = self.elimina_fatture_collegate_db(c, mov_id)

                c.execute("DELETE FROM movimenti WHERE id=? AND user_id=?", (mov_id, self.user_id))

                if c.rowcount == 0:
                    messagebox.showerror("Errore", "Movimento non trovato o non eliminabile.")
                    return
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        file_eliminati, file_non_trovati, file_errori = self.elimina_file_fatture(percorsi_fatture)

        if self.movimento_in_modifica_id == mov_id:
            self.annulla_modifica_movimento()

        self.carica_movimenti_azienda_storico(mostra_errori=False)
        if hasattr(self, "carica_movimenti"):
            self.carica_movimenti()
        if hasattr(self, "carica_produzioni_latte"):
            self.carica_produzioni_latte(mostra_errori=False)

        msg_ok = "Movimento eliminato dal database!"
        if produzioni_eliminate > 0:
            msg_ok += f" Produzioni latte collegate eliminate: {produzioni_eliminate}."
        if fatture_eliminate > 0:
            msg_ok += f" Fatture collegate eliminate: {fatture_eliminate}."
            msg_ok += f" File fattura eliminati: {file_eliminati}."
            if file_non_trovati > 0:
                msg_ok += f" File non trovati: {file_non_trovati}."

        if file_errori:
            messagebox.showwarning(
                "Eliminazione completata con avvisi",
                msg_ok + "\n\nAlcuni file non sono stati eliminati:\n" + "\n".join(file_errori[:3]),
            )
        else:
            messagebox.showinfo("Successo", msg_ok)

    def prepara_modifica_movimento_da_storico_azienda(self):
        if not hasattr(self, "tree_movimenti_azienda"):
            return

        selezione = self.tree_movimenti_azienda.selection()
        if not selezione:
            messagebox.showwarning("Attenzione", "Seleziona prima un movimento da modificare.")
            return

        valori = self.tree_movimenti_azienda.item(selezione[0], "values")
        if not valori:
            messagebox.showerror("Errore", "Impossibile leggere il movimento selezionato.")
            return

        self.movimento_in_modifica_id = int(valori[0])
        self.var_data.set(valori[1] or datetime.now().strftime("%d/%m/%Y"))
        self.var_tipo.set(valori[2] or "ENTRATA")
        self.var_cat.set(valori[3] or "")
        self.var_desc.set(valori[4] or "")
        self.var_imp.set(valori[5] or "")
        self.var_iva.set(valori[6] or "0,00")

        gruppi_collegati_ids = []
        try:
            gruppi_collegati_ids = get_movimento_animali_entry_ids(self.user_id, self.movimento_in_modifica_id)
        except sqlite3.Error:
            gruppi_collegati_ids = []
        if hasattr(self, "imposta_gruppi_animali_movimento_selezionati"):
            self.imposta_gruppi_animali_movimento_selezionati(gruppi_collegati_ids)

        if hasattr(self, "btn_salva_movimento"):
            self.btn_salva_movimento.config(text="Aggiorna nel DB")
        if hasattr(self, "btn_annulla_modifica"):
            self.btn_annulla_modifica.config(state="normal")
        if hasattr(self, "btn_salva_movimento_azienda"):
            self.btn_salva_movimento_azienda.config(text="Aggiorna nel DB")
        if hasattr(self, "btn_annulla_modifica_azienda"):
            self.btn_annulla_modifica_azienda.config(state="normal")

        if hasattr(self, "mostra_categoria") and hasattr(self, "CATEGORIA_AZIENDA"):
            self.mostra_categoria(self.CATEGORIA_AZIENDA)
        if hasattr(self, "azienda_notebook") and hasattr(self, "tab_azienda_fatture"):
            self.azienda_notebook.select(self.tab_azienda_fatture)
        if hasattr(self, "azienda_fatture_notebook") and hasattr(self, "tab_azienda_fatture_inserimento"):
            self.azienda_fatture_notebook.select(self.tab_azienda_fatture_inserimento)

    def _setup_pagina_animali_azienda(self):
        content = self.crea_container_scorribile(self.tab_azienda_animali)
        self._azienda_animali_scroll_content = content
        self._azienda_animali_scroll_canvas = getattr(content, "_scroll_canvas", None)
        self._azienda_animali_scroll_window_id = getattr(content, "_scroll_window_id", None)

        self.var_animale_rimuovi_capi = tk.StringVar(value="")
        self.var_animale_modifica_capi = tk.StringVar(value="")
        self.var_animale_modifica_finalita = tk.StringVar(value=self.PURPOSE_OPTIONS[0])
        self.var_animale_modifica_riproduzione = tk.BooleanVar(value=False)
        self.var_animale_modifica_target = tk.StringVar(value="")
        self.var_animale_modifica_nome_gruppo = tk.StringVar(value="")
        self.var_animale_dividi_target = tk.StringVar(value="")
        self.var_animale_operazione_gruppo = tk.StringVar(value="dividi")
        self.var_animale_dividi_capi_primo = tk.StringVar(value="")
        self.var_animale_dividi_nome_nuovo_gruppo = tk.StringVar(value="")
        self.var_animale_dividi_restanti = tk.StringVar(value="Capi che restano nel gruppo attuale: -")
        self.var_animale_unisci_target = tk.StringVar(value="")
        self.var_animale_unisci_nome_nuovo_gruppo = tk.StringVar(value="")
        self.var_animale_unisci_data = tk.StringVar(value="")
        self.var_animale_unisci_totale = tk.StringVar(value="Totale capi nel gruppo unificato: -")
        self._animale_dividi_capi_totali = 0
        self._animale_unisci_candidati = {}
        self.var_animale_unisci_target.trace_add("write", self._aggiorna_preview_unione_animale)
        self.var_animale_dividi_capi_primo.trace_add("write", self._aggiorna_preview_divisione_animale)

        self.frame_animale_form = ttk.LabelFrame(content, text="Nuovo animale")
        self.frame_animale_form.pack(fill="x", padx=12, pady=(12, 8))

        self.var_animale_tipo = tk.StringVar(value=self.ANIMAL_TYPE_OPTIONS[0])
        self.var_animale_finalita = tk.StringVar(value=self.PURPOSE_OPTIONS[0])
        self.var_animale_altro = tk.StringVar()
        self.var_animale_riproduzione = tk.BooleanVar(value=False)
        self.var_animale_capi = tk.StringVar(value="")
        self.var_animale_nome_gruppo = tk.StringVar(value="")

        self.var_animali_stato = tk.StringVar(value="")
        self.var_animali_report_totale = tk.StringVar(value="Totale capi registrati: 0")

        row_nome_gruppo = ttk.Frame(self.frame_animale_form)
        row_nome_gruppo.pack(fill="x", padx=20, pady=(8, 4))
        ttk.Label(row_nome_gruppo, text="Nome gruppo:", width=16).pack(side="left")
        ttk.Entry(row_nome_gruppo, textvariable=self.var_animale_nome_gruppo).pack(side="left", fill="x", expand=True)

        row_tipo = ttk.Frame(self.frame_animale_form)
        row_tipo.pack(fill="x", padx=20, pady=4)
        ttk.Label(row_tipo, text="Tipo animale:", width=16).pack(side="left")
        combo_tipo = ttk.Combobox(
            row_tipo,
            textvariable=self.var_animale_tipo,
            values=self.ANIMAL_TYPE_OPTIONS,
            state="readonly",
            width=20,
        )
        combo_tipo.pack(side="left")
        combo_tipo.bind("<<ComboboxSelected>>", self._on_tipo_animale_change)

        self.row_animale_finalita = ttk.Frame(self.frame_animale_form)
        ttk.Label(self.row_animale_finalita, text="Destinazione:", width=16).pack(side="left")
        self.combo_animale_finalita = ttk.Combobox(
            self.row_animale_finalita,
            textvariable=self.var_animale_finalita,
            values=self.PURPOSE_OPTIONS,
            state="readonly",
            width=20,
        )
        self.combo_animale_finalita.pack(side="left")

        self.row_animale_altro = ttk.Frame(self.frame_animale_form)
        ttk.Label(self.row_animale_altro, text="Specifica tipo:", width=16).pack(side="left")
        ttk.Entry(self.row_animale_altro, textvariable=self.var_animale_altro).pack(side="left", fill="x", expand=True)

        self.row_animale_capi = ttk.Frame(self.frame_animale_form)
        self.row_animale_capi.pack(fill="x", padx=20, pady=4)
        ttk.Label(self.row_animale_capi, text="Numero capi:", width=16).pack(side="left")
        ttk.Entry(self.row_animale_capi, textvariable=self.var_animale_capi, width=12).pack(side="left")

        self.row_animale_riproduzione = ttk.Frame(self.frame_animale_form)
        self.row_animale_riproduzione.pack(fill="x", padx=20, pady=4, before=self.row_animale_capi)
        ttk.Label(self.row_animale_riproduzione, text="Riproduzione:", width=16).pack(side="left")
        ttk.Checkbutton(
            self.row_animale_riproduzione,
            text="Destinato alla riproduzione",
            variable=self.var_animale_riproduzione,
        ).pack(side="left")

        self.row_animale_form_btn = ttk.Frame(self.frame_animale_form)
        self.row_animale_form_btn.pack(fill="x", padx=20, pady=(6, 8))
        ttk.Button(self.row_animale_form_btn, text="Conferma aggiunta", command=self.aggiungi_animale_da_form).pack(side="left")
        ttk.Button(self.row_animale_form_btn, text="Annulla", command=self._reset_form_aggiungi_animale).pack(
            side="left", padx=6
        )

        self._reset_form_aggiungi_animale()

        frame_report = ttk.LabelFrame(content, text="Report animali presenti in azienda")
        frame_report.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self.tree_animali_report = ttk.Treeview(
            frame_report,
            columns=("gruppo", "tipo", "destinazione", "riproduzione", "capi"),
            show="headings",
            height=10,
            selectmode="browse",
        )
        self.tree_animali_report.heading("gruppo", text="Gruppo")
        self.tree_animali_report.heading("tipo", text="Tipo")
        self.tree_animali_report.heading("destinazione", text="Destinazione")
        self.tree_animali_report.heading("riproduzione", text="Riproduzione")
        self.tree_animali_report.heading("capi", text="Capi")

        self.tree_animali_report.column("gruppo", width=220, anchor="w")
        self.tree_animali_report.column("tipo", width=220, anchor="w")
        self.tree_animali_report.column("destinazione", width=160, anchor="center")
        self.tree_animali_report.column("riproduzione", width=140, anchor="center")
        self.tree_animali_report.column("capi", width=120, anchor="e")

        scroll_report = ttk.Scrollbar(frame_report, orient="vertical", command=self.tree_animali_report.yview)
        self.tree_animali_report.configure(yscrollcommand=scroll_report.set)

        self.tree_animali_report.pack(side="left", fill="both", expand=True)
        scroll_report.pack(side="right", fill="y")

        frame_azioni_lista = ttk.Frame(content)
        frame_azioni_lista.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Button(frame_azioni_lista, text="Modifica", command=self.apri_sezione_modifica_animale).pack(side="left")

        self.frame_modifica_wrapper = ttk.Frame(content)

        self.frame_modifica_animale = ttk.LabelFrame(self.frame_modifica_wrapper, text="Modifica categoria selezionata")
        self.frame_modifica_animale.pack(side="left", fill="both", expand=True, padx=(0, 6))

        ttk.Label(
            self.frame_modifica_animale,
            textvariable=self.var_animale_modifica_target,
            font=("Arial", 10, "bold"),
        ).pack(anchor="w", padx=20, pady=(8, 4))

        row_rimozione = ttk.Frame(self.frame_modifica_animale)
        row_rimozione.pack(fill="x", padx=20, pady=4)
        ttk.Label(row_rimozione, text="Capi da rimuovere:", width=20).pack(side="left")
        ttk.Entry(row_rimozione, textvariable=self.var_animale_rimuovi_capi, width=10).pack(side="left", padx=(6, 8))
        ttk.Button(
            row_rimozione,
            text="Rimuovi capi",
            command=self.rimuovi_capi_categoria_selezionata,
        ).pack(side="left")

        row_modifica = ttk.Frame(self.frame_modifica_animale)
        row_modifica.pack(fill="x", padx=20, pady=4)
        ttk.Label(row_modifica, text="Nuovo numero capi:", width=20).pack(side="left")
        ttk.Entry(row_modifica, textvariable=self.var_animale_modifica_capi, width=10).pack(side="left", padx=(6, 8))
        ttk.Button(
            row_modifica,
            text="Salva numero capi",
            command=self.modifica_capi_categoria_selezionata,
        ).pack(side="left")

        row_nome_gruppo_modifica = ttk.Frame(self.frame_modifica_animale)
        row_nome_gruppo_modifica.pack(fill="x", padx=20, pady=4)
        ttk.Label(row_nome_gruppo_modifica, text="Nuovo nome gruppo:", width=20).pack(side="left")
        ttk.Entry(row_nome_gruppo_modifica, textvariable=self.var_animale_modifica_nome_gruppo).pack(
            side="left", fill="x", expand=True, padx=(6, 8)
        )
        ttk.Button(
            row_nome_gruppo_modifica,
            text="Salva nome gruppo",
            command=self.modifica_nome_gruppo_categoria_selezionata,
        ).pack(side="left")

        self.row_animale_modifica_destinazione = ttk.Frame(self.frame_modifica_animale)
        ttk.Label(self.row_animale_modifica_destinazione, text="Nuova destinazione:", width=20).pack(side="left")
        self.combo_animale_modifica_finalita = ttk.Combobox(
            self.row_animale_modifica_destinazione,
            textvariable=self.var_animale_modifica_finalita,
            values=self.PURPOSE_OPTIONS,
            state="readonly",
            width=16,
        )
        self.combo_animale_modifica_finalita.pack(side="left", padx=(6, 8))
        ttk.Button(
            self.row_animale_modifica_destinazione,
            text="Salva destinazione",
            command=self.modifica_destinazione_categoria_selezionata,
        ).pack(side="left")

        self.row_animale_modifica_riproduzione = ttk.Frame(self.frame_modifica_animale)
        ttk.Label(self.row_animale_modifica_riproduzione, text="Riproduzione:", width=20).pack(side="left")
        ttk.Checkbutton(
            self.row_animale_modifica_riproduzione,
            text="Destinato alla riproduzione",
            variable=self.var_animale_modifica_riproduzione,
        ).pack(side="left", padx=(6, 8))
        ttk.Button(
            self.row_animale_modifica_riproduzione,
            text="Salva riproduzione",
            command=self.modifica_riproduzione_categoria_selezionata,
        ).pack(side="left")

        self.row_animale_modifica_elimina = ttk.Frame(self.frame_modifica_animale)
        self.row_animale_modifica_elimina.pack(fill="x", padx=20, pady=(0, 6))
        ttk.Button(
            self.row_animale_modifica_elimina,
            text="Rimuovi categoria selezionata",
            command=self.rimuovi_categoria_animale_selezionata,
        ).pack(side="left")

        row_chiudi_modifica = ttk.Frame(self.frame_modifica_animale)
        row_chiudi_modifica.pack(fill="x", padx=20, pady=(0, 8))
        ttk.Button(
            row_chiudi_modifica,
            text="Chiudi modifica",
            command=self._chiudi_sezione_modifica_animale,
        ).pack(side="left")

        self.frame_dividi_gruppo = ttk.LabelFrame(self.frame_modifica_wrapper, text="Dividi Gruppo")
        self.frame_dividi_gruppo.pack(side="left", fill="both", expand=True, padx=(6, 0))

        ttk.Label(
            self.frame_dividi_gruppo,
            textvariable=self.var_animale_dividi_target,
            font=("Arial", 10, "bold"),
        ).pack(anchor="w", padx=20, pady=(8, 4))

        row_operazione = ttk.Frame(self.frame_dividi_gruppo)
        row_operazione.pack(fill="x", padx=20, pady=(0, 4))
        ttk.Radiobutton(
            row_operazione,
            text="Dividi",
            value="dividi",
            variable=self.var_animale_operazione_gruppo,
            command=self._on_operazione_gruppo_change,
        ).pack(side="left")
        ttk.Radiobutton(
            row_operazione,
            text="Unisci",
            value="unisci",
            variable=self.var_animale_operazione_gruppo,
            command=self._on_operazione_gruppo_change,
        ).pack(side="left", padx=(12, 0))

        self.frame_operazione_dividi = ttk.Frame(self.frame_dividi_gruppo)
        self.frame_operazione_dividi.pack(fill="x", padx=20, pady=(0, 8))

        row_dividi_capi = ttk.Frame(self.frame_operazione_dividi)
        row_dividi_capi.pack(fill="x", pady=4)
        ttk.Label(row_dividi_capi, text="Capi primo gruppo:", width=20).pack(side="left")
        ttk.Entry(row_dividi_capi, textvariable=self.var_animale_dividi_capi_primo, width=10).pack(side="left", padx=(6, 8))

        ttk.Label(
            self.frame_operazione_dividi,
            textvariable=self.var_animale_dividi_restanti,
        ).pack(anchor="w", pady=(0, 4))

        row_dividi_nome = ttk.Frame(self.frame_operazione_dividi)
        row_dividi_nome.pack(fill="x", pady=4)
        ttk.Label(row_dividi_nome, text="Nuovo nome gruppo:", width=20).pack(side="left")
        ttk.Entry(row_dividi_nome, textvariable=self.var_animale_dividi_nome_nuovo_gruppo).pack(
            side="left", fill="x", expand=True, padx=(6, 8)
        )

        row_dividi_btn = ttk.Frame(self.frame_operazione_dividi)
        row_dividi_btn.pack(fill="x", pady=(0, 4))
        ttk.Button(
            row_dividi_btn,
            text="Conferma divisione",
            command=self.dividi_gruppo_categoria_selezionata,
        ).pack(side="left")

        self.frame_operazione_unisci = ttk.Frame(self.frame_dividi_gruppo)

        row_unisci_target = ttk.Frame(self.frame_operazione_unisci)
        row_unisci_target.pack(fill="x", pady=4)
        ttk.Label(row_unisci_target, text="Gruppo da unire:", width=20).pack(side="left")
        self.combo_animale_unisci_target = ttk.Combobox(
            row_unisci_target,
            textvariable=self.var_animale_unisci_target,
            state="readonly",
        )
        self.combo_animale_unisci_target.pack(side="left", fill="x", expand=True, padx=(6, 8))

        ttk.Label(
            self.frame_operazione_unisci,
            textvariable=self.var_animale_unisci_totale,
        ).pack(anchor="w", pady=(0, 4))

        row_unisci_nome = ttk.Frame(self.frame_operazione_unisci)
        row_unisci_nome.pack(fill="x", pady=4)
        ttk.Label(row_unisci_nome, text="Nuovo nome gruppo:", width=20).pack(side="left")
        ttk.Entry(row_unisci_nome, textvariable=self.var_animale_unisci_nome_nuovo_gruppo).pack(
            side="left", fill="x", expand=True, padx=(6, 8)
        )

        row_unisci_data = ttk.Frame(self.frame_operazione_unisci)
        row_unisci_data.pack(fill="x", pady=4)
        ttk.Label(row_unisci_data, text="Data unione (opz.):", width=20).pack(side="left")
        entry_unisci_data = ttk.Entry(
            row_unisci_data,
            textvariable=self.var_animale_unisci_data,
            width=14,
            state="readonly",
        )
        entry_unisci_data.pack(side="left", padx=(6, 0))
        ttk.Button(
            row_unisci_data,
            text="...",
            width=3,
            command=self._apri_calendario_data_unione_animale,
        ).pack(side="left", padx=(4, 8))
        entry_unisci_data.bind("<Button-1>", lambda _event: self._apri_calendario_data_unione_animale())

        row_unisci_btn = ttk.Frame(self.frame_operazione_unisci)
        row_unisci_btn.pack(fill="x", pady=(0, 4))
        ttk.Button(
            row_unisci_btn,
            text="Conferma unione",
            command=self.unisci_gruppi_categoria_selezionata,
        ).pack(side="left")

        self._set_sezione_modifica_animale(False)

        ttk.Label(content, textvariable=self.var_animali_report_totale, font=("Arial", 10, "bold")).pack(
            anchor="w", padx=12, pady=(0, 4)
        )

        ttk.Label(content, textvariable=self.var_animali_stato, foreground="#1f5f3f").pack(
            anchor="w", padx=12, pady=(0, 8)
        )

    def _parse_positive_int(self, raw_value, label):
        text = (raw_value or "").strip()
        if not text:
            raise ValueError(f"Inserisci il numero capi per {label}.")

        try:
            capi = int(text)
        except ValueError:
            raise ValueError(f"Numero capi non valido per {label}.")

        if capi <= 0:
            raise ValueError(f"Numero capi non valido per {label}: deve essere > 0.")
        return capi

    def _parse_non_negative_int(self, raw_value, label):
        text = (raw_value or "").strip()
        if not text:
            raise ValueError(f"Inserisci il numero capi per {label}.")

        try:
            capi = int(text)
        except ValueError:
            raise ValueError(f"Numero capi non valido per {label}.")

        if capi < 0:
            raise ValueError(f"Numero capi non valido per {label}: deve essere >= 0.")
        return capi

    def _reset_form_aggiungi_animale(self):
        self.var_animale_nome_gruppo.set("")
        self.var_animale_tipo.set(self.ANIMAL_TYPE_OPTIONS[0])
        self.var_animale_finalita.set(self.PURPOSE_OPTIONS[0])
        self.var_animale_altro.set("")
        self.var_animale_riproduzione.set(False)
        self.var_animale_capi.set("")
        self._on_tipo_animale_change()

    def _set_sezione_modifica_animale(self, show: bool):
        visible = self.frame_modifica_wrapper.winfo_manager() != ""
        if show and not visible:
            self.frame_modifica_wrapper.pack(fill="x", padx=12, pady=(0, 8))
        if not show and visible:
            self.frame_modifica_wrapper.pack_forget()
        self._aggiorna_scroll_animali(reset_to_top=not show)

    def _aggiorna_scroll_animali(self, reset_to_top: bool = False):
        content = getattr(self, "_azienda_animali_scroll_content", None)
        canvas = getattr(self, "_azienda_animali_scroll_canvas", None)
        window_id = getattr(self, "_azienda_animali_scroll_window_id", None)

        if content is not None:
            content.update_idletasks()

        if canvas is None:
            return

        if window_id is not None:
            canvas.coords(window_id, 0, 0)

        bbox = canvas.bbox("all")
        if bbox:
            canvas.configure(scrollregion=bbox)

        if reset_to_top:
            canvas.yview_moveto(0.0)
            if content is not None:
                def _finalize_reset():
                    content.update_idletasks()
                    if window_id is not None:
                        canvas.coords(window_id, 0, 0)
                    final_bbox = canvas.bbox("all")
                    if final_bbox:
                        canvas.configure(scrollregion=final_bbox)
                    canvas.yview_moveto(0.0)

                content.after_idle(_finalize_reset)

    def _normalizza_capi_da_testo(self, raw_value):
        text = str(raw_value or "").strip().replace("'", "").replace("’", "").replace(" ", "")
        if not text:
            return ""

        try:
            value = int(float(text.replace(",", ".")))
        except ValueError:
            return ""
        return str(value if value >= 0 else 0)

    def _aggiorna_preview_divisione_animale(self, *_args):
        capi_totali = int(getattr(self, "_animale_dividi_capi_totali", 0) or 0)
        raw_value = self.var_animale_dividi_capi_primo.get().strip()

        if capi_totali <= 0:
            self.var_animale_dividi_restanti.set("Capi che restano nel gruppo attuale: -")
            return

        if not raw_value:
            self.var_animale_dividi_restanti.set(
                f"Capi che restano nel gruppo attuale: {format_number(capi_totali, 0)}"
            )
            return

        try:
            capi_primo = int(raw_value)
        except ValueError:
            self.var_animale_dividi_restanti.set("Capi che restano nel gruppo attuale: valore non valido")
            return

        capi_restanti = capi_totali - capi_primo
        if capi_primo <= 0:
            self.var_animale_dividi_restanti.set("Capi che restano nel gruppo attuale: inserisci un valore > 0")
            return
        if capi_restanti <= 0:
            self.var_animale_dividi_restanti.set("Capi che restano nel gruppo attuale: 0 (non valido)")
            return

        self.var_animale_dividi_restanti.set(
            f"Capi che restano nel gruppo attuale: {format_number(capi_restanti, 0)}"
        )

    def _on_operazione_gruppo_change(self):
        mode = self.var_animale_operazione_gruppo.get().strip().lower()
        if mode == "unisci":
            if self.frame_operazione_dividi.winfo_manager() != "":
                self.frame_operazione_dividi.pack_forget()
            if self.frame_operazione_unisci.winfo_manager() == "":
                self.frame_operazione_unisci.pack(fill="x", padx=20, pady=(0, 8))
            self._aggiorna_preview_unione_animale()
        else:
            if self.frame_operazione_unisci.winfo_manager() != "":
                self.frame_operazione_unisci.pack_forget()
            if self.frame_operazione_dividi.winfo_manager() == "":
                self.frame_operazione_dividi.pack(fill="x", padx=20, pady=(0, 8))

    def _apri_calendario_data_unione_animale(self):
        date_text = self.var_animale_unisci_data.get().strip()
        if date_text:
            try:
                initial_date = datetime.strptime(date_text, "%d/%m/%Y").date()
            except ValueError:
                initial_date = datetime.now().date()
        else:
            initial_date = datetime.now().date()

        scelta = self.calendar_dialog_cls(self.root, initial_date).show()
        if scelta is not None:
            self.var_animale_unisci_data.set(scelta.strftime("%d/%m/%Y"))

    def _carica_candidati_unione_animale(self, entry_id: int):
        self._animale_unisci_candidati = {}
        self.var_animale_unisci_target.set("")
        self.var_animale_unisci_nome_nuovo_gruppo.set("")
        self.var_animale_unisci_data.set("")
        self.var_animale_unisci_totale.set("Totale capi nel gruppo unificato: -")

        try:
            entries = list_azienda_animali_entries(self.user_id)
        except sqlite3.Error:
            entries = []

        entry_corrente = None
        entry_id_value = int(entry_id or 0)
        for entry in entries:
            if int(entry.get("id", 0) or 0) == entry_id_value:
                entry_corrente = entry
                break

        if not entry_corrente:
            self.combo_animale_unisci_target.configure(values=())
            return

        tipo_corrente = (entry_corrente.get("tipo_animale") or "").strip().upper()
        finalita_corrente = (entry_corrente.get("finalita") or "").strip().upper()
        altro_corrente = (entry_corrente.get("altro_label") or "").strip()

        candidati = []
        for entry in entries:
            other_id = int(entry.get("id", 0) or 0)
            if other_id <= 0 or other_id == entry_id_value:
                continue
            if int(entry.get("capi", 0) or 0) <= 0:
                continue

            same_tipo = (entry.get("tipo_animale") or "").strip().upper() == tipo_corrente
            same_finalita = (entry.get("finalita") or "").strip().upper() == finalita_corrente
            same_altro = (entry.get("altro_label") or "").strip() == altro_corrente
            if same_tipo and same_finalita and same_altro:
                candidati.append(entry)

        candidati.sort(key=lambda item: ((item.get("group_name") or "").strip().lower(), int(item.get("id", 0) or 0)))

        valori_combo = []
        for entry in candidati:
            other_id = int(entry.get("id", 0) or 0)
            group_name = (entry.get("group_name") or "").strip() or f"Gruppo {other_id}"
            capi = int(entry.get("capi", 0) or 0)
            base_label = f"{group_name} ({format_number(capi, 0)} capi)"

            label = base_label
            if label in self._animale_unisci_candidati:
                label = f"{base_label} [ID {other_id}]"

            self._animale_unisci_candidati[label] = entry
            valori_combo.append(label)

        self.combo_animale_unisci_target.configure(values=tuple(valori_combo))
        if valori_combo:
            self.var_animale_unisci_target.set(valori_combo[0])
        else:
            self.var_animale_unisci_target.set("")
            self.var_animale_unisci_totale.set("Totale capi nel gruppo unificato: nessun gruppo compatibile")

    def _aggiorna_preview_unione_animale(self, *_args):
        scelta = self.var_animale_unisci_target.get().strip()
        if not scelta:
            if self._animale_unisci_candidati:
                self.var_animale_unisci_totale.set("Totale capi nel gruppo unificato: seleziona un gruppo")
            else:
                self.var_animale_unisci_totale.set("Totale capi nel gruppo unificato: nessun gruppo compatibile")
            return

        candidato = self._animale_unisci_candidati.get(scelta)
        if not candidato:
            self.var_animale_unisci_totale.set("Totale capi nel gruppo unificato: selezione non valida")
            return

        capi_corrente = int(getattr(self, "_animale_dividi_capi_totali", 0) or 0)
        capi_candidato = int(candidato.get("capi", 0) or 0)
        capi_totali = capi_corrente + capi_candidato
        self.var_animale_unisci_totale.set(
            f"Totale capi nel gruppo unificato: {format_number(capi_totali, 0)}"
        )

    def _chiudi_sezione_modifica_animale(self):
        self.var_animale_modifica_target.set("")
        self.var_animale_rimuovi_capi.set("")
        self.var_animale_modifica_capi.set("")
        self.var_animale_modifica_finalita.set(self.PURPOSE_OPTIONS[0])
        self.var_animale_modifica_riproduzione.set(False)
        self.var_animale_modifica_nome_gruppo.set("")
        self.var_animale_dividi_target.set("")
        self.var_animale_operazione_gruppo.set("dividi")
        self.var_animale_dividi_capi_primo.set("")
        self.var_animale_dividi_nome_nuovo_gruppo.set("")
        self.var_animale_dividi_restanti.set("Capi che restano nel gruppo attuale: -")
        self.var_animale_unisci_target.set("")
        self.var_animale_unisci_nome_nuovo_gruppo.set("")
        self.var_animale_unisci_data.set("")
        self.var_animale_unisci_totale.set("Totale capi nel gruppo unificato: -")
        self._animale_unisci_candidati = {}
        if hasattr(self, "combo_animale_unisci_target"):
            self.combo_animale_unisci_target.configure(values=())
        self._animale_dividi_capi_totali = 0
        if self.row_animale_modifica_destinazione.winfo_manager() != "":
            self.row_animale_modifica_destinazione.pack_forget()
        if self.row_animale_modifica_riproduzione.winfo_manager() != "":
            self.row_animale_modifica_riproduzione.pack_forget()
        self._on_operazione_gruppo_change()
        self._set_sezione_modifica_animale(False)

    def apri_sezione_modifica_animale(self):
        entry_id = self._get_selected_animale_entry_id()
        if entry_id is None:
            return

        selection = self.tree_animali_report.selection()
        values = self.tree_animali_report.item(selection[0], "values") if selection else ()
        categoria_label = values[0] if values else "categoria selezionata"
        destinazione_label = values[2] if len(values) > 2 else "-"
        riproduzione_label = values[3] if len(values) > 3 else "No"
        capi_label = values[4] if len(values) > 4 else ""

        self.var_animale_modifica_target.set(f"Selezionato: {categoria_label}")
        self.var_animale_rimuovi_capi.set("")
        self.var_animale_modifica_capi.set(self._normalizza_capi_da_testo(capi_label))
        self.var_animale_modifica_riproduzione.set((riproduzione_label or "").strip().lower() == "si")
        self.var_animale_modifica_nome_gruppo.set(categoria_label if categoria_label != "-" else "")

        capi_totali_text = self._normalizza_capi_da_testo(capi_label)
        self._animale_dividi_capi_totali = int(capi_totali_text) if capi_totali_text else 0
        self.var_animale_dividi_target.set(
            f"Gruppo selezionato: {categoria_label} ({format_number(self._animale_dividi_capi_totali, 0)} capi)"
        )
        self.var_animale_operazione_gruppo.set("dividi")
        self.var_animale_dividi_capi_primo.set("")
        self.var_animale_dividi_nome_nuovo_gruppo.set("")
        self._aggiorna_preview_divisione_animale()
        self._carica_candidati_unione_animale(entry_id)
        self._on_operazione_gruppo_change()

        if destinazione_label in self.PURPOSE_OPTIONS:
            self.var_animale_modifica_finalita.set(destinazione_label)
            if self.row_animale_modifica_destinazione.winfo_manager() == "":
                self.row_animale_modifica_destinazione.pack(
                    fill="x", padx=20, pady=4, before=self.row_animale_modifica_elimina
                )
        else:
            self.var_animale_modifica_finalita.set(self.PURPOSE_OPTIONS[0])
            if self.row_animale_modifica_destinazione.winfo_manager() != "":
                self.row_animale_modifica_destinazione.pack_forget()

        if self.row_animale_modifica_riproduzione.winfo_manager() == "":
            self.row_animale_modifica_riproduzione.pack(fill="x", padx=20, pady=4, before=self.row_animale_modifica_elimina)

        self._set_sezione_modifica_animale(True)

    def _on_tipo_animale_change(self, _event=None):
        tipo = self.var_animale_tipo.get()

        if tipo in ("Bovini", "Ovini"):
            if self.row_animale_finalita.winfo_manager() == "":
                self.row_animale_finalita.pack(fill="x", padx=20, pady=4, before=self.row_animale_capi)
            if self.var_animale_finalita.get() not in self.PURPOSE_OPTIONS:
                self.var_animale_finalita.set(self.PURPOSE_OPTIONS[0])
        else:
            if self.row_animale_finalita.winfo_manager() != "":
                self.row_animale_finalita.pack_forget()
            self.var_animale_finalita.set("")

        if tipo == "Altro":
            if self.row_animale_altro.winfo_manager() == "":
                self.row_animale_altro.pack(fill="x", padx=20, pady=4, before=self.row_animale_capi)
        else:
            if self.row_animale_altro.winfo_manager() != "":
                self.row_animale_altro.pack_forget()
            self.var_animale_altro.set("")

    def aggiungi_animale_da_form(self):
        group_name = self.var_animale_nome_gruppo.get().strip()
        if not group_name:
            messagebox.showerror("Errore", "Inserisci un nome gruppo.")
            return

        tipo_label = self.var_animale_tipo.get().strip()
        tipo_db = self.ANIMAL_TYPE_TO_DB.get(tipo_label, "")
        if not tipo_db:
            messagebox.showerror("Errore", "Seleziona un tipo animale valido.")
            return

        try:
            capi = self._parse_positive_int(self.var_animale_capi.get(), tipo_label)
        except ValueError as e:
            messagebox.showerror("Errore", str(e))
            return

        finalita_db = ""
        if tipo_label in ("Bovini", "Ovini"):
            finalita_label = self.var_animale_finalita.get().strip()
            finalita_db = self.PURPOSE_TO_DB.get(finalita_label, "")
            if not finalita_db:
                messagebox.showerror("Errore", "Seleziona 'Da Latte' o 'Da Carne'.")
                return

        altro_label = self.var_animale_altro.get().strip()
        if tipo_label == "Altro" and not altro_label:
            messagebox.showerror("Errore", "Specifica il tipo animale per la voce Altro.")
            return

        try:
            add_azienda_animale_entry(
                user_id=self.user_id,
                tipo_animale=tipo_db,
                capi=capi,
                finalita=finalita_db,
                altro_label=altro_label,
                group_name=group_name,
                riproduzione=bool(self.var_animale_riproduzione.get()),
            )
        except (sqlite3.Error, ValueError) as e:
            messagebox.showerror("Errore", str(e))
            return

        self.var_animali_stato.set("Animale registrato correttamente.")
        self.carica_report_animali_allevamento(mostra_errori=False)
        if hasattr(self, "aggiorna_categoria_zootecnia"):
            self.aggiorna_categoria_zootecnia()
        self._reset_form_aggiungi_animale()

    def _get_selected_animale_entry_id(self):
        selection = self.tree_animali_report.selection()
        if not selection:
            messagebox.showwarning("Selezione richiesta", "Seleziona una categoria dal report animali.")
            return None

        try:
            return int(selection[0])
        except (TypeError, ValueError):
            messagebox.showwarning("Selezione non valida", "Seleziona una categoria animale valida.")
            return None

    def rimuovi_capi_categoria_selezionata(self):
        entry_id = self._get_selected_animale_entry_id()
        if entry_id is None:
            return

        try:
            capi_da_rimuovere = self._parse_positive_int(self.var_animale_rimuovi_capi.get(), "rimozione")
        except ValueError as e:
            messagebox.showerror("Errore", str(e))
            return

        try:
            categoria_azzerata = remove_azienda_animale_capi(self.user_id, entry_id, capi_da_rimuovere)
        except (sqlite3.Error, ValueError) as e:
            messagebox.showerror("Errore", str(e))
            return

        self.var_animale_rimuovi_capi.set("")
        self.carica_report_animali_allevamento(mostra_errori=False)
        if categoria_azzerata:
            self.var_animali_stato.set("Rimozione completata: categoria azzerata e rimossa.")
        else:
            self.var_animali_stato.set(
                f"Rimozione completata: rimossi {format_number(capi_da_rimuovere, 0)} capi dalla categoria selezionata."
            )
        if hasattr(self, "aggiorna_categoria_zootecnia"):
            self.aggiorna_categoria_zootecnia()

    def rimuovi_categoria_animale_selezionata(self):
        entry_id = self._get_selected_animale_entry_id()
        if entry_id is None:
            return

        selection = self.tree_animali_report.selection()
        values = self.tree_animali_report.item(selection[0], "values") if selection else ()
        categoria_label = values[0] if values else "categoria selezionata"

        if not messagebox.askyesno(
            "Conferma rimozione",
            f"Vuoi rimuovere tutta la categoria '{categoria_label}'?",
        ):
            return

        try:
            delete_azienda_animale_entry(self.user_id, entry_id)
        except (sqlite3.Error, ValueError) as e:
            messagebox.showerror("Errore", str(e))
            return

        self.carica_report_animali_allevamento(mostra_errori=False)
        self.var_animali_stato.set(f"Categoria rimossa: {categoria_label}.")
        if hasattr(self, "aggiorna_categoria_zootecnia"):
            self.aggiorna_categoria_zootecnia()

    def modifica_capi_categoria_selezionata(self):
        entry_id = self._get_selected_animale_entry_id()
        if entry_id is None:
            return

        selection = self.tree_animali_report.selection()
        values = self.tree_animali_report.item(selection[0], "values") if selection else ()
        categoria_label = values[0] if values else "categoria selezionata"

        try:
            nuovo_capi = self._parse_non_negative_int(self.var_animale_modifica_capi.get(), "modifica")
        except ValueError as e:
            messagebox.showerror("Errore", str(e))
            return

        try:
            categoria_rimossa = set_azienda_animale_capi(self.user_id, entry_id, nuovo_capi)
        except (sqlite3.Error, ValueError) as e:
            messagebox.showerror("Errore", str(e))
            return

        self.var_animale_modifica_capi.set("")
        self.carica_report_animali_allevamento(mostra_errori=False)
        if categoria_rimossa:
            self.var_animali_stato.set(f"Categoria rimossa: {categoria_label} (nuovo valore 0).")
        else:
            self.var_animali_stato.set(
                f"Modifica completata: {categoria_label} ora ha {format_number(nuovo_capi, 0)} capi."
            )
        if hasattr(self, "aggiorna_categoria_zootecnia"):
            self.aggiorna_categoria_zootecnia()

    def modifica_nome_gruppo_categoria_selezionata(self):
        entry_id = self._get_selected_animale_entry_id()
        if entry_id is None:
            return

        selection = self.tree_animali_report.selection()
        values = self.tree_animali_report.item(selection[0], "values") if selection else ()
        categoria_label = values[0] if values else "categoria selezionata"
        nuovo_nome_gruppo = self.var_animale_modifica_nome_gruppo.get().strip()

        if not nuovo_nome_gruppo:
            messagebox.showerror("Errore", "Inserisci un nome gruppo valido.")
            return

        try:
            nome_aggiornato = set_azienda_animale_group_name(self.user_id, entry_id, nuovo_nome_gruppo)
        except (sqlite3.Error, ValueError) as e:
            messagebox.showerror("Errore", str(e))
            return

        self.carica_report_animali_allevamento(mostra_errori=False)
        if nome_aggiornato:
            self.var_animali_stato.set(f"Nome gruppo aggiornato: {categoria_label} -> {nuovo_nome_gruppo}.")
        else:
            self.var_animali_stato.set(f"Nome gruppo invariato: {nuovo_nome_gruppo}.")
        if hasattr(self, "aggiorna_categoria_zootecnia"):
            self.aggiorna_categoria_zootecnia()

    def dividi_gruppo_categoria_selezionata(self):
        entry_id = self._get_selected_animale_entry_id()
        if entry_id is None:
            return

        selection = self.tree_animali_report.selection()
        values = self.tree_animali_report.item(selection[0], "values") if selection else ()
        categoria_label = values[0] if values else "gruppo selezionato"

        try:
            capi_primo_gruppo = self._parse_positive_int(self.var_animale_dividi_capi_primo.get(), "divisione")
        except ValueError as e:
            messagebox.showerror("Errore", str(e))
            return

        capi_totali = int(getattr(self, "_animale_dividi_capi_totali", 0) or 0)
        if capi_primo_gruppo >= capi_totali:
            messagebox.showerror(
                "Errore",
                "Il primo gruppo deve avere meno capi del gruppo selezionato, in modo da lasciarne nel gruppo originale.",
            )
            return

        capi_restanti_preview = capi_totali - capi_primo_gruppo

        nuovo_nome_gruppo = self.var_animale_dividi_nome_nuovo_gruppo.get().strip()
        if not nuovo_nome_gruppo:
            messagebox.showerror("Errore", "Inserisci il nome del nuovo gruppo.")
            return

        conferma = messagebox.askyesno(
            "Conferma divisione",
            "Riepilogo divisione:\n"
            f"- Gruppo attuale: {categoria_label} ({format_number(capi_totali, 0)} capi)\n"
            f"- Nuovo gruppo: {nuovo_nome_gruppo} ({format_number(capi_primo_gruppo, 0)} capi)\n"
            f"- Capi restanti nel gruppo attuale: {format_number(capi_restanti_preview, 0)}\n\n"
            "Confermi l'operazione?",
        )
        if not conferma:
            return

        try:
            capi_restanti = split_azienda_animale_group(
                self.user_id,
                entry_id,
                capi_primo_gruppo,
                nuovo_nome_gruppo,
            )
        except (sqlite3.Error, ValueError) as e:
            messagebox.showerror("Errore", str(e))
            return

        self.carica_report_animali_allevamento(mostra_errori=False)
        self.var_animali_stato.set(
            "Divisione completata: "
            f"{categoria_label} ora ha {format_number(capi_restanti, 0)} capi, "
            f"nuovo gruppo '{nuovo_nome_gruppo}' con {format_number(capi_primo_gruppo, 0)} capi."
        )
        if hasattr(self, "aggiorna_categoria_zootecnia"):
            self.aggiorna_categoria_zootecnia()

    def unisci_gruppi_categoria_selezionata(self):
        entry_id = self._get_selected_animale_entry_id()
        if entry_id is None:
            return

        selection = self.tree_animali_report.selection()
        values = self.tree_animali_report.item(selection[0], "values") if selection else ()
        categoria_label = values[0] if values else "gruppo selezionato"

        scelta_candidato = self.var_animale_unisci_target.get().strip()
        candidato = self._animale_unisci_candidati.get(scelta_candidato)
        if not candidato:
            messagebox.showerror("Errore", "Seleziona un gruppo compatibile da unire.")
            return

        entry_id_secondario = int(candidato.get("id", 0) or 0)
        nome_secondario = (candidato.get("group_name") or "").strip() or scelta_candidato
        capi_corrente = int(getattr(self, "_animale_dividi_capi_totali", 0) or 0)
        capi_secondario = int(candidato.get("capi", 0) or 0)
        capi_totali_preview = capi_corrente + capi_secondario

        nuovo_nome_gruppo = self.var_animale_unisci_nome_nuovo_gruppo.get().strip()
        if not nuovo_nome_gruppo:
            messagebox.showerror("Errore", "Inserisci il nome del gruppo unificato.")
            return

        data_unione_text = self.var_animale_unisci_data.get().strip()
        data_unione_db = None
        data_unione_label = "Data odierna"
        if data_unione_text:
            try:
                data_unione_db = datetime.strptime(data_unione_text, "%d/%m/%Y").strftime("%Y-%m-%d")
                data_unione_label = data_unione_text
            except ValueError:
                messagebox.showerror("Errore", "Data unione non valida (Usa GG/MM/AAAA).")
                return

        conferma = messagebox.askyesno(
            "Conferma unione",
            "Riepilogo unione:\n"
            f"- Gruppo 1: {categoria_label} ({format_number(capi_corrente, 0)} capi)\n"
            f"- Gruppo 2: {nome_secondario} ({format_number(capi_secondario, 0)} capi)\n"
            f"- Nuovo nome gruppo: {nuovo_nome_gruppo}\n"
            f"- Data unione: {data_unione_label}\n"
            f"- Totale capi gruppo unificato: {format_number(capi_totali_preview, 0)}\n\n"
            "Confermi l'operazione?",
        )
        if not conferma:
            return

        try:
            capi_totali = merge_azienda_animale_groups(
                self.user_id,
                entry_id,
                entry_id_secondario,
                nuovo_nome_gruppo,
                merge_date=data_unione_db,
            )
        except (sqlite3.Error, ValueError) as e:
            messagebox.showerror("Errore", str(e))
            return

        data_effettiva = data_unione_text if data_unione_text else datetime.now().strftime("%d/%m/%Y")
        self.carica_report_animali_allevamento(mostra_errori=False)
        self.var_animali_stato.set(
            "Unione completata: "
            f"{categoria_label} + {nome_secondario} -> {nuovo_nome_gruppo} "
            f"({format_number(capi_totali, 0)} capi), data unione {data_effettiva}."
        )
        if hasattr(self, "aggiorna_categoria_zootecnia"):
            self.aggiorna_categoria_zootecnia()

    def modifica_destinazione_categoria_selezionata(self):
        entry_id = self._get_selected_animale_entry_id()
        if entry_id is None:
            return

        selection = self.tree_animali_report.selection()
        values = self.tree_animali_report.item(selection[0], "values") if selection else ()
        categoria_label = values[0] if values else "categoria selezionata"
        destinazione_label = self.var_animale_modifica_finalita.get().strip()
        finalita_db = self.PURPOSE_TO_DB.get(destinazione_label, "")

        if not finalita_db:
            messagebox.showerror("Errore", "Seleziona una destinazione valida.")
            return

        try:
            categoria_unificata = set_azienda_animale_finalita(self.user_id, entry_id, finalita_db)
        except (sqlite3.Error, ValueError) as e:
            messagebox.showerror("Errore", str(e))
            return

        self.carica_report_animali_allevamento(mostra_errori=False)
        if categoria_unificata:
            self.var_animali_stato.set(
                f"Destinazione aggiornata per {categoria_label}: categoria unificata con destinazione {destinazione_label}."
            )
        else:
            self.var_animali_stato.set(
                f"Destinazione aggiornata per {categoria_label}: {destinazione_label}."
            )
        if hasattr(self, "aggiorna_categoria_zootecnia"):
            self.aggiorna_categoria_zootecnia()

    def modifica_riproduzione_categoria_selezionata(self):
        entry_id = self._get_selected_animale_entry_id()
        if entry_id is None:
            return

        selection = self.tree_animali_report.selection()
        values = self.tree_animali_report.item(selection[0], "values") if selection else ()
        categoria_label = values[0] if values else "categoria selezionata"

        riproduzione_attiva = bool(self.var_animale_modifica_riproduzione.get())

        try:
            aggiornata = set_azienda_animale_riproduzione(self.user_id, entry_id, riproduzione_attiva)
        except (sqlite3.Error, ValueError) as e:
            messagebox.showerror("Errore", str(e))
            return

        self.carica_report_animali_allevamento(mostra_errori=False)
        if aggiornata:
            stato_label = "attivata" if riproduzione_attiva else "disattivata"
            self.var_animali_stato.set(
                f"Riproduzione {stato_label} per {categoria_label}."
            )
        else:
            self.var_animali_stato.set(
                f"Nessuna modifica: riproduzione invariata per {categoria_label}."
            )
        if hasattr(self, "aggiorna_categoria_zootecnia"):
            self.aggiorna_categoria_zootecnia()

    def _auto_compila_data_fine_azienda(self, *_args):
        if is_blank(self.var_azienda_data_fine.get()) and not is_blank(self.var_azienda_data_inizio.get()):
            self.var_azienda_data_fine.set(self.var_azienda_data_inizio.get())

    def imposta_periodo_report_azienda_default(self, mostra_errori=True):
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

        self.var_azienda_data_inizio.set(data_inizio)
        self.var_azienda_data_fine.set(data_fine)

    def genera_report_azienda(self, mostra_errori=True):
        if not hasattr(self, "tree_azienda_report") or not hasattr(self, "tree_azienda_categorie"):
            return

        use_filter = bool(self.var_azienda_report_usa_filtro.get())
        data_inizio_db = None
        data_fine_db = None
        params = [self.user_id]
        where_clause = "WHERE user_id=?"
        periodo_label = "Storico completo"

        if use_filter:
            try:
                data_inizio = datetime.strptime(self.var_azienda_data_inizio.get().strip(), "%d/%m/%Y")
                data_fine = datetime.strptime(self.var_azienda_data_fine.get().strip(), "%d/%m/%Y")
            except ValueError:
                if mostra_errori:
                    messagebox.showerror("Errore", "Formato date non valido (Usa GG/MM/AAAA).")
                return

            if data_inizio > data_fine:
                if mostra_errori:
                    messagebox.showerror("Errore", "La data INIZIO non puo essere successiva alla data FINE.")
                return

            data_inizio_db = data_inizio.strftime("%Y-%m-%d")
            data_fine_db = data_fine.strftime("%Y-%m-%d")
            where_clause += " AND data_op BETWEEN ? AND ?"
            params.extend([data_inizio_db, data_fine_db])
            periodo_label = f"{data_inizio.strftime('%d/%m/%Y')} - {data_fine.strftime('%d/%m/%Y')}"

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    f'''
                    SELECT
                        COUNT(id),
                        COALESCE(SUM(CASE WHEN tipo='ENTRATA' THEN importo ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN tipo='USCITA' THEN importo ELSE 0 END), 0),
                        COALESCE(SUM(iva_importo), 0)
                    FROM movimenti
                    {where_clause}
                ''',
                    tuple(params),
                )
                row = c.fetchone()

                c.execute(
                    f'''
                    SELECT
                        tipo,
                        COALESCE(NULLIF(TRIM(categoria), ''), '(Senza categoria)') AS categoria,
                        COALESCE(SUM(importo), 0) AS totale,
                        COUNT(id) AS qta
                    FROM movimenti
                    {where_clause}
                    GROUP BY tipo, categoria
                    ORDER BY tipo, totale DESC
                ''',
                    tuple(params),
                )
                righe_categoria = c.fetchall()
        except sqlite3.Error as e:
            if mostra_errori:
                messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        numero_movimenti = int((row[0] if row else 0) or 0)
        tot_entrate = float((row[1] if row else 0) or 0)
        tot_uscite_movimenti = float((row[2] if row else 0) or 0)
        tot_uscite_manutenzioni, numero_manutenzioni = self._calcola_totali_manutenzioni_azienda(
            data_da_db=data_inizio_db,
            data_a_db=data_fine_db,
            mostra_errori=mostra_errori,
        )
        tot_uscite = tot_uscite_movimenti + tot_uscite_manutenzioni
        tot_iva = float((row[3] if row else 0) or 0)
        saldo = tot_entrate - tot_uscite

        clear_treeview(self.tree_azienda_report)
        clear_treeview(self.tree_azienda_categorie)

        righe_riepilogo = [
            ("Modalita", "Periodo filtrato" if use_filter else "Storico completo"),
            ("Periodo", periodo_label),
            ("Movimenti totali", str(numero_movimenti)),
            ("Totale Entrate", format_eur(tot_entrate)),
            ("Uscite manutenzioni", format_eur(tot_uscite_manutenzioni)),
            ("Totale Uscite", format_eur(tot_uscite)),
            ("Totale IVA", format_eur(tot_iva)),
            ("Saldo Netto", format_eur(saldo)),
        ]

        self.tree_azienda_report.configure(height=max(1, len(righe_riepilogo)))

        for metrica, valore in righe_riepilogo:
            self.tree_azienda_report.insert("", "end", values=(metrica, valore))

        for tipo, categoria, totale, qta in righe_categoria:
            self.tree_azienda_categorie.insert(
                "",
                "end",
                values=(tipo, categoria, format_eur(float(totale)), format_number(int(qta), 0)),
            )

        if numero_manutenzioni > 0 or abs(tot_uscite_manutenzioni) > 1e-9:
            self.tree_azienda_categorie.insert(
                "",
                "end",
                values=(
                    "USCITA",
                    "Manutenzioni macchinari",
                    format_eur(tot_uscite_manutenzioni),
                    format_number(int(numero_manutenzioni), 0),
                ),
            )

    def carica_report_animali_allevamento(self, mostra_errori=True):
        try:
            entries = list_azienda_animali_entries(self.user_id)
        except sqlite3.Error as e:
            if mostra_errori:
                messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        clear_treeview(self.tree_animali_report)

        totale_capi = 0
        if not entries:
            self.tree_animali_report.insert("", "end", values=("Nessun gruppo registrato", "-", "-", "-", "0"))
        else:
            for entry in entries:
                entry_id = int(entry.get("id", 0) or 0)
                group_name_text = (entry.get("group_name") or "").strip() or "Gruppo senza nome"
                tipo_text = self._format_tipo_animale_report(entry.get("tipo_animale", ""), entry.get("altro_label", ""))
                finalita_text = self._format_finalita_report(entry.get("finalita", ""))
                riproduzione_text = self._format_riproduzione_report(entry.get("riproduzione", False))
                capi = int(entry.get("capi", 0) or 0)
                totale_capi += capi
                insert_kwargs = {
                    "values": (
                        group_name_text,
                        tipo_text,
                        finalita_text,
                        riproduzione_text,
                        format_number(capi, 0),
                    )
                }
                if entry_id > 0:
                    insert_kwargs["iid"] = str(entry_id)
                self.tree_animali_report.insert("", "end", **insert_kwargs)

        self.var_animali_report_totale.set(f"Totale capi registrati: {format_number(totale_capi, 0)}")
        if hasattr(self, "aggiorna_lista_gruppi_animali_movimento"):
            selected_ids = []
            if hasattr(self, "get_gruppi_animali_movimento_selezionati_ids"):
                selected_ids = self.get_gruppi_animali_movimento_selezionati_ids()
            self.aggiorna_lista_gruppi_animali_movimento(selected_entry_ids=selected_ids)
        if hasattr(self, "_carica_gruppi_filtro_azienda_movimenti"):
            self._carica_gruppi_filtro_azienda_movimenti(mostra_errori=False)
        if hasattr(self, "frame_modifica_animale"):
            self._chiudi_sezione_modifica_animale()
        self.var_animali_stato.set("Report animali aggiornato.")

    def _format_tipo_animale_report(self, tipo_animale, altro_label):
        tipo = (tipo_animale or "").strip().upper()
        if tipo == "ALTRO":
            extra = (altro_label or "").strip()
            return f"Altro ({extra})" if extra else "Altro"
        return tipo.title() if tipo else "-"

    def _format_finalita_report(self, finalita):
        value = (finalita or "").strip().upper()
        if value == "LATTE":
            return "Da Latte"
        if value == "CARNE":
            return "Da Carne"
        return "-"

    def _format_riproduzione_report(self, riproduzione):
        return "Si" if bool(riproduzione) else "No"

    def mostra_tab_azienda_animali(self):
        if hasattr(self, "azienda_notebook") and hasattr(self, "tab_azienda_dati"):
            self.azienda_notebook.select(self.tab_azienda_dati)
        if hasattr(self, "azienda_dati_notebook") and hasattr(self, "tab_azienda_animali"):
            self.azienda_dati_notebook.select(self.tab_azienda_animali)
        if hasattr(self, "carica_report_animali_allevamento"):
            self.carica_report_animali_allevamento(mostra_errori=False)
        if hasattr(self, "_aggiorna_scroll_animali"):
            self._aggiorna_scroll_animali(reset_to_top=True)
