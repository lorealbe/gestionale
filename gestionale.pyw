import tkinter as tk

from app_gui import FinestraLogin
from database import init_db
# --- AVVIO DEL PROGRAMMA ---
if __name__ == "__main__":
    init_db()
    root_window = tk.Tk()
    app = FinestraLogin(root_window)
    root_window.mainloop()