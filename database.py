import os
import json
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


def _migrate_legacy_parser_payload(cursor):
    cursor.execute("PRAGMA table_info(movimenti)")
    colonne = {row[1] for row in cursor.fetchall()}

    colonne_target = {
        "parser_invoice_number",
        "parser_invoice_date",
        "parser_due_date",
        "parser_supplier_name",
        "parser_supplier_vat",
        "parser_customer_name",
        "parser_customer_vat",
        "parser_total_amount",
        "parser_taxable_total",
        "parser_vat_total",
        "parser_payment_terms",
        "parser_warnings",
        "parser_products",
        "parser_fields_view",
    }

    if "parser_payload_json" not in colonne:
        return
    if not colonne_target.issubset(colonne):
        return

    cursor.execute(
        '''
            SELECT id, parser_payload_json
            FROM movimenti
            WHERE parser_payload_json IS NOT NULL
              AND TRIM(parser_payload_json) <> ''
              AND COALESCE(TRIM(parser_fields_view), '') = ''
        '''
    )
    rows = cursor.fetchall()

    for movimento_id, payload_raw in rows:
        try:
            payload = json.loads(payload_raw)
        except Exception:
            continue

        if not isinstance(payload, dict):
            continue

        fields = payload.get("fields")
        if not isinstance(fields, dict):
            fields = {}

        def estrai_valore(field_name):
            field = fields.get(field_name)
            if not isinstance(field, dict):
                return ""
            value = field.get("normalized_value")
            if value in (None, ""):
                value = field.get("raw_value")
            if value in (None, ""):
                return ""
            return str(value).strip()

        warnings = payload.get("warnings", [])
        if not isinstance(warnings, list):
            warnings = []
        warnings_text = " | ".join(str(w).strip() for w in warnings if str(w).strip())

        prodotti = []
        line_items = payload.get("line_items", [])
        if isinstance(line_items, list):
            for item in line_items:
                if not isinstance(item, dict):
                    continue

                descrizione = str(item.get("description") or "").strip()
                quantita = item.get("quantity")
                totale = item.get("line_total")

                if not descrizione or quantita in (None, "") or totale in (None, ""):
                    continue

                try:
                    quantita_num = float(str(quantita).replace(",", "."))
                    totale_num = float(str(totale).replace(",", "."))
                except ValueError:
                    continue

                if quantita_num <= 0 or totale_num <= 0:
                    continue

                prodotti.append(f"{descrizione} - qta {quantita} - tot {totale}")

        products_text = " | ".join(prodotti)

        campi_riepilogo = []
        for field_name in sorted(fields):
            field = fields.get(field_name)
            if not isinstance(field, dict):
                continue

            value = field.get("normalized_value")
            if value in (None, ""):
                value = field.get("raw_value")
            value_text = str(value).strip() if value not in (None, "") else "-"

            confidence = field.get("confidence", 0.0) or 0.0
            try:
                confidence_pct = int(round(float(confidence) * 100))
            except (TypeError, ValueError):
                confidence_pct = 0

            needs_review = bool(field.get("requires_confirmation", False))
            suffix = " [Conferma]" if needs_review else ""
            label = field_name.replace("_", " ").title()
            campi_riepilogo.append(f"{label}: {value_text} ({confidence_pct}%){suffix}")

        fields_view = " | ".join(campi_riepilogo)

        cursor.execute(
            '''
                UPDATE movimenti
                SET parser_invoice_number=?, parser_invoice_date=?, parser_due_date=?,
                    parser_supplier_name=?, parser_supplier_vat=?,
                    parser_customer_name=?, parser_customer_vat=?,
                    parser_total_amount=?, parser_taxable_total=?, parser_vat_total=?,
                    parser_payment_terms=?, parser_warnings=?, parser_products=?, parser_fields_view=?
                WHERE id=?
            ''',
            (
                estrai_valore("invoice_number"),
                estrai_valore("invoice_date"),
                estrai_valore("due_date"),
                estrai_valore("supplier_name"),
                estrai_valore("supplier_vat"),
                estrai_valore("customer_name"),
                estrai_valore("customer_vat"),
                estrai_valore("total_amount"),
                estrai_valore("taxable_total"),
                estrai_valore("vat_total"),
                estrai_valore("payment_terms"),
                warnings_text,
                products_text,
                fields_view,
                movimento_id,
            ),
        )


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

        colonne_parser = {
            "parser_invoice_number": "TEXT",
            "parser_invoice_date": "TEXT",
            "parser_due_date": "TEXT",
            "parser_supplier_name": "TEXT",
            "parser_supplier_vat": "TEXT",
            "parser_customer_name": "TEXT",
            "parser_customer_vat": "TEXT",
            "parser_total_amount": "TEXT",
            "parser_taxable_total": "TEXT",
            "parser_vat_total": "TEXT",
            "parser_payment_terms": "TEXT",
            "parser_warnings": "TEXT",
            "parser_products": "TEXT",
            "parser_fields_view": "TEXT",
        }
        for nome_colonna, tipo_colonna in colonne_parser.items():
            if nome_colonna not in colonne_movimenti:
                c.execute(f"ALTER TABLE movimenti ADD COLUMN {nome_colonna} {tipo_colonna}")

        _migrate_legacy_parser_payload(c)

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
        c.execute('''CREATE INDEX IF NOT EXISTS idx_prod_user_movimento
                 ON produzione_latte(user_id, movimento_id)''')

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

        c.execute('''CREATE INDEX IF NOT EXISTS idx_fatture_user_movimento
                 ON fatture(user_id, movimento_id)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_fatture_user_produzione
                 ON fatture(user_id, produzione_id)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_fatture_user_data
                 ON fatture(user_id, data_caricamento DESC)''')
