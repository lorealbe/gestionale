import os
import shutil
import sqlite3
from pathlib import Path

APP_NAME = "Gestionale"
DB_NAME = "gestionale.db"
LITRI_PER_QUINTALE = 100.0

DATA_ROOT = Path(os.getenv("APPDATA", str(Path.home()))) / APP_NAME
DB_PATH = DATA_ROOT / DB_NAME
FATTURE_ROOT = DATA_ROOT / "fatture_caricate"

LEGACY_ROOT = Path(__file__).resolve().parent
LEGACY_DB_PATH = LEGACY_ROOT / DB_NAME
LEGACY_FATTURE_ROOT = LEGACY_ROOT / "fatture_caricate"

_DATA_READY = False


def _as_relative_fattura_path(percorso_file: str) -> str:
    raw = (percorso_file or "").strip()
    if not raw:
        return raw

    p = Path(raw)
    if not p.is_absolute():
        return raw.replace("\\", "/")

    for root in (FATTURE_ROOT, LEGACY_FATTURE_ROOT):
        try:
            rel = p.resolve().relative_to(root.resolve())
            return rel.as_posix()
        except Exception:
            continue

    # Path assoluto non riconosciuto: lo lasciamo invariato.
    return raw


def _normalize_fatture_paths_in_db():
    if not DB_PATH.exists():
        return

    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            c = conn.cursor()
            c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fatture'")
            if not c.fetchone():
                return

            c.execute("SELECT id, percorso_file FROM fatture")
            rows = c.fetchall()
            for fattura_id, percorso_file in rows:
                nuovo = _as_relative_fattura_path(percorso_file)
                if nuovo and nuovo != percorso_file:
                    c.execute("UPDATE fatture SET percorso_file=? WHERE id=?", (nuovo, fattura_id))
    except sqlite3.Error:
        # La tabella fatture potrebbe non esistere ancora al primo avvio.
        pass


def ensure_data_paths():
    global _DATA_READY
    if _DATA_READY:
        return

    DATA_ROOT.mkdir(parents=True, exist_ok=True)

    # Migrazione automatica: usa il DB storico della cartella progetto se AppData e vuota.
    if not DB_PATH.exists() and LEGACY_DB_PATH.exists():
        shutil.copy2(LEGACY_DB_PATH, DB_PATH)

    # Migrazione automatica archivio fatture storico.
    if not FATTURE_ROOT.exists() and LEGACY_FATTURE_ROOT.exists():
        shutil.copytree(LEGACY_FATTURE_ROOT, FATTURE_ROOT)

    _normalize_fatture_paths_in_db()
    _DATA_READY = True


def get_db_path() -> Path:
    ensure_data_paths()
    return DB_PATH


def get_fatture_root() -> Path:
    ensure_data_paths()
    FATTURE_ROOT.mkdir(parents=True, exist_ok=True)
    return FATTURE_ROOT


def get_fatture_user_dir(user_id: int) -> Path:
    user_dir = get_fatture_root() / f"user_{user_id}"
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def to_storage_fattura_path(file_path: Path) -> str:
    try:
        return file_path.resolve().relative_to(get_fatture_root().resolve()).as_posix()
    except Exception:
        return str(file_path)


def resolve_fattura_path(stored_path: str) -> Path:
    p = Path(stored_path)
    if p.is_absolute():
        return p
    return get_fatture_root() / p


def get_conn():
    conn = sqlite3.connect(str(get_db_path()))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Inizializza le tabelle del database se non esistono."""
    with get_conn() as conn:
        c = conn.cursor()

        # Tabella Utenti (login)
        c.execute('''CREATE TABLE IF NOT EXISTS utenti
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      username TEXT UNIQUE NOT NULL,
                      password_hash TEXT NOT NULL)''')

        # Tabella Profilo (anagrafica collegata all'utente)
        c.execute('''CREATE TABLE IF NOT EXISTS profili
                     (user_id INTEGER PRIMARY KEY,
                      nome TEXT,
                      piva TEXT,
                      professione TEXT,
                      FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE)''')

        # Tabella Movimenti (entrate/uscite collegate all'utente)
        c.execute('''CREATE TABLE IF NOT EXISTS movimenti
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER NOT NULL,
                      data_op TEXT NOT NULL, -- ISO: YYYY-MM-DD
                      tipo TEXT NOT NULL CHECK(tipo IN ('ENTRATA','USCITA')),
                      categoria TEXT,
                      descrizione TEXT,
                      importo REAL NOT NULL,
                      iva_importo REAL NOT NULL DEFAULT 0,
                      FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE)''')

        # Migrazione per database gia esistenti: aggiunge colonna IVA se manca.
        c.execute("PRAGMA table_info(movimenti)")
        colonne_movimenti = {row[1] for row in c.fetchall()}
        if "iva_importo" not in colonne_movimenti:
            c.execute("ALTER TABLE movimenti ADD COLUMN iva_importo REAL NOT NULL DEFAULT 0")

        # Indice utile per velocizzare i report per periodo
        c.execute('''CREATE INDEX IF NOT EXISTS idx_mov_user_date
                     ON movimenti(user_id, data_op)''')

        # Tabella Produzione Latte (quantita salvata in litri, input in quintali)
        c.execute('''CREATE TABLE IF NOT EXISTS produzione_latte
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER NOT NULL,
                      data_op TEXT NOT NULL, -- ISO: YYYY-MM-DD
                      litri REAL NOT NULL CHECK(litri > 0),
                      prezzo_litro REAL NOT NULL DEFAULT 0,
                      movimento_id INTEGER,
                      FOREIGN KEY(movimento_id) REFERENCES movimenti(id) ON DELETE SET NULL,
                      FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE)''')

        # Migrazione per database gia esistenti: aggiunge prezzo_litro se manca.
        c.execute("PRAGMA table_info(produzione_latte)")
        colonne_produzione = {row[1] for row in c.fetchall()}
        if colonne_produzione and "prezzo_litro" not in colonne_produzione:
            c.execute("ALTER TABLE produzione_latte ADD COLUMN prezzo_litro REAL NOT NULL DEFAULT 0")
        if colonne_produzione and "movimento_id" not in colonne_produzione:
            c.execute("ALTER TABLE produzione_latte ADD COLUMN movimento_id INTEGER")

        c.execute('''CREATE INDEX IF NOT EXISTS idx_prod_user_date
                     ON produzione_latte(user_id, data_op)''')

        # Se viene eliminato un movimento latte, elimina anche la produzione collegata.
        c.execute('''CREATE TRIGGER IF NOT EXISTS trg_movimenti_delete_produzione_latte
                     BEFORE DELETE ON movimenti
                     FOR EACH ROW
                     BEGIN
                         DELETE FROM produzione_latte WHERE movimento_id = OLD.id;
                     END''')

        # Archivio fatture caricate
        c.execute('''CREATE TABLE IF NOT EXISTS fatture
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  origine TEXT NOT NULL,
                  movimento_id INTEGER,
                  produzione_id INTEGER,
                  nome_originale TEXT NOT NULL,
                  percorso_file TEXT NOT NULL,
                  data_caricamento TEXT NOT NULL,
                  FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE,
                  FOREIGN KEY(movimento_id) REFERENCES movimenti(id) ON DELETE SET NULL,
                  FOREIGN KEY(produzione_id) REFERENCES produzione_latte(id) ON DELETE SET NULL)''')
