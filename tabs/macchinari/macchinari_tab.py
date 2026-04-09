import sqlite3
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from app_utils import clear_treeview, format_eur, parse_decimal
from database import (
    add_macchinario_entry,
    add_manutenzione_macchinario_entry,
    delete_macchinario_entry,
    delete_manutenzione_macchinario_entry,
    list_macchinari_entries,
    list_manutenzioni_macchinari_entries,
    update_macchinario_entry,
    update_manutenzione_macchinario_entry,
)


class MacchinariTabMixin:
    def _macchinari_adatta_altezza_tree(self, tree, righe_count: int, min_rows: int = 1):
        if tree is None:
            return

        rows = max(int(righe_count or 0), int(min_rows or 1))
        try:
            tree.configure(height=rows)
        except tk.TclError:
            pass

    def _setup_categoria_macchinari(self):
        content = self.crea_container_scorribile(self.frame_macchinari, padding=18)

        ttk.Label(content, text="Macchinari", font=("Arial", 14, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            content,
            text="Aggiungi e consulta i macchinari aziendali.",
            justify="left",
            wraplength=860,
        ).pack(anchor="w", pady=(0, 10))

        self.var_macchinario_nome = tk.StringVar(value="")
        self.var_macchinario_marca = tk.StringVar(value="")
        self.var_macchinario_modello = tk.StringVar(value="")
        self.var_macchinario_identificativo = tk.StringVar(value="")
        self.var_macchinario_anno = tk.StringVar(value="")
        self.var_macchinario_note = tk.StringVar(value="")
        self.var_macchinario_stato = tk.StringVar(value="")
        self.var_ricerca_macchinari = tk.StringVar(value="")
        self.var_filtro_macchinari_anno = tk.StringVar(value="")

        self.var_manutenzione_macchinario = tk.StringVar(value="")
        self.var_manutenzione_data = tk.StringVar(value=datetime.now().strftime("%d/%m/%Y"))
        self.var_manutenzione_tipo = tk.StringVar(value="Ordinaria")
        self.var_manutenzione_descrizione = tk.StringVar(value="")
        self.var_manutenzione_fornitore = tk.StringVar(value="")
        self.var_manutenzione_costo = tk.StringVar(value="")
        self.var_manutenzione_note = tk.StringVar(value="")
        self.var_manutenzione_stato = tk.StringVar(value="")
        self.var_ricerca_manutenzioni = tk.StringVar(value="")
        self.var_filtro_manutenzioni_tipo = tk.StringVar(value="Tutte")
        self.var_filtro_manutenzioni_data_da = tk.StringVar(value="")
        self.var_filtro_manutenzioni_data_a = tk.StringVar(value="")
        self._placeholder_data_periodo = "GG/MM/AAAA"

        self.macchinario_in_modifica_id = None
        self.manutenzione_in_modifica_id = None

        self._map_macchinari_label_to_id = {}
        self._map_macchinari_id_to_label = {}

        self.crea_campo(content, "Nome macchinario:", self.var_macchinario_nome)
        self.crea_campo(content, "Marca:", self.var_macchinario_marca)
        self.crea_campo(content, "Modello:", self.var_macchinario_modello)
        self.crea_campo(content, "Identificativo:", self.var_macchinario_identificativo)
        self.crea_campo(content, "Anno:", self.var_macchinario_anno)
        self.crea_campo(content, "Note:", self.var_macchinario_note)

        frame_actions = ttk.Frame(content)
        frame_actions.pack(anchor="w", pady=(8, 10), padx=20)
        ttk.Button(
            frame_actions,
            text="Salva macchinario",
            command=self.salva_macchinario,
        ).pack(side="left")
        ttk.Button(
            frame_actions,
            text="Pulisci campi",
            command=self._reset_form_macchinario,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            frame_actions,
            text="Modifica selezionato",
            command=self.prepara_modifica_macchinario,
        ).pack(side="left", padx=(6, 0))
        self.btn_annulla_modifica_macchinario = ttk.Button(
            frame_actions,
            text="Annulla modifica",
            command=lambda: self.annulla_modifica_macchinario(reset_campi=True),
            state="disabled",
        )
        self.btn_annulla_modifica_macchinario.pack(side="left", padx=(6, 0))
        ttk.Button(
            frame_actions,
            text="Elimina selezionato",
            command=self.elimina_macchinario_selezionato,
        ).pack(side="left", padx=(6, 0))

        ttk.Label(content, textvariable=self.var_macchinario_stato, foreground="#1f5f3f").pack(
            anchor="w", padx=20, pady=(0, 8)
        )

        frame_tabella = ttk.LabelFrame(content, text="Elenco macchinari")
        frame_tabella.pack(fill="x")

        frame_filtri_macchinari = ttk.Frame(frame_tabella)
        frame_filtri_macchinari.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(frame_filtri_macchinari, text="Ricerca:").pack(side="left")
        self.entry_ricerca_macchinari = ttk.Entry(
            frame_filtri_macchinari,
            textvariable=self.var_ricerca_macchinari,
            width=34,
        )
        self.entry_ricerca_macchinari.pack(side="left", padx=(6, 10))
        ttk.Label(frame_filtri_macchinari, text="Anno:").pack(side="left")
        self.entry_filtro_macchinari_anno = ttk.Entry(
            frame_filtri_macchinari,
            textvariable=self.var_filtro_macchinari_anno,
            width=8,
        )
        self.entry_filtro_macchinari_anno.pack(side="left", padx=(6, 10))
        ttk.Button(
            frame_filtri_macchinari,
            text="Applica",
            command=lambda: self.carica_macchinari(mostra_errori=False),
        ).pack(side="left")
        ttk.Button(
            frame_filtri_macchinari,
            text="Reset",
            command=self._reset_filtri_macchinari,
        ).pack(side="left", padx=(6, 0))

        self.entry_ricerca_macchinari.bind("<Return>", lambda _event: self.carica_macchinari(mostra_errori=False))
        self.entry_filtro_macchinari_anno.bind("<Return>", lambda _event: self.carica_macchinari(mostra_errori=False))
        self.entry_ricerca_macchinari.bind("<KeyRelease>", lambda _event: self.carica_macchinari(mostra_errori=False))
        self.entry_filtro_macchinari_anno.bind(
            "<KeyRelease>", lambda _event: self.carica_macchinari(mostra_errori=False)
        )

        cols = ("id", "nome", "marca", "modello", "identificativo", "anno", "note")
        self.tree_macchinari = ttk.Treeview(frame_tabella, columns=cols, show="headings", height=1)
        self.tree_macchinari.heading("id", text="ID")
        self.tree_macchinari.heading("nome", text="Nome")
        self.tree_macchinari.heading("marca", text="Marca")
        self.tree_macchinari.heading("modello", text="Modello")
        self.tree_macchinari.heading("identificativo", text="Identificativo")
        self.tree_macchinari.heading("anno", text="Anno")
        self.tree_macchinari.heading("note", text="Note")

        self.tree_macchinari.column("id", width=60, anchor="center")
        self.tree_macchinari.column("nome", width=170, anchor="w")
        self.tree_macchinari.column("marca", width=130, anchor="w")
        self.tree_macchinari.column("modello", width=130, anchor="w")
        self.tree_macchinari.column("identificativo", width=150, anchor="w")
        self.tree_macchinari.column("anno", width=70, anchor="center")
        self.tree_macchinari.column("note", width=280, anchor="w")

        self.tree_macchinari.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        self._macchinari_adatta_altezza_tree(self.tree_macchinari, 1)
        self.tree_macchinari.bind("<<TreeviewSelect>>", self._on_tree_macchinari_select)
        self.tree_macchinari.bind("<Double-1>", lambda _event: self.prepara_modifica_macchinario(mostra_errori=False))
        self.tree_macchinari.bind("<Delete>", lambda _event: self.elimina_macchinario_selezionato())

        self.lbl_manutenzione_non_disponibile = ttk.Label(
            content,
            text="Manutenzione disponibile dopo aver registrato almeno 1 macchinario.",
            justify="left",
            wraplength=860,
        )

        self.frame_manutenzione = ttk.LabelFrame(content, text="Manutenzione macchinari")

        frame_macchinario_manut = ttk.Frame(self.frame_manutenzione)
        frame_macchinario_manut.pack(fill="x", padx=20, pady=(8, 5))
        ttk.Label(frame_macchinario_manut, text="Macchinario:", width=20).pack(side="left")
        self.combo_manutenzione_macchinario = ttk.Combobox(
            frame_macchinario_manut,
            textvariable=self.var_manutenzione_macchinario,
            state="readonly",
            values=(),
        )
        self.combo_manutenzione_macchinario.pack(side="left", fill="x", expand=True)
        self.combo_manutenzione_macchinario.bind(
            "<<ComboboxSelected>>", lambda _event: self.carica_manutenzioni_macchinari(mostra_errori=False)
        )

        self.crea_campo_data(self.frame_manutenzione, "Data manutenzione:", self.var_manutenzione_data)

        frame_tipo = ttk.Frame(self.frame_manutenzione)
        frame_tipo.pack(fill="x", padx=20, pady=5)
        ttk.Label(frame_tipo, text="Tipo manutenzione:", width=20).pack(side="left")
        self.combo_manutenzione_tipo = ttk.Combobox(
            frame_tipo,
            textvariable=self.var_manutenzione_tipo,
            state="readonly",
            values=("Ordinaria", "Straordinaria"),
        )
        self.combo_manutenzione_tipo.pack(side="left", fill="x", expand=True)

        self.crea_campo(self.frame_manutenzione, "Descrizione:", self.var_manutenzione_descrizione)
        self.crea_campo(self.frame_manutenzione, "Fornitore/Officina:", self.var_manutenzione_fornitore)
        self.crea_campo(self.frame_manutenzione, "Costo (EUR):", self.var_manutenzione_costo)
        self.crea_campo(self.frame_manutenzione, "Note:", self.var_manutenzione_note)

        frame_actions_manut = ttk.Frame(self.frame_manutenzione)
        frame_actions_manut.pack(anchor="w", pady=(8, 10), padx=20)
        ttk.Button(
            frame_actions_manut,
            text="Salva manutenzione",
            command=self.salva_manutenzione_macchinario,
        ).pack(side="left")
        ttk.Button(
            frame_actions_manut,
            text="Pulisci campi",
            command=self._reset_form_manutenzione,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            frame_actions_manut,
            text="Modifica selezionata",
            command=self.prepara_modifica_manutenzione,
        ).pack(side="left", padx=(6, 0))
        self.btn_annulla_modifica_manutenzione = ttk.Button(
            frame_actions_manut,
            text="Annulla modifica",
            command=lambda: self.annulla_modifica_manutenzione(reset_campi=True),
            state="disabled",
        )
        self.btn_annulla_modifica_manutenzione.pack(side="left", padx=(6, 0))
        ttk.Button(
            frame_actions_manut,
            text="Elimina selezionata",
            command=self.elimina_manutenzione_selezionata,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            frame_actions_manut,
            text="Aggiorna elenco",
            command=lambda: self.carica_manutenzioni_macchinari(mostra_errori=True),
        ).pack(side="left", padx=(6, 0))

        ttk.Label(self.frame_manutenzione, textvariable=self.var_manutenzione_stato, foreground="#1f5f3f").pack(
            anchor="w", padx=20, pady=(0, 8)
        )

        frame_tabella_manut = ttk.LabelFrame(self.frame_manutenzione, text="Storico manutenzioni")
        frame_tabella_manut.pack(fill="x")

        frame_filtri_manut = ttk.Frame(frame_tabella_manut)
        frame_filtri_manut.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(frame_filtri_manut, text="Ricerca:").pack(side="left")
        self.entry_ricerca_manutenzioni = ttk.Entry(
            frame_filtri_manut,
            textvariable=self.var_ricerca_manutenzioni,
            width=34,
        )
        self.entry_ricerca_manutenzioni.pack(side="left", padx=(6, 10))
        ttk.Label(frame_filtri_manut, text="Tipo:").pack(side="left")
        self.combo_filtro_manutenzioni_tipo = ttk.Combobox(
            frame_filtri_manut,
            textvariable=self.var_filtro_manutenzioni_tipo,
            state="readonly",
            width=14,
            values=("Tutte", "Ordinaria", "Straordinaria"),
        )
        self.combo_filtro_manutenzioni_tipo.pack(side="left", padx=(6, 10))
        ttk.Label(frame_filtri_manut, text="Periodo:").pack(side="left")
        self.entry_filtro_manutenzioni_data_da = ttk.Entry(
            frame_filtri_manut,
            textvariable=self.var_filtro_manutenzioni_data_da,
            width=11,
        )
        self.entry_filtro_manutenzioni_data_da.pack(side="left", padx=(6, 4))
        ttk.Button(
            frame_filtri_manut,
            text="...",
            width=3,
            command=lambda: self._apri_calendario_filtro_periodo(self.var_filtro_manutenzioni_data_da),
        ).pack(side="left", padx=(0, 6))
        ttk.Label(frame_filtri_manut, text="a").pack(side="left")
        self.entry_filtro_manutenzioni_data_a = ttk.Entry(
            frame_filtri_manut,
            textvariable=self.var_filtro_manutenzioni_data_a,
            width=11,
        )
        self.entry_filtro_manutenzioni_data_a.pack(side="left", padx=(4, 10))
        ttk.Button(
            frame_filtri_manut,
            text="...",
            width=3,
            command=lambda: self._apri_calendario_filtro_periodo(self.var_filtro_manutenzioni_data_a),
        ).pack(side="left", padx=(0, 10))

        self._bind_placeholder_data_entry(
            self.entry_filtro_manutenzioni_data_da,
            self.var_filtro_manutenzioni_data_da,
        )
        self._bind_placeholder_data_entry(
            self.entry_filtro_manutenzioni_data_a,
            self.var_filtro_manutenzioni_data_a,
        )

        ttk.Button(
            frame_filtri_manut,
            text="Applica",
            command=lambda: self.carica_manutenzioni_macchinari(mostra_errori=False),
        ).pack(side="left")
        ttk.Button(
            frame_filtri_manut,
            text="Reset",
            command=self._reset_filtri_manutenzioni,
        ).pack(side="left", padx=(6, 0))

        self.entry_ricerca_manutenzioni.bind(
            "<Return>", lambda _event: self.carica_manutenzioni_macchinari(mostra_errori=False)
        )
        self.entry_ricerca_manutenzioni.bind(
            "<KeyRelease>", lambda _event: self.carica_manutenzioni_macchinari(mostra_errori=False)
        )
        self.entry_filtro_manutenzioni_data_da.bind(
            "<Return>", lambda _event: self.carica_manutenzioni_macchinari(mostra_errori=False)
        )
        self.entry_filtro_manutenzioni_data_da.bind(
            "<KeyRelease>", lambda _event: self.carica_manutenzioni_macchinari(mostra_errori=False)
        )
        self.entry_filtro_manutenzioni_data_a.bind(
            "<Return>", lambda _event: self.carica_manutenzioni_macchinari(mostra_errori=False)
        )
        self.entry_filtro_manutenzioni_data_a.bind(
            "<KeyRelease>", lambda _event: self.carica_manutenzioni_macchinari(mostra_errori=False)
        )
        self.combo_filtro_manutenzioni_tipo.bind(
            "<<ComboboxSelected>>", lambda _event: self.carica_manutenzioni_macchinari(mostra_errori=False)
        )

        cols_manut = ("id", "data", "tipo", "descrizione", "fornitore", "costo", "note")
        self.tree_manutenzioni = ttk.Treeview(frame_tabella_manut, columns=cols_manut, show="headings", height=1)
        self.tree_manutenzioni.heading("id", text="ID")
        self.tree_manutenzioni.heading("data", text="Data")
        self.tree_manutenzioni.heading("tipo", text="Tipo")
        self.tree_manutenzioni.heading("descrizione", text="Descrizione")
        self.tree_manutenzioni.heading("fornitore", text="Fornitore/Officina")
        self.tree_manutenzioni.heading("costo", text="Costo")
        self.tree_manutenzioni.heading("note", text="Note")

        self.tree_manutenzioni.column("id", width=60, anchor="center")
        self.tree_manutenzioni.column("data", width=90, anchor="center")
        self.tree_manutenzioni.column("tipo", width=120, anchor="center")
        self.tree_manutenzioni.column("descrizione", width=230, anchor="w")
        self.tree_manutenzioni.column("fornitore", width=180, anchor="w")
        self.tree_manutenzioni.column("costo", width=110, anchor="e")
        self.tree_manutenzioni.column("note", width=230, anchor="w")

        self.tree_manutenzioni.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        self._macchinari_adatta_altezza_tree(self.tree_manutenzioni, 1)
        self.abilita_a_capo_treeview(self.tree_manutenzioni, max_lines=3)
        self.tree_manutenzioni.bind("<Double-1>", lambda _event: self.prepara_modifica_manutenzione(mostra_errori=False))
        self.tree_manutenzioni.bind("<Delete>", lambda _event: self.elimina_manutenzione_selezionata())

        self.carica_macchinari(mostra_errori=False)

    def _reset_form_macchinario(self):
        self.var_macchinario_nome.set("")
        self.var_macchinario_marca.set("")
        self.var_macchinario_modello.set("")
        self.var_macchinario_identificativo.set("")
        self.var_macchinario_anno.set("")
        self.var_macchinario_note.set("")

    def _reset_form_manutenzione(self):
        self.var_manutenzione_data.set(datetime.now().strftime("%d/%m/%Y"))
        self.var_manutenzione_tipo.set("Ordinaria")
        self.var_manutenzione_descrizione.set("")
        self.var_manutenzione_fornitore.set("")
        self.var_manutenzione_costo.set("")
        self.var_manutenzione_note.set("")

    def _reset_filtri_macchinari(self):
        self.var_ricerca_macchinari.set("")
        self.var_filtro_macchinari_anno.set("")
        self.carica_macchinari(mostra_errori=False)

    def _reset_filtri_manutenzioni(self):
        self.var_ricerca_manutenzioni.set("")
        self.var_filtro_manutenzioni_tipo.set("Tutte")
        placeholder = getattr(self, "_placeholder_data_periodo", "GG/MM/AAAA")
        self.var_filtro_manutenzioni_data_da.set(placeholder)
        self.var_filtro_manutenzioni_data_a.set(placeholder)
        self.carica_manutenzioni_macchinari(mostra_errori=False)

    def _bind_placeholder_data_entry(self, entry_widget, text_var):
        placeholder = getattr(self, "_placeholder_data_periodo", "GG/MM/AAAA")

        def _on_focus_in(_event=None):
            if text_var.get().strip() == placeholder:
                text_var.set("")

        def _on_focus_out(_event=None):
            if not text_var.get().strip():
                text_var.set(placeholder)

        entry_widget.bind("<FocusIn>", _on_focus_in, add="+")
        entry_widget.bind("<FocusOut>", _on_focus_out, add="+")

        if not text_var.get().strip():
            text_var.set(placeholder)

    def _format_data_iso_to_it(self, data_iso: str) -> str:
        data_clean = (data_iso or "").strip()
        if not data_clean:
            return ""
        try:
            return datetime.strptime(data_clean, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return data_clean

    def _parse_data_it(self, data_text: str):
        value = (data_text or "").strip()
        placeholder = getattr(self, "_placeholder_data_periodo", "GG/MM/AAAA")
        if not value:
            return None
        if value == placeholder:
            return None
        try:
            return datetime.strptime(value, "%d/%m/%Y").date()
        except ValueError:
            return None

    def _parse_data_iso(self, data_text: str):
        value = (data_text or "").strip()
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _apri_calendario_filtro_periodo(self, target_var):
        date_text = target_var.get().strip()
        placeholder = getattr(self, "_placeholder_data_periodo", "GG/MM/AAAA")
        if date_text and date_text != placeholder:
            try:
                initial_date = datetime.strptime(date_text, "%d/%m/%Y").date()
            except ValueError:
                initial_date = datetime.now().date()
        else:
            initial_date = datetime.now().date()

        dialog_cls = getattr(self, "calendar_dialog_cls", None)
        root = getattr(self, "root", None)
        if dialog_cls is None or root is None:
            return

        scelta = dialog_cls(root, initial_date).show()
        if scelta is not None:
            target_var.set(scelta.strftime("%d/%m/%Y"))
            self.carica_manutenzioni_macchinari(mostra_errori=False)

    def _filtra_macchinari_entries(self, entries: list[dict]) -> list[dict]:
        ricerca = self.var_ricerca_macchinari.get().strip().lower()
        anno_filtro = self.var_filtro_macchinari_anno.get().strip()

        if not ricerca and not anno_filtro:
            return list(entries)

        filtrati = []
        for entry in entries:
            anno_value = entry.get("anno")
            anno_display = str(int(anno_value)) if isinstance(anno_value, int) else ""

            if anno_filtro and anno_filtro not in anno_display:
                continue

            searchable = " ".join(
                [
                    str(entry.get("nome") or ""),
                    str(entry.get("marca") or ""),
                    str(entry.get("modello") or ""),
                    str(entry.get("identificativo") or ""),
                    anno_display,
                    str(entry.get("note") or ""),
                ]
            ).lower()

            if ricerca and ricerca not in searchable:
                continue

            filtrati.append(entry)

        return filtrati

    def _filtra_manutenzioni_entries(self, entries: list[dict]) -> list[dict]:
        ricerca = self.var_ricerca_manutenzioni.get().strip().lower()
        tipo_filtro = self.var_filtro_manutenzioni_tipo.get().strip().lower()
        data_da = self._parse_data_it(self.var_filtro_manutenzioni_data_da.get())
        data_a = self._parse_data_it(self.var_filtro_manutenzioni_data_a.get())

        if data_da is not None and data_a is not None and data_da > data_a:
            data_da, data_a = data_a, data_da

        if not ricerca and tipo_filtro in ("", "tutte") and data_da is None and data_a is None:
            return list(entries)

        filtrati = []
        for entry in entries:
            tipo = (entry.get("tipo_manutenzione") or "").strip().upper()
            tipo_display = "Straordinaria" if tipo == "STRAORDINARIA" else "Ordinaria"

            if tipo_filtro == "ordinaria" and tipo != "ORDINARIA":
                continue
            if tipo_filtro == "straordinaria" and tipo != "STRAORDINARIA":
                continue

            data_entry = self._parse_data_iso(entry.get("data_manutenzione") or "")
            if data_da is not None and (data_entry is None or data_entry < data_da):
                continue
            if data_a is not None and (data_entry is None or data_entry > data_a):
                continue

            data_display = self._format_data_iso_to_it(entry.get("data_manutenzione") or "")
            costo = entry.get("costo")
            costo_display = format_eur(costo) if costo is not None else ""

            searchable = " ".join(
                [
                    data_display,
                    tipo_display,
                    str(entry.get("descrizione") or ""),
                    str(entry.get("fornitore") or ""),
                    costo_display,
                    str(entry.get("note") or ""),
                ]
            ).lower()

            if ricerca and ricerca not in searchable:
                continue

            filtrati.append(entry)

        return filtrati

    def _get_selected_macchinario_tree_values(self):
        if not hasattr(self, "tree_macchinari"):
            return None

        selected = self.tree_macchinari.selection()
        if not selected:
            return None

        values = self.tree_macchinari.item(selected[0], "values") or ()
        if not values:
            return None
        return values

    def _get_selected_manutenzione_tree_values(self):
        if not hasattr(self, "tree_manutenzioni"):
            return None

        selected = self.tree_manutenzioni.selection()
        if not selected:
            return None

        values = self.tree_manutenzioni.item(selected[0], "values") or ()
        if not values:
            return None
        return values

    def annulla_modifica_macchinario(self, reset_campi=False):
        self.macchinario_in_modifica_id = None
        if hasattr(self, "btn_annulla_modifica_macchinario"):
            self.btn_annulla_modifica_macchinario.config(state="disabled")
        if reset_campi:
            self._reset_form_macchinario()
        self.var_macchinario_stato.set("")

    def annulla_modifica_manutenzione(self, reset_campi=False):
        self.manutenzione_in_modifica_id = None
        if hasattr(self, "btn_annulla_modifica_manutenzione"):
            self.btn_annulla_modifica_manutenzione.config(state="disabled")
        if reset_campi:
            self._reset_form_manutenzione()
        self.var_manutenzione_stato.set("")

    def _format_macchinario_label(self, entry: dict) -> str:
        entry_id = int(entry.get("id") or 0)
        nome = (entry.get("nome") or "").strip() or "Macchinario"
        identificativo = (entry.get("identificativo") or "").strip()
        if identificativo:
            return f"{nome} - {identificativo}"
        return f"{nome} (ID {entry_id})"

    def _get_selected_macchinario_id(self) -> int:
        label = self.var_manutenzione_macchinario.get().strip()
        try:
            return int(self._map_macchinari_label_to_id.get(label) or 0)
        except (TypeError, ValueError):
            return 0

    def _set_selected_macchinario(self, macchinario_id: int) -> None:
        label = self._map_macchinari_id_to_label.get(int(macchinario_id or 0), "")
        if label:
            self.var_manutenzione_macchinario.set(label)

    def _aggiorna_selector_manutenzione(self, entries: list[dict]) -> None:
        previous_selected_id = self._get_selected_macchinario_id()

        label_to_id = {}
        id_to_label = {}
        labels = []
        for entry in entries:
            try:
                entry_id = int(entry.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if entry_id <= 0:
                continue

            base_label = self._format_macchinario_label(entry)
            label = base_label
            if label in label_to_id:
                label = f"{base_label} [ID {entry_id}]"

            label_to_id[label] = entry_id
            id_to_label[entry_id] = label
            labels.append(label)

        self._map_macchinari_label_to_id = label_to_id
        self._map_macchinari_id_to_label = id_to_label
        self.combo_manutenzione_macchinario.configure(values=labels)

        if previous_selected_id in id_to_label:
            self.var_manutenzione_macchinario.set(id_to_label[previous_selected_id])
        elif labels:
            self.var_manutenzione_macchinario.set(labels[0])
        else:
            self.var_manutenzione_macchinario.set("")

    def _aggiorna_visibilita_manutenzione(self, has_macchinari: bool) -> None:
        if has_macchinari:
            if self.lbl_manutenzione_non_disponibile.winfo_manager():
                self.lbl_manutenzione_non_disponibile.pack_forget()
            if not self.frame_manutenzione.winfo_manager():
                self.frame_manutenzione.pack(fill="x", pady=(14, 0))
            return

        if self.frame_manutenzione.winfo_manager():
            self.frame_manutenzione.pack_forget()
        if not self.lbl_manutenzione_non_disponibile.winfo_manager():
            self.lbl_manutenzione_non_disponibile.pack(anchor="w", pady=(14, 0))

        self.var_manutenzione_stato.set("")
        self.var_manutenzione_macchinario.set("")
        self.annulla_modifica_manutenzione(reset_campi=True)
        if hasattr(self, "tree_manutenzioni"):
            clear_treeview(self.tree_manutenzioni)
            self._macchinari_adatta_altezza_tree(self.tree_manutenzioni, 1)

    def _on_tree_macchinari_select(self, _event=None):
        values = self._get_selected_macchinario_tree_values()
        if not values:
            return

        try:
            macchinario_id = int(values[0] or 0)
        except (TypeError, ValueError):
            return
        if macchinario_id <= 0:
            return

        self._set_selected_macchinario(macchinario_id)
        self.carica_manutenzioni_macchinari(mostra_errori=False)

    def prepara_modifica_macchinario(self, _event=None, mostra_errori=True):
        values = self._get_selected_macchinario_tree_values()
        if not values:
            if mostra_errori:
                messagebox.showwarning("Attenzione", "Seleziona prima un macchinario da modificare.")
            return

        try:
            macchinario_id = int(values[0] or 0)
        except (TypeError, ValueError):
            if mostra_errori:
                messagebox.showwarning("Attenzione", "Macchinario selezionato non valido.")
            return
        if macchinario_id <= 0:
            if mostra_errori:
                messagebox.showwarning("Attenzione", "Macchinario selezionato non valido.")
            return

        self.macchinario_in_modifica_id = macchinario_id
        self.var_macchinario_nome.set(str(values[1] or ""))
        self.var_macchinario_marca.set(str(values[2] or ""))
        self.var_macchinario_modello.set(str(values[3] or ""))
        self.var_macchinario_identificativo.set(str(values[4] or ""))
        self.var_macchinario_anno.set(str(values[5] or ""))
        self.var_macchinario_note.set(str(values[6] or ""))

        if hasattr(self, "btn_annulla_modifica_macchinario"):
            self.btn_annulla_modifica_macchinario.config(state="normal")
        self.var_macchinario_stato.set(
            f"Modifica macchinario ID {macchinario_id} attiva. Premi 'Salva macchinario' per confermare."
        )

    def elimina_macchinario_selezionato(self):
        values = self._get_selected_macchinario_tree_values()
        if not values:
            messagebox.showwarning("Attenzione", "Seleziona prima un macchinario da eliminare.")
            return

        try:
            macchinario_id = int(values[0] or 0)
        except (TypeError, ValueError):
            messagebox.showwarning("Attenzione", "Macchinario selezionato non valido.")
            return
        if macchinario_id <= 0:
            messagebox.showwarning("Attenzione", "Macchinario selezionato non valido.")
            return

        nome = str(values[1] or "").strip() or "(senza nome)"
        identificativo = str(values[4] or "").strip()
        dettaglio = f"Nome: {nome}"
        if identificativo:
            dettaglio += f"\nIdentificativo: {identificativo}"

        conferma = messagebox.askyesno(
            "Conferma eliminazione",
            "Vuoi eliminare il macchinario selezionato?\n\n"
            + dettaglio
            + "\n\nLe manutenzioni collegate saranno eliminate.",
        )
        if not conferma:
            return

        try:
            manutenzioni_eliminate = delete_macchinario_entry(self.user_id, macchinario_id)
        except ValueError as e:
            messagebox.showerror("Errore", str(e))
            return
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        if self.macchinario_in_modifica_id == macchinario_id:
            self.annulla_modifica_macchinario(reset_campi=True)

        self.carica_macchinari(mostra_errori=False)
        msg = "Macchinario eliminato correttamente."
        if manutenzioni_eliminate > 0:
            msg += f" Manutenzioni collegate eliminate: {manutenzioni_eliminate}."
        messagebox.showinfo("Eliminazione completata", msg)

    def prepara_modifica_manutenzione(self, _event=None, mostra_errori=True):
        values = self._get_selected_manutenzione_tree_values()
        if not values:
            if mostra_errori:
                messagebox.showwarning("Attenzione", "Seleziona prima una manutenzione da modificare.")
            return

        try:
            manutenzione_id = int(values[0] or 0)
        except (TypeError, ValueError):
            if mostra_errori:
                messagebox.showwarning("Attenzione", "Manutenzione selezionata non valida.")
            return
        if manutenzione_id <= 0:
            if mostra_errori:
                messagebox.showwarning("Attenzione", "Manutenzione selezionata non valida.")
            return

        tipo_raw = str(values[2] or "").strip().lower()
        tipo = "Straordinaria" if tipo_raw.startswith("straord") else "Ordinaria"

        costo_text = str(values[5] or "").replace("EUR", "").strip()

        self.manutenzione_in_modifica_id = manutenzione_id
        self.var_manutenzione_data.set(str(values[1] or ""))
        self.var_manutenzione_tipo.set(tipo)
        self.var_manutenzione_descrizione.set(str(values[3] or ""))
        self.var_manutenzione_fornitore.set(str(values[4] or ""))
        self.var_manutenzione_costo.set(costo_text)
        self.var_manutenzione_note.set(str(values[6] or ""))

        if hasattr(self, "btn_annulla_modifica_manutenzione"):
            self.btn_annulla_modifica_manutenzione.config(state="normal")
        self.var_manutenzione_stato.set(
            f"Modifica manutenzione ID {manutenzione_id} attiva. Premi 'Salva manutenzione' per confermare."
        )

    def elimina_manutenzione_selezionata(self):
        values = self._get_selected_manutenzione_tree_values()
        if not values:
            messagebox.showwarning("Attenzione", "Seleziona prima una manutenzione da eliminare.")
            return

        try:
            manutenzione_id = int(values[0] or 0)
        except (TypeError, ValueError):
            messagebox.showwarning("Attenzione", "Manutenzione selezionata non valida.")
            return
        if manutenzione_id <= 0:
            messagebox.showwarning("Attenzione", "Manutenzione selezionata non valida.")
            return

        descrizione = str(values[3] or "").strip() or "(senza descrizione)"
        data = str(values[1] or "").strip()
        conferma = messagebox.askyesno(
            "Conferma eliminazione",
            "Vuoi eliminare la manutenzione selezionata?\n\n"
            + f"Data: {data}\n"
            + f"Descrizione: {descrizione}",
        )
        if not conferma:
            return

        try:
            deleted = delete_manutenzione_macchinario_entry(self.user_id, manutenzione_id)
            if not deleted:
                messagebox.showerror("Errore", "Manutenzione non trovata o non eliminabile.")
                return
        except ValueError as e:
            messagebox.showerror("Errore", str(e))
            return
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        if self.manutenzione_in_modifica_id == manutenzione_id:
            self.annulla_modifica_manutenzione(reset_campi=True)

        self.carica_manutenzioni_macchinari(mostra_errori=False)
        messagebox.showinfo("Eliminazione completata", "Manutenzione eliminata correttamente.")

    def salva_macchinario(self):
        nome = self.var_macchinario_nome.get().strip()
        if not nome:
            messagebox.showwarning("Dati mancanti", "Inserisci il nome del macchinario.")
            return

        in_modifica = self.macchinario_in_modifica_id is not None
        macchinario_id = int(self.macchinario_in_modifica_id or 0)

        try:
            if not in_modifica:
                add_macchinario_entry(
                    self.user_id,
                    nome=nome,
                    marca=self.var_macchinario_marca.get(),
                    modello=self.var_macchinario_modello.get(),
                    identificativo=self.var_macchinario_identificativo.get(),
                    anno=self.var_macchinario_anno.get(),
                    note=self.var_macchinario_note.get(),
                )
            else:
                updated = update_macchinario_entry(
                    self.user_id,
                    macchinario_id=macchinario_id,
                    nome=nome,
                    marca=self.var_macchinario_marca.get(),
                    modello=self.var_macchinario_modello.get(),
                    identificativo=self.var_macchinario_identificativo.get(),
                    anno=self.var_macchinario_anno.get(),
                    note=self.var_macchinario_note.get(),
                )
                if not updated:
                    messagebox.showerror("Errore", "Macchinario non trovato o non modificabile.")
                    return
        except ValueError as e:
            messagebox.showerror("Errore", str(e))
            return
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        if in_modifica:
            self.annulla_modifica_macchinario(reset_campi=True)
            self.var_macchinario_stato.set(f"Macchinario ID {macchinario_id} aggiornato correttamente.")
        else:
            self._reset_form_macchinario()
            self.var_macchinario_stato.set("Macchinario salvato correttamente.")

        self.carica_macchinari(mostra_errori=False)

    def salva_manutenzione_macchinario(self):
        macchinario_id = self._get_selected_macchinario_id()
        if macchinario_id <= 0:
            messagebox.showwarning("Dati mancanti", "Seleziona il macchinario da manutenere.")
            return

        data_text = self.var_manutenzione_data.get().strip()
        if not data_text:
            messagebox.showwarning("Dati mancanti", "Inserisci la data della manutenzione.")
            return
        try:
            data_iso = datetime.strptime(data_text, "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            messagebox.showwarning("Data non valida", "Inserisci una data valida nel formato GG/MM/AAAA.")
            return

        tipo_label = self.var_manutenzione_tipo.get().strip().lower()
        tipo_db = "STRAORDINARIA" if tipo_label.startswith("straord") else "ORDINARIA"

        descrizione = self.var_manutenzione_descrizione.get().strip()
        if not descrizione:
            messagebox.showwarning("Dati mancanti", "Inserisci una descrizione della manutenzione.")
            return

        costo_value = None
        costo_text = self.var_manutenzione_costo.get().strip()
        if costo_text:
            costo_value = parse_decimal(costo_text, allow_zero=True, allow_negative=False)
            if costo_value is None:
                messagebox.showwarning("Costo non valido", "Inserisci un costo numerico valido (es. 1200,50).")
                return

        in_modifica = self.manutenzione_in_modifica_id is not None
        manutenzione_id = int(self.manutenzione_in_modifica_id or 0)

        try:
            if not in_modifica:
                add_manutenzione_macchinario_entry(
                    self.user_id,
                    macchinario_id=macchinario_id,
                    data_manutenzione=data_iso,
                    tipo_manutenzione=tipo_db,
                    descrizione=descrizione,
                    costo=costo_value,
                    fornitore=self.var_manutenzione_fornitore.get(),
                    note=self.var_manutenzione_note.get(),
                )
            else:
                updated = update_manutenzione_macchinario_entry(
                    self.user_id,
                    manutenzione_id=manutenzione_id,
                    macchinario_id=macchinario_id,
                    data_manutenzione=data_iso,
                    tipo_manutenzione=tipo_db,
                    descrizione=descrizione,
                    costo=costo_value,
                    fornitore=self.var_manutenzione_fornitore.get(),
                    note=self.var_manutenzione_note.get(),
                )
                if not updated:
                    messagebox.showerror("Errore", "Manutenzione non trovata o non modificabile.")
                    return
        except ValueError as e:
            messagebox.showerror("Errore", str(e))
            return
        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        if in_modifica:
            self.annulla_modifica_manutenzione(reset_campi=True)
            self.var_manutenzione_stato.set(f"Manutenzione ID {manutenzione_id} aggiornata correttamente.")
        else:
            self._reset_form_manutenzione()
            self.var_manutenzione_stato.set("Manutenzione salvata correttamente.")

        self.carica_manutenzioni_macchinari(mostra_errori=False)

    def carica_macchinari(self, mostra_errori=True):
        if not hasattr(self, "tree_macchinari"):
            return

        clear_treeview(self.tree_macchinari)

        try:
            entries = list_macchinari_entries(self.user_id)
        except sqlite3.Error as e:
            if mostra_errori:
                messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        self._aggiorna_selector_manutenzione(entries)
        self._aggiorna_visibilita_manutenzione(bool(entries))

        if self.macchinario_in_modifica_id is not None:
            in_lista = any(int(entry.get("id") or 0) == int(self.macchinario_in_modifica_id) for entry in entries)
            if not in_lista:
                self.annulla_modifica_macchinario(reset_campi=True)

        entries_filtrati = self._filtra_macchinari_entries(entries)

        for entry in entries_filtrati:
            anno_value = entry.get("anno")
            anno_display = str(int(anno_value)) if isinstance(anno_value, int) else ""
            self.tree_macchinari.insert(
                "",
                "end",
                values=(
                    entry.get("id", ""),
                    entry.get("nome", ""),
                    entry.get("marca", ""),
                    entry.get("modello", ""),
                    entry.get("identificativo", ""),
                    anno_display,
                    entry.get("note", ""),
                ),
            )

        self._macchinari_adatta_altezza_tree(self.tree_macchinari, len(entries_filtrati))

        if entries:
            self.carica_manutenzioni_macchinari(mostra_errori=False)
        else:
            self.annulla_modifica_manutenzione(reset_campi=True)

    def carica_manutenzioni_macchinari(self, mostra_errori=True):
        if not hasattr(self, "tree_manutenzioni"):
            return

        clear_treeview(self.tree_manutenzioni)
        self._macchinari_adatta_altezza_tree(self.tree_manutenzioni, 1)

        macchinario_id = self._get_selected_macchinario_id()
        if macchinario_id <= 0:
            return

        try:
            entries = list_manutenzioni_macchinari_entries(self.user_id, macchinario_id=macchinario_id)
        except sqlite3.Error as e:
            if mostra_errori:
                messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        if self.manutenzione_in_modifica_id is not None:
            in_lista = any(int(entry.get("id") or 0) == int(self.manutenzione_in_modifica_id) for entry in entries)
            if not in_lista:
                self.annulla_modifica_manutenzione(reset_campi=True)

        entries_filtrati = self._filtra_manutenzioni_entries(entries)

        for entry in entries_filtrati:
            data_display = self._format_data_iso_to_it(entry.get("data_manutenzione") or "")

            tipo = (entry.get("tipo_manutenzione") or "").strip().upper()
            if tipo == "STRAORDINARIA":
                tipo_display = "Straordinaria"
            else:
                tipo_display = "Ordinaria"

            costo = entry.get("costo")
            costo_display = format_eur(costo) if costo is not None else ""

            self.tree_manutenzioni.insert(
                "",
                "end",
                values=(
                    entry.get("id", ""),
                    data_display,
                    tipo_display,
                    entry.get("descrizione", ""),
                    entry.get("fornitore", ""),
                    costo_display,
                    entry.get("note", ""),
                ),
            )

        self._macchinari_adatta_altezza_tree(self.tree_manutenzioni, len(entries_filtrati))
