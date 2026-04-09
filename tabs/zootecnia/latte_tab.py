import tkinter as tk
import sqlite3
from datetime import datetime
from tkinter import ttk, messagebox

from app_utils import clear_treeview, format_eur, format_number, is_blank, parse_decimal
from database import (
    get_conn,
    get_movimento_animali_entry_ids,
    get_produzione_latte_group_allocations,
    list_azienda_animali_entries,
    set_produzione_latte_group_allocations,
    set_movimento_animali_links,
    LITRI_PER_QUINTALE,
)


class LatteTabMixin:
    _UNITA_QTA_LATTE = ("Quintali", "Litri")
    _UNITA_PREZZO_LATTE = ("EUR/Litro", "EUR/Quintale")

    def _latte_adatta_altezza_tree(self, tree, righe_count: int, min_rows: int = 1):
        if tree is None:
            return

        rows = max(int(righe_count or 0), int(min_rows or 1))
        try:
            tree.configure(height=rows)
        except tk.TclError:
            pass

    def _latte_adatta_altezza_listbox(self, listbox, righe_count: int, min_rows: int = 1):
        if listbox is None:
            return

        rows = max(int(righe_count or 0), int(min_rows or 1))
        try:
            listbox.configure(height=rows)
        except tk.TclError:
            pass

    def setup_tab_latte(self):
        content = self.crea_container_scorribile(self.tab_latte, stretch_to_viewport=True)

        ttk.Label(content, text="Produzione Latte", font=("Arial", 14, "bold")).pack(pady=10)

        self.var_latte_data = tk.StringVar(value=datetime.now().strftime("%d/%m/%Y"))
        self.var_latte_quintali = tk.StringVar()
        self.var_latte_unita_quantita = tk.StringVar(value=self._UNITA_QTA_LATTE[0])
        self.var_latte_prezzo = tk.StringVar(value="0,00")
        self.var_latte_unita_prezzo = tk.StringVar(value=self._UNITA_PREZZO_LATTE[0])
        self.produzione_in_modifica_id = None
        self._latte_litri_quote_by_group = {}

        self.crea_campo_data(content, "Data produzione:", self.var_latte_data)

        row_qta = ttk.Frame(content)
        row_qta.pack(fill="x", padx=20, pady=5)
        ttk.Label(row_qta, text="Quantita prodotta:", width=20).pack(side="left")
        ttk.Entry(row_qta, textvariable=self.var_latte_quintali, width=16).pack(side="left", padx=(0, 8))
        combo_qta = ttk.Combobox(
            row_qta,
            textvariable=self.var_latte_unita_quantita,
            values=self._UNITA_QTA_LATTE,
            state="readonly",
            width=12,
        )
        combo_qta.pack(side="left")

        row_prezzo = ttk.Frame(content)
        row_prezzo.pack(fill="x", padx=20, pady=5)
        ttk.Label(row_prezzo, text="Prezzo:", width=20).pack(side="left")
        ttk.Entry(row_prezzo, textvariable=self.var_latte_prezzo, width=16).pack(side="left", padx=(0, 8))
        combo_prezzo = ttk.Combobox(
            row_prezzo,
            textvariable=self.var_latte_unita_prezzo,
            values=self._UNITA_PREZZO_LATTE,
            state="readonly",
            width=12,
        )
        combo_prezzo.pack(side="left")

        self.var_latte_gruppi_stato = tk.StringVar(value="")
        self._latte_gruppi_entry_ids = []
        self._latte_gruppi_entries_by_id = {}

        frame_gruppi = ttk.LabelFrame(content, text="Attribuzione gruppi animali (da latte)")
        frame_gruppi.pack(fill="x", padx=20, pady=(6, 6))

        corpo_gruppi = ttk.Frame(frame_gruppi)
        corpo_gruppi.pack(fill="x", padx=8, pady=8)

        frame_list_gruppi = ttk.Frame(corpo_gruppi)
        frame_list_gruppi.pack(side="left", fill="x", expand=True)

        self.listbox_latte_gruppi = tk.Listbox(
            frame_list_gruppi,
            selectmode=tk.EXTENDED,
            exportselection=False,
            height=1,
        )
        self.listbox_latte_gruppi.pack(side="left", fill="x", expand=True)
        self._latte_adatta_altezza_listbox(self.listbox_latte_gruppi, 1)

        self.listbox_latte_gruppi.bind("<<ListboxSelect>>", self._on_selezione_gruppi_latte)

        frame_gruppi_btn = ttk.Frame(corpo_gruppi)
        frame_gruppi_btn.pack(side="left", padx=(8, 0))
        ttk.Button(
            frame_gruppi_btn,
            text="Seleziona tutti",
            command=self.seleziona_tutti_gruppi_latte,
        ).pack(fill="x", pady=(0, 4))
        ttk.Button(
            frame_gruppi_btn,
            text="Deseleziona",
            command=self.deseleziona_gruppi_latte,
        ).pack(fill="x")
        self.btn_quote_litri_gruppi = ttk.Button(
            frame_gruppi_btn,
            text="Litri per gruppo...",
            command=self.apri_dialog_quote_litri_gruppi_latte,
        )
        self.btn_quote_litri_gruppi.pack(fill="x", pady=(4, 0))

        ttk.Label(frame_gruppi, textvariable=self.var_latte_gruppi_stato).pack(anchor="w", padx=8, pady=(0, 6))

        ttk.Label(content, text="Conversione automatica: 1 quintale = 100 litri").pack(pady=(0, 6))

        frame_actions = ttk.Frame(content)
        frame_actions.pack(pady=10)

        self.btn_salva_produzione = ttk.Button(frame_actions, text="Salva Produzione", command=self.salva_produzione_latte)
        self.btn_salva_produzione.pack(side="left", padx=6)
        self.btn_modifica_produzione = ttk.Button(
            frame_actions,
            text="Modifica selezionata",
            command=self.modifica_produzione_latte_selezionata,
        )
        self.btn_modifica_produzione.pack(side="left", padx=6)
        self.btn_annulla_modifica_produzione = ttk.Button(
            frame_actions,
            text="Annulla modifica",
            command=lambda: self.annulla_modifica_produzione_latte(reset_campi=True),
            state="disabled",
        )
        self.btn_annulla_modifica_produzione.pack(side="left", padx=6)
        ttk.Button(frame_actions, text="Ricarica Storico", command=self.carica_produzioni_latte).pack(side="left", padx=6)
        ttk.Button(frame_actions, text="Elimina selezionata", command=self.elimina_produzione_latte_selezionata).pack(side="left", padx=6)

        self.var_latte_modifica_stato = tk.StringVar(value="")
        ttk.Label(content, textvariable=self.var_latte_modifica_stato, foreground="#1f5f3f").pack(
            anchor="w", padx=20, pady=(0, 6)
        )

        self.var_nome_fattura_latte = tk.StringVar(value="Nessuna fattura caricata")
        frame_fattura = ttk.Frame(content)
        frame_fattura.pack(fill="x", padx=20, pady=(0, 8))

        ttk.Label(frame_fattura, text="Fattura latte:", width=20).pack(side="left")
        ttk.Label(frame_fattura, textvariable=self.var_nome_fattura_latte).pack(side="left", fill="x", expand=True)
        ttk.Button(frame_fattura, text="Carica Fattura", command=self.seleziona_fattura_latte).pack(side="right")
        ttk.Button(frame_fattura, text="Rimuovi", command=self.rimuovi_fattura_latte).pack(side="right", padx=(0, 5))

        frame_table = ttk.Frame(content)
        frame_table.pack(fill="x", padx=12, pady=8)

        cols = ("id", "data", "quintali", "prezzo")
        self.tree_produzione = ttk.Treeview(frame_table, columns=cols, show="headings", height=1)

        self.tree_produzione.heading("id", text="ID")
        self.tree_produzione.heading("data", text="Data")
        self.tree_produzione.heading("quintali", text="Quintali")
        self.tree_produzione.heading("prezzo", text="Prezzo / L")

        self.tree_produzione.column("id", width=60, anchor="center")
        self.tree_produzione.column("data", width=120, anchor="center")
        self.tree_produzione.column("quintali", width=140, anchor="e")
        self.tree_produzione.column("prezzo", width=140, anchor="e")

        self.tree_produzione.pack(side="left", fill="x", expand=True)
        self._latte_adatta_altezza_tree(self.tree_produzione, 1)

        self.aggiorna_lista_gruppi_latte()
        self.tree_produzione.bind("<<TreeviewSelect>>", self._on_selezione_produzione_latte)
        self.tree_produzione.bind("<Double-1>", lambda _event: self.modifica_produzione_latte_selezionata())
        self.tree_produzione.bind("<Delete>", lambda _event: self.elimina_produzione_latte_selezionata())

    def _label_gruppo_latte(self, entry):
        if hasattr(self, "_label_gruppo_animale_movimento"):
            return self._label_gruppo_animale_movimento(entry)

        entry_id = int(entry.get("id", 0) or 0)
        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
        tipo = (entry.get("tipo_animale") or "").strip().upper()
        altro = (entry.get("altro_label") or "").strip()

        if tipo == "ALTRO":
            tipo_label = f"Altro ({altro})" if altro else "Altro"
        else:
            tipo_label = tipo.title() if tipo else "Tipo"

        capi = int(entry.get("capi", 0) or 0)
        return f"{group_name} | {tipo_label} | {format_number(capi, 0)} capi"

    def _carica_gruppi_latte_attivi(self):
        try:
            entries = list_azienda_animali_entries(self.user_id)
        except sqlite3.Error:
            return []

        gruppi_attivi = []
        for entry in entries:
            entry_id = int(entry.get("id", 0) or 0)
            capi = int(entry.get("capi", 0) or 0)
            finalita = (entry.get("finalita") or "").strip().upper()

            if entry_id <= 0 or capi <= 0 or finalita != "LATTE":
                continue

            gruppi_attivi.append(entry)

        gruppi_attivi.sort(
            key=lambda item: (
                (item.get("group_name") or "").strip().lower(),
                int(item.get("id", 0) or 0),
            )
        )
        return gruppi_attivi

    def aggiorna_lista_gruppi_latte(self, selected_entry_ids=None):
        if not hasattr(self, "listbox_latte_gruppi"):
            return

        if selected_entry_ids is None:
            selected_entry_ids = self.get_gruppi_latte_selezionati_ids()

        selected_ids = set()
        for raw in selected_entry_ids or []:
            try:
                entry_id = int(raw)
            except (TypeError, ValueError):
                continue
            if entry_id > 0:
                selected_ids.add(entry_id)

        entries = self._carica_gruppi_latte_attivi()
        self._latte_gruppi_entry_ids = []
        self._latte_gruppi_entries_by_id = {}

        self.listbox_latte_gruppi.delete(0, tk.END)

        label_seen = set()
        listbox_idx = 0
        for entry in entries:
            entry_id = int(entry.get("id", 0) or 0)
            if entry_id <= 0:
                continue

            self._latte_gruppi_entries_by_id[entry_id] = entry
            self._latte_gruppi_entry_ids.append(entry_id)

            label = self._label_gruppo_latte(entry)
            if label in label_seen:
                label = f"{label} [ID {entry_id}]"
            label_seen.add(label)

            self.listbox_latte_gruppi.insert(tk.END, label)
            if entry_id in selected_ids:
                self.listbox_latte_gruppi.selection_set(listbox_idx)
            listbox_idx += 1

        self._latte_adatta_altezza_listbox(self.listbox_latte_gruppi, listbox_idx)

        self._aggiorna_stato_gruppi_latte()

    def _on_selezione_gruppi_latte(self, _event=None):
        self._pulisci_quote_litri_non_selezionate()
        self._aggiorna_stato_gruppi_latte()

    def _pulisci_quote_litri_non_selezionate(self):
        if not hasattr(self, "_latte_litri_quote_by_group"):
            self._latte_litri_quote_by_group = {}

        selected_ids = set(self.get_gruppi_latte_selezionati_ids())
        filtered = {}
        for entry_id, litri in self._latte_litri_quote_by_group.items():
            if entry_id not in selected_ids:
                continue
            if float(litri or 0) <= 0:
                continue
            filtered[int(entry_id)] = float(litri)
        self._latte_litri_quote_by_group = filtered

    def _litri_totali_correnti(self):
        quintali_text = self.var_latte_quintali.get().strip() if hasattr(self, "var_latte_quintali") else ""
        if is_blank(quintali_text):
            return None

        return self._parse_quantita_litri_latte(
            quintali_text,
            self.var_latte_unita_quantita.get() if hasattr(self, "var_latte_unita_quantita") else "Quintali",
        )

    def _normalizza_unita_quantita_latte(self, raw_value):
        value = (raw_value or "").strip().lower()
        if value.startswith("l"):
            return self._UNITA_QTA_LATTE[1]
        return self._UNITA_QTA_LATTE[0]

    def _normalizza_unita_prezzo_latte(self, raw_value):
        value = (raw_value or "").strip().lower()
        if "quint" in value or value.endswith("/q") or value.endswith("/quintale"):
            return self._UNITA_PREZZO_LATTE[1]
        return self._UNITA_PREZZO_LATTE[0]

    def _parse_quantita_litri_latte(self, raw_value, unita_value):
        quantita = parse_decimal(raw_value, allow_zero=False, allow_negative=False)
        if quantita is None or quantita <= 0:
            return None

        unita_norm = self._normalizza_unita_quantita_latte(unita_value)
        if unita_norm == self._UNITA_QTA_LATTE[1]:
            return float(quantita)
        return float(quantita) * LITRI_PER_QUINTALE

    def _parse_prezzo_litro_latte(self, raw_value, unita_value):
        prezzo = parse_decimal(raw_value, allow_zero=True, allow_negative=False)
        if prezzo is None or prezzo < 0:
            return None

        unita_norm = self._normalizza_unita_prezzo_latte(unita_value)
        if unita_norm == self._UNITA_PREZZO_LATTE[1]:
            return float(prezzo) / LITRI_PER_QUINTALE
        return float(prezzo)

    def _normalizza_quota_litri_input(self, raw_value):
        value = parse_decimal(raw_value, allow_zero=True, allow_negative=False)
        if value is None or value <= 0:
            return None
        return float(value)

    def _quote_litri_gruppi_per_salvataggio(self, gruppi_ids, litri_totali):
        if not hasattr(self, "_latte_litri_quote_by_group"):
            self._latte_litri_quote_by_group = {}

        if len(gruppi_ids) <= 1:
            self._latte_litri_quote_by_group = {}
            return {}

        quote = {}
        for entry_id in gruppi_ids:
            litri = self._latte_litri_quote_by_group.get(int(entry_id))
            if litri is None:
                continue
            litri_value = self._normalizza_quota_litri_input(litri)
            if litri_value is None:
                continue
            quote[int(entry_id)] = litri_value

        totale_esplicito = sum(quote.values())
        if totale_esplicito > float(litri_totali) + 1e-6:
            messagebox.showerror(
                "Errore",
                "La somma dei litri specificati per i gruppi supera i litri totali della produzione.",
            )
            return None

        self._latte_litri_quote_by_group = dict(quote)
        return quote

    def _label_breve_gruppo_latte(self, entry_id):
        entry = self._latte_gruppi_entries_by_id.get(int(entry_id), {})
        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
        capi = int(entry.get("capi", 0) or 0)
        return f"{group_name} ({format_number(capi, 0)} capi)"

    def apri_dialog_quote_litri_gruppi_latte(self):
        gruppi_ids = self.get_gruppi_latte_selezionati_ids()
        if len(gruppi_ids) <= 1:
            messagebox.showinfo(
                "Quote litri per gruppo",
                "Seleziona almeno due gruppi per specificare i litri prodotti da ciascun gruppo.",
            )
            return

        litri_totali = self._litri_totali_correnti()
        if litri_totali is None:
            messagebox.showerror(
                "Errore",
                "Inserisci prima la quantita prodotta (valore valido) per poter ripartire i litri per gruppo.",
            )
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Litri prodotti per gruppo")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text=(
                f"Litri totali produzione: {format_number(litri_totali, 2)} L\n"
                "Compila solo i gruppi con litri espliciti. I restanti litri saranno ripartiti in base ai capi."
            ),
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        entry_vars = {}
        for entry_id in gruppi_ids:
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=3)

            ttk.Label(row, text=self._label_breve_gruppo_latte(entry_id), width=42).pack(side="left")
            var_litri = tk.StringVar(value="")
            litri_existing = self._latte_litri_quote_by_group.get(int(entry_id))
            if litri_existing is not None and float(litri_existing or 0) > 0:
                var_litri.set(format_number(float(litri_existing), 2))

            ttk.Entry(row, textvariable=var_litri, width=16).pack(side="left", padx=(8, 6))
            ttk.Label(row, text="L").pack(side="left")
            entry_vars[int(entry_id)] = var_litri

        var_esito = tk.StringVar(value="")
        ttk.Label(frame, textvariable=var_esito, foreground="#1f5f3f", justify="left").pack(anchor="w", pady=(8, 0))

        def _aggiorna_esito_preview():
            totale_esplicito = 0.0
            for var in entry_vars.values():
                litri_val = self._normalizza_quota_litri_input(var.get())
                if litri_val is None:
                    continue
                totale_esplicito += litri_val

            residuo = max(litri_totali - totale_esplicito, 0.0)
            var_esito.set(
                f"Litri espliciti: {format_number(totale_esplicito, 2)} L | "
                f"Residuo automatico (per capi): {format_number(residuo, 2)} L"
            )

        def _auto_per_capi():
            for var in entry_vars.values():
                var.set("")
            _aggiorna_esito_preview()

        def _conferma():
            nuove_quote = {}
            for entry_id, var in entry_vars.items():
                litri_val = self._normalizza_quota_litri_input(var.get())
                if litri_val is None:
                    continue
                nuove_quote[entry_id] = litri_val

            totale_esplicito = sum(nuove_quote.values())
            if totale_esplicito > litri_totali + 1e-6:
                messagebox.showerror(
                    "Errore",
                    "La somma dei litri inseriti supera i litri totali della produzione.",
                    parent=dialog,
                )
                return

            self._latte_litri_quote_by_group = nuove_quote
            dialog.destroy()
            self._aggiorna_stato_gruppi_latte()

        frame_btn = ttk.Frame(frame)
        frame_btn.pack(fill="x", pady=(10, 0))
        ttk.Button(frame_btn, text="Auto per capi", command=_auto_per_capi).pack(side="left")
        ttk.Button(frame_btn, text="Conferma", command=_conferma).pack(side="right")
        ttk.Button(frame_btn, text="Annulla", command=dialog.destroy).pack(side="right", padx=(0, 6))

        for var in entry_vars.values():
            var.trace_add("write", lambda *_args: _aggiorna_esito_preview())
        _aggiorna_esito_preview()

    def _aggiorna_stato_gruppi_latte(self):
        if not hasattr(self, "var_latte_gruppi_stato") or not hasattr(self, "listbox_latte_gruppi"):
            return

        totale = int(self.listbox_latte_gruppi.size())
        if totale <= 0:
            if hasattr(self, "btn_quote_litri_gruppi"):
                self.btn_quote_litri_gruppi.config(state="disabled")
            self.var_latte_gruppi_stato.set(
                "Nessun gruppo da latte disponibile. Configurali in Azienda > Tipi Allevamento."
            )
            return

        selected_ids = self.get_gruppi_latte_selezionati_ids()
        if hasattr(self, "btn_quote_litri_gruppi"):
            self.btn_quote_litri_gruppi.config(state="normal" if len(selected_ids) > 1 else "disabled")

        if not selected_ids:
            self.var_latte_gruppi_stato.set(
                "Seleziona almeno un gruppo. Puoi selezionare piu gruppi solo se dello stesso tipo animale."
            )
            return

        selected_types = {
            (self._latte_gruppi_entries_by_id.get(entry_id, {}).get("tipo_animale") or "").strip().upper()
            for entry_id in selected_ids
        }
        selected_types.discard("")

        if len(selected_types) > 1:
            self.var_latte_gruppi_stato.set(
                "Selezione non valida: i gruppi scelti appartengono a tipi animali diversi."
            )
            return

        self._pulisci_quote_litri_non_selezionate()
        if len(selected_ids) > 1:
            quote = {
                entry_id: float(litri)
                for entry_id, litri in self._latte_litri_quote_by_group.items()
                if entry_id in set(selected_ids) and float(litri or 0) > 0
            }
            if quote:
                totale_quote = sum(quote.values())
                self.var_latte_gruppi_stato.set(
                    f"Gruppi selezionati: {len(selected_ids)} su {totale}. "
                    f"Quote litri esplicite: {len(quote)} gruppi ({format_number(totale_quote, 2)} L). "
                    "Litri restanti ripartiti automaticamente in base ai capi."
                )
            else:
                self.var_latte_gruppi_stato.set(
                    f"Gruppi selezionati: {len(selected_ids)} su {totale}. "
                    "Nessuna quota litri esplicita: ripartizione automatica in base ai capi."
                )
            return

        self._latte_litri_quote_by_group = {}
        self.var_latte_gruppi_stato.set(
            f"Gruppi selezionati: {len(selected_ids)} su {totale}."
        )

    def get_gruppi_latte_selezionati_ids(self):
        if not hasattr(self, "listbox_latte_gruppi"):
            return []

        selected_ids = []
        for idx in self.listbox_latte_gruppi.curselection():
            if 0 <= idx < len(self._latte_gruppi_entry_ids):
                entry_id = int(self._latte_gruppi_entry_ids[idx] or 0)
                if entry_id > 0:
                    selected_ids.append(entry_id)
        return selected_ids

    def imposta_gruppi_latte_selezionati(self, entry_ids):
        self.aggiorna_lista_gruppi_latte(selected_entry_ids=entry_ids)

    def deseleziona_gruppi_latte(self):
        if not hasattr(self, "listbox_latte_gruppi"):
            return

        self.listbox_latte_gruppi.selection_clear(0, tk.END)
        self._latte_litri_quote_by_group = {}
        self._aggiorna_stato_gruppi_latte()

    def seleziona_tutti_gruppi_latte(self):
        if not hasattr(self, "listbox_latte_gruppi"):
            return
        if not self._latte_gruppi_entry_ids:
            return

        self.listbox_latte_gruppi.selection_clear(0, tk.END)

        first_entry = self._latte_gruppi_entries_by_id.get(self._latte_gruppi_entry_ids[0], {})
        tipo_base = (first_entry.get("tipo_animale") or "").strip().upper()

        for idx, entry_id in enumerate(self._latte_gruppi_entry_ids):
            entry = self._latte_gruppi_entries_by_id.get(entry_id, {})
            tipo = (entry.get("tipo_animale") or "").strip().upper()
            if tipo and tipo == tipo_base:
                self.listbox_latte_gruppi.selection_set(idx)

        self._pulisci_quote_litri_non_selezionate()
        self._aggiorna_stato_gruppi_latte()

    def _valida_gruppi_latte_selezionati(self):
        selected_ids = []
        seen = set()
        for entry_id in self.get_gruppi_latte_selezionati_ids():
            if entry_id <= 0 or entry_id in seen:
                continue
            seen.add(entry_id)
            selected_ids.append(entry_id)

        if not selected_ids:
            messagebox.showerror("Errore", "Seleziona almeno un gruppo da latte.")
            return None

        entries = self._carica_gruppi_latte_attivi()
        entries_by_id = {int(entry.get("id", 0) or 0): entry for entry in entries}

        missing_ids = [entry_id for entry_id in selected_ids if entry_id not in entries_by_id]
        if missing_ids:
            messagebox.showerror(
                "Errore",
                "Uno o piu gruppi selezionati non sono piu disponibili. Aggiorna e riprova.",
            )
            self.aggiorna_lista_gruppi_latte()
            return None

        selected_types = {
            (entries_by_id[entry_id].get("tipo_animale") or "").strip().upper() for entry_id in selected_ids
        }
        selected_types.discard("")

        if len(selected_types) > 1:
            messagebox.showerror(
                "Errore",
                "Puoi attribuire la produzione a piu gruppi solo se appartengono allo stesso tipo animale.",
            )
            return None

        group_names = []
        for entry_id in selected_ids:
            entry = entries_by_id[entry_id]
            group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
            group_names.append(group_name)

        return {
            "entry_ids": selected_ids,
            "group_names": group_names,
        }

    def salva_produzione_latte(self):
        if is_blank(self.var_latte_data.get()):
            messagebox.showerror("Errore", "Inserisci la data di produzione.")
            return
        if is_blank(self.var_latte_quintali.get()):
            messagebox.showerror("Errore", "Inserisci la quantita prodotta.")
            return

        try:
            data_obj = datetime.strptime(self.var_latte_data.get().strip(), "%d/%m/%Y")
            data_db = data_obj.strftime("%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Errore", "Formato data non valido (Usa GG/MM/AAAA)")
            return

        litri_val = self._parse_quantita_litri_latte(
            self.var_latte_quintali.get(),
            self.var_latte_unita_quantita.get() if hasattr(self, "var_latte_unita_quantita") else "Quintali",
        )
        if litri_val is None or litri_val <= 0:
            messagebox.showerror("Errore", "Quantita non valida.")
            return

        quintali_val = litri_val / LITRI_PER_QUINTALE

        prezzo_text = self.var_latte_prezzo.get().strip()
        if is_blank(prezzo_text):
            prezzo_val = 0.0
        else:
            prezzo_val = self._parse_prezzo_litro_latte(
                prezzo_text,
                self.var_latte_unita_prezzo.get() if hasattr(self, "var_latte_unita_prezzo") else "EUR/Litro",
            )
            if prezzo_val is None:
                messagebox.showerror("Errore", "Prezzo non valido.")
                return

        gruppi_info = self._valida_gruppi_latte_selezionati()
        if gruppi_info is None:
            return

        gruppi_ids = gruppi_info["entry_ids"]
        gruppi_text = ", ".join(gruppi_info["group_names"])

        quote_litri_gruppi = self._quote_litri_gruppi_per_salvataggio(gruppi_ids, litri_val)
        if quote_litri_gruppi is None:
            return

        importo_entrata = litri_val * prezzo_val
        descrizione_mov = (
            f"Produzione latte: {format_number(quintali_val, 2)} q "
            f"({format_number(litri_val, 2)} L) x {format_eur(prezzo_val, 4)}/L"
            f" | Gruppi: {gruppi_text}"
        )

        parser_data = getattr(self, "pending_parser_latte_data", None)
        parser_values = None
        if parser_data is not None and hasattr(self, "_estrai_valori_parser_db"):
            parser_values = self._estrai_valori_parser_db(parser_data)

        importo_movimento = importo_entrata
        iva_importo_movimento = 0.0
        if isinstance(parser_data, dict):
            parser_vat = parse_decimal(
                parser_data.get("vat_total"),
                allow_zero=True,
                allow_negative=False,
            )
            parser_taxable = parse_decimal(
                parser_data.get("taxable_total"),
                allow_zero=True,
                allow_negative=False,
            )
            parser_total = parse_decimal(
                parser_data.get("total_amount"),
                allow_zero=False,
                allow_negative=False,
            )

            if parser_taxable is not None and parser_vat is not None:
                importo_movimento = max(parser_taxable, 0.0)
                iva_importo_movimento = max(parser_vat, 0.0)
            elif parser_total is not None and parser_vat is not None and parser_total >= parser_vat:
                iva_importo_movimento = max(parser_vat, 0.0)
                importo_movimento = max(parser_total - iva_importo_movimento, 0.0)
            elif parser_vat is not None and parser_vat > 0 and importo_entrata >= parser_vat:
                iva_importo_movimento = parser_vat
                importo_movimento = max(importo_entrata - iva_importo_movimento, 0.0)

        try:
            with get_conn() as conn:
                c = conn.cursor()
                movimento_id = None
                produzione_id = None

                def _insert_movimento_latte(target_cursor):
                    if parser_values is not None:
                        target_cursor.execute(
                            '''
                            INSERT INTO movimenti (
                                user_id, data_op, tipo, categoria, descrizione, importo, iva_importo,
                                parser_invoice_number, parser_invoice_date, parser_due_date,
                                parser_supplier_name, parser_supplier_vat,
                                parser_customer_name, parser_customer_vat,
                                parser_total_amount, parser_taxable_total, parser_vat_total,
                                parser_payment_terms, parser_warnings, parser_products, parser_fields_view
                            )
                            VALUES (?, ?, 'ENTRATA', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''',
                            (
                                self.user_id,
                                data_db,
                                "Latte",
                                descrizione_mov,
                                importo_movimento,
                                iva_importo_movimento,
                                *parser_values,
                            ),
                        )
                    else:
                        target_cursor.execute(
                            '''
                            INSERT INTO movimenti (user_id, data_op, tipo, categoria, descrizione, importo, iva_importo)
                            VALUES (?, ?, 'ENTRATA', ?, ?, ?, ?)
                        ''',
                            (
                                self.user_id,
                                data_db,
                                "Latte",
                                descrizione_mov,
                                importo_movimento,
                                iva_importo_movimento,
                            ),
                        )
                    return target_cursor.lastrowid

                if self.produzione_in_modifica_id is None:
                    movimento_id = _insert_movimento_latte(c)

                    c.execute(
                        '''
                        INSERT INTO produzione_latte (user_id, data_op, litri, prezzo_litro, movimento_id)
                        VALUES (?, ?, ?, ?, ?)
                    ''',
                        (self.user_id, data_db, litri_val, prezzo_val, movimento_id),
                    )
                    produzione_id = c.lastrowid
                    msg_ok = "Produzione latte salvata"
                else:
                    produzione_id = self.produzione_in_modifica_id

                    c.execute(
                        "SELECT movimento_id FROM produzione_latte WHERE id=? AND user_id=?",
                        (produzione_id, self.user_id),
                    )
                    row = c.fetchone()
                    if not row:
                        messagebox.showerror("Errore", "Produzione non trovata o non modificabile.")
                        return
                    movimento_id = row[0]

                    c.execute(
                        '''
                        UPDATE produzione_latte
                        SET data_op=?, litri=?, prezzo_litro=?
                        WHERE id=? AND user_id=?
                    ''',
                        (data_db, litri_val, prezzo_val, produzione_id, self.user_id),
                    )
                    if c.rowcount == 0:
                        messagebox.showerror("Errore", "Produzione non trovata o non modificabile.")
                        return

                    if movimento_id is not None:
                        if parser_values is None:
                            c.execute(
                                "SELECT importo, iva_importo FROM movimenti WHERE id=? AND user_id=?",
                                (movimento_id, self.user_id),
                            )
                            row_prev = c.fetchone()
                            if row_prev:
                                prev_importo = float((row_prev[0] or 0) if row_prev[0] is not None else 0)
                                prev_iva = float((row_prev[1] or 0) if row_prev[1] is not None else 0)
                                prev_totale = max(prev_importo + prev_iva, 0.0)
                                if prev_totale > 0 and prev_iva > 0 and importo_entrata > 0:
                                    iva_importo_movimento = importo_entrata * (prev_iva / prev_totale)
                                    importo_movimento = max(importo_entrata - iva_importo_movimento, 0.0)

                        if parser_values is not None:
                            c.execute(
                                '''
                                UPDATE movimenti
                                SET data_op=?, tipo='ENTRATA', categoria=?, descrizione=?, importo=?, iva_importo=?,
                                    parser_invoice_number=?, parser_invoice_date=?, parser_due_date=?,
                                    parser_supplier_name=?, parser_supplier_vat=?,
                                    parser_customer_name=?, parser_customer_vat=?,
                                    parser_total_amount=?, parser_taxable_total=?, parser_vat_total=?,
                                    parser_payment_terms=?, parser_warnings=?, parser_products=?, parser_fields_view=?
                                WHERE id=? AND user_id=?
                            ''',
                                (
                                    data_db,
                                    "Latte",
                                    descrizione_mov,
                                    importo_movimento,
                                    iva_importo_movimento,
                                    *parser_values,
                                    movimento_id,
                                    self.user_id,
                                ),
                            )
                        else:
                            c.execute(
                                '''
                                UPDATE movimenti
                                SET data_op=?, tipo='ENTRATA', categoria=?, descrizione=?, importo=?, iva_importo=?
                                WHERE id=? AND user_id=?
                            ''',
                                (
                                    data_db,
                                    "Latte",
                                    descrizione_mov,
                                    importo_movimento,
                                    iva_importo_movimento,
                                    movimento_id,
                                    self.user_id,
                                ),
                            )
                        if c.rowcount == 0:
                            movimento_id = None

                    if movimento_id is None:
                        movimento_id = _insert_movimento_latte(c)
                        c.execute(
                            "UPDATE produzione_latte SET movimento_id=? WHERE id=? AND user_id=?",
                            (movimento_id, produzione_id, self.user_id),
                        )

                    if movimento_id is not None:
                        set_movimento_animali_links(self.user_id, movimento_id, gruppi_ids, cursor=c)

                    msg_ok = "Produzione latte aggiornata"

                if self.produzione_in_modifica_id is None and movimento_id is not None:
                    set_movimento_animali_links(self.user_id, movimento_id, gruppi_ids, cursor=c)

                if self.pending_fattura_latte_id is not None and movimento_id is not None and produzione_id is not None:
                    c.execute(
                        '''
                        UPDATE fatture
                        SET movimento_id=?, produzione_id=?
                        WHERE id=? AND user_id=?
                    ''',
                        (movimento_id, produzione_id, self.pending_fattura_latte_id, self.user_id),
                    )

                if produzione_id is not None:
                    set_produzione_latte_group_allocations(
                        self.user_id,
                        produzione_id,
                        movimento_id,
                        quote_litri_gruppi,
                        cursor=c,
                    )
        except ValueError as e:
            messagebox.showerror("Errore", str(e))
            return
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        self.annulla_modifica_produzione_latte(reset_campi=True)
        self.rimuovi_fattura_latte()
        self.carica_produzioni_latte(mostra_errori=False)
        self.carica_movimenti()
        messagebox.showinfo(
            "Successo",
            f"{msg_ok} ({format_number(quintali_val, 2)} q)! Entrata automatica: {format_eur(importo_entrata)}",
        )

    def carica_produzioni_latte(self, mostra_errori=True):
        if not hasattr(self, "tree_produzione"):
            return

        clear_treeview(self.tree_produzione)

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    '''
                    SELECT id, data_op, litri, prezzo_litro, movimento_id
                    FROM produzione_latte
                    WHERE user_id=?
                    ORDER BY data_op DESC, id DESC
                ''',
                    (self.user_id,),
                )
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
                    format_number(quintali, 2),
                    format_number(float(prezzo_litro), 4),
                ),
            )

        self._latte_adatta_altezza_tree(self.tree_produzione, len(rows))

    def _on_selezione_produzione_latte(self, _event=None):
        if not hasattr(self, "var_latte_modifica_stato"):
            return

        if self.produzione_in_modifica_id is not None:
            return

        selezione = self.tree_produzione.selection() if hasattr(self, "tree_produzione") else []
        if not selezione:
            self.var_latte_modifica_stato.set("")
            return

        self.var_latte_modifica_stato.set(
            "Produzione selezionata. Premi 'Modifica selezionata' per aggiornare dati e quantita per gruppo."
        )

    def modifica_produzione_latte_selezionata(self):
        self.prepara_modifica_produzione_latte(mostra_errori=True)

    def prepara_modifica_produzione_latte(self, _event=None, mostra_errori=False):
        selezione = self.tree_produzione.selection()
        if not selezione:
            if mostra_errori:
                messagebox.showwarning("Attenzione", "Seleziona prima una produzione da modificare.")
            return

        valori = self.tree_produzione.item(selezione[0], "values")
        if not valori:
            if mostra_errori:
                messagebox.showerror("Errore", "Impossibile leggere la produzione selezionata.")
            return

        self.produzione_in_modifica_id = int(valori[0])
        self.var_latte_data.set(valori[1] or datetime.now().strftime("%d/%m/%Y"))
        self.var_latte_quintali.set(valori[2] or "")
        if hasattr(self, "var_latte_unita_quantita"):
            self.var_latte_unita_quantita.set(self._UNITA_QTA_LATTE[0])
        self.var_latte_prezzo.set(valori[3] or "0,00")
        if hasattr(self, "var_latte_unita_prezzo"):
            self.var_latte_unita_prezzo.set(self._UNITA_PREZZO_LATTE[0])

        linked_group_ids = []
        group_allocations = {}
        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT movimento_id FROM produzione_latte WHERE id=? AND user_id=?",
                    (self.produzione_in_modifica_id, self.user_id),
                )
                row = c.fetchone()

            movimento_id = int((row[0] if row else 0) or 0)
            if movimento_id > 0:
                linked_group_ids = get_movimento_animali_entry_ids(self.user_id, movimento_id)

            group_allocations = get_produzione_latte_group_allocations(self.user_id, self.produzione_in_modifica_id)
        except (sqlite3.Error, ValueError):
            linked_group_ids = []
            group_allocations = {}

        self.imposta_gruppi_latte_selezionati(linked_group_ids)
        self._latte_litri_quote_by_group = {
            int(entry_id): float(litri)
            for entry_id, litri in group_allocations.items()
            if int(entry_id) in set(linked_group_ids) and float(litri or 0) > 0
        }
        self._aggiorna_stato_gruppi_latte()

        if hasattr(self, "btn_salva_produzione"):
            self.btn_salva_produzione.config(text="Aggiorna Produzione")
        if hasattr(self, "btn_annulla_modifica_produzione"):
            self.btn_annulla_modifica_produzione.config(state="normal")
        if hasattr(self, "var_latte_modifica_stato"):
            quote_count = len(self._latte_litri_quote_by_group)
            self.var_latte_modifica_stato.set(
                f"Modifica produzione ID {self.produzione_in_modifica_id} attiva. "
                f"Quote gruppi caricate: {quote_count}."
            )

    def annulla_modifica_produzione_latte(self, reset_campi=False):
        self.produzione_in_modifica_id = None
        if hasattr(self, "btn_salva_produzione"):
            self.btn_salva_produzione.config(text="Salva Produzione")
        if hasattr(self, "btn_annulla_modifica_produzione"):
            self.btn_annulla_modifica_produzione.config(state="disabled")
        if hasattr(self, "var_latte_modifica_stato"):
            self.var_latte_modifica_stato.set("")
        if hasattr(self, "tree_produzione"):
            self.tree_produzione.selection_remove(*self.tree_produzione.selection())

        if reset_campi:
            self.var_latte_data.set(datetime.now().strftime("%d/%m/%Y"))
            self.var_latte_quintali.set("")
            if hasattr(self, "var_latte_unita_quantita"):
                self.var_latte_unita_quantita.set(self._UNITA_QTA_LATTE[0])
            self.var_latte_prezzo.set("0,00")
            if hasattr(self, "var_latte_unita_prezzo"):
                self.var_latte_unita_prezzo.set(self._UNITA_PREZZO_LATTE[0])
            self._latte_litri_quote_by_group = {}
            self.deseleziona_gruppi_latte()

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
        era_in_modifica = self.produzione_in_modifica_id == prod_id
        conferma = messagebox.askyesno(
            "Conferma eliminazione",
            f"Vuoi eliminare la produzione selezionata?\n\nData: {valori[1]} - Quintali: {valori[2]}",
        )
        if not conferma:
            return

        fatture_eliminate = 0
        percorsi_fatture = []
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
                    fatture_eliminate, percorsi_fatture = self.elimina_fatture_collegate_db(c, movimento_id)
                    c.execute("DELETE FROM movimenti WHERE id=? AND user_id=?", (movimento_id, self.user_id))
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        file_eliminati, file_non_trovati, file_errori = self.elimina_file_fatture(percorsi_fatture)

        self.carica_produzioni_latte(mostra_errori=False)
        self.carica_movimenti()
        if era_in_modifica:
            self.annulla_modifica_produzione_latte(reset_campi=True)

        msg_ok = "Produzione eliminata dal database!"
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
