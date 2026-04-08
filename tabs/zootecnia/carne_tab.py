import re
import sqlite3
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app_utils import clear_treeview, format_eur, format_number, is_blank, parse_decimal
from database import get_conn


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

        if reset_campi:
            self.var_carne_data.set(datetime.now().strftime("%d/%m/%Y"))
            self.var_carne_quantita.set("")
            self.var_carne_unita_quantita.set(self._UNITA_QTA[0])
            self.var_carne_prezzo.set("0,00")
            self.var_carne_unita_prezzo.set(self._UNITA_PREZZO[0])

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

        quintali_val = kg_val / self.KG_PER_QUINTALE
        importo_entrata = kg_val * prezzo_kg_val
        descrizione_mov = (
            f"Produzione carne: {format_number(kg_val, 2)} Kg "
            f"({format_number(quintali_val, 2)} q) x {format_eur(prezzo_kg_val, 4)}/Kg"
        )

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

                if self.pending_fattura_carne_id is not None and movimento_id is not None:
                    c.execute(
                        '''
                        UPDATE fatture
                        SET movimento_id=?, produzione_id=NULL
                        WHERE id=? AND user_id=?
                    ''',
                        (movimento_id, self.pending_fattura_carne_id, self.user_id),
                    )
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
        messagebox.showinfo(
            "Successo",
            f"{msg_ok}! Entrata automatica: {format_eur(importo_entrata)}",
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
