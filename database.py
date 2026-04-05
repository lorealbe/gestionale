import sqlite3

DB_NAME = "gestionale.db"
LITRI_PER_QUINTALE = 100.0


def get_conn():
    conn = sqlite3.connect(DB_NAME)
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
