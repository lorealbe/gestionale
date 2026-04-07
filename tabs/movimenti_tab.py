import tkinter as tk
import importlib
import re
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

from app_utils import clear_treeview, format_number, is_blank, parse_decimal
from database import (
    get_conn,
    get_fatture_user_dir,
    list_azienda_animali_entries,
    set_movimento_animali_links,
    to_storage_fattura_path,
    LITRI_PER_QUINTALE,
)
from services.product_parser_utils import (
    build_basic_product_storage_line,
    build_detailed_product_storage_line,
    normalize_cost_type,
    serialize_product_storage_lines,
)


class MovimentiTabMixin:
    _PARSER_DB_FIELDS = (
        "invoice_number",
        "invoice_date",
        "due_date",
        "supplier_name",
        "supplier_vat",
        "customer_name",
        "customer_vat",
        "total_amount",
        "taxable_total",
        "vat_total",
        "payment_terms",
        "warnings",
        "products",
        "fields_view",
    )

    def setup_tab_movimenti(self):
        content = self.crea_container_scorribile(self.tab_movimenti)

        ttk.Label(content, text="Registra Movimento", font=("Arial", 14, "bold")).pack(pady=10)

        self.var_data = tk.StringVar(value=datetime.now().strftime("%d/%m/%Y"))
        self.var_tipo = tk.StringVar(value="ENTRATA")
        self.var_cat = tk.StringVar()
        self.var_desc = tk.StringVar()
        self.var_imp = tk.StringVar()
        self.var_iva = tk.StringVar(value="0,00")

        self.crea_campo_data(content, "Data:", self.var_data)

        frame_tipo = ttk.Frame(content)
        frame_tipo.pack(fill="x", padx=20, pady=5)
        ttk.Label(frame_tipo, text="Tipo:", width=20).pack(side="left")
        frame_radio = ttk.Frame(frame_tipo)
        frame_radio.pack(side="left", fill="x", expand=True)

        ttk.Radiobutton(frame_radio, text="Entrata", value="ENTRATA", variable=self.var_tipo).pack(side="left", padx=(0, 15))
        ttk.Radiobutton(frame_radio, text="Uscita", value="USCITA", variable=self.var_tipo).pack(side="left")

        self.crea_campo_categoria(content, "Categoria:", self.var_cat)
        self.crea_campo(content, "Descrizione:", self.var_desc)
        self.crea_campo(content, "Importo (EUR):", self.var_imp)
        self.crea_campo(content, "IVA (EUR):", self.var_iva)

        self.var_nome_fattura_mov = tk.StringVar(value="Nessuna fattura caricata")
        frame_fattura = ttk.Frame(content)
        frame_fattura.pack(fill="x", padx=20, pady=(0, 6))

        ttk.Label(frame_fattura, text="Fattura caricata:", width=20).pack(side="left")
        ttk.Label(frame_fattura, textvariable=self.var_nome_fattura_mov).pack(side="left", fill="x", expand=True)
        ttk.Button(frame_fattura, text="Rimuovi", command=self.rimuovi_fattura_movimento).pack(side="right")

        self._setup_tabella_prodotti_fattura_movimento(content)

        frame_actions = ttk.Frame(content)
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

    def _setup_tabella_prodotti_fattura_movimento(self, parent):
        frame_prodotti = ttk.LabelFrame(parent, text="Prodotti rilevati in fattura")
        frame_prodotti.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        self.var_fattura_prodotti_mov_stato = tk.StringVar(
            value="Importa una fattura PDF per vedere il riepilogo prodotti."
        )
        ttk.Label(frame_prodotti, textvariable=self.var_fattura_prodotti_mov_stato).pack(
            anchor="w", padx=8, pady=(6, 4)
        )

        frame_table = ttk.Frame(frame_prodotti)
        frame_table.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        cols = (
            "n",
            "descrizione",
            "qta",
            "prezzo_unitario",
            "aliquota_iva",
            "totale_riga",
            "natura_costo",
            "gruppi_imputazione",
        )
        self.tree_fattura_prodotti_mov = ttk.Treeview(frame_table, columns=cols, show="headings", height=6)

        self.tree_fattura_prodotti_mov.heading("n", text="#")
        self.tree_fattura_prodotti_mov.heading("descrizione", text="Descrizione")
        self.tree_fattura_prodotti_mov.heading("qta", text="Quantita")
        self.tree_fattura_prodotti_mov.heading("prezzo_unitario", text="Prezzo unit.")
        self.tree_fattura_prodotti_mov.heading("aliquota_iva", text="IVA %")
        self.tree_fattura_prodotti_mov.heading("totale_riga", text="Totale")
        self.tree_fattura_prodotti_mov.heading("natura_costo", text="Tipo costo")
        self.tree_fattura_prodotti_mov.heading("gruppi_imputazione", text="Imputazione gruppi")

        self.tree_fattura_prodotti_mov.column("n", width=40, anchor="center", stretch=False)
        self.tree_fattura_prodotti_mov.column("descrizione", width=300, anchor="w")
        self.tree_fattura_prodotti_mov.column("qta", width=90, anchor="e")
        self.tree_fattura_prodotti_mov.column("prezzo_unitario", width=110, anchor="e")
        self.tree_fattura_prodotti_mov.column("aliquota_iva", width=80, anchor="e")
        self.tree_fattura_prodotti_mov.column("totale_riga", width=110, anchor="e")
        self.tree_fattura_prodotti_mov.column("natura_costo", width=110, anchor="center")
        self.tree_fattura_prodotti_mov.column("gruppi_imputazione", width=260, anchor="w")

        self._fattura_prodotti_item_to_row = {}
        self._fattura_prodotti_combo_editor = None
        self._fattura_prodotti_gruppi_combo_editor = None
        self._fattura_prodotti_gruppi_popup_editor = None
        self._fattura_prodotti_gruppi_popup_bind_id = None
        self.tree_fattura_prodotti_mov.bind("<Double-1>", self._on_doppio_click_tabella_prodotti_mov)

        scroll = ttk.Scrollbar(frame_table, orient="vertical", command=self.tree_fattura_prodotti_mov.yview)
        self.tree_fattura_prodotti_mov.configure(yscrollcommand=scroll.set)

        self.tree_fattura_prodotti_mov.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _aggiorna_tabella_prodotti_fattura_movimento(self, parser_data):
        if not hasattr(self, "tree_fattura_prodotti_mov"):
            return

        self._chiudi_editor_tipo_costo_prodotto()
        self._chiudi_editor_gruppi_imputazione_prodotto()
        clear_treeview(self.tree_fattura_prodotti_mov)
        self._fattura_prodotti_item_to_row = {}

        righe = []
        if isinstance(parser_data, dict):
            raw_rows = parser_data.get("products_rows")
            if isinstance(raw_rows, list):
                righe = raw_rows

        opzioni_gruppi = self._opzioni_gruppi_imputazione_costi_prodotti()

        if not righe:
            if hasattr(self, "var_fattura_prodotti_mov_stato"):
                self.var_fattura_prodotti_mov_stato.set("Nessun prodotto rilevato nella fattura selezionata.")
            return

        for idx, riga in enumerate(righe, start=1):
            tipo_costo = self._normalizza_tipo_costo_prodotto(riga.get("cost_type"))
            riga["cost_type"] = tipo_costo

            selected_group_ids = riga.get("group_entry_ids")
            self._aggiorna_allocazione_gruppi_prodotto(
                riga,
                selected_group_ids,
                opzioni_gruppi,
                default_all_if_empty=True,
            )

            item_id = self.tree_fattura_prodotti_mov.insert(
                "",
                "end",
                values=(
                    idx,
                    riga.get("description", "-") or "-",
                    riga.get("quantity", "-") or "-",
                    riga.get("unit_price", "-") or "-",
                    riga.get("vat_rate", "-") or "-",
                    riga.get("line_total", "-") or "-",
                    tipo_costo,
                    riga.get("groups_text_display", "-"),
                ),
            )
            self._fattura_prodotti_item_to_row[item_id] = riga

        self._sincronizza_products_parser_da_tabella()

        if hasattr(self, "var_fattura_prodotti_mov_stato"):
            self.var_fattura_prodotti_mov_stato.set(f"Prodotti rilevati: {len(righe)}")

    def _normalizza_tipo_costo_prodotto(self, raw_value):
        return normalize_cost_type(raw_value)

    def _opzioni_gruppi_imputazione_costi_prodotti(self):
        try:
            entries = list_azienda_animali_entries(self.user_id)
        except sqlite3.Error:
            return []

        opzioni = []
        for entry in entries:
            entry_id = int(entry.get("id", 0) or 0)
            capi = int(entry.get("capi", 0) or 0)
            if entry_id <= 0 or capi <= 0:
                continue

            if hasattr(self, "_label_gruppo_animale_movimento"):
                label = self._label_gruppo_animale_movimento(entry)
            else:
                group_name = (entry.get("group_name") or "").strip()
                label = group_name or f"Gruppo {entry_id}"

            opzioni.append({"id": entry_id, "label": label})

        opzioni.sort(key=lambda item: (item["label"].lower(), item["id"]))
        return opzioni

    def _aggiorna_allocazione_gruppi_prodotto(self, row, selected_group_ids, opzioni_gruppi, default_all_if_empty):
        label_by_id = {opt["id"]: opt["label"] for opt in opzioni_gruppi}

        normalized_ids = []
        if isinstance(selected_group_ids, (list, tuple, set)):
            for raw in selected_group_ids:
                try:
                    entry_id = int(raw)
                except (TypeError, ValueError):
                    continue

                if entry_id not in label_by_id:
                    continue
                if entry_id in normalized_ids:
                    continue
                normalized_ids.append(entry_id)

        if not normalized_ids and default_all_if_empty and opzioni_gruppi:
            normalized_ids = [opt["id"] for opt in opzioni_gruppi]

        labels = [label_by_id[entry_id] for entry_id in normalized_ids if entry_id in label_by_id]
        if opzioni_gruppi and normalized_ids and len(normalized_ids) == len(opzioni_gruppi):
            groups_text = "Tutti i gruppi"
        elif labels:
            groups_text = ", ".join(labels)
        elif opzioni_gruppi:
            groups_text = "Nessun gruppo"
        else:
            groups_text = "Nessun gruppo disponibile"

        row["group_entry_ids"] = normalized_ids
        row["group_labels"] = labels
        row["groups_text_display"] = groups_text

    def _sincronizza_products_parser_da_tabella(self):
        parser_data = getattr(self, "pending_parser_movimento_data", None)
        if not isinstance(parser_data, dict):
            return

        righe = parser_data.get("products_rows")
        if not isinstance(righe, list):
            return

        prodotti = []
        for riga in righe:
            descrizione = str(riga.get("description") or "-").strip() or "-"
            quantita = str(riga.get("quantity") or "-").strip() or "-"
            totale = str(riga.get("line_total") or "-").strip() or "-"
            tipo_costo = self._normalizza_tipo_costo_prodotto(riga.get("cost_type"))
            gruppi_text = str(riga.get("groups_text_display") or "Nessun gruppo").strip() or "Nessun gruppo"

            riga["cost_type"] = tipo_costo
            riga["groups_text_display"] = gruppi_text
            if not self._totale_riga_prodotto_salvabile_db(riga):
                continue

            prodotti.append(
                build_detailed_product_storage_line(
                    descrizione,
                    quantita,
                    totale,
                    tipo_costo,
                    gruppi_text,
                )
            )

        parser_data["products"] = serialize_product_storage_lines(prodotti, separator="\n")

    def _totale_riga_prodotto_salvabile_db(self, row):
        if not isinstance(row, dict):
            return False

        quantita = self._valore_parser_to_float(row.get("quantity"), allow_zero=True)
        if quantita is None or quantita <= 0:
            return False

        totale = self._valore_parser_to_float(row.get("line_total"), allow_zero=True)
        if totale is None:
            return False
        return totale > 0

    def _gruppi_animali_da_prodotti_parser(self, parser_data):
        if not isinstance(parser_data, dict):
            return None

        righe = parser_data.get("products_rows")
        if not isinstance(righe, list):
            return None

        gruppi_ids = []
        for riga in righe:
            if not isinstance(riga, dict):
                continue
            if not self._totale_riga_prodotto_salvabile_db(riga):
                continue

            raw_ids = riga.get("group_entry_ids")
            if not isinstance(raw_ids, (list, tuple, set)):
                continue

            for raw in raw_ids:
                try:
                    entry_id = int(raw)
                except (TypeError, ValueError):
                    continue

                if entry_id <= 0 or entry_id in gruppi_ids:
                    continue
                gruppi_ids.append(entry_id)

        return gruppi_ids

    def _chiudi_editor_tipo_costo_prodotto(self):
        editor = getattr(self, "_fattura_prodotti_combo_editor", None)
        if editor is not None and editor.winfo_exists():
            editor.destroy()
        self._fattura_prodotti_combo_editor = None

    def _chiudi_editor_gruppi_imputazione_prodotto(self):
        editor = getattr(self, "_fattura_prodotti_gruppi_combo_editor", None)
        if editor is not None and editor.winfo_exists():
            editor.destroy()
        self._fattura_prodotti_gruppi_combo_editor = None

        popup = getattr(self, "_fattura_prodotti_gruppi_popup_editor", None)
        if popup is not None and popup.winfo_exists():
            popup.destroy()
        self._fattura_prodotti_gruppi_popup_editor = None

        bind_id = getattr(self, "_fattura_prodotti_gruppi_popup_bind_id", None)
        if bind_id and hasattr(self, "root"):
            try:
                self.root.unbind("<Button-1>", bind_id)
            except tk.TclError:
                pass
        self._fattura_prodotti_gruppi_popup_bind_id = None

    def _widget_dentro_editor_gruppi_imputazione(self, widget):
        popup = getattr(self, "_fattura_prodotti_gruppi_popup_editor", None)
        if popup is None or not popup.winfo_exists() or widget is None:
            return False

        popup_name = str(popup)
        widget_name = str(widget)
        return widget_name == popup_name or widget_name.startswith(popup_name + ".")

    def _selected_group_ids_for_row(self, row, opzioni_gruppi):
        valid_ids = {opt["id"] for opt in opzioni_gruppi}
        selected_ids = []

        for raw in row.get("group_entry_ids") or []:
            try:
                entry_id = int(raw)
            except (TypeError, ValueError):
                continue

            if entry_id not in valid_ids or entry_id in selected_ids:
                continue
            selected_ids.append(entry_id)

        if not selected_ids and opzioni_gruppi:
            selected_ids = [opt["id"] for opt in opzioni_gruppi]

        return selected_ids

    def _apply_group_selection_to_row(self, row, item_id, column_name, selected_ids, opzioni_gruppi):
        self._aggiorna_allocazione_gruppi_prodotto(
            row,
            list(selected_ids),
            opzioni_gruppi,
            default_all_if_empty=False,
        )
        self.tree_fattura_prodotti_mov.set(item_id, column_name, row.get("groups_text_display", "-"))
        self._sincronizza_products_parser_da_tabella()

    def _on_doppio_click_tabella_prodotti_mov(self, event):
        if not hasattr(self, "tree_fattura_prodotti_mov"):
            return

        tree = self.tree_fattura_prodotti_mov
        if tree.identify("region", event.x, event.y) != "cell":
            return

        item_id = tree.identify_row(event.y)
        col_id = tree.identify_column(event.x)
        if not item_id or not col_id:
            return

        try:
            col_index = int(col_id[1:]) - 1
        except (TypeError, ValueError):
            return

        columns = tree.cget("columns")
        if col_index < 0 or col_index >= len(columns):
            return

        column_name = columns[col_index]
        if column_name == "natura_costo":
            self._apri_editor_tipo_costo_prodotto(item_id, column_name)
        elif column_name == "gruppi_imputazione":
            self._apri_editor_gruppi_imputazione_prodotto(item_id, column_name)

    def _apri_editor_tipo_costo_prodotto(self, item_id, column_name):
        tree = self.tree_fattura_prodotti_mov
        row = self._fattura_prodotti_item_to_row.get(item_id)
        if not isinstance(row, dict):
            return

        bbox = tree.bbox(item_id, column_name)
        if not bbox:
            return

        x, y, width, height = bbox
        self._chiudi_editor_tipo_costo_prodotto()

        combo = ttk.Combobox(tree, values=("Variabili", "Fissi"), state="readonly")
        combo.place(x=x, y=y, width=width, height=height)
        combo.set(self._normalizza_tipo_costo_prodotto(row.get("cost_type")))
        combo.focus_set()
        self._fattura_prodotti_combo_editor = combo

        def _commit(_event=None):
            value = self._normalizza_tipo_costo_prodotto(combo.get())
            row["cost_type"] = value
            tree.set(item_id, column_name, value)
            self._sincronizza_products_parser_da_tabella()
            self._chiudi_editor_tipo_costo_prodotto()

        combo.bind("<<ComboboxSelected>>", _commit)
        combo.bind("<Return>", _commit)
        combo.bind("<KP_Enter>", _commit)
        combo.bind("<FocusOut>", _commit)
        combo.bind("<Escape>", lambda _event: self._chiudi_editor_tipo_costo_prodotto())

    def _apri_editor_gruppi_imputazione_prodotto(self, item_id, column_name):
        tree = self.tree_fattura_prodotti_mov
        row = self._fattura_prodotti_item_to_row.get(item_id)
        if not isinstance(row, dict):
            return

        self._chiudi_editor_tipo_costo_prodotto()
        self._chiudi_editor_gruppi_imputazione_prodotto()

        bbox = tree.bbox(item_id, column_name)
        if not bbox:
            return

        opzioni_gruppi = self._opzioni_gruppi_imputazione_costi_prodotti()
        if not opzioni_gruppi:
            messagebox.showwarning(
                "Imputazione gruppi",
                "Nessun gruppo disponibile. Configura i gruppi in Azienda > Tipi Allevamento.",
            )
            return

        x, y, width, height = bbox
        selected_ids = self._selected_group_ids_for_row(row, opzioni_gruppi)

        popup = tk.Toplevel(self.root)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.configure(borderwidth=1, relief="solid", background="white")
        popup.attributes("-topmost", True)
        self._fattura_prodotti_gruppi_popup_editor = popup

        frame = ttk.Frame(popup, padding=6)
        frame.pack(fill="both", expand=True)

        top_row = ttk.Frame(frame)
        top_row.pack(fill="x", pady=(0, 4))

        listbox_frame = ttk.Frame(frame)
        listbox_frame.pack(fill="both", expand=True)

        listbox = tk.Listbox(
            listbox_frame,
            selectmode=tk.MULTIPLE,
            exportselection=False,
            activestyle="none",
            height=9,
        )
        listbox.configure(selectbackground="#2E6FD8", selectforeground="white")

        scrollbar = ttk.Scrollbar(listbox_frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)

        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ids_by_index = []
        selected_set = set(selected_ids)
        for idx, opt in enumerate(opzioni_gruppi):
            ids_by_index.append(opt["id"])
            listbox.insert(tk.END, opt["label"])
            if opt["id"] in selected_set:
                listbox.selection_set(idx)

        def _apply_from_listbox(_event=None):
            nuovi_ids = [ids_by_index[idx] for idx in listbox.curselection() if 0 <= idx < len(ids_by_index)]
            self._apply_group_selection_to_row(row, item_id, column_name, nuovi_ids, opzioni_gruppi)

        def _select_all():
            listbox.selection_set(0, tk.END)
            _apply_from_listbox()

        def _clear_all():
            listbox.selection_clear(0, tk.END)
            _apply_from_listbox()

        ttk.Button(top_row, text="Seleziona tutti", command=_select_all).pack(side="left")
        ttk.Button(top_row, text="Deseleziona", command=_clear_all).pack(side="left", padx=(4, 0))
        ttk.Button(top_row, text="Chiudi", command=self._chiudi_editor_gruppi_imputazione_prodotto).pack(side="right")

        listbox.bind("<<ListboxSelect>>", _apply_from_listbox)

        popup.update_idletasks()
        popup_w = max(width, popup.winfo_reqwidth(), 360)
        popup_h = min(max(popup.winfo_reqheight(), 180), 320)

        def _center_popup():
            try:
                screen_w = self.root.winfo_screenwidth()
                screen_h = self.root.winfo_screenheight()
            except tk.TclError:
                screen_w = popup.winfo_screenwidth()
                screen_h = popup.winfo_screenheight()

            pos_x = max(int((screen_w - popup_w) / 2), 0)
            pos_y = max(int((screen_h - popup_h) / 2), 0)
            popup.geometry(f"{popup_w}x{popup_h}+{pos_x}+{pos_y}")

        _center_popup()
        popup.deiconify()
        popup.after_idle(_center_popup)

        def _close_on_outside_click(event_click):
            current = getattr(self, "_fattura_prodotti_gruppi_popup_editor", None)
            if current is None or not current.winfo_exists():
                self._chiudi_editor_gruppi_imputazione_prodotto()
                return

            if self._widget_dentro_editor_gruppi_imputazione(event_click.widget):
                return

            self._chiudi_editor_gruppi_imputazione_prodotto()

        def _bind_outside_click():
            if not hasattr(self, "root"):
                return
            bind_id = self.root.bind("<Button-1>", _close_on_outside_click, add="+")
            self._fattura_prodotti_gruppi_popup_bind_id = bind_id

        popup.after(80, _bind_outside_click)
        popup.bind("<Escape>", lambda _event: self._chiudi_editor_gruppi_imputazione_prodotto())
        popup.lift()
        listbox.focus_set()

    def _valore_parser_to_text(self, value, decimals=2):
        number = self._valore_parser_to_float(value, allow_zero=True)
        if number is not None:
            return format_number(number, decimals)

        if value in (None, ""):
            return "-"
        return str(value).strip()

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
                parser_data = getattr(self, "pending_parser_movimento_data", None)
                parser_values = self._estrai_valori_parser_db(parser_data)
                selected_animali_entry_ids = self._gruppi_animali_da_prodotti_parser(parser_data)
                if (
                    selected_animali_entry_ids is None
                    and hasattr(self, "listbox_movimento_animali")
                    and hasattr(self, "get_gruppi_animali_movimento_selezionati_ids")
                ):
                    selected_animali_entry_ids = self.get_gruppi_animali_movimento_selezionati_ids()

                if self.movimento_in_modifica_id is None:
                    c.execute(
                        '''
                        INSERT INTO movimenti (
                            user_id, data_op, tipo, categoria, descrizione, importo, iva_importo,
                            parser_invoice_number, parser_invoice_date, parser_due_date,
                            parser_supplier_name, parser_supplier_vat,
                            parser_customer_name, parser_customer_vat,
                            parser_total_amount, parser_taxable_total, parser_vat_total,
                            parser_payment_terms, parser_warnings, parser_products, parser_fields_view
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                        (
                            self.user_id,
                            data_db,
                            self.var_tipo.get(),
                            self.var_cat.get().strip(),
                            self.var_desc.get().strip(),
                            importo_val,
                            iva_val,
                            *parser_values,
                        ),
                    )
                    movimento_salvato_id = c.lastrowid
                    msg_ok = "Movimento salvato nel database!"
                else:
                    if parser_data is not None:
                        c.execute(
                            '''
                            UPDATE movimenti
                            SET data_op=?, tipo=?, categoria=?, descrizione=?, importo=?, iva_importo=?,
                                parser_invoice_number=?, parser_invoice_date=?, parser_due_date=?,
                                parser_supplier_name=?, parser_supplier_vat=?,
                                parser_customer_name=?, parser_customer_vat=?,
                                parser_total_amount=?, parser_taxable_total=?, parser_vat_total=?,
                                parser_payment_terms=?, parser_warnings=?, parser_products=?, parser_fields_view=?
                            WHERE id=? AND user_id=?
                        ''',
                            (
                                data_db,
                                self.var_tipo.get(),
                                self.var_cat.get().strip(),
                                self.var_desc.get().strip(),
                                importo_val,
                                iva_val,
                                *parser_values,
                                self.movimento_in_modifica_id,
                                self.user_id,
                            ),
                        )
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

                if selected_animali_entry_ids is not None and movimento_salvato_id is not None:
                    set_movimento_animali_links(
                        self.user_id,
                        movimento_salvato_id,
                        selected_animali_entry_ids,
                        cursor=c,
                    )

            messagebox.showinfo("Successo", msg_ok)
            self.annulla_modifica_movimento()
            self.rimuovi_fattura_movimento()
            self.carica_movimenti()
            if hasattr(self, "carica_movimenti_azienda_storico"):
                self.carica_movimenti_azienda_storico(mostra_errori=False)
        except (sqlite3.Error, ValueError) as e:
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
        self.pending_parser_movimento_data = None
        self.var_nome_fattura_mov.set(Path(percorso_archiviato).name)
        self._aggiorna_tabella_prodotti_fattura_movimento(None)

        try:
            dati = self.analizza_fattura_con_parser_fatture(percorso_archiviato, file_path)
        except Exception as e:
            messagebox.showwarning(
                "Analisi non completata",
                f"Fattura salvata correttamente, ma analisi automatica non disponibile: {e}",
            )
            return

        self._applica_dati_parser_al_form(dati)
        self.pending_parser_movimento_data = dati.get("parser_data")
        self._aggiorna_tabella_prodotti_fattura_movimento(self.pending_parser_movimento_data)

        if is_blank(self.var_imp.get()):
            messagebox.showwarning("Attenzione", "Importo non trovato automaticamente. Verificalo manualmente.")
            return

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
        self.pending_parser_movimento_data = None
        if hasattr(self, "var_nome_fattura_mov"):
            self.var_nome_fattura_mov.set("Nessuna fattura caricata")
        self._aggiorna_tabella_prodotti_fattura_movimento(None)

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
        self.pending_parser_latte_data = None
        if hasattr(self, "var_nome_fattura_latte"):
            self.var_nome_fattura_latte.set(Path(percorso_archiviato).name)

        try:
            dati_latte = self.analizza_fattura_latte_con_parser_fatture(percorso_archiviato, file_path)
        except Exception as e:
            messagebox.showwarning(
                "Analisi non completata",
                f"Fattura salvata correttamente, ma analisi automatica non disponibile: {e}",
            )
            return

        self._applica_dati_parser_al_form_latte(dati_latte)
        self.pending_parser_latte_data = dati_latte.get("parser_data")

        iva_label = format_number(dati_latte.get("iva_percent", 0.0), 2)
        messagebox.showinfo(
            "Importazione completata",
            "Valori produzione impostati da fattura:\n"
            f"- Quintali: {self.var_latte_quintali.get()}\n"
            f"- Prezzo al litro (IVA inclusa): {self.var_latte_prezzo.get()}\n"
            f"- Aliquota IVA applicata: {iva_label}%",
        )

    def rimuovi_fattura_latte(self):
        self.pending_fattura_latte_id = None
        self.pending_fattura_latte_path = None
        self.pending_parser_latte_data = None
        if hasattr(self, "var_nome_fattura_latte"):
            self.var_nome_fattura_latte.set("Nessuna fattura caricata")

    def _applica_dati_parser_al_form(self, dati):
        mapping = (
            ("data", self.var_data),
            ("tipo", self.var_tipo),
            ("categoria", self.var_cat),
            ("descrizione", self.var_desc),
            ("importo", self.var_imp),
            ("iva", self.var_iva),
        )
        for chiave, variabile in mapping:
            valore = dati.get(chiave)
            if valore:
                variabile.set(valore)

    def _applica_dati_parser_al_form_latte(self, dati):
        mapping = (
            ("data", "var_latte_data"),
            ("quintali", "var_latte_quintali"),
            ("prezzo_litro", "var_latte_prezzo"),
        )
        for chiave, attr_name in mapping:
            variabile = getattr(self, attr_name, None)
            if variabile is None:
                continue
            valore = dati.get(chiave)
            if valore:
                variabile.set(valore)

    def analizza_fattura_latte_con_parser_fatture(self, pdf_path, file_path):
        parse_invoice_pdf = self._get_parser_fatture_function()
        risultato = parse_invoice_pdf(str(pdf_path))
        fields = getattr(risultato, "fields", {}) or {}
        parser_data = self._costruisci_dati_parser_movimento(risultato, fields)

        data_raw = self._estrai_valore_campo_parser(fields, "invoice_date")
        data_out = self._normalizza_data_fattura(data_raw) or datetime.now().strftime("%d/%m/%Y")

        line_items = getattr(risultato, "line_items", []) or []
        linea_latte = self._seleziona_linea_latte(line_items)
        if linea_latte is None:
            raise RuntimeError(
                "Impossibile individuare riga prodotto latte con quantita e prezzo validi nella fattura."
            )

        quintali = self._valore_parser_to_float(getattr(linea_latte, "quantity", None), allow_zero=False)
        if quintali is None or quintali <= 0:
            raise RuntimeError("Quantita in quintali non trovata o non valida nella fattura.")

        prezzo_quintale = self._valore_parser_to_float(getattr(linea_latte, "unit_price", None), allow_zero=False)
        if prezzo_quintale is None:
            line_total = self._valore_parser_to_float(getattr(linea_latte, "line_total", None), allow_zero=False)
            if line_total is not None and line_total > 0:
                prezzo_quintale = line_total / quintali

        if prezzo_quintale is None or prezzo_quintale <= 0:
            raise RuntimeError("Prezzo al quintale non trovato o non valido nella fattura.")

        iva_percent = self._valore_parser_to_float(getattr(linea_latte, "vat_rate", None), allow_zero=True)
        if iva_percent is None or iva_percent < 0:
            iva_percent = self._calcola_aliquota_iva_parser(fields, risultato)
        if iva_percent is None or iva_percent < 0:
            iva_percent = 0.0

        prezzo_quintale_lordo = prezzo_quintale * (1.0 + (iva_percent / 100.0))
        prezzo_litro_lordo = prezzo_quintale_lordo / LITRI_PER_QUINTALE

        return {
            "data": data_out,
            "quintali": format_number(quintali, 2),
            "prezzo_litro": format_number(prezzo_litro_lordo, 4),
            "iva_percent": iva_percent,
            "file": str(Path(file_path).name),
            "parser_data": parser_data,
        }

    def _seleziona_linea_latte(self, line_items):
        candidati = []
        for item in line_items:
            quantity = self._valore_parser_to_float(getattr(item, "quantity", None), allow_zero=False)
            if quantity is None or quantity <= 0:
                continue

            unit_price = self._valore_parser_to_float(getattr(item, "unit_price", None), allow_zero=False)
            line_total = self._valore_parser_to_float(getattr(item, "line_total", None), allow_zero=False)
            if unit_price is None and line_total is None:
                continue

            description = str(getattr(item, "description", "") or "").strip().lower()
            score = 0
            if "latte" in description:
                score += 4
            if "q" in description or "quint" in description:
                score += 2

            candidati.append((score, line_total or 0.0, item))

        if not candidati:
            return None

        candidati.sort(key=lambda data: (data[0], data[1]), reverse=True)
        return candidati[0][2]

    def _calcola_aliquota_iva_parser(self, fields, risultato=None):
        vat_rows = getattr(risultato, "vat_breakdown", []) or []
        for row in vat_rows:
            vat_rate = self._valore_parser_to_float(getattr(row, "vat_rate", None), allow_zero=False)
            if vat_rate is not None and vat_rate > 0:
                return vat_rate

        vat_total = self._estrai_importo_parser(fields, "vat_total", allow_zero=True)
        taxable_total = self._estrai_importo_parser(fields, "taxable_total", allow_zero=False)

        if vat_total is None or taxable_total is None or taxable_total <= 0:
            total_amount = self._estrai_importo_parser(fields, "total_amount", allow_zero=False)
            if total_amount is None or total_amount <= 0:
                return None
            taxable_total = total_amount - (vat_total or 0.0)
            if taxable_total <= 0:
                return None

        return max((vat_total or 0.0) * 100.0 / taxable_total, 0.0)

    def _valore_parser_to_float(self, value, allow_zero=False):
        if value is None:
            return None

        if isinstance(value, (int, float)):
            number = float(value)
        else:
            try:
                number = float(value)
            except (TypeError, ValueError):
                number = self._normalizza_importo(str(value), allow_zero=allow_zero)
                return number

        if number < 0:
            return None
        if number == 0 and not allow_zero:
            return None
        return number

    def _estrai_valori_parser_db(self, parser_data):
        if not isinstance(parser_data, dict):
            return (None,) * len(self._PARSER_DB_FIELDS)
        return tuple(parser_data.get(field_name) for field_name in self._PARSER_DB_FIELDS)

    def analizza_fattura_con_parser_fatture(self, pdf_path, file_path):
        parse_invoice_pdf = self._get_parser_fatture_function()
        risultato = parse_invoice_pdf(str(pdf_path))
        fields = getattr(risultato, "fields", {}) or {}
        parser_data = self._costruisci_dati_parser_movimento(risultato, fields)

        data_raw = self._estrai_valore_campo_parser(fields, "invoice_date")
        data_out = self._normalizza_data_fattura(data_raw)

        importo = self._estrai_importo_parser(fields, "total_amount", allow_zero=False)
        iva = self._estrai_importo_parser(fields, "vat_total", allow_zero=True)

        if importo is None:
            imponibile = self._estrai_importo_parser(fields, "taxable_total", allow_zero=True)
            if imponibile is not None and iva is not None:
                importo = imponibile + iva
            elif imponibile is not None:
                importo = imponibile

        if iva is None:
            iva = 0.0

        testo_struttura = self._testo_da_struttura_parser(getattr(risultato, "structure", {}))
        testo_struttura_lower = testo_struttura.lower()

        tipo = "USCITA"
        if "nota di credito" in testo_struttura_lower or "rimborso" in testo_struttura_lower:
            tipo = "ENTRATA"

        descrizione = self._estrai_valore_campo_parser(fields, "supplier_name")
        if not descrizione and testo_struttura:
            descrizione = self._estrai_intestazione_fattura(testo_struttura, file_path)

        if not descrizione:
            numero_fattura = self._estrai_valore_campo_parser(fields, "invoice_number")
            if numero_fattura:
                descrizione = f"Fattura {numero_fattura}"
            else:
                descrizione = f"Fattura importata: {Path(file_path).name}"

        return {
            "data": data_out or datetime.now().strftime("%d/%m/%Y"),
            "tipo": tipo,
            "categoria": "Fattura",
            "descrizione": descrizione,
            "importo": format_number(importo, 2) if importo is not None else "",
            "iva": format_number(iva, 2),
            "parser_data": parser_data,
        }

    def _get_parser_fatture_function(self):
        parse_invoice_pdf = getattr(self, "_parser_fatture_parse_fn", None)
        if parse_invoice_pdf is not None:
            return parse_invoice_pdf

        parser_src = Path(__file__).resolve().parents[1] / "parserFatture" / "src"
        if parser_src.exists():
            parser_src_str = str(parser_src)
            if parser_src_str not in sys.path:
                sys.path.insert(0, parser_src_str)

        try:
            parser_module = importlib.import_module("parser")
            parse_invoice_pdf = getattr(parser_module, "parse_invoice_pdf")
        except Exception as exc:
            raise RuntimeError(
                "parserFatture non disponibile. Installa dipendenze con: pip install -e parserFatture"
            ) from exc

        self._parser_fatture_parse_fn = parse_invoice_pdf
        return parse_invoice_pdf

    def _estrai_valore_campo_parser(self, fields, field_name):
        field = fields.get(field_name)
        if field is None:
            return ""

        valore = getattr(field, "normalized_value", None)
        if valore in (None, ""):
            valore = getattr(field, "raw_value", None)

        return str(valore).strip() if valore is not None else ""

    def _estrai_importo_parser(self, fields, field_name, allow_zero):
        field = fields.get(field_name)
        if field is None:
            return None

        valore = getattr(field, "normalized_value", None)
        if valore in (None, ""):
            valore = getattr(field, "raw_value", None)
        if valore in (None, ""):
            return None

        if isinstance(valore, (int, float)):
            numero = float(valore)
            if numero < 0:
                return None
            if not allow_zero and numero <= 0:
                return None
            return numero

        return self._normalizza_importo(str(valore), allow_zero=allow_zero)

    def _testo_da_struttura_parser(self, struttura):
        if not isinstance(struttura, dict):
            return ""

        righe = []
        for blocco in struttura.values():
            if not isinstance(blocco, list):
                continue
            for riga in blocco:
                testo_riga = str(riga).strip()
                if testo_riga:
                    righe.append(testo_riga)

        return "\n".join(righe)

    def _costruisci_dati_parser_movimento(self, risultato, fields):
        warnings = getattr(risultato, "warnings", []) or []
        line_items = getattr(risultato, "line_items", []) or []

        prodotti = []
        prodotti_rows = []
        for line in line_items:
            descrizione = str(getattr(line, "description", "") or "").strip()
            quantita_raw = getattr(line, "quantity", None)
            prezzo_unit_raw = getattr(line, "unit_price", None)
            totale_raw = getattr(line, "line_total", None)
            iva_raw = getattr(line, "vat_rate", None)

            quantita = self._valore_parser_to_float(quantita_raw, allow_zero=True)
            totale = self._valore_parser_to_float(totale_raw, allow_zero=True)

            if not descrizione and quantita is None and totale is None and prezzo_unit_raw in (None, ""):
                continue

            prodotti_rows.append(
                {
                    "description": descrizione or "-",
                    "quantity": self._valore_parser_to_text(quantita_raw, 3),
                    "unit_price": self._valore_parser_to_text(prezzo_unit_raw, 4),
                    "vat_rate": self._valore_parser_to_text(iva_raw, 2),
                    "line_total": self._valore_parser_to_text(totale_raw, 2),
                }
            )

            if not descrizione or quantita is None or totale is None:
                continue
            if quantita <= 0 or totale <= 0:
                continue

            prodotti.append(
                build_basic_product_storage_line(
                    descrizione,
                    format_number(quantita, 3),
                    format_number(totale, 2),
                )
            )

        campi_riepilogo = []
        for field_name in sorted(fields):
            field = fields.get(field_name)
            if field is None:
                continue

            valore = getattr(field, "normalized_value", None)
            if valore in (None, ""):
                valore = getattr(field, "raw_value", None)

            valore_text = str(valore).strip() if valore not in (None, "") else "-"
            conf = getattr(field, "confidence", 0.0) or 0.0
            try:
                conf_pct = int(round(float(conf) * 100))
            except (TypeError, ValueError):
                conf_pct = 0

            needs_review = bool(getattr(field, "requires_confirmation", False))
            suffisso = " [Conferma]" if needs_review else ""
            label = field_name.replace("_", " ").title()
            campi_riepilogo.append(f"{label}: {valore_text} ({conf_pct}%){suffisso}")

        return {
            "invoice_number": self._estrai_valore_campo_parser(fields, "invoice_number"),
            "invoice_date": self._estrai_valore_campo_parser(fields, "invoice_date"),
            "due_date": self._estrai_valore_campo_parser(fields, "due_date"),
            "supplier_name": self._estrai_valore_campo_parser(fields, "supplier_name"),
            "supplier_vat": self._estrai_valore_campo_parser(fields, "supplier_vat"),
            "customer_name": self._estrai_valore_campo_parser(fields, "customer_name"),
            "customer_vat": self._estrai_valore_campo_parser(fields, "customer_vat"),
            "total_amount": self._estrai_valore_campo_parser(fields, "total_amount"),
            "taxable_total": self._estrai_valore_campo_parser(fields, "taxable_total"),
            "vat_total": self._estrai_valore_campo_parser(fields, "vat_total"),
            "payment_terms": self._estrai_valore_campo_parser(fields, "payment_terms"),
            "warnings": " | ".join(str(w).strip() for w in warnings if str(w).strip()),
            "products": serialize_product_storage_lines(prodotti, separator="\n"),
            "products_rows": prodotti_rows,
            "fields_view": " | ".join(campi_riepilogo),
        }

    def _normalizza_data_fattura(self, raw_data):
        if not raw_data:
            return ""

        testo_data = raw_data.strip().replace(".", "/").replace("-", "/")
        formati = []

        if re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", testo_data):
            formati = ["%Y/%m/%d"]
        elif re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", testo_data):
            formati = ["%d/%m/%Y", "%d/%m/%y"]

        for formato in formati:
            try:
                data = datetime.strptime(testo_data, formato)
                return data.strftime("%d/%m/%Y")
            except ValueError:
                continue

        return ""

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
        return parse_decimal(raw, allow_zero=allow_zero, allow_negative=False)
