import re
import sqlite3
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app_utils import clear_treeview, format_eur, format_number, is_blank, parse_decimal
from database import (
    get_conn,
    get_movimento_animali_entry_ids,
    list_azienda_animali_entries,
    remove_azienda_animale_capi,
    set_movimento_animali_links,
)


class CarneTabMixin:
    KG_PER_QUINTALE = 100.0
    _UNITA_QTA = ("Kg", "Quintali")
    _UNITA_PREZZO = ("EUR/Kg", "EUR/Quintale")

    def setup_tab_carne(self):
        content = self.crea_container_scorribile(self.tab_carne, stretch_to_viewport=True)

        ttk.Label(content, text="Produzione Carne", font=("Arial", 14, "bold")).pack(pady=10)

        self.var_carne_data = tk.StringVar(value=datetime.now().strftime("%d/%m/%Y"))
        self.var_carne_quantita = tk.StringVar()
        self.var_carne_unita_quantita = tk.StringVar(value=self._UNITA_QTA[0])
        self.var_carne_prezzo = tk.StringVar(value="0,00")
        self.var_carne_unita_prezzo = tk.StringVar(value=self._UNITA_PREZZO[0])
        self.var_nome_fattura_carne = tk.StringVar(value="Nessuna fattura caricata")
        self.var_carne_modifica_stato = tk.StringVar(value="")
        self.var_carne_rimuovi_capi = tk.BooleanVar(value=False)
        self.var_carne_capi_da_rimuovere = tk.StringVar(value="")
        self.var_carne_gruppi_stato = tk.StringVar(value="")
        self._carne_gruppi_entry_ids = []
        self._carne_gruppi_entries_by_id = {}

        if not hasattr(self, "produzione_carne_in_modifica_id"):
            self.produzione_carne_in_modifica_id = None
        if not hasattr(self, "pending_fattura_carne_id"):
            self.pending_fattura_carne_id = None
        if not hasattr(self, "pending_fattura_carne_path"):
            self.pending_fattura_carne_path = None
        if not hasattr(self, "pending_parser_carne_data"):
            self.pending_parser_carne_data = None

        self.crea_campo_data(content, "Data produzione:", self.var_carne_data)

        row_qta = ttk.Frame(content)
        row_qta.pack(fill="x", padx=20, pady=5)
        ttk.Label(row_qta, text="Quantita venduta:", width=20).pack(side="left")
        ttk.Entry(row_qta, textvariable=self.var_carne_quantita, width=16).pack(side="left", padx=(0, 8))
        combo_qta = ttk.Combobox(
            row_qta,
            textvariable=self.var_carne_unita_quantita,
            values=self._UNITA_QTA,
            state="readonly",
            width=12,
        )
        combo_qta.pack(side="left")

        row_prezzo = ttk.Frame(content)
        row_prezzo.pack(fill="x", padx=20, pady=5)
        ttk.Label(row_prezzo, text="Prezzo:", width=20).pack(side="left")
        ttk.Entry(row_prezzo, textvariable=self.var_carne_prezzo, width=16).pack(side="left", padx=(0, 8))
        combo_prezzo = ttk.Combobox(
            row_prezzo,
            textvariable=self.var_carne_unita_prezzo,
            values=self._UNITA_PREZZO,
            state="readonly",
            width=12,
        )
        combo_prezzo.pack(side="left")

        ttk.Label(
            content,
            text="Salvataggio automatico in Kg e EUR/Kg (conversione da Quintali automatica).",
        ).pack(anchor="w", padx=20, pady=(0, 6))

        frame_gruppi = ttk.LabelFrame(content, text="Gruppi da carne")
        frame_gruppi.pack(fill="x", padx=20, pady=(6, 6))

        corpo_gruppi = ttk.Frame(frame_gruppi)
        corpo_gruppi.pack(fill="x", padx=8, pady=8)

        frame_list_gruppi = ttk.Frame(corpo_gruppi)
        frame_list_gruppi.pack(side="left", fill="x", expand=True)

        self.listbox_carne_gruppi = tk.Listbox(
            frame_list_gruppi,
            selectmode=tk.EXTENDED,
            exportselection=False,
            height=5,
        )
        scroll_carne_gruppi = ttk.Scrollbar(frame_list_gruppi, orient="vertical", command=self.listbox_carne_gruppi.yview)
        self.listbox_carne_gruppi.configure(yscrollcommand=scroll_carne_gruppi.set)
        self.listbox_carne_gruppi.pack(side="left", fill="x", expand=True)
        scroll_carne_gruppi.pack(side="right", fill="y")
        self.listbox_carne_gruppi.bind("<<ListboxSelect>>", self._on_selezione_gruppi_carne)

        frame_gruppi_btn = ttk.Frame(corpo_gruppi)
        frame_gruppi_btn.pack(side="left", padx=(8, 0))
        ttk.Button(
            frame_gruppi_btn,
            text="Seleziona tutti",
            command=self.seleziona_tutti_gruppi_carne,
        ).pack(fill="x", pady=(0, 4))
        ttk.Button(
            frame_gruppi_btn,
            text="Deseleziona",
            command=self.deseleziona_gruppi_carne,
        ).pack(fill="x")

        frame_rimozione = ttk.Frame(frame_gruppi)
        frame_rimozione.pack(fill="x", padx=8, pady=(0, 4))

        self.chk_carne_rimuovi_capi = ttk.Checkbutton(
            frame_rimozione,
            text="Rimuovi capi dai gruppi selezionati durante il salvataggio",
            variable=self.var_carne_rimuovi_capi,
            command=self._on_toggle_rimozione_capi_carne,
        )
        self.chk_carne_rimuovi_capi.pack(side="left")

        ttk.Label(frame_rimozione, text="Capi da rimuovere:").pack(side="left", padx=(14, 4))
        self.entry_carne_capi_da_rimuovere = ttk.Entry(
            frame_rimozione,
            textvariable=self.var_carne_capi_da_rimuovere,
            width=10,
        )
        self.entry_carne_capi_da_rimuovere.pack(side="left")

        self.var_carne_capi_da_rimuovere.trace_add(
            "write",
            lambda *_args: self._aggiorna_stato_gruppi_carne(),
        )

        ttk.Label(frame_gruppi, textvariable=self.var_carne_gruppi_stato, wraplength=860, justify="left").pack(
            anchor="w",
            padx=8,
            pady=(0, 6),
        )

        frame_actions = ttk.Frame(content)
        frame_actions.pack(pady=10)

        self.btn_salva_produzione_carne = ttk.Button(
            frame_actions,
            text="Salva Produzione Carne",
            command=self.salva_produzione_carne,
        )
        self.btn_salva_produzione_carne.pack(side="left", padx=6)

        self.btn_modifica_produzione_carne = ttk.Button(
            frame_actions,
            text="Modifica selezionata",
            command=self.modifica_produzione_carne_selezionata,
        )
        self.btn_modifica_produzione_carne.pack(side="left", padx=6)

        self.btn_annulla_modifica_produzione_carne = ttk.Button(
            frame_actions,
            text="Annulla modifica",
            command=lambda: self.annulla_modifica_produzione_carne(reset_campi=True),
            state="disabled",
        )
        self.btn_annulla_modifica_produzione_carne.pack(side="left", padx=6)

        ttk.Button(
            frame_actions,
            text="Ricarica Storico",
            command=self.carica_produzioni_carne,
        ).pack(side="left", padx=6)

        ttk.Button(
            frame_actions,
            text="Elimina selezionata",
            command=self.elimina_produzione_carne_selezionata,
        ).pack(side="left", padx=6)

        ttk.Label(content, textvariable=self.var_carne_modifica_stato, foreground="#1f5f3f").pack(
            anchor="w", padx=20, pady=(0, 6)
        )

        frame_fattura = ttk.Frame(content)
        frame_fattura.pack(fill="x", padx=20, pady=(0, 8))
        ttk.Label(frame_fattura, text="Fattura carne:", width=20).pack(side="left")
        ttk.Label(frame_fattura, textvariable=self.var_nome_fattura_carne).pack(side="left", fill="x", expand=True)
        ttk.Button(frame_fattura, text="Carica Fattura", command=self.seleziona_fattura_carne).pack(side="right")
        ttk.Button(frame_fattura, text="Rimuovi", command=self.rimuovi_fattura_carne).pack(side="right", padx=(0, 5))

        frame_table = ttk.Frame(content)
        frame_table.pack(fill="both", expand=True, padx=12, pady=8)

        cols = ("id", "data", "kg", "prezzo_kg", "totale")
        self.tree_produzione_carne = ttk.Treeview(frame_table, columns=cols, show="headings", height=10)

        self.tree_produzione_carne.heading("id", text="ID")
        self.tree_produzione_carne.heading("data", text="Data")
        self.tree_produzione_carne.heading("kg", text="Kg")
        self.tree_produzione_carne.heading("prezzo_kg", text="Prezzo / Kg")
        self.tree_produzione_carne.heading("totale", text="Totale")

        self.tree_produzione_carne.column("id", width=60, anchor="center")
        self.tree_produzione_carne.column("data", width=120, anchor="center")
        self.tree_produzione_carne.column("kg", width=140, anchor="e")
        self.tree_produzione_carne.column("prezzo_kg", width=140, anchor="e")
        self.tree_produzione_carne.column("totale", width=140, anchor="e")

        scroll = ttk.Scrollbar(frame_table, orient="vertical", command=self.tree_produzione_carne.yview)
        self.tree_produzione_carne.configure(yscrollcommand=scroll.set)

        self.tree_produzione_carne.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tree_produzione_carne.bind("<<TreeviewSelect>>", self._on_selezione_produzione_carne)
        self.tree_produzione_carne.bind("<Double-1>", lambda _event: self.modifica_produzione_carne_selezionata())
        self.tree_produzione_carne.bind("<Delete>", lambda _event: self.elimina_produzione_carne_selezionata())

        self.aggiorna_lista_gruppi_carne()
        self._on_toggle_rimozione_capi_carne()
        self.carica_produzioni_carne(mostra_errori=False)

    def _normalizza_unita_quantita_carne(self, raw_value):
        value = (raw_value or "").strip().lower()
        if value.startswith("q"):
            return self._UNITA_QTA[1]
        return self._UNITA_QTA[0]

    def _normalizza_unita_prezzo_carne(self, raw_value):
        value = (raw_value or "").strip().lower()
        if "quint" in value or value.endswith("/q") or value.endswith("/quintale"):
            return self._UNITA_PREZZO[1]
        return self._UNITA_PREZZO[0]

    def _parse_quantita_kg_carne(self, raw_value, unita_value):
        quantita = parse_decimal(raw_value, allow_zero=False, allow_negative=False)
        if quantita is None or quantita <= 0:
            return None

        unita_norm = self._normalizza_unita_quantita_carne(unita_value)
        if unita_norm == self._UNITA_QTA[1]:
            return float(quantita) * self.KG_PER_QUINTALE
        return float(quantita)

    def _parse_prezzo_kg_carne(self, raw_value, unita_value):
        prezzo = parse_decimal(raw_value, allow_zero=True, allow_negative=False)
        if prezzo is None or prezzo < 0:
            return None

        unita_norm = self._normalizza_unita_prezzo_carne(unita_value)
        if unita_norm == self._UNITA_PREZZO[1]:
            return float(prezzo) / self.KG_PER_QUINTALE
        return float(prezzo)

    def _label_gruppo_carne(self, entry):
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
        return f"{group_name} | {tipo_label} | Da Carne | {format_number(capi, 0)} capi"

    def _carica_gruppi_carne_attivi(self):
        try:
            entries = list_azienda_animali_entries(self.user_id)
        except sqlite3.Error:
            return []

        gruppi_attivi = []
        for entry in entries:
            entry_id = int(entry.get("id", 0) or 0)
            capi = int(entry.get("capi", 0) or 0)
            finalita = (entry.get("finalita") or "").strip().upper()

            if entry_id <= 0 or capi <= 0 or finalita != "CARNE":
                continue

            gruppi_attivi.append(entry)

        gruppi_attivi.sort(
            key=lambda item: (
                (item.get("group_name") or "").strip().lower(),
                int(item.get("id", 0) or 0),
            )
        )
        return gruppi_attivi

    def aggiorna_lista_gruppi_carne(self, selected_entry_ids=None):
        if not hasattr(self, "listbox_carne_gruppi"):
            return

        if selected_entry_ids is None:
            selected_entry_ids = self.get_gruppi_carne_selezionati_ids()

        selected_ids = set()
        for raw in selected_entry_ids or []:
            try:
                entry_id = int(raw)
            except (TypeError, ValueError):
                continue
            if entry_id > 0:
                selected_ids.add(entry_id)

        entries = self._carica_gruppi_carne_attivi()
        self._carne_gruppi_entry_ids = []
        self._carne_gruppi_entries_by_id = {}

        self.listbox_carne_gruppi.delete(0, tk.END)

        labels_seen = set()
        listbox_idx = 0
        for entry in entries:
            entry_id = int(entry.get("id", 0) or 0)
            if entry_id <= 0:
                continue

            self._carne_gruppi_entries_by_id[entry_id] = entry
            self._carne_gruppi_entry_ids.append(entry_id)

            label = self._label_gruppo_carne(entry)
            if label in labels_seen:
                label = f"{label} [ID {entry_id}]"
            labels_seen.add(label)

            self.listbox_carne_gruppi.insert(tk.END, label)
            if entry_id in selected_ids:
                self.listbox_carne_gruppi.selection_set(listbox_idx)
            listbox_idx += 1

        self._aggiorna_stato_gruppi_carne()

    def _on_selezione_gruppi_carne(self, _event=None):
        self._aggiorna_stato_gruppi_carne()

    def get_gruppi_carne_selezionati_ids(self):
        if not hasattr(self, "listbox_carne_gruppi"):
            return []

        selected_ids = []
        for idx in self.listbox_carne_gruppi.curselection():
            if 0 <= idx < len(self._carne_gruppi_entry_ids):
                entry_id = int(self._carne_gruppi_entry_ids[idx] or 0)
                if entry_id > 0:
                    selected_ids.append(entry_id)
        return selected_ids

    def imposta_gruppi_carne_selezionati(self, entry_ids):
        self.aggiorna_lista_gruppi_carne(selected_entry_ids=entry_ids)

    def deseleziona_gruppi_carne(self):
        if not hasattr(self, "listbox_carne_gruppi"):
            return

        self.listbox_carne_gruppi.selection_clear(0, tk.END)
        self._aggiorna_stato_gruppi_carne()

    def seleziona_tutti_gruppi_carne(self):
        if not hasattr(self, "listbox_carne_gruppi"):
            return
        if not self._carne_gruppi_entry_ids:
            return

        self.listbox_carne_gruppi.selection_clear(0, tk.END)
        self.listbox_carne_gruppi.selection_set(0, tk.END)
        self._aggiorna_stato_gruppi_carne()

    def _parse_capi_da_rimuovere_carne(self, raw_value):
        value = parse_decimal(raw_value, allow_zero=False, allow_negative=False)
        if value is None or value <= 0:
            return None

        value_float = float(value)
        value_int = int(round(value_float))
        if abs(value_float - value_int) > 1e-9:
            return None

        if value_int <= 0:
            return None
        return value_int

    def _valida_gruppi_carne_selezionati(self):
        selected_ids = []
        seen = set()
        for entry_id in self.get_gruppi_carne_selezionati_ids():
            if entry_id <= 0 or entry_id in seen:
                continue
            seen.add(entry_id)
            selected_ids.append(entry_id)

        entries = self._carica_gruppi_carne_attivi()
        entries_by_id = {int(entry.get("id", 0) or 0): entry for entry in entries}

        missing_ids = [entry_id for entry_id in selected_ids if entry_id not in entries_by_id]
        if missing_ids:
            messagebox.showerror(
                "Errore",
                "Uno o piu gruppi da carne selezionati non sono piu disponibili. Aggiorna e riprova.",
            )
            self.aggiorna_lista_gruppi_carne()
            return None

        group_names = []
        for entry_id in selected_ids:
            entry = entries_by_id[entry_id]
            group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
            group_names.append(group_name)

        return {
            "entry_ids": selected_ids,
            "group_names": group_names,
            "entries_by_id": entries_by_id,
        }

    def _calcola_piano_rimozione_capi_carne(self, gruppi_ids, entries_by_id, capi_da_rimuovere):
        capi_target = int(capi_da_rimuovere or 0)
        if capi_target <= 0:
            return {}

        capi_by_group = {}
        for entry_id in gruppi_ids:
            entry = entries_by_id.get(int(entry_id), {})
            capi = int(entry.get("capi", 0) or 0)
            if capi <= 0:
                continue
            capi_by_group[int(entry_id)] = capi

        if not capi_by_group:
            raise ValueError("Non ci sono capi disponibili nei gruppi selezionati.")

        totale_capi_disponibili = sum(capi_by_group.values())
        if capi_target > totale_capi_disponibili:
            raise ValueError(
                "I capi da rimuovere superano i capi disponibili nei gruppi da carne selezionati."
            )

        if len(capi_by_group) == 1:
            only_id = next(iter(capi_by_group))
            return {only_id: capi_target}

        piano = {entry_id: 0 for entry_id in capi_by_group}
        metriche = []
        assegnati = 0

        for entry_id in gruppi_ids:
            if entry_id not in capi_by_group:
                continue

            capi_correnti = capi_by_group[entry_id]
            quota = (capi_target * capi_correnti) / totale_capi_disponibili
            base = min(int(quota), capi_correnti)
            piano[entry_id] = base
            assegnati += base

            metriche.append(
                {
                    "entry_id": entry_id,
                    "resto": quota - base,
                    "capi": capi_correnti,
                }
            )

        residuo = capi_target - assegnati
        metriche.sort(
            key=lambda item: (item["resto"], item["capi"], -item["entry_id"]),
            reverse=True,
        )

        while residuo > 0:
            assegnato = False
            for item in metriche:
                entry_id = int(item["entry_id"])
                if piano[entry_id] >= capi_by_group[entry_id]:
                    continue

                piano[entry_id] += 1
                residuo -= 1
                assegnato = True
                if residuo <= 0:
                    break

            if not assegnato:
                break

        if residuo > 0:
            raise ValueError("Impossibile distribuire la rimozione capi sui gruppi selezionati.")

        return {entry_id: qty for entry_id, qty in piano.items() if int(qty or 0) > 0}

    def _valida_rimozione_capi_carne(self, gruppi_info):
        attiva = bool(self.var_carne_rimuovi_capi.get()) and self.produzione_carne_in_modifica_id is None
        if not attiva:
            return {
                "attiva": False,
                "totale": 0,
                "piano": {},
            }

        gruppi_ids = list(gruppi_info.get("entry_ids") or [])
        if not gruppi_ids:
            messagebox.showerror(
                "Errore",
                "Per rimuovere capi seleziona almeno un gruppo con destinazione Da Carne.",
            )
            return None

        capi_da_rimuovere = self._parse_capi_da_rimuovere_carne(self.var_carne_capi_da_rimuovere.get())
        if capi_da_rimuovere is None:
            messagebox.showerror(
                "Errore",
                "Inserisci un numero intero valido di capi da rimuovere.",
            )
            return None

        try:
            piano_rimozione = self._calcola_piano_rimozione_capi_carne(
                gruppi_ids,
                gruppi_info.get("entries_by_id") or {},
                capi_da_rimuovere,
            )
        except ValueError as e:
            messagebox.showerror("Errore", str(e))
            return None

        return {
            "attiva": True,
            "totale": capi_da_rimuovere,
            "piano": piano_rimozione,
        }

    def _on_toggle_rimozione_capi_carne(self):
        in_modifica = self.produzione_carne_in_modifica_id is not None
        attiva = bool(self.var_carne_rimuovi_capi.get()) and not in_modifica

        if in_modifica and bool(self.var_carne_rimuovi_capi.get()):
            self.var_carne_rimuovi_capi.set(False)
            attiva = False

        if hasattr(self, "chk_carne_rimuovi_capi"):
            self.chk_carne_rimuovi_capi.config(state="disabled" if in_modifica else "normal")
        if hasattr(self, "entry_carne_capi_da_rimuovere"):
            self.entry_carne_capi_da_rimuovere.config(state="normal" if attiva else "disabled")

        if not attiva and hasattr(self, "var_carne_capi_da_rimuovere"):
            self.var_carne_capi_da_rimuovere.set("")

        self._aggiorna_stato_gruppi_carne()

    def _aggiorna_stato_gruppi_carne(self):
        if not hasattr(self, "var_carne_gruppi_stato") or not hasattr(self, "listbox_carne_gruppi"):
            return

        totale = int(self.listbox_carne_gruppi.size())
        if totale <= 0:
            self.var_carne_gruppi_stato.set(
                "Nessun gruppo da carne disponibile. Configurali in Azienda > Tipi Allevamento."
            )
            return

        selected_ids = self.get_gruppi_carne_selezionati_ids()
        msg = f"Gruppi selezionati: {len(selected_ids)} su {totale}."

        in_modifica = self.produzione_carne_in_modifica_id is not None
        if in_modifica:
            self.var_carne_gruppi_stato.set(msg + " In modifica la rimozione capi e disattivata.")
            return

        if bool(self.var_carne_rimuovi_capi.get()):
            capi_text = (self.var_carne_capi_da_rimuovere.get() or "").strip()
            if not selected_ids:
                msg += " Seleziona almeno un gruppo per poter rimuovere capi."
            elif not capi_text:
                msg += " Inserisci il numero capi da rimuovere."
            else:
                capi_value = self._parse_capi_da_rimuovere_carne(capi_text)
                if capi_value is None:
                    msg += " Numero capi non valido (usa un intero maggiore di zero)."
                else:
                    msg += f" Rimozione attiva: {format_number(capi_value, 0)} capi."

        self.var_carne_gruppi_stato.set(msg)

    def _on_selezione_produzione_carne(self, _event=None):
        if not hasattr(self, "var_carne_modifica_stato"):
            return

        if self.produzione_carne_in_modifica_id is not None:
            return

        selezione = self.tree_produzione_carne.selection() if hasattr(self, "tree_produzione_carne") else []
        if not selezione:
            self.var_carne_modifica_stato.set("")
            return

        self.var_carne_modifica_stato.set(
            "Produzione selezionata. Premi 'Modifica selezionata' per aggiornare i dati."
        )

    def modifica_produzione_carne_selezionata(self):
        self.prepara_modifica_produzione_carne(mostra_errori=True)

    def prepara_modifica_produzione_carne(self, _event=None, mostra_errori=False):
        if not hasattr(self, "tree_produzione_carne"):
            return

        selezione = self.tree_produzione_carne.selection()
        if not selezione:
            if mostra_errori:
                messagebox.showwarning("Attenzione", "Seleziona prima una produzione carne da modificare.")
            return

        valori = self.tree_produzione_carne.item(selezione[0], "values")
        if not valori:
            if mostra_errori:
                messagebox.showerror("Errore", "Impossibile leggere la produzione selezionata.")
            return

        self.produzione_carne_in_modifica_id = int(valori[0])
        self.var_carne_data.set(valori[1] or datetime.now().strftime("%d/%m/%Y"))
        self.var_carne_quantita.set(valori[2] or "")
        self.var_carne_unita_quantita.set(self._UNITA_QTA[0])
        self.var_carne_prezzo.set(valori[3] or "0,00")
        self.var_carne_unita_prezzo.set(self._UNITA_PREZZO[0])

        linked_group_ids = []
        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT movimento_id FROM produzione_carne WHERE id=? AND user_id=?",
                    (self.produzione_carne_in_modifica_id, self.user_id),
                )
                row = c.fetchone()

            movimento_id = int((row[0] if row else 0) or 0)
            if movimento_id > 0:
                linked_group_ids = get_movimento_animali_entry_ids(self.user_id, movimento_id)
        except (sqlite3.Error, ValueError):
            linked_group_ids = []

        self.imposta_gruppi_carne_selezionati(linked_group_ids)
        self.var_carne_rimuovi_capi.set(False)
        self.var_carne_capi_da_rimuovere.set("")
        self._on_toggle_rimozione_capi_carne()

        if hasattr(self, "btn_salva_produzione_carne"):
            self.btn_salva_produzione_carne.config(text="Aggiorna Produzione Carne")
        if hasattr(self, "btn_annulla_modifica_produzione_carne"):
            self.btn_annulla_modifica_produzione_carne.config(state="normal")
        if hasattr(self, "var_carne_modifica_stato"):
            self.var_carne_modifica_stato.set(
                f"Modifica produzione carne ID {self.produzione_carne_in_modifica_id} attiva."
            )

    def annulla_modifica_produzione_carne(self, reset_campi=False):
        self.produzione_carne_in_modifica_id = None
        if hasattr(self, "btn_salva_produzione_carne"):
            self.btn_salva_produzione_carne.config(text="Salva Produzione Carne")
        if hasattr(self, "btn_annulla_modifica_produzione_carne"):
            self.btn_annulla_modifica_produzione_carne.config(state="disabled")
        if hasattr(self, "var_carne_modifica_stato"):
            self.var_carne_modifica_stato.set("")
        if hasattr(self, "tree_produzione_carne"):
            self.tree_produzione_carne.selection_remove(*self.tree_produzione_carne.selection())

        self.var_carne_rimuovi_capi.set(False)
        self.var_carne_capi_da_rimuovere.set("")
        self._on_toggle_rimozione_capi_carne()

        if reset_campi:
            self.var_carne_data.set(datetime.now().strftime("%d/%m/%Y"))
            self.var_carne_quantita.set("")
            self.var_carne_unita_quantita.set(self._UNITA_QTA[0])
            self.var_carne_prezzo.set("0,00")
            self.var_carne_unita_prezzo.set(self._UNITA_PREZZO[0])
            self.deseleziona_gruppi_carne()

        self.aggiorna_lista_gruppi_carne()

    def salva_produzione_carne(self):
        if is_blank(self.var_carne_data.get()):
            messagebox.showerror("Errore", "Inserisci la data di produzione.")
            return
        if is_blank(self.var_carne_quantita.get()):
            messagebox.showerror("Errore", "Inserisci la quantita venduta.")
            return

        try:
            data_obj = datetime.strptime(self.var_carne_data.get().strip(), "%d/%m/%Y")
            data_db = data_obj.strftime("%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Errore", "Formato data non valido (Usa GG/MM/AAAA)")
            return

        kg_val = self._parse_quantita_kg_carne(
            self.var_carne_quantita.get().strip(),
            self.var_carne_unita_quantita.get(),
        )
        if kg_val is None or kg_val <= 0:
            messagebox.showerror("Errore", "Quantita non valida.")
            return

        prezzo_kg_val = self._parse_prezzo_kg_carne(
            self.var_carne_prezzo.get().strip(),
            self.var_carne_unita_prezzo.get(),
        )
        if prezzo_kg_val is None:
            messagebox.showerror("Errore", "Prezzo non valido.")
            return

        gruppi_info = self._valida_gruppi_carne_selezionati()
        if gruppi_info is None:
            return

        gruppi_ids = list(gruppi_info.get("entry_ids") or [])
        gruppi_text = ", ".join(gruppi_info.get("group_names") or [])

        rimozione_info = self._valida_rimozione_capi_carne(gruppi_info)
        if rimozione_info is None:
            return
        rimozione_attiva = bool(rimozione_info.get("attiva"))
        capi_da_rimuovere = int(rimozione_info.get("totale") or 0)

        quintali_val = kg_val / self.KG_PER_QUINTALE
        importo_entrata = kg_val * prezzo_kg_val
        descrizione_mov = (
            f"Produzione carne: {format_number(kg_val, 2)} Kg "
            f"({format_number(quintali_val, 2)} q) x {format_eur(prezzo_kg_val, 4)}/Kg"
        )
        if gruppi_ids:
            descrizione_mov += f" | Gruppi: {gruppi_text}"
        if rimozione_attiva and capi_da_rimuovere > 0:
            descrizione_mov += f" | Capi rimossi: {format_number(capi_da_rimuovere, 0)}"

        parser_data = getattr(self, "pending_parser_carne_data", None)
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

        rimozioni_effettuate = []
        try:
            with get_conn() as conn:
                c = conn.cursor()
                movimento_id = None
                produzione_id = None

                def _insert_movimento_carne(target_cursor):
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
                                "Carne",
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
                                "Carne",
                                descrizione_mov,
                                importo_movimento,
                                iva_importo_movimento,
                            ),
                        )
                    return target_cursor.lastrowid

                if self.produzione_carne_in_modifica_id is None:
                    movimento_id = _insert_movimento_carne(c)

                    c.execute(
                        '''
                        INSERT INTO produzione_carne (user_id, data_op, kg, prezzo_kg, movimento_id)
                        VALUES (?, ?, ?, ?, ?)
                    ''',
                        (self.user_id, data_db, kg_val, prezzo_kg_val, movimento_id),
                    )
                    produzione_id = c.lastrowid
                    msg_ok = "Produzione carne salvata"
                else:
                    produzione_id = int(self.produzione_carne_in_modifica_id)

                    c.execute(
                        "SELECT movimento_id FROM produzione_carne WHERE id=? AND user_id=?",
                        (produzione_id, self.user_id),
                    )
                    row = c.fetchone()
                    if not row:
                        messagebox.showerror("Errore", "Produzione carne non trovata o non modificabile.")
                        return
                    movimento_id = row[0]

                    c.execute(
                        '''
                        UPDATE produzione_carne
                        SET data_op=?, kg=?, prezzo_kg=?
                        WHERE id=? AND user_id=?
                    ''',
                        (data_db, kg_val, prezzo_kg_val, produzione_id, self.user_id),
                    )
                    if c.rowcount == 0:
                        messagebox.showerror("Errore", "Produzione carne non trovata o non modificabile.")
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
                                    "Carne",
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
                                    "Carne",
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
                        movimento_id = _insert_movimento_carne(c)
                        c.execute(
                            "UPDATE produzione_carne SET movimento_id=? WHERE id=? AND user_id=?",
                            (movimento_id, produzione_id, self.user_id),
                        )

                    msg_ok = "Produzione carne aggiornata"

                if movimento_id is not None:
                    set_movimento_animali_links(self.user_id, movimento_id, gruppi_ids, cursor=c)

                if self.produzione_carne_in_modifica_id is None and rimozione_attiva:
                    piano_rimozione = rimozione_info.get("piano") or {}
                    entries_by_id = gruppi_info.get("entries_by_id") or {}

                    for entry_id in gruppi_ids:
                        capi_rimossi = int(piano_rimozione.get(entry_id) or 0)
                        if capi_rimossi <= 0:
                            continue

                        remove_azienda_animale_capi(
                            self.user_id,
                            entry_id,
                            capi_rimossi,
                            cursor=c,
                        )

                        entry = entries_by_id.get(entry_id, {})
                        group_name = (entry.get("group_name") or "").strip() or f"Gruppo {entry_id}"
                        rimozioni_effettuate.append(
                            f"{group_name}: -{format_number(capi_rimossi, 0)} capi"
                        )

                if self.pending_fattura_carne_id is not None and movimento_id is not None:
                    c.execute(
                        '''
                        UPDATE fatture
                        SET movimento_id=?, produzione_id=NULL
                        WHERE id=? AND user_id=?
                    ''',
                        (movimento_id, self.pending_fattura_carne_id, self.user_id),
                    )
        except ValueError as e:
            messagebox.showerror("Errore", str(e))
            return
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        self.annulla_modifica_produzione_carne(reset_campi=True)
        self.rimuovi_fattura_carne()
        self.carica_produzioni_carne(mostra_errori=False)
        if hasattr(self, "carica_movimenti"):
            self.carica_movimenti()
        if hasattr(self, "aggiorna_categoria_zootecnia"):
            self.aggiorna_categoria_zootecnia()

        msg_successo = f"{msg_ok}! Entrata automatica: {format_eur(importo_entrata)}"
        if rimozioni_effettuate:
            msg_successo += "\nCapi rimossi dai gruppi da carne: " + ", ".join(rimozioni_effettuate)

        messagebox.showinfo(
            "Successo",
            msg_successo,
        )

    def carica_produzioni_carne(self, mostra_errori=True):
        if not hasattr(self, "tree_produzione_carne"):
            return

        clear_treeview(self.tree_produzione_carne)

        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    '''
                    SELECT id, data_op, kg, prezzo_kg, movimento_id
                    FROM produzione_carne
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

        for prod_id, data_op, kg, prezzo_kg, _movimento_id in rows:
            try:
                data_view = datetime.strptime(data_op, "%Y-%m-%d").strftime("%d/%m/%Y")
            except ValueError:
                data_view = data_op

            kg_value = float(kg or 0)
            prezzo_kg_value = float(prezzo_kg or 0)
            totale = kg_value * prezzo_kg_value

            self.tree_produzione_carne.insert(
                "",
                "end",
                values=(
                    prod_id,
                    data_view,
                    format_number(kg_value, 2),
                    format_number(prezzo_kg_value, 4),
                    format_number(totale, 2),
                ),
            )

    def elimina_produzione_carne_selezionata(self):
        if not hasattr(self, "tree_produzione_carne"):
            return

        selezione = self.tree_produzione_carne.selection()
        if not selezione:
            messagebox.showwarning("Attenzione", "Seleziona prima una riga di produzione carne da eliminare.")
            return

        valori = self.tree_produzione_carne.item(selezione[0], "values")
        if not valori:
            messagebox.showerror("Errore", "Impossibile leggere la produzione selezionata.")
            return

        prod_id = int(valori[0])
        era_in_modifica = self.produzione_carne_in_modifica_id == prod_id
        conferma = messagebox.askyesno(
            "Conferma eliminazione",
            f"Vuoi eliminare la produzione carne selezionata?\n\nData: {valori[1]} - Kg: {valori[2]}",
        )
        if not conferma:
            return

        fatture_eliminate = 0
        percorsi_fatture = []
        try:
            with get_conn() as conn:
                c = conn.cursor()

                c.execute("SELECT movimento_id FROM produzione_carne WHERE id=? AND user_id=?", (prod_id, self.user_id))
                row = c.fetchone()
                if not row:
                    messagebox.showerror("Errore", "Produzione carne non trovata o non eliminabile.")
                    return

                movimento_id = row[0]

                c.execute("DELETE FROM produzione_carne WHERE id=? AND user_id=?", (prod_id, self.user_id))
                if c.rowcount == 0:
                    messagebox.showerror("Errore", "Produzione carne non trovata o non eliminabile.")
                    return

                if movimento_id is not None:
                    if hasattr(self, "elimina_fatture_collegate_db"):
                        fatture_eliminate, percorsi_fatture = self.elimina_fatture_collegate_db(c, movimento_id)
                    c.execute("DELETE FROM movimenti WHERE id=? AND user_id=?", (movimento_id, self.user_id))
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        file_eliminati = 0
        file_non_trovati = 0
        file_errori = []
        if hasattr(self, "elimina_file_fatture"):
            file_eliminati, file_non_trovati, file_errori = self.elimina_file_fatture(percorsi_fatture)

        self.carica_produzioni_carne(mostra_errori=False)
        if hasattr(self, "carica_movimenti"):
            self.carica_movimenti()
        if hasattr(self, "aggiorna_categoria_zootecnia"):
            self.aggiorna_categoria_zootecnia()
        if era_in_modifica:
            self.annulla_modifica_produzione_carne(reset_campi=True)

        msg_ok = "Produzione carne eliminata dal database!"
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

    def seleziona_fattura_carne(self):
        file_path = filedialog.askopenfilename(title="Seleziona fattura PDF (Carne)", filetypes=[("PDF", "*.pdf")])
        if not file_path:
            return

        if not hasattr(self, "archivia_fattura_caricata"):
            messagebox.showerror("Caricamento fattura", "Funzione archiviazione fattura non disponibile.")
            return

        try:
            fattura_id, percorso_archiviato = self.archivia_fattura_caricata(file_path, "CARNE")
        except Exception as e:
            messagebox.showerror("Caricamento fattura", f"Impossibile salvare la fattura: {e}")
            return

        self.pending_fattura_carne_id = fattura_id
        self.pending_fattura_carne_path = percorso_archiviato
        self.pending_parser_carne_data = None
        if hasattr(self, "var_nome_fattura_carne"):
            self.var_nome_fattura_carne.set(Path(percorso_archiviato).name)

        try:
            dati_carne = self.analizza_fattura_carne_con_parser_fatture(percorso_archiviato, file_path)
        except Exception as e:
            messagebox.showwarning(
                "Analisi non completata",
                f"Fattura salvata correttamente, ma analisi automatica non disponibile: {e}",
            )
            return

        self._applica_dati_parser_al_form_carne(dati_carne)
        self.pending_parser_carne_data = dati_carne.get("parser_data")

        iva_label = format_number(dati_carne.get("iva_percent", 0.0), 2)
        messagebox.showinfo(
            "Importazione completata",
            "Valori produzione carne impostati da fattura:\n"
            f"- Quantita: {self.var_carne_quantita.get()} {self.var_carne_unita_quantita.get()}\n"
            f"- Prezzo: {self.var_carne_prezzo.get()} {self.var_carne_unita_prezzo.get()}\n"
            f"- Aliquota IVA applicata: {iva_label}%",
        )

    def rimuovi_fattura_carne(self):
        self.pending_fattura_carne_id = None
        self.pending_fattura_carne_path = None
        self.pending_parser_carne_data = None
        if hasattr(self, "var_nome_fattura_carne"):
            self.var_nome_fattura_carne.set("Nessuna fattura caricata")

    def _applica_dati_parser_al_form_carne(self, dati):
        if not isinstance(dati, dict):
            return

        data_value = dati.get("data")
        if data_value:
            self.var_carne_data.set(data_value)

        quantita_value = dati.get("quantita")
        if quantita_value:
            self.var_carne_quantita.set(quantita_value)

        unita_quantita = self._normalizza_unita_quantita_carne(dati.get("quantita_unita"))
        self.var_carne_unita_quantita.set(unita_quantita)

        prezzo_value = dati.get("prezzo")
        if prezzo_value:
            self.var_carne_prezzo.set(prezzo_value)

        unita_prezzo = self._normalizza_unita_prezzo_carne(dati.get("prezzo_unita"))
        self.var_carne_unita_prezzo.set(unita_prezzo)

    def analizza_fattura_carne_con_parser_fatture(self, pdf_path, file_path):
        if not hasattr(self, "_get_parser_fatture_function"):
            raise RuntimeError("Parser fatture non disponibile")

        parse_invoice_pdf = self._get_parser_fatture_function()
        risultato = parse_invoice_pdf(str(pdf_path))
        fields = getattr(risultato, "fields", {}) or {}
        parser_data = self._costruisci_dati_parser_movimento(risultato, fields)

        data_raw = self._estrai_valore_campo_parser(fields, "invoice_date")
        data_out = self._normalizza_data_fattura(data_raw) or datetime.now().strftime("%d/%m/%Y")

        line_items = getattr(risultato, "line_items", []) or []
        linea_carne = self._seleziona_linea_carne(line_items)
        if linea_carne is None:
            raise RuntimeError("Impossibile individuare riga prodotto carne con quantita e prezzo validi nella fattura.")

        quantita = self._valore_parser_to_float(getattr(linea_carne, "quantity", None), allow_zero=False)
        if quantita is None or quantita <= 0:
            raise RuntimeError("Quantita non trovata o non valida nella fattura.")

        prezzo_unita = self._valore_parser_to_float(getattr(linea_carne, "unit_price", None), allow_zero=False)
        if prezzo_unita is None:
            line_total = self._valore_parser_to_float(getattr(linea_carne, "line_total", None), allow_zero=False)
            if line_total is not None and line_total > 0:
                prezzo_unita = line_total / quantita

        if prezzo_unita is None or prezzo_unita <= 0:
            raise RuntimeError("Prezzo non trovato o non valido nella fattura.")

        descrizione = str(getattr(linea_carne, "description", "") or "").lower()
        quantita_unita = self._UNITA_QTA[1] if re.search(r"\bq\b|quint", descrizione) else self._UNITA_QTA[0]
        prezzo_unita_label = self._UNITA_PREZZO[1] if quantita_unita == self._UNITA_QTA[1] else self._UNITA_PREZZO[0]

        iva_percent = self._valore_parser_to_float(getattr(linea_carne, "vat_rate", None), allow_zero=True)
        if iva_percent is None or iva_percent < 0:
            iva_percent = self._calcola_aliquota_iva_parser(fields, risultato)
        if iva_percent is None or iva_percent < 0:
            iva_percent = 0.0

        prezzo_unita_lordo = prezzo_unita * (1.0 + (iva_percent / 100.0))

        return {
            "data": data_out,
            "quantita": format_number(quantita, 2),
            "quantita_unita": quantita_unita,
            "prezzo": format_number(prezzo_unita_lordo, 4),
            "prezzo_unita": prezzo_unita_label,
            "iva_percent": iva_percent,
            "file": str(Path(file_path).name),
            "parser_data": parser_data,
        }

    def _seleziona_linea_carne(self, line_items):
        candidati = []
        parole_carne = (
            "carne",
            "bov",
            "vitell",
            "manzo",
            "suin",
            "maial",
            "ovin",
            "agnell",
            "caprin",
            "pollo",
            "tacchin",
        )

        for item in line_items:
            quantita = self._valore_parser_to_float(getattr(item, "quantity", None), allow_zero=False)
            if quantita is None or quantita <= 0:
                continue

            prezzo_unita = self._valore_parser_to_float(getattr(item, "unit_price", None), allow_zero=False)
            line_total = self._valore_parser_to_float(getattr(item, "line_total", None), allow_zero=False)
            if prezzo_unita is None and line_total is None:
                continue

            descrizione = str(getattr(item, "description", "") or "").strip().lower()
            score = 0
            if any(parola in descrizione for parola in parole_carne):
                score += 4
            if "latte" in descrizione:
                score -= 3
            if re.search(r"\bq\b|quint", descrizione):
                score += 1

            candidati.append((score, line_total or 0.0, item))

        if not candidati:
            return None

        candidati.sort(key=lambda data: (data[0], data[1]), reverse=True)
        return candidati[0][2]
