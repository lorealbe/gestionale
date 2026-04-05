import sqlite3
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from app_utils import is_blank
from database import get_conn, LITRI_PER_QUINTALE


class ReportTabMixin:
    def setup_tab_report(self):
        ttk.Label(self.tab_report, text="Genera Report", font=("Arial", 14, "bold")).pack(pady=10)

        self.var_data_inizio = tk.StringVar()
        self.var_data_fine = tk.StringVar()
        self.var_data_inizio.trace_add("write", self._auto_compila_data_fine)

        self.crea_campo_data(self.tab_report, "Data INIZIO:", self.var_data_inizio)
        self.crea_campo_data(self.tab_report, "Data FINE:", self.var_data_fine)

        ttk.Button(self.tab_report, text="Interroga DB e Calcola", command=self.genera_report).pack(pady=15)

        frame_report = ttk.Frame(self.tab_report)
        frame_report.pack(padx=20, pady=10, fill="both", expand=True)

        scroll = ttk.Scrollbar(frame_report, orient="vertical")
        scroll.pack(side="right", fill="y")

        self.txt_risultato = tk.Text(
            frame_report,
            height=12,
            width=60,
            state="disabled",
            wrap="word",
            yscrollcommand=scroll.set,
        )
        self.txt_risultato.pack(side="left", fill="both", expand=True)

        scroll.config(command=self.txt_risultato.yview)

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

        report_text = f"Movimenti estratti dal DB: {conteggio}\n"
        report_text += f"Produzioni latte nel periodo: {qta_produzioni}\n"
        report_text += "-" * 30 + "\n"
        report_text += f"Totale Entrate: EUR {tot_entrate:.2f}\n"
        report_text += f"Totale Uscite:  EUR {tot_uscite:.2f}\n"
        report_text += f"Totale IVA:     EUR {totale_iva:.2f}\n"
        report_text += f"Totale Quintali: {tot_quintali:.2f} q ({tot_litri:.2f} L)\n"
        report_text += f"Media Quintali/Giorno: {media_quintali_giorno:.2f} q\n"
        report_text += f"Media Quintali/Registrazione: {media_quintali_registrazione:.2f} q\n"
        report_text += f"Prezzo Medio/Litro: EUR {prezzo_medio_litro:.4f}\n"
        report_text += f"Costo Produzione/Litro: EUR {costo_produzione_litro:.4f}\n"
        report_text += f"Utile/Litro: EUR {utile_litro:.4f}\n"
        report_text += "-" * 30 + "\n"
        report_text += f"SALDO NETTO:   EUR {saldo:.2f}\n\n"

        report_text += "DETTAGLIO PER CATEGORIA\n"
        report_text += "-" * 30 + "\n"

        tipo_corrente = None
        for tipo, cat, totale, qta in righe_cat:
            if tipo != tipo_corrente:
                tipo_corrente = tipo
                report_text += f"\n[{tipo}]\n"
            report_text += f"- {cat}: EUR {float(totale):.2f} ({qta} mov.)\n"

        self.txt_risultato.config(state="normal")
        self.txt_risultato.delete(1.0, tk.END)
        self.txt_risultato.insert(tk.END, report_text)
        self.txt_risultato.config(state="disabled")
