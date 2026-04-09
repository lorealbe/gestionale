import re
import sqlite3
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from app_utils import clear_treeview, format_eur, format_number, parse_decimal
from database import (
    add_azienda_animale_entry,
    add_azienda_animali_storico_entry,
    delete_azienda_animali_storico_entry,
    get_conn,
    list_azienda_animali_entries,
    list_azienda_animali_storico_entries,
    remove_azienda_animale_capi,
)
from services.latte_group_metrics import (
    calcola_metriche_latte_da_totali as svc_calcola_metriche_latte_da_totali,
    costruisci_quote_litri_produzioni as svc_costruisci_quote_litri_produzioni,
    ripartizione_litri_produzione_per_gruppo as svc_ripartizione_litri_produzione_per_gruppo,
)


class ZootecniaTabMixin:
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
        self.btn_zootecnia_riporta_nascita = ttk.Button(
            frame_btn,
            text="Riporta nascita",
            command=self.apri_popup_riporta_nascita,
            state="disabled",
        )
        self.btn_zootecnia_riporta_nascita.pack(side="left", padx=(0, 6))
        ttk.Button(frame_btn, text="Aggiorna", command=self.aggiorna_categoria_zootecnia).pack(side="left")

        self.frame_zootecnia_pagine = ttk.Frame(container)
        self.frame_zootecnia_pagine.pack(fill="both", expand=True)

        self.zootecnia_notebook = ttk.Notebook(self.frame_zootecnia_pagine)
        self.zootecnia_notebook.pack(fill="both", expand=True)
        self.tab_zootecnia_latte = None
        self.tab_zootecnia_carne = None
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

    def _zootecnia_label_evento_storico(self, event_type: str) -> str:
        evento = (event_type or "").strip().upper()
        mapping = {
            "AGGIUNTA_CAPI": "Aggiunta capi",
            "RIMOZIONE_CAPI": "Rimozione capi",
            "DIVISIONE_GRUPPO": "Divisione gruppo",
            "UNIONE_GRUPPI": "Unione gruppi",
            "CAMBIO_DESTINAZIONE": "Cambio destinazione",
            "CAMBIO_RIPRODUZIONE": "Cambio riproduzione",
            "RIPORTA_NASCITA": "Riporta nascita",
        }
        if evento in mapping:
            return mapping[evento]
        return evento.replace("_", " ").title() if evento else "Evento"

    def _zootecnia_data_evento_storico(self, event_time: str) -> str:
        testo = (event_time or "").strip()
        if not testo:
            return "-"

        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(testo, fmt).strftime("%d/%m/%Y %H:%M")
            except ValueError:
                continue

        return testo

    def _zootecnia_adatta_altezza_tree(self, tree, righe_count: int, min_rows: int = 1):
        if tree is None:
            return

        rows = max(int(righe_count or 0), int(min_rows or 1))
        try:
            tree.configure(height=rows)
        except tk.TclError:
            pass

    def _carica_storico_gruppi_zootecnia(self, mostra_errori=False):
        if not hasattr(self, "tree_zootecnia_storico_gruppi"):
            return

        clear_treeview(self.tree_zootecnia_storico_gruppi)
        self._zootecnia_storico_item_to_entry_id = {}

        try:
            entries = list_azienda_animali_storico_entries(self.user_id, limit=300)
        except sqlite3.Error:
            entries = []

        if not entries:
            self.tree_zootecnia_storico_gruppi.insert(
                "",
                "end",
                values=("-", "-", "Nessun evento registrato", "-", "-", "-"),
            )
            self._zootecnia_adatta_altezza_tree(self.tree_zootecnia_storico_gruppi, 1)
            return

        for entry in entries:
            gruppo_nome = (entry.get("gruppo_nome") or "").strip() or "Gruppo"
            tipo = (entry.get("tipo_animale") or "").strip().upper()
            finalita = (entry.get("finalita") or "").strip().upper()

            gruppo_label = gruppo_nome
            dettagli_tipo = []
            if tipo:
                dettagli_tipo.append(tipo.title())
            if finalita == "LATTE":
                dettagli_tipo.append("Da Latte")
            elif finalita == "CARNE":
                dettagli_tipo.append("Da Carne")
            if dettagli_tipo:
                gruppo_label = f"{gruppo_label} ({', '.join(dettagli_tipo)})"

            delta = int(entry.get("capi_variazione") or 0)
            delta_label = f"+{delta}" if delta > 0 else str(delta)

            capi_dopo = entry.get("capi_dopo")
            capi_dopo_label = "-" if capi_dopo is None else format_number(int(capi_dopo), 0)

            correlato = (entry.get("gruppo_correlato_nome") or "").strip()
            note = (entry.get("note") or "").strip()
            dettaglio_parts = []
            if correlato:
                dettaglio_parts.append(f"Correlato: {correlato}")
            if note:
                dettaglio_parts.append(note)
            dettaglio = " | ".join(dettaglio_parts) if dettaglio_parts else "-"

            item_id = self.tree_zootecnia_storico_gruppi.insert(
                "",
                "end",
                values=(
                    self._zootecnia_data_evento_storico(entry.get("event_time") or ""),
                    self._zootecnia_label_evento_storico(entry.get("event_type") or ""),
                    gruppo_label,
                    delta_label,
                    capi_dopo_label,
                    dettaglio,
                ),
            )

            entry_id = int(entry.get("id") or 0)
            if entry_id > 0:
                self._zootecnia_storico_item_to_entry_id[item_id] = entry_id

        self._zootecnia_adatta_altezza_tree(self.tree_zootecnia_storico_gruppi, len(entries))

    def elimina_operazioni_storico_gruppi_selezionate(self):
        if not hasattr(self, "tree_zootecnia_storico_gruppi"):
            return

        selected_items = list(self.tree_zootecnia_storico_gruppi.selection())
        if not selected_items:
            messagebox.showwarning("Attenzione", "Seleziona prima almeno un'operazione dallo storico.")
            return

        item_to_entry = getattr(self, "_zootecnia_storico_item_to_entry_id", {}) or {}

        selected_entry_ids = []
        selected_preview = []
        seen = set()
        for item_id in selected_items:
            entry_id = int(item_to_entry.get(item_id) or 0)
            if entry_id <= 0 or entry_id in seen:
                continue

            seen.add(entry_id)
            selected_entry_ids.append(entry_id)

            values = self.tree_zootecnia_storico_gruppi.item(item_id, "values") or ()
            data_text = str(values[0] or "-") if len(values) > 0 else "-"
            evento_text = str(values[1] or "-") if len(values) > 1 else "-"
            gruppo_text = str(values[2] or "-") if len(values) > 2 else "-"
            selected_preview.append(f"{data_text} | {evento_text} | {gruppo_text}")

        if not selected_entry_ids:
            messagebox.showwarning("Attenzione", "La selezione corrente non contiene operazioni eliminabili.")
            return

        if len(selected_entry_ids) == 1:
            conferma_msg = (
                "Vuoi eliminare l'operazione selezionata dallo storico gruppi?\n\n"
                f"{selected_preview[0]}"
            )
        else:
            preview_text = "\n".join(selected_preview[:3])
            extra = len(selected_preview) - 3
            if extra > 0:
                preview_text += f"\n... e altre {extra} operazioni"

            conferma_msg = (
                f"Vuoi eliminare {len(selected_entry_ids)} operazioni dallo storico gruppi?\n\n"
                f"{preview_text}"
            )

        conferma = messagebox.askyesno("Conferma eliminazione", conferma_msg)
        if not conferma:
            return

        eliminati = 0
        try:
            for entry_id in selected_entry_ids:
                if delete_azienda_animali_storico_entry(self.user_id, entry_id):
                    eliminati += 1
        except ValueError as e:
            messagebox.showerror("Errore", str(e))
            return
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        self._carica_storico_gruppi_zootecnia(mostra_errori=False)

        if eliminati <= 0:
            messagebox.showwarning(
                "Nessuna operazione eliminata",
                "Le operazioni selezionate potrebbero essere gia state eliminate.",
            )
            return

        if eliminati == 1:
            msg = "Operazione eliminata dallo storico gruppi."
        else:
            msg = f"Operazioni eliminate dallo storico gruppi: {eliminati}."
        messagebox.showinfo("Eliminazione completata", msg)

    def _is_entry_latte_attiva(self, entry):
        finalita = (entry.get("finalita") or "").strip().upper()
        capi = int(entry.get("capi") or 0)
        return finalita == "LATTE" and capi > 0

    def _is_entry_carne_attiva(self, entry):
        finalita = (entry.get("finalita") or "").strip().upper()
        capi = int(entry.get("capi") or 0)
        return finalita == "CARNE" and capi > 0

    def _is_entry_riproduzione_attiva(self, entry):
        capi = int(entry.get("capi") or 0)
        return bool(entry.get("riproduzione")) and capi > 0

    def _zootecnia_parse_positive_int(self, raw_value, label: str) -> int:
        testo = str(raw_value or "").strip()
        if not testo:
            raise ValueError(f"Inserisci un valore per '{label}'.")

        try:
            value = int(testo)
        except ValueError:
            raise ValueError(f"Valore non valido per '{label}'.")

        if value <= 0:
            raise ValueError(f"Il valore per '{label}' deve essere maggiore di zero.")
        return value

    def _zootecnia_finalita_label_to_db(self, finalita_label: str) -> str:
        label = (finalita_label or "").strip()
        if label == "Da Latte":
            return "LATTE"
        if label == "Da Carne":
            return "CARNE"
        return ""

    def _zootecnia_label_gruppo_riporta_nascita(self, entry: dict) -> str:
        group_name = (entry.get("group_name") or "").strip() or "Gruppo"
        tipo = self._zootecnia_label_tipo(entry)
        destinazione = self._zootecnia_label_destinazione(entry)
        riproduzione = "Si" if bool(entry.get("riproduzione")) else "No"
        capi = format_number(int(entry.get("capi") or 0), 0)
        return f"{group_name} ({tipo}, Dest: {destinazione}, Ripro: {riproduzione}, {capi} capi)"

    def apri_popup_riporta_nascita(self):
        try:
            entries = list_azienda_animali_entries(self.user_id)
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        entries_attivi = [entry for entry in entries if int(entry.get("capi") or 0) > 0]
        gruppi_riproduzione = [entry for entry in entries_attivi if self._is_entry_riproduzione_attiva(entry)]

        if not gruppi_riproduzione:
            messagebox.showwarning(
                "Nessun gruppo disponibile",
                "Per usare 'Riporta nascita' serve almeno un gruppo con flag Riproduzione attivo.",
            )
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Riporta nascita")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)

        var_gruppo_origine = tk.StringVar(value="")
        var_numero_genitori = tk.StringVar(value="")

        var_genitori_nuovo_gruppo = tk.BooleanVar(value=False)
        var_genitori_nome_gruppo = tk.StringVar(value="")
        var_genitori_gruppo_esistente = tk.StringVar(value="")

        var_numero_nascite = tk.StringVar(value="")
        var_nascite_nuovo_gruppo = tk.BooleanVar(value=False)
        var_nascite_nome_gruppo = tk.StringVar(value="")
        var_nascite_destinazione = tk.StringVar(value="Da Latte")
        var_nascite_riproduzione = tk.StringVar(value="No")
        var_nascite_gruppo_esistente = tk.StringVar(value="")

        map_gruppi_origine = {}
        map_gruppi_destinazione_genitori = {}
        map_gruppi_destinazione_nascite = {}

        def _entry_id(entry: dict) -> int:
            try:
                return int(entry.get("id") or 0)
            except (TypeError, ValueError):
                return 0

        def _entry_tipo_key(entry: dict):
            return (
                (entry.get("tipo_animale") or "").strip().upper(),
                (entry.get("altro_label") or "").strip().lower(),
            )

        def _set_combo_values(combo: ttk.Combobox, text_var: tk.StringVar, labels: list[str]):
            combo.configure(values=tuple(labels))
            selected = text_var.get().strip()
            if labels:
                if selected not in labels:
                    text_var.set(labels[0])
            else:
                text_var.set("")

        row_origine = ttk.Frame(frame)
        row_origine.pack(fill="x", pady=(0, 6))
        ttk.Label(row_origine, text="Gruppo di origine genitore:", width=30).pack(side="left")
        combo_gruppo_origine = ttk.Combobox(
            row_origine,
            textvariable=var_gruppo_origine,
            state="readonly",
            width=78,
        )
        combo_gruppo_origine.pack(side="left", fill="x", expand=True)

        row_numero_genitori = ttk.Frame(frame)
        row_numero_genitori.pack(fill="x", pady=6)
        ttk.Label(row_numero_genitori, text="Numero:", width=30).pack(side="left")
        ttk.Entry(row_numero_genitori, textvariable=var_numero_genitori, width=12).pack(side="left")

        frame_dest_genitori = ttk.LabelFrame(frame, text="Gruppo destinazione genitore")
        frame_dest_genitori.pack(fill="x", pady=(8, 6))

        row_genitori_toggle = ttk.Frame(frame_dest_genitori)
        row_genitori_toggle.pack(fill="x", padx=10, pady=(8, 4))
        ttk.Checkbutton(
            row_genitori_toggle,
            text="Nuovo gruppo",
            variable=var_genitori_nuovo_gruppo,
        ).pack(side="left")

        frame_genitori_gruppo_nuovo = ttk.Frame(frame_dest_genitori)
        row_genitori_nome = ttk.Frame(frame_genitori_gruppo_nuovo)
        row_genitori_nome.pack(fill="x", pady=4)
        ttk.Label(row_genitori_nome, text="Nome nuovo gruppo:", width=30).pack(side="left")
        ttk.Entry(row_genitori_nome, textvariable=var_genitori_nome_gruppo).pack(side="left", fill="x", expand=True)

        frame_genitori_gruppo_esistente = ttk.Frame(frame_dest_genitori)
        row_genitori_esistente = ttk.Frame(frame_genitori_gruppo_esistente)
        row_genitori_esistente.pack(fill="x", pady=4)
        ttk.Label(row_genitori_esistente, text="Scegli gruppo:", width=30).pack(side="left")
        combo_genitori_esistente = ttk.Combobox(
            row_genitori_esistente,
            textvariable=var_genitori_gruppo_esistente,
            state="readonly",
            width=78,
        )
        combo_genitori_esistente.pack(side="left", fill="x", expand=True)

        row_numero_nascite = ttk.Frame(frame)
        row_numero_nascite.pack(fill="x", pady=(10, 6))
        ttk.Label(row_numero_nascite, text="Numero nascite:", width=30).pack(side="left")
        ttk.Entry(row_numero_nascite, textvariable=var_numero_nascite, width=12).pack(side="left")

        frame_dest_nascite = ttk.LabelFrame(frame, text="Gruppo destinazione nascite")
        frame_dest_nascite.pack(fill="x", pady=(8, 6))

        row_nascite_toggle = ttk.Frame(frame_dest_nascite)
        row_nascite_toggle.pack(fill="x", padx=10, pady=(8, 4))
        ttk.Checkbutton(
            row_nascite_toggle,
            text="Nuovo gruppo nascite",
            variable=var_nascite_nuovo_gruppo,
        ).pack(side="left")

        frame_nascite_gruppo_nuovo = ttk.Frame(frame_dest_nascite)
        row_nascite_nome = ttk.Frame(frame_nascite_gruppo_nuovo)
        row_nascite_nome.pack(fill="x", pady=4)
        ttk.Label(row_nascite_nome, text="Nome nuovo gruppo:", width=30).pack(side="left")
        ttk.Entry(row_nascite_nome, textvariable=var_nascite_nome_gruppo).pack(side="left", fill="x", expand=True)

        row_nascite_dest = ttk.Frame(frame_nascite_gruppo_nuovo)
        row_nascite_dest.pack(fill="x", pady=4)
        ttk.Label(row_nascite_dest, text="Destinazione:", width=30).pack(side="left")
        ttk.Combobox(
            row_nascite_dest,
            textvariable=var_nascite_destinazione,
            values=("Da Latte", "Da Carne"),
            state="readonly",
            width=16,
        ).pack(side="left")

        row_nascite_ripro = ttk.Frame(frame_nascite_gruppo_nuovo)
        row_nascite_ripro.pack(fill="x", pady=4)
        ttk.Label(row_nascite_ripro, text="Riproduzione:", width=30).pack(side="left")
        ttk.Combobox(
            row_nascite_ripro,
            textvariable=var_nascite_riproduzione,
            values=("Si", "No"),
            state="readonly",
            width=16,
        ).pack(side="left")

        frame_nascite_gruppo_esistente = ttk.Frame(frame_dest_nascite)
        row_nascite_esistente = ttk.Frame(frame_nascite_gruppo_esistente)
        row_nascite_esistente.pack(fill="x", pady=4)
        ttk.Label(row_nascite_esistente, text="Scegli gruppo:", width=30).pack(side="left")
        combo_nascite_esistente = ttk.Combobox(
            row_nascite_esistente,
            textvariable=var_nascite_gruppo_esistente,
            state="readonly",
            width=78,
        )
        combo_nascite_esistente.pack(side="left", fill="x", expand=True)

        def _toggle_destinazione_genitori():
            if var_genitori_nuovo_gruppo.get():
                if frame_genitori_gruppo_esistente.winfo_manager() != "":
                    frame_genitori_gruppo_esistente.pack_forget()
                if frame_genitori_gruppo_nuovo.winfo_manager() == "":
                    frame_genitori_gruppo_nuovo.pack(fill="x", padx=10, pady=(0, 8))
            else:
                if frame_genitori_gruppo_nuovo.winfo_manager() != "":
                    frame_genitori_gruppo_nuovo.pack_forget()
                if frame_genitori_gruppo_esistente.winfo_manager() == "":
                    frame_genitori_gruppo_esistente.pack(fill="x", padx=10, pady=(0, 8))

        def _toggle_destinazione_nascite():
            if var_nascite_nuovo_gruppo.get():
                if frame_nascite_gruppo_esistente.winfo_manager() != "":
                    frame_nascite_gruppo_esistente.pack_forget()
                if frame_nascite_gruppo_nuovo.winfo_manager() == "":
                    frame_nascite_gruppo_nuovo.pack(fill="x", padx=10, pady=(0, 8))
            else:
                if frame_nascite_gruppo_nuovo.winfo_manager() != "":
                    frame_nascite_gruppo_nuovo.pack_forget()
                if frame_nascite_gruppo_esistente.winfo_manager() == "":
                    frame_nascite_gruppo_esistente.pack(fill="x", padx=10, pady=(0, 8))

        def _aggiorna_gruppi_origine():
            map_gruppi_origine.clear()
            labels = []

            def _sort_key(item):
                return ((item.get("group_name") or "").strip().lower(), _entry_id(item))

            for entry in sorted(gruppi_riproduzione, key=_sort_key):
                label = self._zootecnia_label_gruppo_riporta_nascita(entry)
                if label in map_gruppi_origine:
                    label = f"{label} [ID {_entry_id(entry)}]"
                map_gruppi_origine[label] = entry
                labels.append(label)

            _set_combo_values(combo_gruppo_origine, var_gruppo_origine, labels)

        def _aggiorna_gruppi_destinazione():
            map_gruppi_destinazione_genitori.clear()
            map_gruppi_destinazione_nascite.clear()

            origine = map_gruppi_origine.get(var_gruppo_origine.get().strip())
            labels_genitori = []
            labels_nascite = []

            if origine:
                origine_id = _entry_id(origine)
                tipo_key = _entry_tipo_key(origine)

                for entry in entries_attivi:
                    entry_id = _entry_id(entry)
                    if entry_id <= 0:
                        continue
                    if _entry_tipo_key(entry) != tipo_key:
                        continue

                    label_base = self._zootecnia_label_gruppo_riporta_nascita(entry)
                    label_nascite = label_base
                    if label_nascite in map_gruppi_destinazione_nascite:
                        label_nascite = f"{label_nascite} [ID {entry_id}]"
                    map_gruppi_destinazione_nascite[label_nascite] = entry
                    labels_nascite.append(label_nascite)

                    if entry_id == origine_id:
                        continue

                    label_genitori = label_base
                    if label_genitori in map_gruppi_destinazione_genitori:
                        label_genitori = f"{label_genitori} [ID {entry_id}]"
                    map_gruppi_destinazione_genitori[label_genitori] = entry
                    labels_genitori.append(label_genitori)

            _set_combo_values(combo_genitori_esistente, var_genitori_gruppo_esistente, labels_genitori)
            _set_combo_values(combo_nascite_esistente, var_nascite_gruppo_esistente, labels_nascite)

            if not labels_genitori and not var_genitori_nuovo_gruppo.get():
                var_genitori_nuovo_gruppo.set(True)
            if not labels_nascite and not var_nascite_nuovo_gruppo.get():
                var_nascite_nuovo_gruppo.set(True)

            _toggle_destinazione_genitori()
            _toggle_destinazione_nascite()

        def _conferma_operazione():
            origine = map_gruppi_origine.get(var_gruppo_origine.get().strip())
            if not origine:
                messagebox.showerror("Errore", "Seleziona un gruppo di origine valido.")
                return

            try:
                numero_genitori = self._zootecnia_parse_positive_int(var_numero_genitori.get(), "Numero")
                numero_nascite = self._zootecnia_parse_positive_int(var_numero_nascite.get(), "Numero nascite")
            except ValueError as e:
                messagebox.showerror("Errore", str(e))
                return

            capi_origine = int(origine.get("capi") or 0)
            if numero_genitori > capi_origine:
                messagebox.showerror(
                    "Errore",
                    "Il numero capi da rimuovere non puo superare i capi presenti nel gruppo di origine.",
                )
                return

            dest_genitori_nome = ""
            dest_genitori_entry = None
            if var_genitori_nuovo_gruppo.get():
                dest_genitori_nome = var_genitori_nome_gruppo.get().strip()
                if not dest_genitori_nome:
                    messagebox.showerror("Errore", "Inserisci il nome del nuovo gruppo destinazione genitore.")
                    return
            else:
                dest_genitori_entry = map_gruppi_destinazione_genitori.get(var_genitori_gruppo_esistente.get().strip())
                if not dest_genitori_entry:
                    messagebox.showerror("Errore", "Seleziona un gruppo esistente per la destinazione genitore.")
                    return

            dest_nascite_nome = ""
            dest_nascite_finalita = ""
            dest_nascite_riproduzione = False
            dest_nascite_entry = None
            dest_nascite_finalita_label = "-"
            dest_nascite_riproduzione_label = "No"
            if var_nascite_nuovo_gruppo.get():
                dest_nascite_nome = var_nascite_nome_gruppo.get().strip()
                if not dest_nascite_nome:
                    messagebox.showerror("Errore", "Inserisci il nome del nuovo gruppo nascite.")
                    return

                tipo_origine = (origine.get("tipo_animale") or "").strip().upper()
                if tipo_origine in ("BOVINI", "OVINI"):
                    dest_nascite_finalita = self._zootecnia_finalita_label_to_db(var_nascite_destinazione.get())
                    if dest_nascite_finalita not in ("LATTE", "CARNE"):
                        messagebox.showerror("Errore", "Seleziona una destinazione valida per il gruppo nascite.")
                        return
                else:
                    dest_nascite_finalita = ""

                dest_nascite_riproduzione = (var_nascite_riproduzione.get().strip().lower() == "si")
                dest_nascite_finalita_label = var_nascite_destinazione.get().strip() or "-"
                if not dest_nascite_finalita:
                    dest_nascite_finalita_label = "-"
                dest_nascite_riproduzione_label = "Si" if dest_nascite_riproduzione else "No"
            else:
                dest_nascite_entry = map_gruppi_destinazione_nascite.get(var_nascite_gruppo_esistente.get().strip())
                if not dest_nascite_entry:
                    messagebox.showerror("Errore", "Seleziona un gruppo esistente per la destinazione nascite.")
                    return
                dest_nascite_finalita_label = self._zootecnia_label_destinazione(dest_nascite_entry)
                dest_nascite_riproduzione_label = "Si" if bool(dest_nascite_entry.get("riproduzione")) else "No"

            origine_nome = (origine.get("group_name") or "").strip() or "Gruppo origine"
            dest_genitori_nome_effettivo = (
                dest_genitori_nome
                if var_genitori_nuovo_gruppo.get()
                else (dest_genitori_entry.get("group_name") or "").strip() or "Gruppo"
            )
            dest_nascite_nome_effettivo = (
                dest_nascite_nome
                if var_nascite_nuovo_gruppo.get()
                else (dest_nascite_entry.get("group_name") or "").strip() or "Gruppo"
            )
            riepilogo_genitori = (
                f"Nuovo gruppo '{dest_genitori_nome}'"
                if var_genitori_nuovo_gruppo.get()
                else f"Gruppo esistente '{(dest_genitori_entry.get('group_name') or '').strip() or 'Gruppo'}'"
            )
            if var_nascite_nuovo_gruppo.get():
                finalita_label = var_nascite_destinazione.get().strip() or "-"
                ripro_label = var_nascite_riproduzione.get().strip() or "No"
                riepilogo_nascite = (
                    f"Nuovo gruppo '{dest_nascite_nome}' "
                    f"(Destinazione: {finalita_label}, Riproduzione: {ripro_label})"
                )
            else:
                riepilogo_nascite = (
                    f"Gruppo esistente '{(dest_nascite_entry.get('group_name') or '').strip() or 'Gruppo'}'"
                )

            conferma = messagebox.askyesno(
                "Conferma operazione",
                "Riepilogo operazione:\n"
                f"- Gruppo origine genitore: {origine_nome}\n"
                f"- Capi da spostare (genitori): {format_number(numero_genitori, 0)}\n"
                f"- Destinazione genitore: {riepilogo_genitori}\n"
                f"- Numero nascite: {format_number(numero_nascite, 0)}\n"
                f"- Destinazione nascite: {riepilogo_nascite}\n\n"
                "Confermi?",
            )
            if not conferma:
                return

            try:
                with get_conn() as conn:
                    c = conn.cursor()

                    remove_azienda_animale_capi(
                        self.user_id,
                        _entry_id(origine),
                        numero_genitori,
                        cursor=c,
                    )

                    if var_genitori_nuovo_gruppo.get():
                        add_azienda_animale_entry(
                            user_id=self.user_id,
                            tipo_animale=(origine.get("tipo_animale") or "").strip().upper(),
                            capi=numero_genitori,
                            finalita=(origine.get("finalita") or "").strip().upper(),
                            altro_label=(origine.get("altro_label") or "").strip(),
                            group_name=dest_genitori_nome,
                            riproduzione=True,
                            cursor=c,
                        )
                    else:
                        add_azienda_animale_entry(
                            user_id=self.user_id,
                            tipo_animale=(dest_genitori_entry.get("tipo_animale") or "").strip().upper(),
                            capi=numero_genitori,
                            finalita=(dest_genitori_entry.get("finalita") or "").strip().upper(),
                            altro_label=(dest_genitori_entry.get("altro_label") or "").strip(),
                            group_name=(dest_genitori_entry.get("group_name") or "").strip(),
                            riproduzione=bool(dest_genitori_entry.get("riproduzione")),
                            cursor=c,
                        )

                    if var_nascite_nuovo_gruppo.get():
                        add_azienda_animale_entry(
                            user_id=self.user_id,
                            tipo_animale=(origine.get("tipo_animale") or "").strip().upper(),
                            capi=numero_nascite,
                            finalita=dest_nascite_finalita,
                            altro_label=(origine.get("altro_label") or "").strip(),
                            group_name=dest_nascite_nome,
                            riproduzione=dest_nascite_riproduzione,
                            cursor=c,
                        )
                    else:
                        add_azienda_animale_entry(
                            user_id=self.user_id,
                            tipo_animale=(dest_nascite_entry.get("tipo_animale") or "").strip().upper(),
                            capi=numero_nascite,
                            finalita=(dest_nascite_entry.get("finalita") or "").strip().upper(),
                            altro_label=(dest_nascite_entry.get("altro_label") or "").strip(),
                            group_name=(dest_nascite_entry.get("group_name") or "").strip(),
                            riproduzione=bool(dest_nascite_entry.get("riproduzione")),
                            cursor=c,
                        )

                    capi_dopo_origine = capi_origine - numero_genitori
                    entry_id_correlato = 0
                    if dest_genitori_entry is not None:
                        entry_id_correlato = _entry_id(dest_genitori_entry)
                    elif dest_nascite_entry is not None:
                        entry_id_correlato = _entry_id(dest_nascite_entry)

                    add_azienda_animali_storico_entry(
                        user_id=self.user_id,
                        event_type="RIPORTA_NASCITA",
                        gruppo_entry_id=_entry_id(origine),
                        gruppo_nome=origine_nome,
                        tipo_animale=(origine.get("tipo_animale") or "").strip().upper(),
                        finalita=(origine.get("finalita") or "").strip().upper(),
                        capi_prima=capi_origine,
                        capi_variazione=0,
                        capi_dopo=max(capi_dopo_origine, 0),
                        gruppo_correlato_entry_id=entry_id_correlato,
                        gruppo_correlato_nome=dest_genitori_nome_effettivo,
                        note=(
                            f"Genitori spostati: {format_number(numero_genitori, 0)} -> {dest_genitori_nome_effettivo}. "
                            f"Nascite: {format_number(numero_nascite, 0)} -> {dest_nascite_nome_effettivo} "
                            f"(Destinazione: {dest_nascite_finalita_label}, Riproduzione: {dest_nascite_riproduzione_label})."
                        ),
                        cursor=c,
                    )
            except ValueError as e:
                messagebox.showerror("Errore", str(e))
                return
            except sqlite3.Error as e:
                messagebox.showerror("Errore DB", f"Errore database: {e}")
                return

            dialog.destroy()
            self.aggiorna_categoria_zootecnia()
            messagebox.showinfo("Successo", "Operazione 'Riporta nascita' completata.")

        frame_btn = ttk.Frame(frame)
        frame_btn.pack(fill="x", pady=(12, 0))
        ttk.Button(frame_btn, text="Conferma", command=_conferma_operazione).pack(side="left")
        ttk.Button(frame_btn, text="Annulla", command=dialog.destroy).pack(side="left", padx=6)

        var_gruppo_origine.trace_add("write", lambda *_args: _aggiorna_gruppi_destinazione())
        var_genitori_nuovo_gruppo.trace_add("write", lambda *_args: _toggle_destinazione_genitori())
        var_nascite_nuovo_gruppo.trace_add("write", lambda *_args: _toggle_destinazione_nascite())

        _aggiorna_gruppi_origine()
        _aggiorna_gruppi_destinazione()
        _toggle_destinazione_genitori()
        _toggle_destinazione_nascite()

    def _prima_data_produzione_latte_con_fattura(self):
        try:
            with get_conn() as conn:
                c = conn.cursor()

                c.execute(
                    '''
                    SELECT MIN(p.data_op)
                    FROM produzione_latte p
                    WHERE p.user_id=?
                      AND EXISTS (
                          SELECT 1
                          FROM fatture f
                          WHERE f.user_id = p.user_id
                            AND (
                                f.produzione_id = p.id
                                OR (p.movimento_id IS NOT NULL AND f.movimento_id = p.movimento_id)
                            )
                      )
                ''',
                    (self.user_id,),
                )
                row = c.fetchone()

                data_iso = (row[0] if row else "") or ""
                if not data_iso:
                    c.execute(
                        '''
                        SELECT MIN(data_op)
                        FROM produzione_latte
                        WHERE user_id=?
                    ''',
                        (self.user_id,),
                    )
                    fallback_row = c.fetchone()
                    data_iso = (fallback_row[0] if fallback_row else "") or ""
        except sqlite3.Error:
            return None

        if not data_iso:
            return None

        try:
            return datetime.strptime(data_iso, "%Y-%m-%d")
        except ValueError:
            return None

    def _ultima_data_produzione_latte_aggiunta(self):
        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    '''
                    SELECT data_op
                    FROM produzione_latte
                    WHERE user_id=?
                    ORDER BY id DESC
                    LIMIT 1
                ''',
                    (self.user_id,),
                )
                row = c.fetchone()
        except sqlite3.Error:
            return None

        data_iso = (row[0] if row else "") or ""
        if not data_iso:
            return None

        try:
            return datetime.strptime(data_iso, "%Y-%m-%d")
        except ValueError:
            return None

    def _prima_data_produzione_carne(self):
        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    '''
                    SELECT MIN(data_op)
                    FROM produzione_carne
                    WHERE user_id=?
                ''',
                    (self.user_id,),
                )
                row = c.fetchone()
        except sqlite3.Error:
            return None

        data_iso = (row[0] if row else "") or ""
        if not data_iso:
            return None

        try:
            return datetime.strptime(data_iso, "%Y-%m-%d")
        except ValueError:
            return None

    def _ultima_data_produzione_carne_aggiunta(self):
        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    '''
                    SELECT data_op
                    FROM produzione_carne
                    WHERE user_id=?
                    ORDER BY id DESC
                    LIMIT 1
                ''',
                    (self.user_id,),
                )
                row = c.fetchone()
        except sqlite3.Error:
            return None

        data_iso = (row[0] if row else "") or ""
        if not data_iso:
            return None

        try:
            return datetime.strptime(data_iso, "%Y-%m-%d")
        except ValueError:
            return None

    def _auto_compila_data_fine_report_latte(self, *_args):
        if not hasattr(self, "var_zootecnia_latte_data_inizio") or not hasattr(self, "var_zootecnia_latte_data_fine"):
            return

        data_inizio = self.var_zootecnia_latte_data_inizio.get().strip()
        data_fine = self.var_zootecnia_latte_data_fine.get().strip()
        if data_inizio and not data_fine:
            self.var_zootecnia_latte_data_fine.set(data_inizio)

    def _ensure_periodo_report_latte_vars(self):
        if not hasattr(self, "var_zootecnia_latte_data_inizio"):
            self.var_zootecnia_latte_data_inizio = tk.StringVar(value="")
        if not hasattr(self, "var_zootecnia_latte_data_fine"):
            self.var_zootecnia_latte_data_fine = tk.StringVar(value="")

        if not getattr(self, "_zootecnia_latte_periodo_trace_attivo", False):
            self.var_zootecnia_latte_data_inizio.trace_add("write", self._auto_compila_data_fine_report_latte)
            self._zootecnia_latte_periodo_trace_attivo = True

    def _crea_filtro_periodo_report_latte(self, parent, titolo="Periodo report Latte", pady=(0, 10)):
        self._ensure_periodo_report_latte_vars()

        frame_filtri_latte = ttk.LabelFrame(parent, text=titolo)
        frame_filtri_latte.pack(fill="x", pady=pady)

        self.crea_campo_data(frame_filtri_latte, "Data INIZIO:", self.var_zootecnia_latte_data_inizio)
        self.crea_campo_data(frame_filtri_latte, "Data FINE:", self.var_zootecnia_latte_data_fine)

        frame_btn_filtri_latte = ttk.Frame(frame_filtri_latte)
        frame_btn_filtri_latte.pack(fill="x", padx=20, pady=(0, 8))
        ttk.Button(
            frame_btn_filtri_latte,
            text="Applica periodo report",
            command=self.aggiorna_categoria_zootecnia,
        ).pack(side="left")
        ttk.Button(
            frame_btn_filtri_latte,
            text="Periodo default",
            command=lambda: self._imposta_periodo_report_latte_default(aggiorna=True),
        ).pack(side="left", padx=(6, 0))

        return frame_filtri_latte

    def _imposta_periodo_report_latte_default(self, aggiorna=False):
        oggi = datetime.now()
        data_inizio = oggi
        data_fine = oggi

        prima_data = self._prima_data_produzione_latte_con_fattura()
        if prima_data is not None:
            data_inizio = prima_data.replace(day=1)

        ultima_data = self._ultima_data_produzione_latte_aggiunta()
        if ultima_data is not None:
            data_fine = ultima_data

        if data_inizio > data_fine:
            data_inizio, data_fine = data_fine, data_inizio

        if hasattr(self, "var_zootecnia_latte_data_inizio"):
            self.var_zootecnia_latte_data_inizio.set(data_inizio.strftime("%d/%m/%Y"))
        if hasattr(self, "var_zootecnia_latte_data_fine"):
            self.var_zootecnia_latte_data_fine.set(data_fine.strftime("%d/%m/%Y"))

        if aggiorna:
            self.aggiorna_categoria_zootecnia()

    def _periodo_report_corrente_db(self):
        oggi = datetime.now()
        data_inizio = oggi
        data_fine = oggi

        data_inizio_text = ""
        data_fine_text = ""
        if hasattr(self, "var_zootecnia_latte_data_inizio"):
            data_inizio_text = self.var_zootecnia_latte_data_inizio.get().strip()
        elif hasattr(self, "var_data_inizio"):
            data_inizio_text = self.var_data_inizio.get().strip()

        if hasattr(self, "var_zootecnia_latte_data_fine"):
            data_fine_text = self.var_zootecnia_latte_data_fine.get().strip()
        elif hasattr(self, "var_data_fine"):
            data_fine_text = self.var_data_fine.get().strip()

        if data_inizio_text:
            try:
                data_inizio = datetime.strptime(data_inizio_text, "%d/%m/%Y")
            except ValueError:
                pass
        else:
            prima_data = self._prima_data_produzione_latte_con_fattura()
            if prima_data is not None:
                # Il report latte parte dal primo giorno del mese della prima produzione/fattura latte.
                data_inizio = prima_data.replace(day=1)

        if data_fine_text:
            try:
                data_fine = datetime.strptime(data_fine_text, "%d/%m/%Y")
            except ValueError:
                pass
        else:
            ultima_data = self._ultima_data_produzione_latte_aggiunta()
            if ultima_data is not None:
                data_fine = ultima_data

        if data_inizio > data_fine:
            data_inizio, data_fine = data_fine, data_inizio

        return {
            "inizio": data_inizio,
            "fine": data_fine,
            "inizio_db": data_inizio.strftime("%Y-%m-%d"),
            "fine_db": data_fine.strftime("%Y-%m-%d"),
        }

    def _periodo_report_carne_db(self):
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
        else:
            prima_data = self._prima_data_produzione_carne()
            if prima_data is not None:
                data_inizio = prima_data.replace(day=1)

        if data_fine_text:
            try:
                data_fine = datetime.strptime(data_fine_text, "%d/%m/%Y")
            except ValueError:
                pass
        else:
            ultima_data = self._ultima_data_produzione_carne_aggiunta()
            if ultima_data is not None:
                data_fine = ultima_data

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
            entries = list_azienda_animali_entries(self.user_id, include_merged=True)
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

    @staticmethod
    def _applica_alias_gruppo(entry_id, alias_map):
        try:
            current = int(entry_id or 0)
        except (TypeError, ValueError):
            return 0

        if current <= 0:
            return 0

        visited = set()
        while current in alias_map and current not in visited:
            visited.add(current)
            try:
                next_id = int(alias_map.get(current) or 0)
            except (TypeError, ValueError):
                next_id = 0
            if next_id <= 0:
                break
            current = next_id

        return current if current > 0 else 0

    @staticmethod
    def _applica_alias_gruppo_per_data(entry_id, data_db, merge_rules):
        try:
            current = int(entry_id or 0)
        except (TypeError, ValueError):
            return 0

        if current <= 0:
            return 0

        data_text = str(data_db or "").strip()
        rules = merge_rules if isinstance(merge_rules, dict) else {}
        visited = set()

        while current not in visited:
            visited.add(current)
            rule = rules.get(current)
            if not isinstance(rule, dict):
                break

            try:
                target_id = int(rule.get("target_id") or 0)
            except (TypeError, ValueError):
                target_id = 0
            if target_id <= 0:
                break

            merge_date = str(rule.get("merge_date") or "").strip()
            merge_effettivo = True
            if merge_date and data_text:
                merge_effettivo = merge_date <= data_text
            elif merge_date and not data_text:
                merge_effettivo = merge_date <= datetime.now().strftime("%Y-%m-%d")

            if not merge_effettivo:
                break

            current = target_id

        return current if current > 0 else 0

    def _snapshot_gruppi_animali_per_periodo(self, periodo=None):
        try:
            entries = list_azienda_animali_entries(self.user_id, include_merged=True)
        except sqlite3.Error:
            entries = []

        period_start_db = ""
        period_end_db = ""
        if isinstance(periodo, dict):
            period_start_db = str(periodo.get("inizio_db") or "").strip()
            period_end_db = str(periodo.get("fine_db") or "").strip()

        entries_norm = []
        by_id = {}
        for entry in entries:
            try:
                entry_id = int(entry.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if entry_id <= 0:
                continue

            normalized = dict(entry)
            normalized["id"] = entry_id
            normalized["capi"] = max(int(entry.get("capi") or 0), 0)
            merged_into = entry.get("merged_into_entry_id")
            try:
                merged_into_id = int(merged_into or 0)
            except (TypeError, ValueError):
                merged_into_id = 0
            normalized["merged_into_entry_id"] = merged_into_id if merged_into_id > 0 else None
            normalized["merge_date"] = str(entry.get("merge_date") or "").strip()

            entries_norm.append(normalized)
            by_id[entry_id] = normalized

        effective_capi = {entry["id"]: int(entry.get("capi") or 0) for entry in entries_norm}
        alias_map = {}
        merge_rules = {}
        visible_ids = set()

        for entry in entries_norm:
            entry_id = entry["id"]
            merged_into_id = int(entry.get("merged_into_entry_id") or 0)
            if merged_into_id <= 0:
                visible_ids.add(entry_id)
                continue

            merge_date = str(entry.get("merge_date") or "").strip()
            merge_rules[entry_id] = {
                "target_id": merged_into_id,
                "merge_date": merge_date,
            }

            merge_effettivo_intero_periodo = True
            if merge_date and period_start_db:
                merge_effettivo_intero_periodo = merge_date <= period_start_db
            elif merge_date and not period_start_db:
                merge_effettivo_intero_periodo = merge_date <= datetime.now().strftime("%Y-%m-%d")

            if merge_effettivo_intero_periodo:
                alias_map[entry_id] = merged_into_id
                continue

            visible_ids.add(entry_id)
            if merged_into_id in effective_capi:
                effective_capi[merged_into_id] = max(effective_capi[merged_into_id] - int(entry.get("capi") or 0), 0)

        visible_entries = []
        for entry in entries_norm:
            entry_id = entry["id"]
            merged_into_id = int(entry.get("merged_into_entry_id") or 0)
            if merged_into_id > 0 and entry_id not in visible_ids:
                continue

            entry_with_effective = dict(entry)
            entry_with_effective["effective_capi"] = max(int(effective_capi.get(entry_id, entry.get("capi") or 0)), 0)
            visible_entries.append(entry_with_effective)

        capi_map_visibile = {
            int(entry["id"]): max(int(entry.get("effective_capi") or 0), 0)
            for entry in visible_entries
            if int(entry.get("id") or 0) > 0
        }

        return {
            "entries_visibili": visible_entries,
            "capi_map_visibile": capi_map_visibile,
            "alias_map": alias_map,
            "merge_rules": merge_rules,
            "entries_all": entries_norm,
            "periodo": periodo,
        }

    def _mappa_capi_gruppi_animali(self, periodo=None):
        snapshot = self._snapshot_gruppi_animali_per_periodo(periodo=periodo)
        return dict(snapshot.get("capi_map_visibile") or {})

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

        snapshot_gruppi = self._snapshot_gruppi_animali_per_periodo(periodo=periodo)
        alias_map = snapshot_gruppi.get("alias_map") or {}
        merge_rules = snapshot_gruppi.get("merge_rules") or {}

        def _active_parent(entry_id):
            try:
                current = int(entry_id or 0)
            except (TypeError, ValueError):
                return 0
            if current <= 0:
                return 0

            visited = set()
            while current not in visited:
                visited.add(current)
                rule = merge_rules.get(current)
                if not isinstance(rule, dict):
                    break
                try:
                    target_id = int(rule.get("target_id") or 0)
                except (TypeError, ValueError):
                    target_id = 0
                if target_id <= 0:
                    break
                current = target_id
            return current if current > 0 else 0

        lookup_gruppi = self._costruisci_lookup_gruppi_parser()

        with get_conn() as conn:
            c = conn.cursor()

            c.execute(
                '''
                SELECT id,
                      data_op,
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
                                SELECT l.movimento_id, l.animale_entry_id, m.data_op
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
                      data_op,
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
                      COALESCE(g.litri, 0),
                      p.data_op
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
        link_map_source = {}
        for movimento_id_raw, entry_id_raw, movimento_data_op in link_rows:
            try:
                movimento_id = int(movimento_id_raw or 0)
                entry_id = int(entry_id_raw or 0)
            except (TypeError, ValueError):
                continue
            if movimento_id <= 0 or entry_id <= 0:
                continue

            source_ids = link_map_source.setdefault(movimento_id, [])
            if entry_id not in source_ids:
                source_ids.append(entry_id)

            entry_id_competenza = self._applica_alias_gruppo_per_data(entry_id, movimento_data_op, merge_rules)
            if entry_id_competenza <= 0:
                continue

            entry_id = _active_parent(entry_id_competenza)
            if entry_id <= 0:
                continue

            current_ids = link_map.setdefault(movimento_id, [])
            if entry_id not in current_ids:
                current_ids.append(entry_id)

        allocazioni_esplicite_map = {}
        explicit_source_by_produzione = {}
        for produzione_id_raw, entry_id_raw, litri_raw, produzione_data_op in allocazioni_rows:
            try:
                produzione_id = int(produzione_id_raw or 0)
                source_entry_id = int(entry_id_raw or 0)
            except (TypeError, ValueError):
                continue
            if produzione_id <= 0 or source_entry_id <= 0:
                continue

            entry_id_competenza = self._applica_alias_gruppo_per_data(source_entry_id, produzione_data_op, merge_rules)
            if entry_id_competenza <= 0:
                continue

            entry_id = _active_parent(entry_id_competenza)
            if entry_id <= 0:
                continue

            litri_value = parse_decimal(litri_raw, allow_zero=True, allow_negative=False)
            if litri_value is None or litri_value <= 0:
                continue

            source_ids = explicit_source_by_produzione.setdefault(produzione_id, [])
            if source_entry_id not in source_ids:
                source_ids.append(source_entry_id)

            quote_produzione = allocazioni_esplicite_map.setdefault(produzione_id, {})
            quote_produzione[entry_id] = float(litri_value)

        capi_map = self._mappa_capi_gruppi_animali(periodo=periodo)
        if isinstance(capi_overrides, dict):
            for raw_entry_id, raw_capi in capi_overrides.items():
                try:
                    entry_id = int(raw_entry_id)
                    capi = int(raw_capi)
                except (TypeError, ValueError):
                    continue
                if entry_id <= 0:
                    continue
                entry_id = self._applica_alias_gruppo(entry_id, alias_map)
                if entry_id <= 0:
                    continue
                capi_map[entry_id] = max(capi, 0)

        produzione_rows_base = [
            (row[0], row[2], row[3], row[4])
            for row in produzione_rows
            if isinstance(row, (tuple, list)) and len(row) >= 5
        ]

        quote_per_produzione, quote_ratio_per_movimento_entrate = self._costruisci_quote_litri_produzioni(
            produzione_rows_base,
            link_map,
            allocazioni_esplicite_map,
            capi_map,
        )

        capi_by_entry = {}
        for entry in snapshot_gruppi.get("entries_all") or []:
            try:
                entry_id = int(entry.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if entry_id <= 0:
                continue
            capi_by_entry[entry_id] = max(int(entry.get("capi") or 0), 0)

        # Ricostruisce la quota capi del "sorgente" parent sottraendo i figli uniti.
        source_capi_by_entry = dict(capi_by_entry)
        for child_id, rule in merge_rules.items():
            if not isinstance(rule, dict):
                continue
            try:
                child = int(child_id or 0)
                target = int(rule.get("target_id") or 0)
            except (TypeError, ValueError):
                continue
            if child <= 0 or target <= 0:
                continue
            child_capi = max(int(capi_by_entry.get(child, 0) or 0), 0)
            current_target = max(int(source_capi_by_entry.get(target, 0) or 0), 0)
            source_capi_by_entry[target] = max(current_target - child_capi, 0)

        for entry in snapshot_gruppi.get("entries_visibili") or []:
            try:
                entry_id = int(entry.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if entry_id <= 0:
                continue

            # Se non abbiamo una quota sorgente esplicita, usa i capi correnti della entry.
            if entry_id not in source_capi_by_entry:
                source_capi_by_entry[entry_id] = max(int(entry.get("capi") or 0), 0)

        merged_children_by_target = {}
        for child_id, rule in merge_rules.items():
            if not isinstance(rule, dict):
                continue
            try:
                child = int(child_id or 0)
                target = int(rule.get("target_id") or 0)
            except (TypeError, ValueError):
                continue
            if child <= 0 or target <= 0:
                continue
            merge_date = str(rule.get("merge_date") or "").strip()
            merged_children_by_target.setdefault(target, []).append((child, merge_date))

        for target_id, children in merged_children_by_target.items():
            merged_children_by_target[target_id] = sorted(
                children,
                key=lambda item: item[1] or "",
                reverse=True,
            )

        producer_source_ids_by_effective_group = {}
        for row in produzione_rows:
            if not isinstance(row, (tuple, list)) or len(row) < 5:
                continue

            try:
                produzione_id = int(row[0] or 0)
                movimento_id = int(row[2] or 0)
            except (TypeError, ValueError):
                continue
            if produzione_id <= 0:
                continue

            produzione_data_op = str(row[1] or "").strip()
            quote = quote_per_produzione.get(produzione_id, {})
            if not quote:
                continue

            source_ids = explicit_source_by_produzione.get(produzione_id) or link_map_source.get(movimento_id, [])
            source_ids_norm = []
            source_seen = set()
            for raw_source_id in source_ids:
                try:
                    source_id_norm = int(raw_source_id or 0)
                except (TypeError, ValueError):
                    continue
                if source_id_norm <= 0 or source_id_norm in source_seen:
                    continue
                source_seen.add(source_id_norm)
                source_ids_norm.append(source_id_norm)
            source_ids = source_ids_norm

            # Fallback per dati storici "compattati" in merge: quando il sorgente
            # risulta solo il gruppo principale, usa il figlio unito piu recente
            # valido per la data produzione come sorgente produttore.
            if len(source_ids) == 1:
                only_source_id = int(source_ids[0] or 0)
                if only_source_id > 0:
                    eff_id_only = self._applica_alias_gruppo_per_data(only_source_id, produzione_data_op, merge_rules)
                    display_id_only = _active_parent(eff_id_only)
                    if display_id_only > 0 and only_source_id == display_id_only:
                        candidate_children = []
                        for child_id, child_merge_date in merged_children_by_target.get(display_id_only, []):
                            if child_merge_date:
                                if inizio_db and child_merge_date < inizio_db:
                                    continue
                                if fine_db and child_merge_date > fine_db:
                                    continue
                            if child_merge_date and produzione_data_op and child_merge_date > produzione_data_op:
                                continue
                            if int(source_capi_by_entry.get(child_id, 0) or 0) <= 0:
                                continue
                            candidate_children.append(child_id)
                        if candidate_children:
                            source_ids = [int(candidate_children[0])]

            for source_id in source_ids:
                eff_id = self._applica_alias_gruppo_per_data(source_id, produzione_data_op, merge_rules)
                if eff_id <= 0:
                    continue

                display_id = _active_parent(eff_id)
                if display_id <= 0:
                    continue

                if float(quote.get(display_id, 0) or 0) <= 0:
                    continue

                producer_set = producer_source_ids_by_effective_group.setdefault(display_id, set())
                producer_set.add(int(source_id))

        return {
            "periodo": periodo,
            "lookup_gruppi": lookup_gruppi,
            "movimenti_rows": movimenti_rows,
            "link_map": link_map,
            "produzione_rows": produzione_rows,
            "quote_per_produzione": quote_per_produzione,
            "quote_ratio_per_movimento_entrate": quote_ratio_per_movimento_entrate,
            "alias_map": alias_map,
            "merge_rules": merge_rules,
            "capi_map_effettiva": capi_map,
            "capi_by_entry": source_capi_by_entry,
            "producer_source_ids_by_effective_group": producer_source_ids_by_effective_group,
            "snapshot_gruppi": snapshot_gruppi,
        }

    def _quota_movimento_per_gruppo(
        self,
        movimento_row,
        animale_entry_id,
        movimento_link_ids,
        lookup_gruppi,
        quote_ratio_entrate_per_movimento=None,
        merge_rules=None,
        active_parent_map=None,
    ):
        movimento_id = 0
        movimento_data_op = ""
        tipo = ""
        importo_raw = 0
        iva_raw = 0
        parser_products = ""

        if isinstance(movimento_row, (tuple, list)):
            if len(movimento_row) >= 6:
                movimento_id, movimento_data_op, tipo, importo_raw, iva_raw, parser_products = movimento_row[:6]
            elif len(movimento_row) >= 5:
                movimento_id, tipo, importo_raw, iva_raw, parser_products = movimento_row[:5]

        if not isinstance(merge_rules, dict):
            merge_rules = {}
        if not isinstance(active_parent_map, dict):
            active_parent_map = {}

        linked_ids = []
        linked_seen = set()
        for raw_id in movimento_link_ids or []:
            try:
                entry_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            entry_id = self._applica_alias_gruppo_per_data(entry_id, movimento_data_op, merge_rules)
            if entry_id <= 0:
                continue
            entry_id = int(active_parent_map.get(entry_id, entry_id) or 0)
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
            quota_ratio = 0.0
            for raw_entry_id, raw_ratio in quote_mov.items():
                try:
                    entry_id_q = int(raw_entry_id or 0)
                except (TypeError, ValueError):
                    continue
                entry_id_q = int(active_parent_map.get(entry_id_q, entry_id_q) or 0)
                if entry_id_q != animale_entry_id:
                    continue
                quota_ratio += float(raw_ratio or 0)
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
                    ids_riga_norm = []
                    ids_riga_seen = set()
                    for raw_entry_id in ids_riga:
                        entry_id_norm = self._applica_alias_gruppo_per_data(raw_entry_id, movimento_data_op, merge_rules)
                        if entry_id_norm <= 0:
                            continue
                        entry_id_norm = int(active_parent_map.get(entry_id_norm, entry_id_norm) or 0)
                        if entry_id_norm <= 0 or entry_id_norm in ids_riga_seen:
                            continue
                        ids_riga_seen.add(entry_id_norm)
                        ids_riga_norm.append(entry_id_norm)
                    ids_riga = ids_riga_norm
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
                WHERE user_id=?
                  AND data_op BETWEEN ? AND ?
                  AND UPPER(TRIM(COALESCE(categoria, '')))='LATTE'
                GROUP BY tipo
            ''',
                (self.user_id, inizio_db, fine_db),
            )
            risultati_movimenti = c.fetchall()

            c.execute(
                '''
                SELECT COALESCE(SUM(iva_importo), 0)
                FROM movimenti
                WHERE user_id=?
                  AND data_op BETWEEN ? AND ?
                  AND UPPER(TRIM(COALESCE(categoria, '')))='LATTE'
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

    def _calcola_metriche_carne_report_operativa(self):
        periodo = self._periodo_report_carne_db()
        inizio_db = periodo["inizio_db"]
        fine_db = periodo["fine_db"]

        with get_conn() as conn:
            c = conn.cursor()

            c.execute(
                '''
                SELECT COALESCE(SUM(kg), 0),
                       COUNT(id),
                       COALESCE(SUM(kg * prezzo_kg), 0)
                FROM produzione_carne
                WHERE user_id=? AND data_op BETWEEN ? AND ?
            ''',
                (self.user_id, inizio_db, fine_db),
            )
            row_carne = c.fetchone()

            c.execute(
                '''
                SELECT COALESCE(SUM(COALESCE(m.importo, 0)), 0),
                       COALESCE(SUM(COALESCE(m.iva_importo, 0)), 0),
                       COUNT(DISTINCT m.id)
                FROM produzione_carne pc
                LEFT JOIN movimenti m
                  ON m.user_id = pc.user_id
                 AND m.id = pc.movimento_id
                WHERE pc.user_id=? AND pc.data_op BETWEEN ? AND ?
            ''',
                (self.user_id, inizio_db, fine_db),
            )
            row_movimenti = c.fetchone()

        tot_kg = float((row_carne[0] if row_carne else 0) or 0)
        qta_produzioni = int((row_carne[1] if row_carne else 0) or 0)
        tot_valore_stimato = float((row_carne[2] if row_carne else 0) or 0)

        tot_importo_movimenti = float((row_movimenti[0] if row_movimenti else 0) or 0)
        tot_iva_movimenti = float((row_movimenti[1] if row_movimenti else 0) or 0)
        movimenti_collegati = int((row_movimenti[2] if row_movimenti else 0) or 0)

        giorni_periodo = (periodo["fine"] - periodo["inizio"]).days + 1
        media_kg_giorno = (tot_kg / giorni_periodo) if giorni_periodo > 0 else 0.0
        media_kg_registrazione = (tot_kg / qta_produzioni) if qta_produzioni > 0 else 0.0
        prezzo_medio_kg = (tot_valore_stimato / tot_kg) if tot_kg > 0 else 0.0
        prezzo_medio_quintale = prezzo_medio_kg * 100.0
        tot_quintali = tot_kg / 100.0
        tot_lordo_movimenti = tot_importo_movimenti + tot_iva_movimenti
        scostamento_imponibile = tot_importo_movimenti - tot_valore_stimato

        return {
            "periodo": f"{periodo['inizio'].strftime('%d/%m/%Y')} - {periodo['fine'].strftime('%d/%m/%Y')}",
            "qta_produzioni": qta_produzioni,
            "movimenti_collegati": movimenti_collegati,
            "tot_kg": tot_kg,
            "tot_quintali": tot_quintali,
            "media_kg_giorno": media_kg_giorno,
            "media_kg_registrazione": media_kg_registrazione,
            "prezzo_medio_kg": prezzo_medio_kg,
            "prezzo_medio_quintale": prezzo_medio_quintale,
            "tot_valore_stimato": tot_valore_stimato,
            "tot_importo_movimenti": tot_importo_movimenti,
            "tot_iva_movimenti": tot_iva_movimenti,
            "tot_lordo_movimenti": tot_lordo_movimenti,
            "scostamento_imponibile": scostamento_imponibile,
        }

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
        alias_map = shared_data.get("alias_map") or {}
        merge_rules = shared_data.get("merge_rules") or {}
        capi_map_effettiva = shared_data.get("capi_map_effettiva") or {}
        capi_by_entry = shared_data.get("capi_by_entry") or {}
        producer_source_ids_by_effective_group = shared_data.get("producer_source_ids_by_effective_group") or {}

        active_parent_map = {}
        if isinstance(merge_rules, dict):
            all_ids = set(capi_map_effettiva.keys()) | set(capi_by_entry.keys()) | set(merge_rules.keys())
            for raw_id in all_ids:
                try:
                    current = int(raw_id or 0)
                except (TypeError, ValueError):
                    continue
                if current <= 0:
                    continue
                visited = set()
                while current not in visited:
                    visited.add(current)
                    rule = merge_rules.get(current)
                    if not isinstance(rule, dict):
                        break
                    try:
                        target_id = int(rule.get("target_id") or 0)
                    except (TypeError, ValueError):
                        target_id = 0
                    if target_id <= 0:
                        break
                    current = target_id
                active_parent_map[int(raw_id)] = current if current > 0 else int(raw_id)

        animale_entry_id_eff = int(active_parent_map.get(animale_entry_id, animale_entry_id) or 0)
        if animale_entry_id_eff <= 0:
            animale_entry_id_eff = self._applica_alias_gruppo(animale_entry_id, alias_map)
        if animale_entry_id_eff <= 0:
            animale_entry_id_eff = int(animale_entry_id or 0)

        capi_nel_periodo = 0
        if animale_entry_id_eff > 0:
            capi_nel_periodo = int(capi_map_effettiva.get(animale_entry_id_eff, 0) or 0)
        if capi_nel_periodo <= 0:
            capi_nel_periodo = max(int(totale_capi or 0), 0)

        producer_source_ids = set()
        if isinstance(producer_source_ids_by_effective_group, dict):
            raw_set = producer_source_ids_by_effective_group.get(animale_entry_id_eff, set())
            if isinstance(raw_set, (set, list, tuple)):
                for raw_id in raw_set:
                    try:
                        entry_id = int(raw_id)
                    except (TypeError, ValueError):
                        continue
                    if entry_id > 0:
                        producer_source_ids.add(entry_id)

        capi_produttivi = 0
        for source_id in producer_source_ids:
            try:
                capi_source = int(capi_by_entry.get(source_id, 0) or 0)
            except (TypeError, ValueError):
                capi_source = 0
            capi_produttivi += max(capi_source, 0)

        if capi_produttivi > 0:
            totale_capi = capi_produttivi
        elif capi_nel_periodo > 0:
            totale_capi = capi_nel_periodo
        elif int(totale_capi or 0) <= 0 and animale_entry_id_eff > 0:
            totale_capi = int(capi_map_effettiva.get(animale_entry_id_eff, 0) or 0)

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
                animale_entry_id_eff,
                linked_ids,
                lookup_gruppi,
                quote_ratio_entrate_per_movimento=quote_ratio_per_movimento_entrate,
                merge_rules=merge_rules,
                active_parent_map=active_parent_map,
            )
            if not contribuisce:
                continue

            movimenti_estratti.add(movimento_id)
            tipo = ""
            if isinstance(movimento_row, (tuple, list)):
                if len(movimento_row) >= 3:
                    tipo = str(movimento_row[2] or "").strip().upper()
                elif len(movimento_row) >= 2:
                    tipo = str(movimento_row[1] or "").strip().upper()
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
        for produzione_id_raw, _data_op_raw, _movimento_id_raw, _litri_raw, prezzo_raw in produzione_rows:
            try:
                produzione_id = int(produzione_id_raw or 0)
            except (TypeError, ValueError):
                continue

            if produzione_id <= 0:
                continue

            quote_produzione = quote_per_produzione.get(produzione_id, {})
            litri_quota = 0.0
            for raw_entry_id, raw_litri in quote_produzione.items():
                try:
                    entry_id_q = int(raw_entry_id or 0)
                except (TypeError, ValueError):
                    continue
                entry_id_q = int(active_parent_map.get(entry_id_q, entry_id_q) or 0)
                if entry_id_q != animale_entry_id_eff:
                    continue
                litri_quota += float(raw_litri or 0)
            if litri_quota <= 0:
                continue

            qta_produzioni += 1
            prezzo_litro = float(prezzo_raw or 0)
            tot_litri += litri_quota
            totale_valore_latte += litri_quota * prezzo_litro

        metriche = self._calcola_metriche_latte_da_totali(
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

        metriche["capi_nel_periodo"] = max(int(capi_nel_periodo or 0), 0)
        metriche["capi_produttori_nel_periodo"] = max(int(capi_produttivi or 0), 0)
        return metriche

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
            (
                "Capi nel periodo",
                f"{format_number(metriche.get('capi_nel_periodo', metriche.get('totale_capi', 0)), 0)}",
            ),
            (
                "Capi produttori nel periodo",
                f"{format_number(metriche.get('capi_produttori_nel_periodo', 0), 0)}",
            ),
        ]

    def _righe_report_indici_gruppo(self, metriche):
        return [
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
            fill_mode = "x"
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

        tree.pack(fill="x", expand=True, padx=8, pady=8)
        self._zootecnia_adatta_altezza_tree(tree, len(righe))

    def _ensure_tab_zootecnia_latte(self):
        pagina = getattr(self, "tab_zootecnia_latte", None)
        if pagina is not None and pagina.winfo_exists():
            return pagina

        self.tab_zootecnia_latte = ttk.Frame(self.zootecnia_notebook)
        self.tab_latte = self.tab_zootecnia_latte
        self.setup_tab_latte()
        return self.tab_zootecnia_latte

    def _ensure_tab_zootecnia_carne(self):
        pagina = getattr(self, "tab_zootecnia_carne", None)
        if pagina is not None and pagina.winfo_exists():
            return pagina

        self.tab_zootecnia_carne = ttk.Frame(self.zootecnia_notebook)
        self.tab_carne = self.tab_zootecnia_carne
        self.setup_tab_carne()
        return self.tab_zootecnia_carne

    def _ensure_tab_zootecnia_info_generali(self):
        pagina = getattr(self, "tab_zootecnia_info_generali", None)
        if pagina is not None and pagina.winfo_exists():
            return pagina

        self.tab_zootecnia_info_generali = ttk.Frame(self.zootecnia_notebook)
        content = self.crea_container_scorribile(
            self.tab_zootecnia_info_generali,
            padding=12,
            stretch_to_viewport=True,
        )

        self._crea_filtro_periodo_report_latte(content, titolo="Periodo report Latte")

        self._imposta_periodo_report_latte_default(aggiorna=False)

        frame_report_affiancati = ttk.Frame(content)
        frame_report_affiancati.pack(fill="x")

        frame_info = ttk.LabelFrame(frame_report_affiancati, text="Riepilogo zootecnia")
        frame_info.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.tree_zootecnia_info_generali = ttk.Treeview(
            frame_info,
            columns=("metrica", "valore"),
            show="headings",
            height=1,
        )
        self.tree_zootecnia_info_generali.heading("metrica", text="Metrica")
        self.tree_zootecnia_info_generali.heading("valore", text="Valore")
        self.tree_zootecnia_info_generali.column("metrica", width=250, anchor="w")
        self.tree_zootecnia_info_generali.column("valore", width=220, anchor="e")
        self.tree_zootecnia_info_generali.pack(fill="x", expand=True, padx=8, pady=8)

        frame_latte = ttk.LabelFrame(frame_report_affiancati, text="Calcoli latte (riepilogo generale)")
        frame_latte.pack(side="left", fill="x", expand=True, padx=(6, 0))

        self.tree_zootecnia_info_latte = ttk.Treeview(
            frame_latte,
            columns=("metrica", "valore"),
            show="headings",
            height=1,
        )
        self.tree_zootecnia_info_latte.heading("metrica", text="Metrica")
        self.tree_zootecnia_info_latte.heading("valore", text="Valore")
        self.tree_zootecnia_info_latte.column("metrica", width=250, anchor="w")
        self.tree_zootecnia_info_latte.column("valore", width=220, anchor="e")
        self.tree_zootecnia_info_latte.pack(fill="x", expand=True, padx=8, pady=8)

        frame_carne = ttk.LabelFrame(content, text="Calcoli carne (riepilogo generale)")
        frame_carne.pack(fill="x", pady=(10, 0))

        self.tree_zootecnia_info_carne = ttk.Treeview(
            frame_carne,
            columns=("metrica", "valore"),
            show="headings",
            height=1,
        )
        self.tree_zootecnia_info_carne.heading("metrica", text="Metrica")
        self.tree_zootecnia_info_carne.heading("valore", text="Valore")
        self.tree_zootecnia_info_carne.column("metrica", width=330, anchor="w")
        self.tree_zootecnia_info_carne.column("valore", width=280, anchor="e")
        self.tree_zootecnia_info_carne.pack(fill="x", expand=True, padx=8, pady=8)

        frame_storico_gruppi = ttk.LabelFrame(
            content,
            text="Storico gruppi (unioni, divisioni, aggiunte/rimozioni capi)",
        )
        frame_storico_gruppi.pack(fill="x", pady=(10, 0))

        frame_storico_azioni = ttk.Frame(frame_storico_gruppi)
        frame_storico_azioni.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(frame_storico_azioni, text="Mostra le ultime 300 operazioni sui gruppi.").pack(side="left")
        ttk.Button(
            frame_storico_azioni,
            text="Elimina selezionate",
            command=self.elimina_operazioni_storico_gruppi_selezionate,
        ).pack(side="right", padx=(0, 6))
        ttk.Button(
            frame_storico_azioni,
            text="Aggiorna storico",
            command=lambda: self._carica_storico_gruppi_zootecnia(mostra_errori=True),
        ).pack(side="right")

        self.tree_zootecnia_storico_gruppi = ttk.Treeview(
            frame_storico_gruppi,
            columns=("data", "evento", "gruppo", "delta", "capi_dopo", "dettaglio"),
            show="headings",
            selectmode="extended",
            height=1,
        )
        self.tree_zootecnia_storico_gruppi.heading("data", text="Data")
        self.tree_zootecnia_storico_gruppi.heading("evento", text="Evento")
        self.tree_zootecnia_storico_gruppi.heading("gruppo", text="Gruppo")
        self.tree_zootecnia_storico_gruppi.heading("delta", text="Delta capi")
        self.tree_zootecnia_storico_gruppi.heading("capi_dopo", text="Capi dopo")
        self.tree_zootecnia_storico_gruppi.heading("dettaglio", text="Dettaglio")

        self.tree_zootecnia_storico_gruppi.column("data", width=130, anchor="center")
        self.tree_zootecnia_storico_gruppi.column("evento", width=150, anchor="center")
        self.tree_zootecnia_storico_gruppi.column("gruppo", width=280, anchor="w")
        self.tree_zootecnia_storico_gruppi.column("delta", width=90, anchor="e")
        self.tree_zootecnia_storico_gruppi.column("capi_dopo", width=100, anchor="e")
        self.tree_zootecnia_storico_gruppi.column("dettaglio", width=430, anchor="w")

        self.tree_zootecnia_storico_gruppi.pack(fill="x", expand=True, padx=8, pady=8)
        self.tree_zootecnia_storico_gruppi.bind(
            "<Delete>",
            lambda _event: self.elimina_operazioni_storico_gruppi_selezionate(),
        )

        if hasattr(self, "abilita_a_capo_treeview"):
            self.abilita_a_capo_treeview(self.tree_zootecnia_storico_gruppi, max_lines=3)

        frame_azioni = ttk.Frame(content)
        frame_azioni.pack(anchor="w", pady=(10, 0))
        ttk.Button(
            frame_azioni,
            text="Configura tipi allevamento",
            command=self.apri_configurazione_allevamento,
        ).pack(side="left")

        return self.tab_zootecnia_info_generali

    def _aggiorna_tab_zootecnia_info_generali(self, gruppi_attivi, gruppi_latte_attivi):
        if (
            not hasattr(self, "tree_zootecnia_info_generali")
            or not hasattr(self, "tree_zootecnia_info_latte")
            or not hasattr(self, "tree_zootecnia_info_carne")
        ):
            return

        totale_gruppi = len(gruppi_attivi)
        totale_gruppi_latte = len(gruppi_latte_attivi)
        totale_gruppi_carne = sum(1 for gruppo in gruppi_attivi if gruppo.get("destinazione") == "Da Carne")
        totale_capi = sum(int(gruppo.get("capi") or 0) for gruppo in gruppi_attivi)

        clear_treeview(self.tree_zootecnia_info_generali)
        clear_treeview(self.tree_zootecnia_info_latte)
        clear_treeview(self.tree_zootecnia_info_carne)

        if totale_gruppi <= 0:
            righe_generali = [
                ("Stato", "Nessun gruppo animale attivo"),
                ("Azione consigliata", "Configura i gruppi in Azienda > Tipi Allevamento"),
            ]
        else:
            righe_generali = [
                ("Gruppi attivi", str(totale_gruppi)),
                ("Gruppi da latte attivi", str(totale_gruppi_latte)),
                ("Gruppi da carne attivi", str(totale_gruppi_carne)),
                ("Capi totali registrati", format_number(totale_capi, 0)),
            ]

        for metrica, valore in righe_generali:
            self.tree_zootecnia_info_generali.insert("", "end", values=(metrica, valore))
        self._zootecnia_adatta_altezza_tree(self.tree_zootecnia_info_generali, len(righe_generali))

        try:
            metriche_latte = self._calcola_metriche_latte_report_operativa()
            righe_latte = [
                ("Periodo", metriche_latte["periodo"]),
                ("Produzioni latte nel periodo", str(metriche_latte["qta_produzioni"])),
                (
                    "Totale Quintali",
                    f"{format_number(metriche_latte['tot_quintali'], 2)} q "
                    f"({format_number(metriche_latte['tot_litri'], 2)} L)",
                ),
                ("Media Quintali/Giorno", f"{format_number(metriche_latte['media_quintali_giorno'], 2)} q"),
                (
                    "Media Quintali/Registrazione",
                    f"{format_number(metriche_latte['media_quintali_registrazione'], 2)} q",
                ),
                ("Prezzo Medio/Litro", format_eur(metriche_latte["prezzo_medio_litro"], 4)),
                ("Costo Produzione/Litro", format_eur(metriche_latte["costo_produzione_litro"], 4)),
                ("Utile/Litro", format_eur(metriche_latte["utile_litro"], 4)),
            ]
        except Exception:
            righe_latte = [("Calcoli latte", "Non disponibili (errore durante il calcolo)")]

        for metrica, valore in righe_latte:
            self.tree_zootecnia_info_latte.insert("", "end", values=(metrica, valore))
        self._zootecnia_adatta_altezza_tree(self.tree_zootecnia_info_latte, len(righe_latte))

        try:
            metriche_carne = self._calcola_metriche_carne_report_operativa()
            righe_carne = [
                ("Periodo", metriche_carne["periodo"]),
                ("Produzioni carne nel periodo", str(metriche_carne["qta_produzioni"])),
                ("Movimenti carne collegati", str(metriche_carne["movimenti_collegati"])),
                (
                    "Totale Quantita",
                    f"{format_number(metriche_carne['tot_kg'], 2)} Kg "
                    f"({format_number(metriche_carne['tot_quintali'], 2)} q)",
                ),
                (
                    "Media Kg/Registrazione",
                    f"{format_number(metriche_carne['media_kg_registrazione'], 2)} Kg",
                ),
                ("Prezzo Medio/Kg", format_eur(metriche_carne["prezzo_medio_kg"], 4)),
                ("Valore Produzione (Kg x Prezzo)", format_eur(metriche_carne["tot_valore_stimato"])),
                ("Imponibile Movimenti Carne", format_eur(metriche_carne["tot_importo_movimenti"])),
                ("IVA Movimenti Carne", format_eur(metriche_carne["tot_iva_movimenti"])),
                ("Totale Lordo Movimenti Carne", format_eur(metriche_carne["tot_lordo_movimenti"])),
                (
                    "Scostamento Imponibile vs Produzione",
                    format_eur(metriche_carne["scostamento_imponibile"]),
                ),
            ]
        except Exception:
            righe_carne = [("Calcoli carne", "Non disponibili (errore durante il calcolo)")]

        for metrica, valore in righe_carne:
            self.tree_zootecnia_info_carne.insert("", "end", values=(metrica, valore))
        self._zootecnia_adatta_altezza_tree(self.tree_zootecnia_info_carne, len(righe_carne))

        self._carica_storico_gruppi_zootecnia(mostra_errori=False)

    def apri_configurazione_allevamento(self):
        self.mostra_categoria(self.CATEGORIA_AZIENDA)
        if hasattr(self, "mostra_tab_azienda_animali"):
            self.mostra_tab_azienda_animali()

    def aggiorna_categoria_zootecnia(self):
        periodo_latte = self._periodo_report_corrente_db()

        # Le schede gruppo devono rappresentare solo i gruppi attivi correnti.
        # La competenza storica intra-periodo resta usata nei calcoli metrici.
        try:
            entries = list_azienda_animali_entries(self.user_id)
        except sqlite3.Error:
            entries = []

        if not hasattr(self, "zootecnia_notebook"):
            return

        tab_preferita = ""
        try:
            current_tab = self.zootecnia_notebook.select()
            if current_tab:
                tab_preferita = str(self.zootecnia_notebook.tab(current_tab, "text") or "")
        except Exception:
            tab_preferita = ""

        for tab_id in self.zootecnia_notebook.tabs():
            self.zootecnia_notebook.forget(tab_id)

        gruppi_attivi = []
        gruppi_latte_attivi = []
        gruppi_carne_attivi = []
        gruppi_riproduzione_attivi = []

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

            entry_active_view = dict(entry)
            entry_active_view["capi"] = capi

            if self._is_entry_latte_attiva(entry_active_view):
                gruppi_latte_attivi.append(entry_active_view)
            if self._is_entry_carne_attiva(entry_active_view):
                gruppi_carne_attivi.append(entry_active_view)
            if self._is_entry_riproduzione_attiva(entry_active_view):
                gruppi_riproduzione_attivi.append(entry_active_view)

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

        if hasattr(self, "btn_zootecnia_riporta_nascita"):
            nuovo_stato = "normal" if gruppi_riproduzione_attivi else "disabled"
            self.btn_zootecnia_riporta_nascita.config(state=nuovo_stato)

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

            if gruppi_carne_attivi:
                pagina_carne = self._ensure_tab_zootecnia_carne()
                self.zootecnia_notebook.add(pagina_carne, text="Produzione Carne")
                if hasattr(self, "carica_produzioni_carne"):
                    self.carica_produzioni_carne(mostra_errori=False)

            for gruppo in gruppi_attivi:
                pagina = ttk.Frame(self.zootecnia_notebook, padding=12)

                frame_info = ttk.LabelFrame(pagina, text=gruppo["nome"])
                frame_info.pack(fill="x")

                ttk.Label(frame_info, text=f"Tipo: {gruppo['tipo']}").pack(anchor="w", padx=12, pady=(10, 4))
                ttk.Label(frame_info, text=f"Destinazione: {gruppo['destinazione']}").pack(anchor="w", padx=12, pady=4)
                ttk.Label(frame_info, text=f"Capi registrati: {gruppo['capi']}").pack(anchor="w", padx=12, pady=(4, 10))

                if gruppo["destinazione"] == "Da Latte":
                    self._crea_filtro_periodo_report_latte(
                        pagina,
                        titolo="Periodo report Latte",
                        pady=(10, 10),
                    )

                try:
                    metriche_gruppo = self._calcola_metriche_latte_report_operativa_per_gruppo(
                        gruppo["entry_id"],
                        totale_capi=gruppo["capi"],
                        shared_data=shared_metriche_gruppi,
                    )

                    frame_report_affiancati = ttk.Frame(pagina)
                    frame_report_affiancati.pack(fill="x")

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

            if gruppi_latte_attivi and gruppi_carne_attivi:
                self.var_zootecnia_stato.set(
                    f"Sono disponibili {len(gruppi_attivi)} sottopagine per i gruppi animali attivi "
                    "oltre alle pagine Informazioni Generali, Produzione Latte e Produzione Carne."
                )
            elif gruppi_latte_attivi:
                self.var_zootecnia_stato.set(
                    f"Sono disponibili {len(gruppi_attivi)} sottopagine per i gruppi animali attivi "
                    "oltre alle pagine Informazioni Generali e Produzione Latte."
                )
            elif gruppi_carne_attivi:
                self.var_zootecnia_stato.set(
                    f"Sono disponibili {len(gruppi_attivi)} sottopagine per i gruppi animali attivi "
                    "oltre alle pagine Informazioni Generali e Produzione Carne."
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

        restored = False
        if tab_preferita:
            for tab_id in self.zootecnia_notebook.tabs():
                try:
                    tab_text = str(self.zootecnia_notebook.tab(tab_id, "text") or "")
                except Exception:
                    continue
                if tab_text == tab_preferita:
                    self.zootecnia_notebook.select(tab_id)
                    restored = True
                    break

        if not restored:
            tabs = self.zootecnia_notebook.tabs()
            if tabs:
                self.zootecnia_notebook.select(tabs[0])

        if hasattr(self, "abilita_a_capo_tutte_treeview"):
            self.abilita_a_capo_tutte_treeview()
