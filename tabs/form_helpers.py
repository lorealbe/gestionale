import tkinter as tk
import textwrap
from tkinter import ttk
from tkinter import font as tkfont
from datetime import datetime


class FormHelpersMixin:
    def abilita_a_capo_tutte_treeview(self, max_lines=None):
        root = getattr(self, "root", None)
        if root is None:
            return

        stack = [root]
        while stack:
            widget = stack.pop()
            try:
                children = widget.winfo_children()
            except tk.TclError:
                continue

            stack.extend(children)

            if isinstance(widget, ttk.Treeview):
                self.abilita_a_capo_treeview(widget, max_lines=max_lines)

    def abilita_a_capo_treeview(self, tree, max_lines=None):
        if tree is None or getattr(tree, "_wrap_auto_enabled", False):
            return

        tree._wrap_auto_enabled = True
        if max_lines is None:
            tree._wrap_max_lines = None
        else:
            tree._wrap_max_lines = max(1, int(max_lines))
        tree._wrap_raw_values = {}

        base_style = tree.cget("style") or "Treeview"
        wrap_style = f"Wrap{str(id(tree))}.{base_style}"

        tree._wrap_base_style = base_style
        tree._wrap_style = wrap_style

        style = ttk.Style(tree)
        style.configure(wrap_style)
        tree.configure(style=wrap_style)

        original_insert = tree.insert
        original_set = tree.set
        original_delete = tree.delete

        tree._wrap_original_insert = original_insert
        tree._wrap_original_set = original_set
        tree._wrap_original_delete = original_delete

        def _normalize_values(raw_values):
            if raw_values is None:
                return tuple()
            if isinstance(raw_values, (list, tuple)):
                return tuple(raw_values)
            return (raw_values,)

        def _wrapped_insert(parent, index, iid=None, **kwargs):
            raw_values = _normalize_values(kwargs.get("values"))
            if raw_values:
                kwargs["values"] = self._treeview_wrap_values(tree, raw_values)

            item_id = original_insert(parent, index, iid=iid, **kwargs)

            if raw_values:
                tree._wrap_raw_values[item_id] = raw_values
                self._treeview_update_rowheight(tree)

            return item_id

        def _wrapped_set(item, column=None, value=None):
            # query mode
            if value is None:
                return original_set(item, column)

            if column is None:
                return original_set(item, column, value)

            raw_values = list(tree._wrap_raw_values.get(item, tree.item(item, "values") or tuple()))
            col_index = self._treeview_column_index(tree, column)

            if col_index is None:
                return original_set(item, column, value)

            if col_index >= len(raw_values):
                raw_values.extend([""] * (col_index - len(raw_values) + 1))
            raw_values[col_index] = value
            tree._wrap_raw_values[item] = tuple(raw_values)

            col_key = self._treeview_column_key(tree, col_index)
            wrapped_value = self._treeview_wrap_value(tree, col_key, value)
            result = original_set(item, column, wrapped_value)
            self._treeview_update_rowheight(tree)
            return result

        def _drop_item_cache(item_id):
            tree._wrap_raw_values.pop(item_id, None)
            for child_id in tree.get_children(item_id):
                _drop_item_cache(child_id)

        def _wrapped_delete(*items):
            for item_id in items:
                _drop_item_cache(item_id)
            return original_delete(*items)

        def _schedule_rewrap(_event=None):
            pending = getattr(tree, "_wrap_after_id", None)
            if pending:
                try:
                    tree.after_cancel(pending)
                except tk.TclError:
                    pass
            tree._wrap_after_id = tree.after(120, lambda: self._treeview_rewrap_all_items(tree))

        tree.insert = _wrapped_insert
        tree.set = _wrapped_set
        tree.delete = _wrapped_delete
        tree.bind("<Configure>", _schedule_rewrap, add="+")

        self._treeview_rewrap_all_items(tree)

    def _treeview_column_key(self, tree, column_index):
        columns = tuple(tree.cget("columns"))
        if 0 <= int(column_index) < len(columns):
            return columns[int(column_index)]
        return None

    def _treeview_column_index(self, tree, column_name):
        columns = tuple(tree.cget("columns"))
        if isinstance(column_name, str) and column_name.startswith("#"):
            try:
                index = int(column_name[1:]) - 1
            except ValueError:
                return None
            return index if 0 <= index < len(columns) else None

        try:
            return columns.index(column_name)
        except ValueError:
            return None

    def _treeview_wrap_values(self, tree, raw_values):
        columns = tuple(tree.cget("columns"))
        wrapped = []

        for idx, raw in enumerate(raw_values):
            column = columns[idx] if idx < len(columns) else None
            wrapped.append(self._treeview_wrap_value(tree, column, raw))

        return tuple(wrapped)

    def _treeview_wrap_value(self, tree, column, value):
        if value is None:
            return ""

        text = str(value).replace("\r\n", "\n").replace("\r", "\n")
        text_lines = []
        for raw_line in text.split("\n"):
            if not raw_line.strip():
                text_lines.append("")
                continue
            text_lines.append(" ".join(raw_line.split()))
        text = "\n".join(text_lines)

        if not text:
            return ""

        if not column:
            return text

        try:
            col_width = int(tree.column(column, "width") or 0)
        except tk.TclError:
            col_width = 0

        if col_width <= 24:
            return text

        font_name = ttk.Style(tree).lookup(tree._wrap_base_style, "font")
        try:
            font_obj = tkfont.nametofont(font_name) if font_name else tkfont.nametofont("TkDefaultFont")
        except tk.TclError:
            font_obj = tkfont.nametofont("TkDefaultFont")

        char_px = max(int(font_obj.measure("0") or 0), 7)
        max_chars = max(6, int((col_width - 14) / char_px))

        wrapped_lines = []
        for line in text.split("\n"):
            if not line:
                wrapped_lines.append("")
                continue
            wrapped_lines.append(
                textwrap.fill(
                    line,
                    width=max_chars,
                    break_long_words=True,
                    break_on_hyphens=False,
                )
            )

        return "\n".join(wrapped_lines)

    def _treeview_rewrap_all_items(self, tree):
        if tree is None or not getattr(tree, "_wrap_auto_enabled", False):
            return

        original_set = getattr(tree, "_wrap_original_set", None)
        if original_set is None:
            return

        columns = tuple(tree.cget("columns"))
        for item_id in tree.get_children(""):
            raw_values = tree._wrap_raw_values.get(item_id)
            if raw_values is None:
                raw_values = tuple(tree.item(item_id, "values") or tuple())
                tree._wrap_raw_values[item_id] = raw_values

            wrapped_values = self._treeview_wrap_values(tree, raw_values)
            for idx, wrapped in enumerate(wrapped_values):
                if idx >= len(columns):
                    break
                original_set(item_id, columns[idx], wrapped)

        self._treeview_update_rowheight(tree)

    def _treeview_update_rowheight(self, tree):
        if tree is None or not getattr(tree, "_wrap_auto_enabled", False):
            return

        max_lines = 1
        for item_id in tree.get_children(""):
            for value in tree.item(item_id, "values"):
                lines = str(value).count("\n") + 1
                if lines > max_lines:
                    max_lines = lines

        max_lines_cap = getattr(tree, "_wrap_max_lines", None)
        if max_lines_cap is not None:
            max_lines = min(max_lines, int(max_lines_cap))

        style_name = getattr(tree, "_wrap_style", "Treeview")
        base_style = getattr(tree, "_wrap_base_style", "Treeview")
        style = ttk.Style(tree)

        font_name = style.lookup(base_style, "font")
        try:
            font_obj = tkfont.nametofont(font_name) if font_name else tkfont.nametofont("TkDefaultFont")
        except tk.TclError:
            font_obj = tkfont.nametofont("TkDefaultFont")

        line_px = max(int(font_obj.metrics("linespace") or 0), 14)
        rowheight = (line_px * max_lines) + 6
        style.configure(style_name, rowheight=rowheight)

    def crea_container_scorribile(self, parent, *, padding=0, stretch_to_viewport=False):
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

        def _sync_window_size(canvas_width=None):
            options = {}
            if canvas_width is not None:
                options["width"] = canvas_width

            if stretch_to_viewport:
                viewport_height = max(int(canvas.winfo_height()), 0)
                required_height = max(int(content.winfo_reqheight()), 0)
                options["height"] = max(required_height, viewport_height)

            if options:
                canvas.itemconfigure(window_id, **options)

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
            _sync_window_size()
            _refresh_scrollregion_and_clamp()

        def _on_canvas_configure(event):
            _sync_window_size(canvas_width=event.width)
            _refresh_scrollregion_and_clamp()

        def _mousewheel_step(event):
            if getattr(event, "num", None) == 4:
                return -1
            if getattr(event, "num", None) == 5:
                return 1

            delta = int(getattr(event, "delta", 0) or 0)
            if delta == 0:
                return 0
            return -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)

        def _find_ancestor_scrollable_widget(widget):
            current = widget
            while current is not None:
                if isinstance(current, (ttk.Treeview, tk.Listbox, tk.Text)):
                    return current
                current = getattr(current, "master", None)
            return None

        def _on_mousewheel(event):
            step = _mousewheel_step(event)
            if step == 0:
                return "break"

            # If the pointer is over a scrollable widget, scroll it instead of the page.
            scrollable_widget = _find_ancestor_scrollable_widget(getattr(event, "widget", None))
            if scrollable_widget is not None:
                try:
                    scrollable_widget.yview_scroll(step, "units")
                except tk.TclError:
                    pass
                return "break"

            _refresh_scrollregion_and_clamp()
            if not _has_vertical_overflow():
                return "break"

            canvas.yview_scroll(step, "units")
            return "break"

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
