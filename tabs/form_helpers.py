import tkinter as tk
from tkinter import ttk
from datetime import datetime


class FormHelpersMixin:
    def crea_campo(self, parent, label_text, text_var):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", padx=20, pady=5)
        ttk.Label(frame, text=label_text, width=20).pack(side="left")
        ttk.Entry(frame, textvariable=text_var).pack(side="left", fill="x", expand=True)

    def crea_campo_categoria(self, parent, label_text, text_var):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", padx=20, pady=5)
        ttk.Label(frame, text=label_text, width=20).pack(side="left")

        self.combo_categoria = ttk.Combobox(
            frame,
            textvariable=text_var,
            state="normal",
            postcommand=self.carica_categorie_salvate,
        )
        self.combo_categoria.pack(side="left", fill="x", expand=True)

        ttk.Button(frame, text="Aggiorna", command=self.carica_categorie_salvate).pack(side="left", padx=(5, 0))

    def crea_campo_data(self, parent, label_text, text_var):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", padx=20, pady=5)
        ttk.Label(frame, text=label_text, width=20).pack(side="left")

        entry = ttk.Entry(frame, textvariable=text_var, state="readonly")
        entry.pack(side="left", fill="x", expand=True)

        def apri_calendario():
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

        ttk.Button(frame, text="...", width=3, command=apri_calendario).pack(side="left", padx=(5, 0))
        entry.bind("<Button-1>", lambda _event: apri_calendario())
