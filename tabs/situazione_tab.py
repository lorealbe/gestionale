import tkinter as tk
import sqlite3
from tkinter import ttk, messagebox

from database import get_conn


class SituazioneTabMixin:
    def setup_tab_situazione(self):
        ttk.Label(self.tab_situazione, text="Situazione Attuale", font=("Arial", 14, "bold")).pack(pady=12)

        frame_stats = ttk.Frame(self.tab_situazione, padding=12)
        frame_stats.pack(fill="x", padx=20, pady=10)

        self.var_tot_movimenti = tk.StringVar(value="0")
        self.var_tot_entrate = tk.StringVar(value="EUR 0.00")
        self.var_tot_uscite = tk.StringVar(value="EUR 0.00")
        self.var_tot_utile = tk.StringVar(value="EUR 0.00")

        righe = [
            ("Numero di movimenti:", self.var_tot_movimenti),
            ("Entrate:", self.var_tot_entrate),
            ("Uscite:", self.var_tot_uscite),
            ("Utile:", self.var_tot_utile),
        ]

        for idx, (testo, valore) in enumerate(righe):
            ttk.Label(frame_stats, text=testo, width=22).grid(row=idx, column=0, sticky="w", pady=4)
            ttk.Label(frame_stats, textvariable=valore, font=("Arial", 11, "bold")).grid(row=idx, column=1, sticky="w", pady=4)

        ttk.Button(self.tab_situazione, text="Aggiorna situazione", command=self.aggiorna_situazione_attuale).pack(pady=8)

    def aggiorna_situazione_attuale(self, mostra_errori=True):
        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute(
                    '''
                    SELECT COUNT(id),
                           COALESCE(SUM(CASE WHEN tipo='ENTRATA' THEN importo ELSE 0 END), 0),
                           COALESCE(SUM(CASE WHEN tipo='USCITA' THEN importo ELSE 0 END), 0)
                    FROM movimenti
                    WHERE user_id=?
                ''',
                    (self.user_id,),
                )
                row = c.fetchone()
        except sqlite3.Error as e:
            if mostra_errori:
                messagebox.showerror("Errore DB", f"Errore database: {e}")
            return

        num_movimenti = int((row[0] if row else 0) or 0)
        tot_entrate = float((row[1] if row else 0) or 0)
        tot_uscite = float((row[2] if row else 0) or 0)
        utile = tot_entrate - tot_uscite

        self.var_tot_movimenti.set(str(num_movimenti))
        self.var_tot_entrate.set(f"EUR {tot_entrate:.2f}")
        self.var_tot_uscite.set(f"EUR {tot_uscite:.2f}")
        self.var_tot_utile.set(f"EUR {utile:.2f}")
