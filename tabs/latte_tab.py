import tkinter as tk
import sqlite3
from datetime import datetime
from tkinter import ttk, messagebox

from app_utils import clear_treeview, format_eur, format_number, is_blank
from database import get_conn, LITRI_PER_QUINTALE


class LatteTabMixin:
    def setup_tab_latte(self):
        content = self.crea_container_scorribile(self.tab_latte)

        ttk.Label(content, text="Produzione Latte", font=("Arial", 14, "bold")).pack(pady=10)

        self.var_latte_data = tk.StringVar(value=datetime.now().strftime("%d/%m/%Y"))
        self.var_latte_quintali = tk.StringVar()
        self.var_latte_prezzo = tk.StringVar(value="0,00")
        self.produzione_in_modifica_id = None

        self.crea_campo_data(content, "Data produzione:", self.var_latte_data)
        self.crea_campo(content, "Quintali prodotti:", self.var_latte_quintali)
        self.crea_campo(content, "Prezzo al litro (EUR):", self.var_latte_prezzo)

        ttk.Label(content, text="Conversione automatica: 1 quintale = 100 litri").pack(pady=(0, 6))

        frame_actions = ttk.Frame(content)
        frame_actions.pack(pady=10)

        self.btn_salva_produzione = ttk.Button(frame_actions, text="Salva Produzione", command=self.salva_produzione_latte)
        self.btn_salva_produzione.pack(side="left", padx=6)
        ttk.Button(frame_actions, text="Ricarica Storico", command=self.carica_produzioni_latte).pack(side="left", padx=6)
        ttk.Button(frame_actions, text="Elimina selezionata", command=self.elimina_produzione_latte_selezionata).pack(side="left", padx=6)

        self.var_nome_fattura_latte = tk.StringVar(value="Nessuna fattura caricata")
        frame_fattura = ttk.Frame(content)
        frame_fattura.pack(fill="x", padx=20, pady=(0, 8))

        ttk.Label(frame_fattura, text="Fattura latte:", width=20).pack(side="left")
        ttk.Label(frame_fattura, textvariable=self.var_nome_fattura_latte).pack(side="left", fill="x", expand=True)
        ttk.Button(frame_fattura, text="Carica Fattura", command=self.seleziona_fattura_latte).pack(side="right")
        ttk.Button(frame_fattura, text="Rimuovi", command=self.rimuovi_fattura_latte).pack(side="right", padx=(0, 5))

        frame_table = ttk.Frame(content)
        frame_table.pack(fill="both", expand=True, padx=12, pady=8)

        cols = ("id", "data", "quintali", "prezzo")
        self.tree_produzione = ttk.Treeview(frame_table, columns=cols, show="headings", height=10)

        self.tree_produzione.heading("id", text="ID")
        self.tree_produzione.heading("data", text="Data")
        self.tree_produzione.heading("quintali", text="Quintali")
        self.tree_produzione.heading("prezzo", text="Prezzo / L")

        self.tree_produzione.column("id", width=60, anchor="center")
        self.tree_produzione.column("data", width=120, anchor="center")
        self.tree_produzione.column("quintali", width=140, anchor="e")
        self.tree_produzione.column("prezzo", width=140, anchor="e")

        scroll = ttk.Scrollbar(frame_table, orient="vertical", command=self.tree_produzione.yview)
        self.tree_produzione.configure(yscrollcommand=scroll.set)

        self.tree_produzione.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tree_produzione.bind("<<TreeviewSelect>>", self.prepara_modifica_produzione_latte)
        self.tree_produzione.bind("<Delete>", lambda _event: self.elimina_produzione_latte_selezionata())

    def salva_produzione_latte(self):
        if is_blank(self.var_latte_data.get()):
            messagebox.showerror("Errore", "Inserisci la data di produzione.")
            return
        if is_blank(self.var_latte_quintali.get()):
            messagebox.showerror("Errore", "Inserisci i quintali prodotti.")
            return

        try:
            data_obj = datetime.strptime(self.var_latte_data.get().strip(), "%d/%m/%Y")
            data_db = data_obj.strftime("%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Errore", "Formato data non valido (Usa GG/MM/AAAA)")
            return

        quintali_val = self._normalizza_importo(self.var_latte_quintali.get(), allow_zero=False)
        if quintali_val is None:
            messagebox.showerror("Errore", "Quintali non validi.")
            return

        litri_val = quintali_val * LITRI_PER_QUINTALE

        prezzo_text = self.var_latte_prezzo.get().strip()
        if is_blank(prezzo_text):
            prezzo_val = 0.0
        else:
            prezzo_val = self._normalizza_importo(prezzo_text, allow_zero=True)
            if prezzo_val is None:
                messagebox.showerror("Errore", "Prezzo al litro non valido.")
                return

        importo_entrata = litri_val * prezzo_val
        descrizione_mov = (
            f"Produzione latte: {format_number(quintali_val, 2)} q "
            f"({format_number(litri_val, 2)} L) x {format_eur(prezzo_val, 4)}/L"
        )

        try:
            with get_conn() as conn:
                c = conn.cursor()
                movimento_id = None
                produzione_id = None

                if self.produzione_in_modifica_id is None:
                    c.execute(
                        '''
                        INSERT INTO movimenti (user_id, data_op, tipo, categoria, descrizione, importo, iva_importo)
                        VALUES (?, ?, 'ENTRATA', ?, ?, ?, 0)
                    ''',
                        (
                            self.user_id,
                            data_db,
                            "Latte",
                            descrizione_mov,
                            importo_entrata,
                        ),
                    )
                    movimento_id = c.lastrowid

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
                        c.execute(
                            '''
                            UPDATE movimenti
                            SET data_op=?, tipo='ENTRATA', categoria=?, descrizione=?, importo=?, iva_importo=0
                            WHERE id=? AND user_id=?
                        ''',
                            (
                                data_db,
                                "Latte",
                                descrizione_mov,
                                importo_entrata,
                                movimento_id,
                                self.user_id,
                            ),
                        )
                        if c.rowcount == 0:
                            movimento_id = None

                    if movimento_id is None:
                        c.execute(
                            '''
                            INSERT INTO movimenti (user_id, data_op, tipo, categoria, descrizione, importo, iva_importo)
                            VALUES (?, ?, 'ENTRATA', ?, ?, ?, 0)
                        ''',
                            (
                                self.user_id,
                                data_db,
                                "Latte",
                                descrizione_mov,
                                importo_entrata,
                            ),
                        )
                        movimento_id = c.lastrowid
                        c.execute(
                            "UPDATE produzione_latte SET movimento_id=? WHERE id=? AND user_id=?",
                            (movimento_id, produzione_id, self.user_id),
                        )

                    msg_ok = "Produzione latte aggiornata"

                if self.pending_fattura_latte_id is not None and movimento_id is not None and produzione_id is not None:
                    c.execute(
                        '''
                        UPDATE fatture
                        SET movimento_id=?, produzione_id=?
                        WHERE id=? AND user_id=?
                    ''',
                        (movimento_id, produzione_id, self.pending_fattura_latte_id, self.user_id),
                    )
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

    def prepara_modifica_produzione_latte(self, _event=None):
        selezione = self.tree_produzione.selection()
        if not selezione:
            return

        valori = self.tree_produzione.item(selezione[0], "values")
        if not valori:
            return

        self.produzione_in_modifica_id = int(valori[0])
        self.var_latte_data.set(valori[1] or datetime.now().strftime("%d/%m/%Y"))
        self.var_latte_quintali.set(valori[2] or "")
        self.var_latte_prezzo.set(valori[3] or "0,00")
        if hasattr(self, "btn_salva_produzione"):
            self.btn_salva_produzione.config(text="Aggiorna Produzione")

    def annulla_modifica_produzione_latte(self, reset_campi=False):
        self.produzione_in_modifica_id = None
        if hasattr(self, "btn_salva_produzione"):
            self.btn_salva_produzione.config(text="Salva Produzione")
        if hasattr(self, "tree_produzione"):
            self.tree_produzione.selection_remove(*self.tree_produzione.selection())

        if reset_campi:
            self.var_latte_data.set(datetime.now().strftime("%d/%m/%Y"))
            self.var_latte_quintali.set("")
            self.var_latte_prezzo.set("0,00")

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
