import sqlite3
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from app_utils import clear_treeview, format_eur, format_number, is_blank
from database import get_conn, LITRI_PER_QUINTALE


class ReportTabMixin:
    def setup_tab_report(self):
        container = ttk.Frame(self.tab_report)
        container.pack(fill="both", expand=True)

        self.report_canvas = tk.Canvas(container, highlightthickness=0)
        self.report_scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.report_canvas.yview)
        self.report_canvas.configure(yscrollcommand=self.report_scrollbar.set)

        self.report_scrollbar.pack(side="right", fill="y")
        self.report_canvas.pack(side="left", fill="both", expand=True)

        content = ttk.Frame(self.report_canvas)
        self.report_canvas_window = self.report_canvas.create_window((0, 0), window=content, anchor="nw")

        def _on_content_configure(_event):
            self.report_canvas.configure(scrollregion=self.report_canvas.bbox("all"))

        def _on_canvas_configure(event):
            self.report_canvas.itemconfigure(self.report_canvas_window, width=event.width)

        content.bind("<Configure>", _on_content_configure)
        self.report_canvas.bind("<Configure>", _on_canvas_configure)

        ttk.Label(content, text="Genera Report", font=("Arial", 14, "bold")).pack(pady=10)

        self.var_data_inizio = tk.StringVar()
        self.var_data_fine = tk.StringVar()
        self.var_data_inizio.trace_add("write", self._auto_compila_data_fine)

        self.crea_campo_data(content, "Data INIZIO:", self.var_data_inizio)
        self.crea_campo_data(content, "Data FINE:", self.var_data_fine)

        ttk.Button(content, text="Interroga DB e Calcola", command=self.genera_report).pack(pady=15)

        frame_report = ttk.Frame(content)
        frame_report.pack(padx=20, pady=10, fill="both", expand=True)

        frame_riepilogo = ttk.LabelFrame(frame_report, text="Riepilogo")
        frame_riepilogo.pack(fill="x", expand=False, pady=(0, 8))

        cols_riepilogo = ("metrica", "valore")
        self.tree_report_riepilogo = ttk.Treeview(
            frame_riepilogo,
            columns=cols_riepilogo,
            show="headings",
            height=12,
        )
        self.tree_report_riepilogo.heading("metrica", text="Metrica")
        self.tree_report_riepilogo.heading("valore", text="Valore")
        self.tree_report_riepilogo.column("metrica", width=260, anchor="w")
        self.tree_report_riepilogo.column("valore", width=220, anchor="e")

        scroll_riepilogo = ttk.Scrollbar(frame_riepilogo, orient="vertical", command=self.tree_report_riepilogo.yview)
        self.tree_report_riepilogo.configure(yscrollcommand=scroll_riepilogo.set)

        self.tree_report_riepilogo.pack(side="left", fill="both", expand=True)
        scroll_riepilogo.pack(side="right", fill="y")

        frame_categorie = ttk.LabelFrame(frame_report, text="Dettaglio per categoria")
        frame_categorie.pack(fill="both", expand=True)

        cols_categorie = ("tipo", "categoria", "totale", "movimenti")
        self.tree_report_categorie = ttk.Treeview(
            frame_categorie,
            columns=cols_categorie,
            show="headings",
            height=10,
        )
        self.tree_report_categorie.heading("tipo", text="Tipo")
        self.tree_report_categorie.heading("categoria", text="Categoria")
        self.tree_report_categorie.heading("totale", text="Totale")
        self.tree_report_categorie.heading("movimenti", text="N. Movimenti")

        self.tree_report_categorie.column("tipo", width=100, anchor="center")
        self.tree_report_categorie.column("categoria", width=240, anchor="w")
        self.tree_report_categorie.column("totale", width=140, anchor="e")
        self.tree_report_categorie.column("movimenti", width=120, anchor="e")

        scroll_categorie = ttk.Scrollbar(frame_categorie, orient="vertical", command=self.tree_report_categorie.yview)
        self.tree_report_categorie.configure(yscrollcommand=scroll_categorie.set)

        self.tree_report_categorie.pack(side="left", fill="both", expand=True)
        scroll_categorie.pack(side="right", fill="y")

    def _auto_compila_data_fine(self, *_args):
        if is_blank(self.var_data_fine.get()) and not is_blank(self.var_data_inizio.get()):
            self.var_data_fine.set(self.var_data_inizio.get())

    def imposta_periodo_report_default(self, mostra_errori=True):
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

        self.var_data_inizio.set(data_inizio)
        self.var_data_fine.set(data_fine)

    def genera_report(self):
        try:
            inizio = datetime.strptime(self.var_data_inizio.get().strip(), "%d/%m/%Y")
            fine = datetime.strptime(self.var_data_fine.get().strip(), "%d/%m/%Y")
        except ValueError:
            messagebox.showerror("Errore", "Formato date non valido (Usa GG/MM/AAAA).")
            return

        if inizio > fine:
            messagebox.showerror("Errore", "La data INIZIO non puo essere successiva alla data FINE.")
            return

        inizio_db = inizio.strftime("%Y-%m-%d")
        fine_db = fine.strftime("%Y-%m-%d")

        try:
            with get_conn() as conn:
                c = conn.cursor()

                c.execute(
                    '''
                    SELECT tipo, COALESCE(SUM(importo), 0) AS totale, COUNT(id) AS qta
                    FROM movimenti
                    WHERE user_id=? AND data_op BETWEEN ? AND ?
                    GROUP BY tipo
                ''',
                    (self.user_id, inizio_db, fine_db),
                )
                risultati = c.fetchall()

                c.execute(
                    '''
                    SELECT COALESCE(SUM(iva_importo), 0)
                    FROM movimenti
                    WHERE user_id=? AND data_op BETWEEN ? AND ?
                ''',
                    (self.user_id, inizio_db, fine_db),
                )
                row_iva = c.fetchone()
                totale_iva = float(row_iva[0] or 0)

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
                tot_litri = float(row_latte[0] or 0)
                qta_produzioni = int(row_latte[1] or 0)
                totale_valore_latte = float(row_latte[2] or 0)

                c.execute(
                    '''
                    SELECT tipo,
                           COALESCE(NULLIF(TRIM(categoria), ''), '(Senza categoria)') AS cat,
                           COALESCE(SUM(importo), 0) AS totale,
                           COUNT(id) AS qta
                    FROM movimenti
                    WHERE user_id=? AND data_op BETWEEN ? AND ?
                    GROUP BY tipo, cat
                    ORDER BY tipo, totale DESC
                ''',
                    (self.user_id, inizio_db, fine_db),
                )
                righe_cat = c.fetchall()

        except sqlite3.Error as e:
            messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        tot_entrate = 0.0
        tot_uscite = 0.0
        conteggio = 0

        for tipo, totale, qta in risultati:
            conteggio += qta
            if tipo == "ENTRATA":
                tot_entrate = float(totale or 0)
            elif tipo == "USCITA":
                tot_uscite = float(totale or 0)

        saldo = tot_entrate - tot_uscite
        giorni_periodo = (fine - inizio).days + 1
        media_litri_giorno = (tot_litri / giorni_periodo) if giorni_periodo > 0 else 0.0
        media_litri_registrazione = (tot_litri / qta_produzioni) if qta_produzioni > 0 else 0.0
        tot_quintali = tot_litri / LITRI_PER_QUINTALE
        media_quintali_giorno = media_litri_giorno / LITRI_PER_QUINTALE
        media_quintali_registrazione = media_litri_registrazione / LITRI_PER_QUINTALE
        prezzo_medio_litro = (totale_valore_latte / tot_litri) if tot_litri > 0 else 0.0
        costo_produzione_litro = (tot_uscite / tot_litri) if tot_litri > 0 else 0.0
        utile_litro = (saldo / tot_litri) if tot_litri > 0 else 0.0

        if not hasattr(self, "tree_report_riepilogo") or not hasattr(self, "tree_report_categorie"):
            return

        clear_treeview(self.tree_report_riepilogo)
        clear_treeview(self.tree_report_categorie)

        righe_riepilogo = [
            ("Movimenti estratti dal DB", str(conteggio)),
            ("Produzioni latte nel periodo", str(qta_produzioni)),
            ("Totale Entrate", format_eur(tot_entrate)),
            ("Totale Uscite", format_eur(tot_uscite)),
            ("Totale IVA", format_eur(totale_iva)),
            ("Totale Quintali", f"{format_number(tot_quintali, 2)} q ({format_number(tot_litri, 2)} L)"),
            ("Media Quintali/Giorno", f"{format_number(media_quintali_giorno, 2)} q"),
            ("Media Quintali/Registrazione", f"{format_number(media_quintali_registrazione, 2)} q"),
            ("Prezzo Medio/Litro", format_eur(prezzo_medio_litro, 4)),
            ("Costo Produzione/Litro", format_eur(costo_produzione_litro, 4)),
            ("Utile/Litro", format_eur(utile_litro, 4)),
            ("Saldo Netto", format_eur(saldo)),
        ]

        for metrica, valore in righe_riepilogo:
            self.tree_report_riepilogo.insert("", "end", values=(metrica, valore))

        for tipo, cat, totale, qta in righe_cat:
            self.tree_report_categorie.insert(
                "",
                "end",
                values=(
                    tipo,
                    cat,
                    format_eur(float(totale)),
                    qta,
                ),
            )
