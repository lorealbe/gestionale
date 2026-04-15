import os
import sqlite3
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox

from app_utils import clear_treeview, format_number, parse_decimal
from database import get_conn, get_movimento_animali_entry_ids, get_movimento_animali_group_labels, resolve_fattura_path


class StoricoTabMixin:
    def setup_tab_storico(self):
        content = self.crea_container_scorribile(self.tab_storico)

        ttk.Label(content, text="Movimenti inseriti", font=("Arial", 14, "bold")).pack(pady=10)

        self.var_filtro_categoria = tk.StringVar(value="Tutte")
        self.var_filtro_descrizione = tk.StringVar()
        self.var_filtro_data_da = tk.StringVar()
        self.var_filtro_data_a = tk.StringVar()

        frame_filtri = ttk.LabelFrame(content, text="Filtri")
        frame_filtri.pack(fill="x", padx=12, pady=(0, 6))

        riga_filtri_1 = ttk.Frame(frame_filtri)
        riga_filtri_1.pack(fill="x", padx=8, pady=(8, 4))

        ttk.Label(riga_filtri_1, text="Categoria:").pack(side="left")
        self.combo_filtro_categoria = ttk.Combobox(
            riga_filtri_1,
            textvariable=self.var_filtro_categoria,
            state="readonly",
            width=24,
        )
        self.combo_filtro_categoria.pack(side="left", padx=(6, 14))
        self.combo_filtro_categoria["values"] = ["Tutte"]
        self.combo_filtro_categoria.current(0)
        self.combo_filtro_categoria.bind("<<ComboboxSelected>>", lambda _event: self.carica_movimenti())

        ttk.Label(riga_filtri_1, text="Descrizione:").pack(side="left")
        entry_filtro_descrizione = ttk.Entry(riga_filtri_1, textvariable=self.var_filtro_descrizione)
        entry_filtro_descrizione.pack(side="left", fill="x", expand=True, padx=(6, 0))
        entry_filtro_descrizione.bind("<Return>", lambda _event: self.carica_movimenti())

        riga_filtri_2 = ttk.Frame(frame_filtri)
        riga_filtri_2.pack(fill="x", padx=8, pady=(0, 8))

        ttk.Label(riga_filtri_2, text="Data da:").pack(side="left")
        entry_data_da = ttk.Entry(riga_filtri_2, textvariable=self.var_filtro_data_da, width=12, state="readonly")
        entry_data_da.pack(side="left", padx=(6, 0))
        ttk.Button(
            riga_filtri_2,
            text="...",
            width=3,
            command=lambda: self._apri_calendario_filtro(self.var_filtro_data_da),
        ).pack(side="left", padx=(4, 14))
        entry_data_da.bind("<Button-1>", lambda _event: self._apri_calendario_filtro(self.var_filtro_data_da))

        ttk.Label(riga_filtri_2, text="Data a:").pack(side="left")
        entry_data_a = ttk.Entry(riga_filtri_2, textvariable=self.var_filtro_data_a, width=12, state="readonly")
        entry_data_a.pack(side="left", padx=(6, 0))
        ttk.Button(
            riga_filtri_2,
            text="...",
            width=3,
            command=lambda: self._apri_calendario_filtro(self.var_filtro_data_a),
        ).pack(side="left", padx=(4, 14))
        entry_data_a.bind("<Button-1>", lambda _event: self._apri_calendario_filtro(self.var_filtro_data_a))

        ttk.Button(riga_filtri_2, text="Applica filtri", command=self.carica_movimenti).pack(side="left", padx=(0, 6))
        ttk.Button(riga_filtri_2, text="Pulisci", command=self.pulisci_filtri_movimenti).pack(side="left")

        frame_table = ttk.Frame(content)
        frame_table.pack(fill="both", expand=True, padx=12, pady=6)

        cols = ("id", "data", "tipo", "categoria", "descrizione", "importo", "iva")
        self.tree_movimenti = ttk.Treeview(frame_table, columns=cols, show="headings", height=9)

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
        self.tree_movimenti.column("descrizione", width=260, anchor="w")
        self.tree_movimenti.column("importo", width=90, anchor="e")
        self.tree_movimenti.column("iva", width=90, anchor="e")

        scroll_y = ttk.Scrollbar(frame_table, orient="vertical", command=self.tree_movimenti.yview)
        self.tree_movimenti.configure(yscrollcommand=scroll_y.set)

        self.tree_movimenti.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        frame_table.grid_rowconfigure(0, weight=1)
        frame_table.grid_columnconfigure(0, weight=1)

        self.tree_movimenti.bind("<<TreeviewSelect>>", self._on_selezione_movimento_storico)
        self.tree_movimenti.bind("<Double-1>", lambda _event: self.prepara_modifica_movimento())
        self.tree_movimenti.bind("<Delete>", lambda _event: self.elimina_movimento_selezionato())

        frame_btn = ttk.Frame(content)
        frame_btn.pack(fill="x", padx=12, pady=(0, 6))

        ttk.Button(frame_btn, text="Ricarica", command=self.carica_movimenti).pack(side="left", padx=6)
        ttk.Button(frame_btn, text="Modifica selezionato", command=self.prepara_modifica_movimento).pack(side="left", padx=6)
        ttk.Button(frame_btn, text="Apri fattura", command=self.apri_fattura_movimento_selezionato).pack(side="left", padx=6)
        ttk.Button(frame_btn, text="Elimina selezionato", command=self.elimina_movimento_selezionato).pack(side="left", padx=6)

        frame_dettagli = ttk.LabelFrame(content, text="Dati fattura del movimento selezionato")
        frame_dettagli.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        self.tree_fattura_dettagli = ttk.Treeview(
            frame_dettagli,
            columns=("campo", "valore"),
            show="headings",
            height=9,
        )
        self.tree_fattura_dettagli.heading("campo", text="Campo")
        self.tree_fattura_dettagli.heading("valore", text="Valore")
        self.tree_fattura_dettagli.column("campo", width=220, anchor="w")
        self.tree_fattura_dettagli.column("valore", width=620, anchor="w")

        dettagli_scroll_y = ttk.Scrollbar(frame_dettagli, orient="vertical", command=self.tree_fattura_dettagli.yview)
        self.tree_fattura_dettagli.configure(yscrollcommand=dettagli_scroll_y.set)

        self.tree_fattura_dettagli.grid(row=0, column=0, sticky="nsew")
        dettagli_scroll_y.grid(row=0, column=1, sticky="ns")
        frame_dettagli.grid_rowconfigure(0, weight=1)
        frame_dettagli.grid_columnconfigure(0, weight=1)

        self._fattura_dettaglio_corrente = None
        self._azzera_dettagli_fattura()

    def carica_movimenti(self):
        if not hasattr(self, "tree_movimenti"):
            return

        clear_treeview(self.tree_movimenti)

        filtro_categoria = self.var_filtro_categoria.get().strip() if hasattr(self, "var_filtro_categoria") else ""
        filtro_descrizione = self.var_filtro_descrizione.get().strip() if hasattr(self, "var_filtro_descrizione") else ""
        filtro_data_da = self.var_filtro_data_da.get().strip() if hasattr(self, "var_filtro_data_da") else ""
        filtro_data_a = self.var_filtro_data_a.get().strip() if hasattr(self, "var_filtro_data_a") else ""

        data_da_iso = None
        data_a_iso = None

        if filtro_data_da:
            try:
                data_da_iso = datetime.strptime(filtro_data_da, "%d/%m/%Y").strftime("%Y-%m-%d")
            except ValueError:
                messagebox.showerror("Errore", "Data DA non valida (usa GG/MM/AAAA).")
                return

        if filtro_data_a:
            try:
                data_a_iso = datetime.strptime(filtro_data_a, "%d/%m/%Y").strftime("%Y-%m-%d")
            except ValueError:
                messagebox.showerror("Errore", "Data A non valida (usa GG/MM/AAAA).")
                return

        if data_da_iso and data_a_iso and data_da_iso > data_a_iso:
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

            self.tree_movimenti.insert(
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

        self._azzera_dettagli_fattura()
        self.carica_categorie_salvate(mostra_errori=False)

    def _azzera_dettagli_fattura(self, testo="Seleziona un movimento per vedere la fattura collegata."):
        self._fattura_dettaglio_corrente = None
        if not hasattr(self, "tree_fattura_dettagli"):
            return

        clear_treeview(self.tree_fattura_dettagli)
        self.tree_fattura_dettagli.insert("", "end", values=("Info", testo))

    def _on_selezione_movimento_storico(self, _event=None):
        self.carica_dettagli_fattura_movimento_selezionato()

    def carica_dettagli_fattura_movimento_selezionato(self):
        if not hasattr(self, "tree_movimenti"):
            return

        selezione = self.tree_movimenti.selection()
        if not selezione:
            self._azzera_dettagli_fattura("Seleziona un movimento per vedere la fattura collegata.")
            return

        valori = self.tree_movimenti.item(selezione[0], "values")
        if not valori:
            self._azzera_dettagli_fattura("Movimento selezionato non valido.")
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
            self._azzera_dettagli_fattura("Errore durante il caricamento della fattura collegata.")
            return

        if not row:
            self._azzera_dettagli_fattura("Nessuna fattura collegata al movimento selezionato.")
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

        try:
            gruppi_animali_collegati = get_movimento_animali_group_labels(self.user_id, mov_id)
        except sqlite3.Error:
            gruppi_animali_collegati = []

        gruppi_animali_text = "\n".join(gruppi_animali_collegati) if gruppi_animali_collegati else "Nessun gruppo collegato"

        self._fattura_dettaglio_corrente = {
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
            "products": parser_products or "",
            "fields_view": parser_fields_view or "",
            "gruppi_animali": gruppi_animali_text,
        }
        self._mostra_dettagli_fattura(self._fattura_dettaglio_corrente)

    def _mostra_dettagli_fattura(self, dettagli):
        clear_treeview(self.tree_fattura_dettagli)
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
            self.tree_fattura_dettagli.insert("", "end", values=(campo, valore or ""))

    def _format_data_caricamento(self, raw_value):
        testo = (raw_value or "").strip()
        if not testo:
            return ""

        for fmt_in in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
        ):
            try:
                data = datetime.strptime(testo, fmt_in)
                if "%H" in fmt_in:
                    return data.strftime("%d/%m/%Y %H:%M")
                return data.strftime("%d/%m/%Y")
            except ValueError:
                continue

        return testo.replace("T", " ")

    def carica_categorie_salvate(self, mostra_errori=True):
        if not hasattr(self, "combo_categoria") and not hasattr(self, "combo_filtro_categoria"):
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
        if hasattr(self, "combo_categoria"):
            self.combo_categoria["values"] = categorie

        if hasattr(self, "combo_filtro_categoria"):
            valori_filtri = ["Tutte", *categorie]
            filtro_corrente = self.var_filtro_categoria.get().strip() if hasattr(self, "var_filtro_categoria") else ""
            self.combo_filtro_categoria["values"] = valori_filtri
            if filtro_corrente and filtro_corrente in valori_filtri:
                self.var_filtro_categoria.set(filtro_corrente)
            else:
                self.var_filtro_categoria.set("Tutte")

    def _apri_calendario_filtro(self, text_var):
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
            self.carica_movimenti()

    def pulisci_filtri_movimenti(self):
        if hasattr(self, "var_filtro_categoria"):
            self.var_filtro_categoria.set("Tutte")
        if hasattr(self, "var_filtro_descrizione"):
            self.var_filtro_descrizione.set("")
        if hasattr(self, "var_filtro_data_da"):
            self.var_filtro_data_da.set("")
        if hasattr(self, "var_filtro_data_a"):
            self.var_filtro_data_a.set("")
        self.carica_movimenti()

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
        elif hasattr(self, "notebook") and hasattr(self, "tab_movimenti"):
            self.notebook.select(self.tab_movimenti)

    def apri_fattura_movimento_selezionato(self):
        dettagli = getattr(self, "_fattura_dettaglio_corrente", None)
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

    def _format_data_parser(self, raw_value):
        testo = (raw_value or "").strip()
        if not testo:
            return ""

        for fmt_in in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(testo, fmt_in).strftime("%d/%m/%Y")
            except ValueError:
                continue

        return testo

    def _format_importo_parser(self, raw_value):
        testo = (raw_value or "").strip()
        if not testo:
            return ""

        numero = parse_decimal(testo, allow_zero=True, allow_negative=False)
        if numero is None:
            return testo
        return format_number(numero, 2)

    def apri_file_locale(self, file_path):
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(file_path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(file_path)], check=False)
            else:
                subprocess.run(["xdg-open", str(file_path)], check=False)
        except Exception as e:
            messagebox.showerror("Errore apertura", f"Impossibile aprire il file:\n{e}")

    def elimina_fatture_collegate_db(self, cursor, movimento_id):
        cursor.execute(
            "SELECT percorso_file FROM fatture WHERE user_id=? AND movimento_id=?",
            (self.user_id, movimento_id),
        )
        percorsi = [row[0] for row in cursor.fetchall() if row and row[0]]

        cursor.execute("DELETE FROM fatture WHERE user_id=? AND movimento_id=?", (self.user_id, movimento_id))
        fatture_eliminate = max(cursor.rowcount, 0)
        return fatture_eliminate, percorsi

    def elimina_file_fatture(self, percorsi):
        file_eliminati = 0
        file_non_trovati = 0
        errori = []

        for percorso in sorted(set(p for p in percorsi if p)):
            file_path = resolve_fattura_path(percorso)
            try:
                if file_path.exists():
                    file_path.unlink()
                    file_eliminati += 1
                else:
                    file_non_trovati += 1
            except Exception as e:
                errori.append(f"{file_path} ({e})")

        return file_eliminati, file_non_trovati, errori

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

        self.carica_movimenti()
        if hasattr(self, "carica_movimenti_azienda_storico"):
            self.carica_movimenti_azienda_storico(mostra_errori=False)
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

    def annulla_modifica_movimento(self):
        self.movimento_in_modifica_id = None
        if hasattr(self, "btn_salva_movimento"):
            self.btn_salva_movimento.config(text="Salva nel DB")
        if hasattr(self, "btn_annulla_modifica"):
            self.btn_annulla_modifica.config(state="disabled")
        if hasattr(self, "btn_salva_movimento_azienda"):
            self.btn_salva_movimento_azienda.config(text="Salva nel DB")
        if hasattr(self, "btn_annulla_modifica_azienda"):
            self.btn_annulla_modifica_azienda.config(state="disabled")

        self.var_data.set(datetime.now().strftime("%d/%m/%Y"))
        self.var_tipo.set("ENTRATA")
        self.var_cat.set("")
        self.var_desc.set("")
        self.var_imp.set("")
        self.var_iva.set("0,00")

        if hasattr(self, "deseleziona_gruppi_animali_movimento"):
            self.deseleziona_gruppi_animali_movimento()
