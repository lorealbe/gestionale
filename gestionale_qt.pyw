from database import init_db


def _show_dependency_error(message: str):
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Dipendenza mancante", message)
        root.destroy()
    except Exception:
        # Fallback in caso non sia possibile mostrare una dialog.
        print(message)


if __name__ == "__main__":
    init_db()

    try:
        from qt_app.bootstrap import run_qt_app
    except ModuleNotFoundError as exc:
        missing_name = str(exc.name or "")
        if "PySide6" in missing_name or missing_name == "shiboken6":
            _show_dependency_error(
                "PySide6 non e installato.\n\n"
                "Installa con:\n"
                "pip install PySide6"
            )
            raise SystemExit(1)
        raise

    raise SystemExit(run_qt_app())
