import tkinter as tk
from tkinter import ttk
from datetime import datetime


class FormHelpersMixin:
    def crea_container_scorribile(self, parent, *, padding=0):
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        content = ttk.Frame(canvas, padding=padding)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        # Keep references to update scroll region/position when child layouts change dynamically.
        content._scroll_canvas = canvas
        content._scroll_container = container
        content._scroll_window_id = window_id

        def _has_vertical_overflow():
            bbox = canvas.bbox("all")
            if not bbox:
                return False

            content_height = max(int(bbox[3] - bbox[1]), 0)
            viewport_height = max(int(canvas.winfo_height()), 0)
            # Small tolerance avoids residual 1-2px offsets from geometry recalculations.
            return content_height > (viewport_height + 2)

        def _refresh_scrollregion_and_clamp():
            bbox = canvas.bbox("all")
            if bbox:
                canvas.configure(scrollregion=bbox)

            if not _has_vertical_overflow():
                canvas.yview_moveto(0.0)

        def _on_content_configure(_event):
            _refresh_scrollregion_and_clamp()

        def _on_canvas_configure(event):
            canvas.itemconfigure(window_id, width=event.width)
            _refresh_scrollregion_and_clamp()

        def _on_mousewheel(event):
            _refresh_scrollregion_and_clamp()
            if not _has_vertical_overflow():
                return "break"

            # Windows/macOS use event.delta, Linux often uses Button-4/5.
            if getattr(event, "num", None) == 4:
                step = -1
            elif getattr(event, "num", None) == 5:
                step = 1
            else:
                delta = int(getattr(event, "delta", 0) or 0)
                if delta == 0:
                    step = 0
                else:
                    step = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)

            if step != 0:
                canvas.yview_scroll(step, "units")
                return "break"
            return None

        def _bind_mousewheel(_event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            canvas.bind_all("<Button-4>", _on_mousewheel)
            canvas.bind_all("<Button-5>", _on_mousewheel)

        def _unbind_mousewheel(_event):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        content.bind("<Configure>", _on_content_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        container.bind("<Enter>", _bind_mousewheel)
        container.bind("<Leave>", _unbind_mousewheel)
        return content

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
