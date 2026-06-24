import os
import re
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from services.product_parser_utils import build_basic_product_storage_line, serialize_product_storage_lines

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

DEFAULT_AZIENDA_ANIMALI = {
    "bovini": False,
    "bovini_capi": 0,
    "ovini": False,
    "ovini_capi": 0,
    "caprini": False,
    "caprini_capi": 0,
    "altro_text": "",
    "altro_capi": 0,
}

DEFAULT_AZIENDA_INFO = {
    "nome_azienda": "",
    "piva": "",
    "occupazione": "",
    "data_creazione": "",
}

ANIMAL_TYPE_OPTIONS = ("BOVINI", "OVINI", "CAPRINI", "SUINI", "AVICOLI", "EQUINI", "ALTRO")
ANIMAL_PURPOSE_OPTIONS = ("LATTE", "CARNE")
GROUPS_DESCRIPTION_PATTERN = re.compile(r"\s*\|\s*Gruppi:\s*.*$", re.IGNORECASE)


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

                prodotti.append(build_basic_product_storage_line(descrizione, quantita, totale))

        products_text = serialize_product_storage_lines(prodotti, separator=" | ")

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


def get_azienda_animali(user_id: int) -> dict:
    config = dict(DEFAULT_AZIENDA_ANIMALI)

    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute(
                '''
                SELECT
                    bovini,
                    bovini_capi,
                    ovini,
                    ovini_capi,
                    caprini,
                    caprini_capi,
                    altro_text,
                    altro_capi
                FROM azienda_animali
                WHERE user_id=?
            ''',
                (user_id,),
            )
            row = c.fetchone()
    except sqlite3.Error:
        return config

    if not row:
        return config

    config["bovini"] = bool(row[0])
    config["bovini_capi"] = int(row[1] or 0)
    config["ovini"] = bool(row[2])
    config["ovini_capi"] = int(row[3] or 0)
    config["caprini"] = bool(row[4])
    config["caprini_capi"] = int(row[5] or 0)
    config["altro_text"] = (row[6] or "").strip()
    config["altro_capi"] = int(row[7] or 0)
    return config


def get_azienda_info(user_id: int) -> dict:
    info = dict(DEFAULT_AZIENDA_INFO)

    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute(
                '''
                SELECT nome_azienda, piva, occupazione, data_creazione
                FROM azienda_info
                WHERE user_id=?
            ''',
                (user_id,),
            )
            row = c.fetchone()
    except sqlite3.Error:
        return info

    if not row:
        return info

    info["nome_azienda"] = (row[0] or "").strip()
    info["piva"] = (row[1] or "").strip()
    info["occupazione"] = (row[2] or "").strip()
    info["data_creazione"] = (row[3] or "").strip()
    return info


def save_azienda_info(user_id: int, nome_azienda: str, piva: str, occupazione: str, data_creazione: str):
    nome_clean = (nome_azienda or "").strip()
    piva_clean = (piva or "").strip()
    occupazione_clean = (occupazione or "").strip()
    data_creazione_clean = (data_creazione or "").strip()
    updated_at = datetime.now().isoformat(timespec="seconds")

    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO azienda_info (user_id, nome_azienda, piva, occupazione, data_creazione, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                nome_azienda=excluded.nome_azienda,
                piva=excluded.piva,
                occupazione=excluded.occupazione,
                data_creazione=excluded.data_creazione,
                updated_at=excluded.updated_at
        ''',
            (
                user_id,
                nome_clean,
                piva_clean,
                occupazione_clean,
                data_creazione_clean,
                updated_at,
            ),
        )


def _to_non_negative_int(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number >= 0 else 0


def _to_bool_int(value) -> int:
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "si", "s", "yes", "y", "on"):
            return 1
        if text in ("0", "false", "no", "n", "off", ""):
            return 0

    if isinstance(value, (int, float)):
        try:
            return 1 if int(value) != 0 else 0
        except (TypeError, ValueError):
            return 0

    return 1 if bool(value) else 0


def _normalize_tipo_animale(raw_value: str) -> str:
    return (raw_value or "").strip().upper()


def _normalize_finalita_animale(raw_value: str) -> str:
    return (raw_value or "").strip().upper()


def _default_group_name(tipo_animale: str, finalita: str = "", altro_label: str = "") -> str:
    tipo = _normalize_tipo_animale(tipo_animale)
    finalita_norm = _normalize_finalita_animale(finalita)
    altro_clean = (altro_label or "").strip()

    if tipo == "ALTRO":
        base = f"Altro ({altro_clean})" if altro_clean else "Altro"
    else:
        base = tipo.title() if tipo else "Gruppo"

    if finalita_norm == "LATTE":
        return f"{base} - Da Latte"
    if finalita_norm == "CARNE":
        return f"{base} - Da Carne"
    return base


def _migrate_legacy_azienda_animali_to_dettaglio(cursor):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='azienda_animali'")
    if not cursor.fetchone():
        return

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='azienda_animali_dettaglio'")
    if not cursor.fetchone():
        return

    cursor.execute(
        '''
        SELECT user_id, bovini, bovini_capi, ovini, ovini_capi, caprini, caprini_capi, altro_text, altro_capi
        FROM azienda_animali
    '''
    )
    rows = cursor.fetchall()
    now_text = datetime.now().isoformat(timespec="seconds")

    for user_id, bovini, bovini_capi, ovini, ovini_capi, caprini, caprini_capi, altro_text, altro_capi in rows:
        cursor.execute("SELECT COUNT(1) FROM azienda_animali_dettaglio WHERE user_id=?", (user_id,))
        count_row = cursor.fetchone()
        if int((count_row[0] if count_row else 0) or 0) > 0:
            continue

        entries = []
        bovini_num = _to_non_negative_int(bovini_capi)
        ovini_num = _to_non_negative_int(ovini_capi)
        caprini_num = _to_non_negative_int(caprini_capi)
        altro_num = _to_non_negative_int(altro_capi)

        if bool(bovini) and bovini_num > 0:
            entries.append(("BOVINI", "", "", bovini_num))
        if bool(ovini) and ovini_num > 0:
            entries.append(("OVINI", "", "", ovini_num))
        if bool(caprini) and caprini_num > 0:
            entries.append(("CAPRINI", "", "", caprini_num))

        altro_clean = (altro_text or "").strip()
        if altro_clean and altro_num > 0:
            entries.append(("ALTRO", "", altro_clean, altro_num))

        for tipo, finalita, altro_label, capi in entries:
            group_name = _default_group_name(tipo, finalita, altro_label)
            cursor.execute(
                '''
                INSERT OR IGNORE INTO azienda_animali_dettaglio
                    (
                        user_id,
                        tipo_animale,
                        finalita,
                        altro_label,
                        group_name,
                        riproduzione,
                        capi,
                        created_at,
                        updated_at
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
                (user_id, tipo, finalita, altro_label, group_name, 0, capi, now_text, now_text),
            )


def _backfill_missing_group_names(cursor):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='azienda_animali_dettaglio'")
    if not cursor.fetchone():
        return

    cursor.execute("PRAGMA table_info(azienda_animali_dettaglio)")
    colonne = {row[1] for row in cursor.fetchall()}
    if "group_name" not in colonne:
        return

    cursor.execute(
        '''
        SELECT id, tipo_animale, finalita, altro_label
        FROM azienda_animali_dettaglio
        WHERE COALESCE(NULLIF(TRIM(group_name), ''), '') = ''
    '''
    )
    rows = cursor.fetchall()

    for row_id, tipo_animale, finalita, altro_label in rows:
        group_name = _default_group_name(tipo_animale, finalita, altro_label)
        cursor.execute(
            "UPDATE azienda_animali_dettaglio SET group_name=? WHERE id=?",
            (group_name, row_id),
        )


def _ensure_animali_dettaglio_unique_on_group_name(cursor):
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='azienda_animali_dettaglio'")
    row = cursor.fetchone()
    if not row:
        return

    table_sql = " ".join(((row[0] or "").upper()).split())
    if "UNIQUE(USER_ID, TIPO_ANIMALE, FINALITA, ALTRO_LABEL, GROUP_NAME)" in table_sql:
        return

    cursor.execute("PRAGMA table_info(azienda_animali_dettaglio)")
    colonne = {row[1] for row in cursor.fetchall()}

    merged_into_expr = "COALESCE(merged_into_entry_id, 0)" if "merged_into_entry_id" in colonne else "0"
    merge_date_expr = "COALESCE(merge_date, '')" if "merge_date" in colonne else "''"
    riproduzione_expr = "COALESCE(riproduzione, 0)" if "riproduzione" in colonne else "0"

    cursor.execute(
        f'''
        SELECT
            id,
            user_id,
            tipo_animale,
            finalita,
            altro_label,
            group_name,
            {riproduzione_expr} AS riproduzione,
            capi,
            created_at,
            updated_at,
            {merged_into_expr} AS merged_into_entry_id,
            {merge_date_expr} AS merge_date
        FROM azienda_animali_dettaglio
        ORDER BY id
    '''
    )
    rows = cursor.fetchall()

    cursor.execute("DROP TABLE IF EXISTS azienda_animali_dettaglio_new")
    cursor.execute(
        '''
        CREATE TABLE azienda_animali_dettaglio_new
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             user_id INTEGER NOT NULL,
             tipo_animale TEXT NOT NULL,
             finalita TEXT NOT NULL DEFAULT '',
             altro_label TEXT NOT NULL DEFAULT '',
             group_name TEXT NOT NULL DEFAULT '',
             riproduzione INTEGER NOT NULL DEFAULT 0,
             capi INTEGER NOT NULL DEFAULT 0 CHECK(capi >= 0),
             created_at TEXT NOT NULL DEFAULT '',
             updated_at TEXT NOT NULL DEFAULT '',
             merged_into_entry_id INTEGER,
             merge_date TEXT NOT NULL DEFAULT '',
             UNIQUE(user_id, tipo_animale, finalita, altro_label, group_name),
             FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE)
    '''
    )

    now_text = datetime.now().isoformat(timespec="seconds")
    for (
        row_id,
        user_id,
        tipo_animale,
        finalita,
        altro_label,
        group_name,
        riproduzione,
        capi,
        created_at,
        updated_at,
        merged_into_entry_id,
        merge_date,
    ) in rows:
        tipo_norm = _normalize_tipo_animale(tipo_animale)
        finalita_norm = _normalize_finalita_animale(finalita)
        altro_clean = (altro_label or "").strip()
        group_name_clean = (group_name or "").strip() or _default_group_name(tipo_norm, finalita_norm, altro_clean)
        created_at_clean = (created_at or "").strip() or now_text
        updated_at_clean = (updated_at or "").strip() or now_text
        merged_into_clean = _to_non_negative_int(merged_into_entry_id)
        if merged_into_clean <= 0:
            merged_into_clean = None
        merge_date_clean = (merge_date or "").strip()

        cursor.execute(
            '''
            INSERT INTO azienda_animali_dettaglio_new
                (
                    id,
                    user_id,
                    tipo_animale,
                    finalita,
                    altro_label,
                    group_name,
                    riproduzione,
                    capi,
                    created_at,
                    updated_at,
                    merged_into_entry_id,
                    merge_date
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
            (
                int(row_id),
                int(user_id),
                tipo_norm,
                finalita_norm,
                altro_clean,
                group_name_clean,
                _to_bool_int(riproduzione),
                _to_non_negative_int(capi),
                created_at_clean,
                updated_at_clean,
                merged_into_clean,
                merge_date_clean,
            ),
        )

    cursor.execute("DROP TABLE azienda_animali_dettaglio")
    cursor.execute("ALTER TABLE azienda_animali_dettaglio_new RENAME TO azienda_animali_dettaglio")


def list_azienda_animali_entries(user_id: int, include_merged: bool = False) -> list[dict]:
    with get_conn() as conn:
        c = conn.cursor()
        query = (
            '''
            SELECT
                id,
                tipo_animale,
                finalita,
                altro_label,
                COALESCE(riproduzione, 0),
                capi,
                group_name,
                COALESCE(created_at, ''),
                COALESCE(updated_at, ''),
                COALESCE(merged_into_entry_id, 0),
                COALESCE(merge_date, '')
            FROM azienda_animali_dettaglio
            WHERE user_id=?
        '''
        )
        if not include_merged:
            query += " AND COALESCE(merged_into_entry_id, 0)=0"
        query += (
            '''
            ORDER BY
                COALESCE(NULLIF(TRIM(group_name), ''), tipo_animale) COLLATE NOCASE,
                tipo_animale,
                finalita,
                altro_label,
                id
        '''
        )
        c.execute(
            query,
            (user_id,),
        )
        rows = c.fetchall()

    entries = []
    for (
        row_id,
        tipo_animale,
        finalita,
        altro_label,
        riproduzione,
        capi,
        group_name,
        created_at,
        updated_at,
        merged_into_entry_id,
        merge_date,
    ) in rows:
        group_name_clean = (group_name or "").strip()
        if not group_name_clean:
            group_name_clean = _default_group_name(tipo_animale, finalita, altro_label)

        merged_into_clean = _to_non_negative_int(merged_into_entry_id)
        if merged_into_clean <= 0:
            merged_into_clean = None

        entries.append(
            {
                "id": int(row_id),
                "tipo_animale": (tipo_animale or "").strip().upper(),
                "finalita": (finalita or "").strip().upper(),
                "altro_label": (altro_label or "").strip(),
                "riproduzione": bool(_to_bool_int(riproduzione)),
                "capi": _to_non_negative_int(capi),
                "group_name": group_name_clean,
                "created_at": (created_at or "").strip(),
                "updated_at": (updated_at or "").strip(),
                "merged_into_entry_id": merged_into_clean,
                "merge_date": (merge_date or "").strip(),
            }
        )
    return entries


def upsert_azienda_animali_nascite_media(
    user_id: int,
    tipo_animale: str,
    altro_label: str,
    rapporto_nascite_genitori: float,
    cursor: sqlite3.Cursor | None = None,
) -> dict:
    tipo = _normalize_tipo_animale(tipo_animale)
    if tipo not in ANIMAL_TYPE_OPTIONS:
        raise ValueError("Tipo animale non valido.")

    altro_clean = (altro_label or "").strip()
    if tipo != "ALTRO":
        altro_clean = ""

    try:
        rapporto_value = float(rapporto_nascite_genitori)
    except (TypeError, ValueError):
        raise ValueError("Rapporto nascite/genitori non valido.")

    if rapporto_value <= 0:
        raise ValueError("Rapporto nascite/genitori deve essere maggiore di zero.")

    now_text = datetime.now().isoformat(timespec="seconds")

    def _apply(target_cursor: sqlite3.Cursor) -> dict:
        target_cursor.execute(
            '''
            SELECT COALESCE(media_nascite_per_capo, 0), COALESCE(campioni, 0)
            FROM azienda_animali_nascite_media
            WHERE user_id=? AND tipo_animale=? AND altro_label=?
        ''',
            (user_id, tipo, altro_clean),
        )
        row = target_cursor.fetchone()

        if row:
            media_attuale = float(row[0] or 0)
            campioni_attuali = _to_non_negative_int(row[1])
        else:
            media_attuale = 0.0
            campioni_attuali = 0

        campioni_nuovi = campioni_attuali + 1
        if campioni_attuali > 0:
            media_nuova = ((media_attuale * campioni_attuali) + rapporto_value) / campioni_nuovi
        else:
            media_nuova = rapporto_value

        target_cursor.execute(
            '''
            INSERT INTO azienda_animali_nascite_media
                (user_id, tipo_animale, altro_label, media_nascite_per_capo, campioni, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, tipo_animale, altro_label) DO UPDATE SET
                media_nascite_per_capo=excluded.media_nascite_per_capo,
                campioni=excluded.campioni,
                updated_at=excluded.updated_at
        ''',
            (user_id, tipo, altro_clean, media_nuova, campioni_nuovi, now_text),
        )

        return {
            "tipo_animale": tipo,
            "altro_label": altro_clean,
            "media_nascite_per_capo": media_nuova,
            "campioni": campioni_nuovi,
            "updated_at": now_text,
        }

    if cursor is not None:
        return _apply(cursor)

    with get_conn() as conn:
        c = conn.cursor()
        return _apply(c)


def list_azienda_animali_nascite_media(user_id: int) -> list[dict]:
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute(
                '''
                SELECT
                    COALESCE(tipo_animale, ''),
                    COALESCE(altro_label, ''),
                    COALESCE(media_nascite_per_capo, 0),
                    COALESCE(campioni, 0),
                    COALESCE(updated_at, '')
                FROM azienda_animali_nascite_media
                WHERE user_id=?
                  AND COALESCE(campioni, 0) > 0
                ORDER BY tipo_animale, altro_label
            ''',
                (user_id,),
            )
            rows = c.fetchall()
    except sqlite3.Error:
        return []

    entries = []
    for tipo_animale, altro_label, media_nascite_per_capo, campioni, updated_at in rows:
        tipo = _normalize_tipo_animale(tipo_animale)
        if tipo not in ANIMAL_TYPE_OPTIONS:
            continue

        altro_clean = (altro_label or "").strip() if tipo == "ALTRO" else ""
        campioni_value = _to_non_negative_int(campioni)
        if campioni_value <= 0:
            continue

        try:
            media_value = float(media_nascite_per_capo or 0)
        except (TypeError, ValueError):
            media_value = 0.0

        entries.append(
            {
                "tipo_animale": tipo,
                "altro_label": altro_clean,
                "media_nascite_per_capo": media_value,
                "campioni": campioni_value,
                "updated_at": (updated_at or "").strip(),
            }
        )

    return entries


def _normalize_entry_id_list(entry_ids) -> list[int]:
    if not entry_ids:
        return []

    normalized = []
    seen = set()
    for raw in entry_ids:
        entry_id = _to_non_negative_int(raw)
        if entry_id <= 0 or entry_id in seen:
            continue
        seen.add(entry_id)
        normalized.append(entry_id)
    return normalized


def set_movimento_animali_links(
    user_id: int,
    movimento_id: int,
    animale_entry_ids,
    cursor: sqlite3.Cursor | None = None,
):
    movimento_id_value = _to_non_negative_int(movimento_id)
    if movimento_id_value <= 0:
        raise ValueError("Movimento non valido.")

    entry_ids = _normalize_entry_id_list(animale_entry_ids)

    def _apply(target_cursor: sqlite3.Cursor):
        target_cursor.execute(
            "SELECT 1 FROM movimenti WHERE id=? AND user_id=?",
            (movimento_id_value, user_id),
        )
        if not target_cursor.fetchone():
            raise ValueError("Movimento non trovato.")

        if entry_ids:
            placeholders = ",".join(["?"] * len(entry_ids))
            target_cursor.execute(
                f"""
                SELECT id
                FROM azienda_animali_dettaglio
                WHERE user_id=? AND id IN ({placeholders})
            """,
                (user_id, *entry_ids),
            )
            valid_ids = {int(row[0]) for row in target_cursor.fetchall()}
            missing_ids = [entry_id for entry_id in entry_ids if entry_id not in valid_ids]
            if missing_ids:
                raise ValueError("Uno o piu gruppi animali selezionati non sono piu disponibili.")

        target_cursor.execute(
            "DELETE FROM movimenti_animali_link WHERE user_id=? AND movimento_id=?",
            (user_id, movimento_id_value),
        )

        if not entry_ids:
            return

        now_text = datetime.now().isoformat(timespec="seconds")
        target_cursor.executemany(
            '''
            INSERT INTO movimenti_animali_link (user_id, movimento_id, animale_entry_id, created_at)
            VALUES (?, ?, ?, ?)
        ''',
            [(user_id, movimento_id_value, entry_id, now_text) for entry_id in entry_ids],
        )

    if cursor is not None:
        _apply(cursor)
        return

    with get_conn() as conn:
        c = conn.cursor()
        _apply(c)


def get_movimento_animali_entry_ids(user_id: int, movimento_id: int) -> list[int]:
    movimento_id_value = _to_non_negative_int(movimento_id)
    if movimento_id_value <= 0:
        return []

    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            SELECT animale_entry_id
            FROM movimenti_animali_link
            WHERE user_id=? AND movimento_id=?
            ORDER BY id
        ''',
            (user_id, movimento_id_value),
        )
        rows = c.fetchall()

    entry_ids = []
    for row in rows:
        entry_id = _to_non_negative_int(row[0] if row else 0)
        if entry_id > 0:
            entry_ids.append(entry_id)
    return entry_ids


def get_movimento_animali_group_labels(user_id: int, movimento_id: int) -> list[str]:
    movimento_id_value = _to_non_negative_int(movimento_id)
    if movimento_id_value <= 0:
        return []

    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            SELECT
                a.id,
                a.tipo_animale,
                a.finalita,
                a.altro_label,
                a.group_name,
                a.capi
            FROM movimenti_animali_link l
            JOIN azienda_animali_dettaglio a
              ON a.id = l.animale_entry_id
             AND a.user_id = l.user_id
            WHERE l.user_id=? AND l.movimento_id=?
            ORDER BY
                COALESCE(NULLIF(TRIM(a.group_name), ''), a.tipo_animale) COLLATE NOCASE,
                a.id
        ''',
            (user_id, movimento_id_value),
        )
        rows = c.fetchall()

    labels = []
    for entry_id, tipo_animale, finalita, altro_label, group_name, capi in rows:
        tipo = (tipo_animale or "").strip().upper()
        finalita_norm = (finalita or "").strip().upper()
        altro_clean = (altro_label or "").strip()
        group_name_clean = (group_name or "").strip() or _default_group_name(tipo, finalita_norm, altro_clean)

        if tipo == "ALTRO":
            tipo_label = f"Altro ({altro_clean})" if altro_clean else "Altro"
        else:
            tipo_label = tipo.title() if tipo else "Tipo"

        if finalita_norm == "LATTE":
            finalita_label = "Da Latte"
        elif finalita_norm == "CARNE":
            finalita_label = "Da Carne"
        else:
            finalita_label = "N/D"

        capi_count = _to_non_negative_int(capi)
        labels.append(f"{group_name_clean} ({tipo_label}, {finalita_label}, {capi_count} capi)")

    return labels


def _refresh_linked_group_descriptions(user_id: int, movimento_ids, cursor: sqlite3.Cursor) -> int:
    normalized_ids = []
    seen = set()
    for raw_movimento_id in movimento_ids or []:
        movimento_id = _to_non_negative_int(raw_movimento_id)
        if movimento_id <= 0 or movimento_id in seen:
            continue
        seen.add(movimento_id)
        normalized_ids.append(movimento_id)

    if not normalized_ids:
        return 0

    placeholders = ",".join(["?"] * len(normalized_ids))

    cursor.execute(
        f'''
            SELECT
                l.movimento_id,
                a.id,
                a.tipo_animale,
                a.finalita,
                a.altro_label,
                a.group_name
            FROM movimenti_animali_link l
            JOIN azienda_animali_dettaglio a
              ON a.id = l.animale_entry_id
             AND a.user_id = l.user_id
            WHERE l.user_id=? AND l.movimento_id IN ({placeholders})
            ORDER BY
                l.movimento_id,
                COALESCE(NULLIF(TRIM(a.group_name), ''), a.tipo_animale) COLLATE NOCASE,
                a.id
        ''',
        (user_id, *normalized_ids),
    )
    rows = cursor.fetchall()

    group_names_by_movimento = {}
    for movimento_id, _entry_id, tipo_animale, finalita, altro_label, group_name in rows:
        movimento_id_value = _to_non_negative_int(movimento_id)
        if movimento_id_value <= 0:
            continue

        tipo_norm = (tipo_animale or "").strip().upper()
        finalita_norm = (finalita or "").strip().upper()
        altro_norm = (altro_label or "").strip()
        group_name_clean = (group_name or "").strip() or _default_group_name(tipo_norm, finalita_norm, altro_norm)

        names = group_names_by_movimento.setdefault(movimento_id_value, [])
        if group_name_clean and group_name_clean not in names:
            names.append(group_name_clean)

    cursor.execute(
        f'''
            SELECT id, COALESCE(descrizione, '')
            FROM movimenti
            WHERE user_id=? AND id IN ({placeholders})
        ''',
        (user_id, *normalized_ids),
    )
    movimenti_rows = cursor.fetchall()

    updated_rows = 0
    for movimento_id, descrizione in movimenti_rows:
        movimento_id_value = _to_non_negative_int(movimento_id)
        descrizione_text = str(descrizione or "").strip()
        if movimento_id_value <= 0 or not descrizione_text:
            continue

        if not GROUPS_DESCRIPTION_PATTERN.search(descrizione_text):
            continue

        base_descrizione = GROUPS_DESCRIPTION_PATTERN.sub("", descrizione_text).rstrip()
        if not base_descrizione:
            continue

        group_names = group_names_by_movimento.get(movimento_id_value, [])
        groups_text = ", ".join(group_names) if group_names else "Nessun gruppo"
        nuova_descrizione = f"{base_descrizione} | Gruppi: {groups_text}"
        if nuova_descrizione == descrizione_text:
            continue

        cursor.execute(
            "UPDATE movimenti SET descrizione=? WHERE id=? AND user_id=?",
            (nuova_descrizione, movimento_id_value, user_id),
        )
        updated_rows += int(cursor.rowcount or 0)

    return updated_rows


def set_produzione_latte_group_allocations(
    user_id: int,
    produzione_id: int,
    movimento_id: int | None,
    allocations,
    cursor: sqlite3.Cursor | None = None,
):
    produzione_id_value = _to_non_negative_int(produzione_id)
    if produzione_id_value <= 0:
        raise ValueError("Produzione non valida.")

    movimento_id_value = _to_non_negative_int(movimento_id)
    if movimento_id_value <= 0:
        movimento_id_value = 0

    def _parse_litri(raw_value) -> float:
        if raw_value is None:
            return 0.0
        if isinstance(raw_value, (int, float)):
            return float(raw_value)

        text = str(raw_value).strip()
        if not text:
            return 0.0

        text = text.replace(" ", "").replace("'", "").replace("’", "").replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return 0.0

    parsed_by_entry = {}
    iterable = []
    if isinstance(allocations, dict):
        iterable = allocations.items()
    elif allocations is not None:
        iterable = allocations

    for item in iterable:
        if isinstance(item, dict):
            raw_entry_id = item.get("animale_entry_id")
            raw_litri = item.get("litri")
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            raw_entry_id = item[0]
            raw_litri = item[1]
        else:
            continue

        entry_id = _to_non_negative_int(raw_entry_id)
        if entry_id <= 0:
            continue

        litri_value = _parse_litri(raw_litri)
        if litri_value <= 0:
            continue

        parsed_by_entry[entry_id] = float(litri_value)

    def _apply(target_cursor: sqlite3.Cursor):
        target_cursor.execute(
            "SELECT movimento_id FROM produzione_latte WHERE id=? AND user_id=?",
            (produzione_id_value, user_id),
        )
        produzione_row = target_cursor.fetchone()
        if not produzione_row:
            raise ValueError("Produzione non trovata.")

        movimento_id_db = _to_non_negative_int((produzione_row[0] if produzione_row else 0) or 0)
        movimento_fk = movimento_id_value if movimento_id_value > 0 else movimento_id_db
        if movimento_fk <= 0:
            movimento_fk = None

        entry_ids = list(parsed_by_entry.keys())
        if entry_ids:
            placeholders = ",".join(["?"] * len(entry_ids))
            target_cursor.execute(
                f"""
                SELECT id
                FROM azienda_animali_dettaglio
                WHERE user_id=? AND id IN ({placeholders})
            """,
                (user_id, *entry_ids),
            )
            valid_ids = {int(row[0]) for row in target_cursor.fetchall()}
            missing_ids = [entry_id for entry_id in entry_ids if entry_id not in valid_ids]
            if missing_ids:
                raise ValueError("Uno o piu gruppi animali non sono piu disponibili.")

        target_cursor.execute(
            "DELETE FROM produzione_latte_gruppi WHERE user_id=? AND produzione_id=?",
            (user_id, produzione_id_value),
        )

        if not entry_ids:
            return

        now_text = datetime.now().isoformat(timespec="seconds")
        rows_to_insert = [
            (
                user_id,
                produzione_id_value,
                movimento_fk,
                entry_id,
                parsed_by_entry[entry_id],
                now_text,
                now_text,
            )
            for entry_id in entry_ids
        ]
        target_cursor.executemany(
            '''
            INSERT INTO produzione_latte_gruppi
                (user_id, produzione_id, movimento_id, animale_entry_id, litri, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
            rows_to_insert,
        )

    if cursor is not None:
        _apply(cursor)
        return

    with get_conn() as conn:
        c = conn.cursor()
        _apply(c)


def get_produzione_latte_group_allocations(user_id: int, produzione_id: int) -> dict[int, float]:
    produzione_id_value = _to_non_negative_int(produzione_id)
    if produzione_id_value <= 0:
        return {}

    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            SELECT animale_entry_id, COALESCE(litri, 0)
            FROM produzione_latte_gruppi
            WHERE user_id=? AND produzione_id=?
            ORDER BY id
        ''',
            (user_id, produzione_id_value),
        )
        rows = c.fetchall()

    allocations = {}
    for entry_id_raw, litri_raw in rows:
        entry_id = _to_non_negative_int(entry_id_raw)
        litri = float(litri_raw or 0)
        if entry_id <= 0 or litri <= 0:
            continue
        allocations[entry_id] = litri
    return allocations


def _log_azienda_animali_storico(
    cursor,
    user_id: int,
    event_type: str,
    event_time: str,
    gruppo_entry_id=None,
    gruppo_nome: str = "",
    tipo_animale: str = "",
    finalita: str = "",
    capi_prima=None,
    capi_variazione=0,
    capi_dopo=None,
    gruppo_correlato_entry_id=None,
    gruppo_correlato_nome: str = "",
    note: str = "",
):
    event_type_clean = (event_type or "").strip().upper() or "AGGIUNTA_CAPI"
    event_time_clean = (event_time or "").strip() or datetime.now().isoformat(timespec="seconds")

    gruppo_entry_value = _to_non_negative_int(gruppo_entry_id)
    gruppo_correlato_value = _to_non_negative_int(gruppo_correlato_entry_id)

    capi_prima_value = None if capi_prima is None else _to_non_negative_int(capi_prima)
    capi_dopo_value = None if capi_dopo is None else _to_non_negative_int(capi_dopo)

    try:
        capi_variazione_value = int(capi_variazione or 0)
    except (TypeError, ValueError):
        capi_variazione_value = 0

    cursor.execute(
        '''
        INSERT INTO azienda_animali_storico (
            user_id,
            event_type,
            event_time,
            gruppo_entry_id,
            gruppo_nome,
            tipo_animale,
            finalita,
            capi_prima,
            capi_variazione,
            capi_dopo,
            gruppo_correlato_entry_id,
            gruppo_correlato_nome,
            note
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''',
        (
            user_id,
            event_type_clean,
            event_time_clean,
            gruppo_entry_value if gruppo_entry_value > 0 else None,
            (gruppo_nome or "").strip(),
            (tipo_animale or "").strip().upper(),
            (finalita or "").strip().upper(),
            capi_prima_value,
            capi_variazione_value,
            capi_dopo_value,
            gruppo_correlato_value if gruppo_correlato_value > 0 else None,
            (gruppo_correlato_nome or "").strip(),
            (note or "").strip(),
        ),
    )


def list_azienda_animali_storico_entries(user_id: int, limit: int = 300) -> list[dict]:
    limit_value = _to_non_negative_int(limit)
    if limit_value <= 0:
        limit_value = 300

    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            SELECT
                id,
                COALESCE(event_type, ''),
                COALESCE(event_time, ''),
                gruppo_entry_id,
                COALESCE(gruppo_nome, ''),
                COALESCE(tipo_animale, ''),
                COALESCE(finalita, ''),
                capi_prima,
                COALESCE(capi_variazione, 0),
                capi_dopo,
                gruppo_correlato_entry_id,
                COALESCE(gruppo_correlato_nome, ''),
                COALESCE(note, '')
            FROM azienda_animali_storico
            WHERE user_id=?
            ORDER BY COALESCE(NULLIF(TRIM(event_time), ''), '') DESC, id DESC
            LIMIT ?
        ''',
            (user_id, limit_value),
        )
        rows = c.fetchall()

    entries = []
    for (
        row_id,
        event_type,
        event_time,
        gruppo_entry_id,
        gruppo_nome,
        tipo_animale,
        finalita,
        capi_prima,
        capi_variazione,
        capi_dopo,
        gruppo_correlato_entry_id,
        gruppo_correlato_nome,
        note,
    ) in rows:
        entry_id = _to_non_negative_int(row_id)
        if entry_id <= 0:
            continue

        capi_prima_value = None if capi_prima is None else _to_non_negative_int(capi_prima)
        capi_dopo_value = None if capi_dopo is None else _to_non_negative_int(capi_dopo)
        try:
            capi_variazione_value = int(capi_variazione or 0)
        except (TypeError, ValueError):
            capi_variazione_value = 0

        entries.append(
            {
                "id": entry_id,
                "event_type": (event_type or "").strip().upper(),
                "event_time": (event_time or "").strip(),
                "gruppo_entry_id": _to_non_negative_int(gruppo_entry_id),
                "gruppo_nome": (gruppo_nome or "").strip(),
                "tipo_animale": (tipo_animale or "").strip().upper(),
                "finalita": (finalita or "").strip().upper(),
                "capi_prima": capi_prima_value,
                "capi_variazione": capi_variazione_value,
                "capi_dopo": capi_dopo_value,
                "gruppo_correlato_entry_id": _to_non_negative_int(gruppo_correlato_entry_id),
                "gruppo_correlato_nome": (gruppo_correlato_nome or "").strip(),
                "note": (note or "").strip(),
            }
        )

    return entries


def delete_azienda_animali_storico_entry(user_id: int, storico_id: int) -> bool:
    storico_id_value = _to_non_negative_int(storico_id)
    if storico_id_value <= 0:
        raise ValueError("Operazione storico non valida.")

    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "DELETE FROM azienda_animali_storico WHERE id=? AND user_id=?",
            (storico_id_value, user_id),
        )
        return int(c.rowcount or 0) > 0


def add_azienda_animali_storico_entry(
    user_id: int,
    event_type: str,
    event_time: str | None = None,
    gruppo_entry_id=None,
    gruppo_nome: str = "",
    tipo_animale: str = "",
    finalita: str = "",
    capi_prima=None,
    capi_variazione=0,
    capi_dopo=None,
    gruppo_correlato_entry_id=None,
    gruppo_correlato_nome: str = "",
    note: str = "",
    cursor: sqlite3.Cursor | None = None,
):
    event_time_clean = (event_time or "").strip() or datetime.now().isoformat(timespec="seconds")

    def _apply(target_cursor: sqlite3.Cursor):
        _log_azienda_animali_storico(
            target_cursor,
            user_id=user_id,
            event_type=event_type,
            event_time=event_time_clean,
            gruppo_entry_id=gruppo_entry_id,
            gruppo_nome=gruppo_nome,
            tipo_animale=tipo_animale,
            finalita=finalita,
            capi_prima=capi_prima,
            capi_variazione=capi_variazione,
            capi_dopo=capi_dopo,
            gruppo_correlato_entry_id=gruppo_correlato_entry_id,
            gruppo_correlato_nome=gruppo_correlato_nome,
            note=note,
        )

    if cursor is not None:
        _apply(cursor)
        return

    with get_conn() as conn:
        c = conn.cursor()
        _apply(c)


def add_azienda_animale_entry(
    user_id: int,
    tipo_animale: str,
    capi: int,
    finalita: str = "",
    altro_label: str = "",
    group_name: str = "",
    riproduzione: bool = False,
    cursor: sqlite3.Cursor | None = None,
):
    tipo = _normalize_tipo_animale(tipo_animale)
    if tipo not in ANIMAL_TYPE_OPTIONS:
        raise ValueError("Tipo animale non valido.")

    capi_value = _to_non_negative_int(capi)
    if capi_value <= 0:
        raise ValueError("Il numero capi deve essere maggiore di zero.")

    finalita_norm = _normalize_finalita_animale(finalita)
    if tipo in ("BOVINI", "OVINI"):
        if finalita_norm not in ANIMAL_PURPOSE_OPTIONS:
            raise ValueError("Per bovini e ovini seleziona 'Da Latte' o 'Da Carne'.")
    else:
        finalita_norm = ""

    altro_clean = (altro_label or "").strip()
    if tipo == "ALTRO":
        if not altro_clean:
            raise ValueError("Specifica il tipo animale per la voce Altro.")
    else:
        altro_clean = ""

    group_name_clean = (group_name or "").strip()
    if not group_name_clean:
        group_name_clean = _default_group_name(tipo, finalita_norm, altro_clean)

    riproduzione_value = _to_bool_int(riproduzione)

    now_text = datetime.now().isoformat(timespec="seconds")
    def _apply(target_cursor: sqlite3.Cursor):
        target_cursor.execute(
            '''
            SELECT id, capi, group_name
            FROM azienda_animali_dettaglio
            WHERE user_id=? AND tipo_animale=? AND finalita=? AND altro_label=? AND group_name=?
        ''',
            (user_id, tipo, finalita_norm, altro_clean, group_name_clean),
        )
        existing_row = target_cursor.fetchone()

        target_cursor.execute(
            '''
            INSERT INTO azienda_animali_dettaglio
                (
                    user_id,
                    tipo_animale,
                    finalita,
                    altro_label,
                    group_name,
                    riproduzione,
                    capi,
                    created_at,
                    updated_at
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, tipo_animale, finalita, altro_label, group_name) DO UPDATE SET
                capi = azienda_animali_dettaglio.capi + excluded.capi,
                riproduzione = CASE
                    WHEN COALESCE(azienda_animali_dettaglio.riproduzione, 0) <> 0
                         OR COALESCE(excluded.riproduzione, 0) <> 0 THEN 1
                    ELSE 0
                END,
                updated_at = excluded.updated_at
        ''',
            (
                user_id,
                tipo,
                finalita_norm,
                altro_clean,
                group_name_clean,
                riproduzione_value,
                capi_value,
                now_text,
                now_text,
            ),
        )

        target_cursor.execute(
            '''
            SELECT id, capi, group_name
            FROM azienda_animali_dettaglio
            WHERE user_id=? AND tipo_animale=? AND finalita=? AND altro_label=? AND group_name=?
        ''',
            (user_id, tipo, finalita_norm, altro_clean, group_name_clean),
        )
        saved_row = target_cursor.fetchone()

        if saved_row:
            saved_entry_id = _to_non_negative_int(saved_row[0])
            capi_dopo = _to_non_negative_int(saved_row[1])
            group_name_saved = (saved_row[2] or "").strip() or group_name_clean

            capi_prima = _to_non_negative_int(existing_row[1]) if existing_row else 0
            delta_capi = capi_dopo - capi_prima

            if delta_capi != 0:
                note = "Creato nuovo gruppo." if not existing_row else "Aggiunti capi al gruppo."
                _log_azienda_animali_storico(
                    target_cursor,
                    user_id=user_id,
                    event_type="AGGIUNTA_CAPI",
                    event_time=now_text,
                    gruppo_entry_id=saved_entry_id,
                    gruppo_nome=group_name_saved,
                    tipo_animale=tipo,
                    finalita=finalita_norm,
                    capi_prima=capi_prima,
                    capi_variazione=delta_capi,
                    capi_dopo=capi_dopo,
                    note=note,
                )

    if cursor is not None:
        _apply(cursor)
        return

    with get_conn() as conn:
        c = conn.cursor()
        _apply(c)


def remove_azienda_animale_capi(
    user_id: int,
    entry_id: int,
    capi_da_rimuovere: int,
    cursor: sqlite3.Cursor | None = None,
) -> bool:
    entry_id_value = _to_non_negative_int(entry_id)
    if entry_id_value <= 0:
        raise ValueError("Categoria animale non valida.")

    capi_value = _to_non_negative_int(capi_da_rimuovere)
    if capi_value <= 0:
        raise ValueError("Il numero capi da rimuovere deve essere maggiore di zero.")

    now_text = datetime.now().isoformat(timespec="seconds")

    def _apply(target_cursor: sqlite3.Cursor) -> bool:
        target_cursor.execute(
            '''
            SELECT tipo_animale, finalita, group_name, capi
            FROM azienda_animali_dettaglio
            WHERE id=? AND user_id=?
        ''',
            (entry_id_value, user_id),
        )
        row = target_cursor.fetchone()

        if not row:
            raise ValueError("Categoria animale non trovata.")

        tipo_animale = (row[0] or "").strip().upper()
        finalita = (row[1] or "").strip().upper()
        group_name = (row[2] or "").strip()
        capi_attuali = _to_non_negative_int(row[3])
        if capi_value > capi_attuali:
            raise ValueError("Non puoi rimuovere piu capi di quelli presenti nella categoria selezionata.")

        if capi_value == capi_attuali:
            target_cursor.execute(
                '''
                UPDATE azienda_animali_dettaglio
                SET merged_into_entry_id=NULL, merge_date='', updated_at=?
                WHERE user_id=? AND merged_into_entry_id=?
            ''',
                (now_text, user_id, entry_id_value),
            )
            target_cursor.execute(
                "DELETE FROM azienda_animali_dettaglio WHERE id=? AND user_id=?",
                (entry_id_value, user_id),
            )

            _log_azienda_animali_storico(
                target_cursor,
                user_id=user_id,
                event_type="RIMOZIONE_CAPI",
                event_time=now_text,
                gruppo_entry_id=entry_id_value,
                gruppo_nome=group_name,
                tipo_animale=tipo_animale,
                finalita=finalita,
                capi_prima=capi_attuali,
                capi_variazione=-capi_value,
                capi_dopo=0,
                note="Rimozione completa capi: gruppo eliminato.",
            )
            return True

        capi_dopo = capi_attuali - capi_value
        target_cursor.execute(
            '''
            UPDATE azienda_animali_dettaglio
            SET capi=?, updated_at=?
            WHERE id=? AND user_id=?
        ''',
            (capi_dopo, now_text, entry_id_value, user_id),
        )

        _log_azienda_animali_storico(
            target_cursor,
            user_id=user_id,
            event_type="RIMOZIONE_CAPI",
            event_time=now_text,
            gruppo_entry_id=entry_id_value,
            gruppo_nome=group_name,
            tipo_animale=tipo_animale,
            finalita=finalita,
            capi_prima=capi_attuali,
            capi_variazione=-capi_value,
            capi_dopo=capi_dopo,
            note="Rimozione capi dal gruppo.",
        )
        return False

    if cursor is not None:
        return _apply(cursor)

    with get_conn() as conn:
        c = conn.cursor()
        return _apply(c)


def set_azienda_animale_capi(user_id: int, entry_id: int, nuovo_capi: int) -> bool:
    entry_id_value = _to_non_negative_int(entry_id)
    if entry_id_value <= 0:
        raise ValueError("Categoria animale non valida.")

    nuovo_capi_value = _to_non_negative_int(nuovo_capi)

    now_text = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            SELECT tipo_animale, finalita, group_name, capi
            FROM azienda_animali_dettaglio
            WHERE id=? AND user_id=?
        ''',
            (entry_id_value, user_id),
        )
        row = c.fetchone()
        if not row:
            raise ValueError("Categoria animale non trovata.")

        tipo_animale = (row[0] or "").strip().upper()
        finalita = (row[1] or "").strip().upper()
        group_name = (row[2] or "").strip()
        capi_attuali = _to_non_negative_int(row[3])

        if nuovo_capi_value == capi_attuali:
            return False

        if nuovo_capi_value == 0:
            c.execute(
                '''
                UPDATE azienda_animali_dettaglio
                SET merged_into_entry_id=NULL, merge_date='', updated_at=?
                WHERE user_id=? AND merged_into_entry_id=?
            ''',
                (now_text, user_id, entry_id_value),
            )
            c.execute(
                "DELETE FROM azienda_animali_dettaglio WHERE id=? AND user_id=?",
                (entry_id_value, user_id),
            )

            if capi_attuali > 0:
                _log_azienda_animali_storico(
                    c,
                    user_id=user_id,
                    event_type="RIMOZIONE_CAPI",
                    event_time=now_text,
                    gruppo_entry_id=entry_id_value,
                    gruppo_nome=group_name,
                    tipo_animale=tipo_animale,
                    finalita=finalita,
                    capi_prima=capi_attuali,
                    capi_variazione=-capi_attuali,
                    capi_dopo=0,
                    note="Capi impostati a zero: gruppo eliminato.",
                )
            return True

        c.execute(
            '''
            UPDATE azienda_animali_dettaglio
            SET capi=?, updated_at=?
            WHERE id=? AND user_id=?
        ''',
            (nuovo_capi_value, now_text, entry_id_value, user_id),
        )

        delta_capi = nuovo_capi_value - capi_attuali
        if delta_capi != 0:
            event_type = "AGGIUNTA_CAPI" if delta_capi > 0 else "RIMOZIONE_CAPI"
            note = "Aggiornamento numero capi del gruppo."
            _log_azienda_animali_storico(
                c,
                user_id=user_id,
                event_type=event_type,
                event_time=now_text,
                gruppo_entry_id=entry_id_value,
                gruppo_nome=group_name,
                tipo_animale=tipo_animale,
                finalita=finalita,
                capi_prima=capi_attuali,
                capi_variazione=delta_capi,
                capi_dopo=nuovo_capi_value,
                note=note,
            )
    return False


def set_azienda_animale_finalita(user_id: int, entry_id: int, nuova_finalita: str) -> bool:
    entry_id_value = _to_non_negative_int(entry_id)
    if entry_id_value <= 0:
        raise ValueError("Categoria animale non valida.")

    finalita_norm = _normalize_finalita_animale(nuova_finalita)
    if finalita_norm not in ANIMAL_PURPOSE_OPTIONS:
        raise ValueError("Destinazione non valida. Seleziona 'Da Latte' o 'Da Carne'.")

    def _label_finalita(value: str) -> str:
        finalita_value = (value or "").strip().upper()
        if finalita_value == "LATTE":
            return "Da Latte"
        if finalita_value == "CARNE":
            return "Da Carne"
        return "-"

    now_text = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            SELECT id, tipo_animale, finalita, altro_label, capi, group_name, COALESCE(riproduzione, 0)
            FROM azienda_animali_dettaglio
            WHERE id=? AND user_id=?
        ''',
            (entry_id_value, user_id),
        )
        row = c.fetchone()

        if not row:
            raise ValueError("Categoria animale non trovata.")

        current_id = int(row[0])
        tipo_animale = (row[1] or "").strip().upper()
        current_finalita = (row[2] or "").strip().upper()
        altro_label = (row[3] or "").strip()
        capi_value = _to_non_negative_int(row[4])
        current_group_name = (row[5] or "").strip()
        current_riproduzione = _to_bool_int(row[6])
        if not current_group_name:
            current_group_name = _default_group_name(tipo_animale, current_finalita, altro_label)

        if tipo_animale not in ("BOVINI", "OVINI"):
            raise ValueError("La destinazione e modificabile solo per Bovini e Ovini.")

        if current_finalita == finalita_norm:
            return False

        c.execute(
            '''
            SELECT id, capi, group_name, COALESCE(riproduzione, 0)
            FROM azienda_animali_dettaglio
            WHERE user_id=? AND tipo_animale=? AND finalita=? AND altro_label=? AND group_name=?
        ''',
            (user_id, tipo_animale, finalita_norm, altro_label, current_group_name),
        )
        conflict = c.fetchone()

        if conflict and int(conflict[0]) != current_id:
            conflict_id = int(conflict[0])
            conflict_capi = _to_non_negative_int(conflict[1])
            conflict_group_name = (conflict[2] or "").strip()
            conflict_riproduzione = _to_bool_int(conflict[3])
            merged_group_name = conflict_group_name or current_group_name or _default_group_name(
                tipo_animale,
                finalita_norm,
                altro_label,
            )
            capi_dopo = conflict_capi + capi_value
            riproduzione_dopo = 1 if (conflict_riproduzione or current_riproduzione) else 0

            c.execute(
                '''
                UPDATE azienda_animali_dettaglio
                SET capi=?, group_name=?, riproduzione=?, updated_at=?
                WHERE id=? AND user_id=?
            ''',
                (capi_dopo, merged_group_name, riproduzione_dopo, now_text, conflict_id, user_id),
            )
            c.execute(
                "DELETE FROM azienda_animali_dettaglio WHERE id=? AND user_id=?",
                (current_id, user_id),
            )

            _log_azienda_animali_storico(
                c,
                user_id=user_id,
                event_type="CAMBIO_DESTINAZIONE",
                event_time=now_text,
                gruppo_entry_id=conflict_id,
                gruppo_nome=merged_group_name,
                tipo_animale=tipo_animale,
                finalita=finalita_norm,
                capi_prima=conflict_capi,
                capi_variazione=capi_value,
                capi_dopo=capi_dopo,
                gruppo_correlato_entry_id=current_id,
                gruppo_correlato_nome=current_group_name,
                note=(
                    f"Cambio destinazione da {_label_finalita(current_finalita)} "
                    f"a {_label_finalita(finalita_norm)} con accorpamento gruppo."
                ),
            )
            return True

        c.execute(
            '''
            UPDATE azienda_animali_dettaglio
            SET finalita=?, updated_at=?
            WHERE id=? AND user_id=?
        ''',
            (finalita_norm, now_text, current_id, user_id),
        )

        _log_azienda_animali_storico(
            c,
            user_id=user_id,
            event_type="CAMBIO_DESTINAZIONE",
            event_time=now_text,
            gruppo_entry_id=current_id,
            gruppo_nome=current_group_name,
            tipo_animale=tipo_animale,
            finalita=finalita_norm,
            capi_prima=capi_value,
            capi_variazione=0,
            capi_dopo=capi_value,
            note=(
                f"Cambio destinazione da {_label_finalita(current_finalita)} "
                f"a {_label_finalita(finalita_norm)}."
            ),
        )
    return False


def set_azienda_animale_riproduzione(user_id: int, entry_id: int, destinato_riproduzione) -> bool:
    entry_id_value = _to_non_negative_int(entry_id)
    if entry_id_value <= 0:
        raise ValueError("Categoria animale non valida.")

    riproduzione_nuova = _to_bool_int(destinato_riproduzione)
    now_text = datetime.now().isoformat(timespec="seconds")

    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            SELECT tipo_animale, finalita, group_name, capi, COALESCE(riproduzione, 0)
            FROM azienda_animali_dettaglio
            WHERE id=? AND user_id=?
        ''',
            (entry_id_value, user_id),
        )
        row = c.fetchone()
        if not row:
            raise ValueError("Categoria animale non trovata.")

        tipo_animale = (row[0] or "").strip().upper()
        finalita = (row[1] or "").strip().upper()
        group_name = (row[2] or "").strip()
        capi_attuali = _to_non_negative_int(row[3])
        riproduzione_attuale = _to_bool_int(row[4])

        if riproduzione_attuale == riproduzione_nuova:
            return False

        c.execute(
            '''
            UPDATE azienda_animali_dettaglio
            SET riproduzione=?, updated_at=?
            WHERE id=? AND user_id=?
        ''',
            (riproduzione_nuova, now_text, entry_id_value, user_id),
        )

        stato_label = "attivata" if riproduzione_nuova else "disattivata"
        _log_azienda_animali_storico(
            c,
            user_id=user_id,
            event_type="CAMBIO_RIPRODUZIONE",
            event_time=now_text,
            gruppo_entry_id=entry_id_value,
            gruppo_nome=group_name,
            tipo_animale=tipo_animale,
            finalita=finalita,
            capi_prima=capi_attuali,
            capi_variazione=0,
            capi_dopo=capi_attuali,
            note=f"Destinazione riproduzione {stato_label}.",
        )

    return True


def set_azienda_animale_group_name(user_id: int, entry_id: int, nuovo_group_name: str) -> bool:
    entry_id_value = _to_non_negative_int(entry_id)
    if entry_id_value <= 0:
        raise ValueError("Categoria animale non valida.")

    group_name_clean = (nuovo_group_name or "").strip()
    if not group_name_clean:
        raise ValueError("Inserisci un nome gruppo valido.")

    now_text = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            SELECT group_name
            FROM azienda_animali_dettaglio
            WHERE id=? AND user_id=?
        ''',
            (entry_id_value, user_id),
        )
        row = c.fetchone()

        if not row:
            raise ValueError("Categoria animale non trovata.")

        current_group_name = (row[0] or "").strip()
        if current_group_name == group_name_clean:
            return False

        try:
            c.execute(
                '''
                UPDATE azienda_animali_dettaglio
                SET group_name=?, updated_at=?
                WHERE id=? AND user_id=?
            ''',
                (group_name_clean, now_text, entry_id_value, user_id),
            )
        except sqlite3.IntegrityError:
            raise ValueError("Esiste gia un gruppo con questo nome per la stessa categoria.")

        c.execute(
            '''
            SELECT DISTINCT movimento_id
            FROM movimenti_animali_link
            WHERE user_id=? AND animale_entry_id=?
        ''',
            (user_id, entry_id_value),
        )
        movimento_ids = [int(row[0]) for row in c.fetchall() if _to_non_negative_int(row[0]) > 0]
        _refresh_linked_group_descriptions(user_id, movimento_ids, c)
    return True


def split_azienda_animale_group(user_id: int, entry_id: int, capi_nuovo_gruppo: int, nuovo_group_name: str) -> int:
    entry_id_value = _to_non_negative_int(entry_id)
    if entry_id_value <= 0:
        raise ValueError("Categoria animale non valida.")

    capi_nuovo_value = _to_non_negative_int(capi_nuovo_gruppo)
    if capi_nuovo_value <= 0:
        raise ValueError("Il nuovo gruppo deve avere almeno 1 capo.")

    new_group_name_clean = (nuovo_group_name or "").strip()
    if not new_group_name_clean:
        raise ValueError("Inserisci un nome per il nuovo gruppo.")

    now_text = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            SELECT tipo_animale, finalita, altro_label, group_name, capi, COALESCE(riproduzione, 0)
            FROM azienda_animali_dettaglio
            WHERE id=? AND user_id=?
        ''',
            (entry_id_value, user_id),
        )
        row = c.fetchone()

        if not row:
            raise ValueError("Categoria animale non trovata.")

        tipo_animale = (row[0] or "").strip().upper()
        finalita = (row[1] or "").strip().upper()
        altro_label = (row[2] or "").strip()
        current_group_name = (row[3] or "").strip()
        capi_attuali = _to_non_negative_int(row[4])
        riproduzione = _to_bool_int(row[5])
        if not current_group_name:
            current_group_name = _default_group_name(tipo_animale, finalita, altro_label)

        if capi_attuali <= 1:
            raise ValueError("Il gruppo selezionato non ha abbastanza capi per essere diviso.")

        if capi_nuovo_value >= capi_attuali:
            raise ValueError("Il nuovo gruppo deve avere meno capi del gruppo selezionato.")

        if new_group_name_clean == current_group_name:
            raise ValueError("Il nuovo gruppo deve avere un nome diverso dal gruppo selezionato.")

        capi_restanti = capi_attuali - capi_nuovo_value

        c.execute(
            '''
            UPDATE azienda_animali_dettaglio
            SET capi=?, updated_at=?
            WHERE id=? AND user_id=?
        ''',
            (capi_restanti, now_text, entry_id_value, user_id),
        )

        try:
            c.execute(
                '''
                INSERT INTO azienda_animali_dettaglio
                    (
                        user_id,
                        tipo_animale,
                        finalita,
                        altro_label,
                        group_name,
                        riproduzione,
                        capi,
                        created_at,
                        updated_at
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
                (
                    user_id,
                    tipo_animale,
                    finalita,
                    altro_label,
                    new_group_name_clean,
                    riproduzione,
                    capi_nuovo_value,
                    now_text,
                    now_text,
                ),
            )
            nuovo_entry_id = int(c.lastrowid or 0)
        except sqlite3.IntegrityError:
            raise ValueError("Esiste gia un gruppo con questo nome per la stessa categoria.")

        # Tutti i movimenti/fatture collegati al gruppo origine vengono collegati anche al nuovo gruppo.
        if nuovo_entry_id > 0:
            c.execute(
                '''
                INSERT OR IGNORE INTO movimenti_animali_link (user_id, movimento_id, animale_entry_id, created_at)
                SELECT user_id, movimento_id, ?, ?
                FROM movimenti_animali_link
                WHERE user_id=? AND animale_entry_id=?
            ''',
                (nuovo_entry_id, now_text, user_id, entry_id_value),
            )

            c.execute(
                '''
                SELECT DISTINCT movimento_id
                FROM movimenti_animali_link
                WHERE user_id=? AND animale_entry_id=?
            ''',
                (user_id, entry_id_value),
            )
            movimento_ids = [int(row[0]) for row in c.fetchall() if _to_non_negative_int(row[0]) > 0]
            _refresh_linked_group_descriptions(user_id, movimento_ids, c)

            _log_azienda_animali_storico(
                c,
                user_id=user_id,
                event_type="DIVISIONE_GRUPPO",
                event_time=now_text,
                gruppo_entry_id=entry_id_value,
                gruppo_nome=current_group_name,
                tipo_animale=tipo_animale,
                finalita=finalita,
                capi_prima=capi_attuali,
                capi_variazione=-capi_nuovo_value,
                capi_dopo=capi_restanti,
                gruppo_correlato_entry_id=nuovo_entry_id,
                gruppo_correlato_nome=new_group_name_clean,
                note=f"Creato nuovo gruppo '{new_group_name_clean}' con {capi_nuovo_value} capi.",
            )

    return capi_restanti


def merge_azienda_animale_groups(
    user_id: int,
    entry_id_principale: int,
    entry_id_secondario: int,
    nuovo_group_name: str,
    merge_date: str | None = None,
) -> int:
    entry_id_principale_value = _to_non_negative_int(entry_id_principale)
    entry_id_secondario_value = _to_non_negative_int(entry_id_secondario)

    if entry_id_principale_value <= 0 or entry_id_secondario_value <= 0:
        raise ValueError("Gruppo animale non valido.")
    if entry_id_principale_value == entry_id_secondario_value:
        raise ValueError("Seleziona due gruppi diversi da unire.")

    new_group_name_clean = (nuovo_group_name or "").strip()
    if not new_group_name_clean:
        raise ValueError("Inserisci un nome per il gruppo unificato.")

    merge_date_clean = (merge_date or "").strip()
    if merge_date_clean:
        try:
            datetime.strptime(merge_date_clean, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Data unione non valida. Usa il formato YYYY-MM-DD.")
    else:
        merge_date_clean = datetime.now().strftime("%Y-%m-%d")

    now_text = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        c = conn.cursor()

        c.execute(
            '''
            SELECT DISTINCT movimento_id
            FROM movimenti_animali_link
            WHERE user_id=? AND animale_entry_id IN (?, ?)
        ''',
            (user_id, entry_id_principale_value, entry_id_secondario_value),
        )
        movimento_ids = [int(row[0]) for row in c.fetchall() if _to_non_negative_int(row[0]) > 0]

        c.execute(
            '''
            SELECT id, tipo_animale, finalita, altro_label, group_name, COALESCE(riproduzione, 0), capi,
                   COALESCE(merged_into_entry_id, 0)
            FROM azienda_animali_dettaglio
            WHERE id IN (?, ?) AND user_id=?
        ''',
            (entry_id_principale_value, entry_id_secondario_value, user_id),
        )
        rows = c.fetchall()
        if len(rows) != 2:
            raise ValueError("Uno o piu gruppi selezionati non sono disponibili.")

        rows_by_id = {int(row[0]): row for row in rows}
        principale = rows_by_id.get(entry_id_principale_value)
        secondario = rows_by_id.get(entry_id_secondario_value)
        if not principale or not secondario:
            raise ValueError("Uno o piu gruppi selezionati non sono disponibili.")

        tipo_principale = (principale[1] or "").strip().upper()
        finalita_principale = (principale[2] or "").strip().upper()
        altro_principale = (principale[3] or "").strip()
        group_name_principale = (principale[4] or "").strip()
        riproduzione_principale = _to_bool_int(principale[5])
        capi_principale = _to_non_negative_int(principale[6])
        merged_principale = _to_non_negative_int(principale[7])

        tipo_secondario = (secondario[1] or "").strip().upper()
        finalita_secondario = (secondario[2] or "").strip().upper()
        altro_secondario = (secondario[3] or "").strip()
        group_name_secondario = (secondario[4] or "").strip()
        riproduzione_secondario = _to_bool_int(secondario[5])
        capi_secondario = _to_non_negative_int(secondario[6])
        merged_secondario = _to_non_negative_int(secondario[7])

        if not group_name_principale:
            group_name_principale = _default_group_name(tipo_principale, finalita_principale, altro_principale)
        if not group_name_secondario:
            group_name_secondario = _default_group_name(tipo_secondario, finalita_secondario, altro_secondario)

        if merged_principale > 0:
            raise ValueError("Il gruppo principale risulta gia unito ad un altro gruppo.")
        if merged_secondario > 0:
            raise ValueError("Il gruppo secondario risulta gia unito ad un altro gruppo.")

        if (
            tipo_principale != tipo_secondario
            or finalita_principale != finalita_secondario
            or altro_principale != altro_secondario
        ):
            raise ValueError("Puoi unire solo gruppi compatibili dello stesso tipo animale.")

        capi_totali = capi_principale + capi_secondario
        if capi_totali <= 0:
            raise ValueError("Impossibile unire gruppi senza capi.")

        c.execute(
            '''
            UPDATE OR IGNORE movimenti_animali_link
            SET animale_entry_id=?
            WHERE user_id=?
              AND animale_entry_id=?
              AND EXISTS (
                  SELECT 1
                  FROM movimenti m
                  WHERE m.user_id = movimenti_animali_link.user_id
                    AND m.id = movimenti_animali_link.movimento_id
                    AND m.data_op >= ?
              )
        ''',
            (entry_id_principale_value, user_id, entry_id_secondario_value, merge_date_clean),
        )
        c.execute(
            '''
            DELETE FROM movimenti_animali_link
            WHERE user_id=?
              AND animale_entry_id=?
              AND EXISTS (
                  SELECT 1
                  FROM movimenti m
                  WHERE m.user_id = movimenti_animali_link.user_id
                    AND m.id = movimenti_animali_link.movimento_id
                    AND m.data_op >= ?
              )
        ''',
            (user_id, entry_id_secondario_value, merge_date_clean),
        )

        c.execute(
            '''
            INSERT INTO produzione_latte_gruppi
                (user_id, produzione_id, movimento_id, animale_entry_id, litri, created_at, updated_at)
            SELECT
                g.user_id,
                g.produzione_id,
                g.movimento_id,
                ?,
                COALESCE(g.litri, 0),
                ?,
                ?
            FROM produzione_latte_gruppi g
            WHERE g.user_id=?
              AND g.animale_entry_id=?
              AND EXISTS (
                  SELECT 1
                  FROM produzione_latte p
                  WHERE p.user_id = g.user_id
                    AND p.id = g.produzione_id
                    AND p.data_op >= ?
              )
            ON CONFLICT(user_id, produzione_id, animale_entry_id) DO UPDATE SET
                litri = COALESCE(produzione_latte_gruppi.litri, 0) + COALESCE(excluded.litri, 0),
                updated_at = excluded.updated_at
        ''',
            (
                entry_id_principale_value,
                now_text,
                now_text,
                user_id,
                entry_id_secondario_value,
                merge_date_clean,
            ),
        )
        c.execute(
            '''
            DELETE FROM produzione_latte_gruppi
            WHERE user_id=?
              AND animale_entry_id=?
              AND EXISTS (
                  SELECT 1
                  FROM produzione_latte p
                  WHERE p.user_id = produzione_latte_gruppi.user_id
                    AND p.id = produzione_latte_gruppi.produzione_id
                    AND p.data_op >= ?
              )
        ''',
            (user_id, entry_id_secondario_value, merge_date_clean),
        )

        c.execute(
            '''
            UPDATE azienda_animali_dettaglio
            SET merged_into_entry_id=?, merge_date=?, updated_at=?
            WHERE id=? AND user_id=?
        ''',
            (
                entry_id_principale_value,
                merge_date_clean,
                now_text,
                entry_id_secondario_value,
                user_id,
            ),
        )

        try:
            c.execute(
                '''
                UPDATE azienda_animali_dettaglio
                SET capi=?, group_name=?, riproduzione=?, updated_at=?
                WHERE id=? AND user_id=?
            ''',
                (
                    capi_totali,
                    new_group_name_clean,
                    1 if (riproduzione_principale or riproduzione_secondario) else 0,
                    now_text,
                    entry_id_principale_value,
                    user_id,
                ),
            )
        except sqlite3.IntegrityError:
            raise ValueError("Esiste gia un gruppo con questo nome per la stessa categoria.")

        _log_azienda_animali_storico(
            c,
            user_id=user_id,
            event_type="UNIONE_GRUPPI",
            event_time=now_text,
            gruppo_entry_id=entry_id_principale_value,
            gruppo_nome=new_group_name_clean,
            tipo_animale=tipo_principale,
            finalita=finalita_principale,
            capi_prima=capi_principale,
            capi_variazione=capi_secondario,
            capi_dopo=capi_totali,
            gruppo_correlato_entry_id=entry_id_secondario_value,
            gruppo_correlato_nome=group_name_secondario,
            note=f"Unione gruppi con competenza dal {merge_date_clean}.",
        )

        _refresh_linked_group_descriptions(user_id, movimento_ids, c)

    return capi_totali


def delete_azienda_animale_entry(user_id: int, entry_id: int):
    entry_id_value = _to_non_negative_int(entry_id)
    if entry_id_value <= 0:
        raise ValueError("Categoria animale non valida.")

    with get_conn() as conn:
        c = conn.cursor()
        now_text = datetime.now().isoformat(timespec="seconds")
        c.execute(
            '''
            SELECT tipo_animale, finalita, group_name, capi
            FROM azienda_animali_dettaglio
            WHERE id=? AND user_id=?
        ''',
            (entry_id_value, user_id),
        )
        row = c.fetchone()
        if not row:
            raise ValueError("Categoria animale non trovata.")

        tipo_animale = (row[0] or "").strip().upper()
        finalita = (row[1] or "").strip().upper()
        group_name = (row[2] or "").strip()
        capi_attuali = _to_non_negative_int(row[3])

        c.execute(
            '''
            UPDATE azienda_animali_dettaglio
            SET merged_into_entry_id=NULL, merge_date='', updated_at=?
            WHERE user_id=? AND merged_into_entry_id=?
        ''',
            (now_text, user_id, entry_id_value),
        )

        c.execute(
            "DELETE FROM azienda_animali_dettaglio WHERE id=? AND user_id=?",
            (entry_id_value, user_id),
        )

        _log_azienda_animali_storico(
            c,
            user_id=user_id,
            event_type="RIMOZIONE_CAPI",
            event_time=now_text,
            gruppo_entry_id=entry_id_value,
            gruppo_nome=group_name,
            tipo_animale=tipo_animale,
            finalita=finalita,
            capi_prima=capi_attuali,
            capi_variazione=-capi_attuali,
            capi_dopo=0,
            note="Eliminazione gruppo.",
        )


def save_azienda_animali(
    user_id: int,
    bovini: bool,
    bovini_capi: int,
    ovini: bool,
    ovini_capi: int,
    caprini: bool,
    caprini_capi: int,
    altro_text: str,
    altro_capi: int,
):
    altro_clean = (altro_text or "").strip()
    updated_at = datetime.now().isoformat(timespec="seconds")
    bovini_capi_clean = _to_non_negative_int(bovini_capi)
    ovini_capi_clean = _to_non_negative_int(ovini_capi)
    caprini_capi_clean = _to_non_negative_int(caprini_capi)
    altro_capi_clean = _to_non_negative_int(altro_capi)

    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO azienda_animali (
                user_id,
                bovini,
                bovini_capi,
                ovini,
                ovini_capi,
                caprini,
                caprini_capi,
                altro_text,
                altro_capi,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                bovini=excluded.bovini,
                bovini_capi=excluded.bovini_capi,
                ovini=excluded.ovini,
                ovini_capi=excluded.ovini_capi,
                caprini=excluded.caprini,
                caprini_capi=excluded.caprini_capi,
                altro_text=excluded.altro_text,
                altro_capi=excluded.altro_capi,
                updated_at=excluded.updated_at
        ''',
            (
                user_id,
                int(bool(bovini)),
                bovini_capi_clean,
                int(bool(ovini)),
                ovini_capi_clean,
                int(bool(caprini)),
                caprini_capi_clean,
                altro_clean,
                altro_capi_clean,
                updated_at,
            ),
        )


def list_macchinari_entries(user_id: int) -> list[dict]:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            SELECT
                id,
                COALESCE(nome, ''),
                COALESCE(marca, ''),
                COALESCE(modello, ''),
                COALESCE(identificativo, ''),
                anno,
                COALESCE(note, ''),
                COALESCE(created_at, ''),
                COALESCE(updated_at, '')
            FROM macchinari
            WHERE user_id=?
            ORDER BY COALESCE(NULLIF(TRIM(nome), ''), ''), id DESC
        ''',
            (user_id,),
        )
        rows = c.fetchall()

    entries = []
    for (
        row_id,
        nome,
        marca,
        modello,
        identificativo,
        anno,
        note,
        created_at,
        updated_at,
    ) in rows:
        try:
            entry_id = int(row_id or 0)
        except (TypeError, ValueError):
            continue
        if entry_id <= 0:
            continue

        anno_value = None
        if anno is not None:
            try:
                anno_value = int(anno)
            except (TypeError, ValueError):
                anno_value = None

        entries.append(
            {
                "id": entry_id,
                "nome": (nome or "").strip(),
                "marca": (marca or "").strip(),
                "modello": (modello or "").strip(),
                "identificativo": (identificativo or "").strip(),
                "anno": anno_value,
                "note": (note or "").strip(),
                "created_at": (created_at or "").strip(),
                "updated_at": (updated_at or "").strip(),
            }
        )
    return entries


def _normalize_macchinario_payload(
    nome: str,
    marca: str = "",
    modello: str = "",
    identificativo: str = "",
    anno=None,
    note: str = "",
) -> tuple[str, str, str, str, int | None, str]:
    nome_clean = (nome or "").strip()
    if not nome_clean:
        raise ValueError("Inserisci il nome del macchinario.")

    marca_clean = (marca or "").strip()
    modello_clean = (modello or "").strip()
    identificativo_clean = (identificativo or "").strip()
    note_clean = (note or "").strip()

    anno_value = None
    anno_text = str(anno or "").strip()
    if anno_text:
        try:
            anno_value = int(anno_text)
        except (TypeError, ValueError):
            raise ValueError("Anno non valido. Inserisci un numero.")
        if anno_value < 0 or anno_value > 9999:
            raise ValueError("Anno non valido. Inserisci un valore tra 0 e 9999.")

    return nome_clean, marca_clean, modello_clean, identificativo_clean, anno_value, note_clean


def add_macchinario_entry(
    user_id: int,
    nome: str,
    marca: str = "",
    modello: str = "",
    identificativo: str = "",
    anno=None,
    note: str = "",
) -> int:
    (
        nome_clean,
        marca_clean,
        modello_clean,
        identificativo_clean,
        anno_value,
        note_clean,
    ) = _normalize_macchinario_payload(
        nome=nome,
        marca=marca,
        modello=modello,
        identificativo=identificativo,
        anno=anno,
        note=note,
    )

    now_text = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO macchinari
                (user_id, nome, marca, modello, identificativo, anno, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
            (
                user_id,
                nome_clean,
                marca_clean,
                modello_clean,
                identificativo_clean,
                anno_value,
                note_clean,
                now_text,
                now_text,
            ),
        )
        return int(c.lastrowid or 0)


def update_macchinario_entry(
    user_id: int,
    macchinario_id: int,
    nome: str,
    marca: str = "",
    modello: str = "",
    identificativo: str = "",
    anno=None,
    note: str = "",
) -> bool:
    macchinario_id_value = _to_non_negative_int(macchinario_id)
    if macchinario_id_value <= 0:
        raise ValueError("Macchinario non valido.")

    (
        nome_clean,
        marca_clean,
        modello_clean,
        identificativo_clean,
        anno_value,
        note_clean,
    ) = _normalize_macchinario_payload(
        nome=nome,
        marca=marca,
        modello=modello,
        identificativo=identificativo,
        anno=anno,
        note=note,
    )

    now_text = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            UPDATE macchinari
            SET nome=?, marca=?, modello=?, identificativo=?, anno=?, note=?, updated_at=?
            WHERE id=? AND user_id=?
        ''',
            (
                nome_clean,
                marca_clean,
                modello_clean,
                identificativo_clean,
                anno_value,
                note_clean,
                now_text,
                macchinario_id_value,
                user_id,
            ),
        )

        return int(c.rowcount or 0) > 0


def delete_macchinario_entry(user_id: int, macchinario_id: int) -> int:
    macchinario_id_value = _to_non_negative_int(macchinario_id)
    if macchinario_id_value <= 0:
        raise ValueError("Macchinario non valido.")

    with get_conn() as conn:
        c = conn.cursor()

        c.execute(
            "SELECT 1 FROM macchinari WHERE id=? AND user_id=?",
            (macchinario_id_value, user_id),
        )
        if not c.fetchone():
            raise ValueError("Macchinario non trovato.")

        c.execute(
            "SELECT COUNT(1) FROM manutenzioni_macchinari WHERE user_id=? AND macchinario_id=?",
            (user_id, macchinario_id_value),
        )
        row = c.fetchone()
        manutenzioni_collegate = int((row[0] if row else 0) or 0)

        c.execute(
            "DELETE FROM macchinari WHERE id=? AND user_id=?",
            (macchinario_id_value, user_id),
        )

        if int(c.rowcount or 0) <= 0:
            raise ValueError("Macchinario non trovato o non eliminabile.")

    return max(manutenzioni_collegate, 0)


def _normalize_manutenzione_tipo(raw_value: str) -> str:
    tipo = (raw_value or "").strip().upper()
    if not tipo:
        return ""
    if tipo.startswith("STRAORD"):
        return "STRAORDINARIA"
    if tipo.startswith("ORDINAR"):
        return "ORDINARIA"
    if tipo in ("ORDINARIA", "STRAORDINARIA"):
        return tipo
    return ""


def list_manutenzioni_macchinari_entries(user_id: int, macchinario_id: int | None = None) -> list[dict]:
    macchinario_id_value = _to_non_negative_int(macchinario_id)
    if macchinario_id is not None and macchinario_id_value <= 0:
        return []

    params = [user_id]
    where_macchinario = ""
    if macchinario_id is not None:
        where_macchinario = " AND m.macchinario_id=?"
        params.append(macchinario_id_value)

    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            f'''
            SELECT
                m.id,
                m.macchinario_id,
                COALESCE(k.nome, ''),
                COALESCE(k.identificativo, ''),
                COALESCE(m.data_manutenzione, ''),
                COALESCE(m.tipo_manutenzione, ''),
                COALESCE(m.descrizione, ''),
                m.costo,
                COALESCE(m.fornitore, ''),
                COALESCE(m.note, ''),
                COALESCE(m.created_at, ''),
                COALESCE(m.updated_at, '')
            FROM manutenzioni_macchinari m
            LEFT JOIN macchinari k
              ON k.id = m.macchinario_id AND k.user_id = m.user_id
            WHERE m.user_id=?{where_macchinario}
            ORDER BY COALESCE(NULLIF(TRIM(m.data_manutenzione), ''), '') DESC, m.id DESC
        ''',
            tuple(params),
        )
        rows = c.fetchall()

    entries = []
    for (
        row_id,
        row_macchinario_id,
        macchinario_nome,
        macchinario_identificativo,
        data_manutenzione,
        tipo_manutenzione,
        descrizione,
        costo,
        fornitore,
        note,
        created_at,
        updated_at,
    ) in rows:
        entry_id = _to_non_negative_int(row_id)
        if entry_id <= 0:
            continue

        macchinario_value = _to_non_negative_int(row_macchinario_id)
        if macchinario_value <= 0:
            continue

        costo_value = None
        if costo is not None:
            try:
                costo_value = float(costo)
            except (TypeError, ValueError):
                costo_value = None

        entries.append(
            {
                "id": entry_id,
                "macchinario_id": macchinario_value,
                "macchinario_nome": (macchinario_nome or "").strip(),
                "macchinario_identificativo": (macchinario_identificativo or "").strip(),
                "data_manutenzione": (data_manutenzione or "").strip(),
                "tipo_manutenzione": (tipo_manutenzione or "").strip().upper(),
                "descrizione": (descrizione or "").strip(),
                "costo": costo_value,
                "fornitore": (fornitore or "").strip(),
                "note": (note or "").strip(),
                "created_at": (created_at or "").strip(),
                "updated_at": (updated_at or "").strip(),
            }
        )
    return entries


def _normalize_manutenzione_payload(
    macchinario_id: int,
    data_manutenzione: str,
    tipo_manutenzione: str,
    descrizione: str,
    costo=None,
    fornitore: str = "",
    note: str = "",
) -> tuple[int, str, str, str, float | None, str, str]:
    macchinario_id_value = _to_non_negative_int(macchinario_id)
    if macchinario_id_value <= 0:
        raise ValueError("Macchinario non valido.")

    data_manutenzione_clean = (data_manutenzione or "").strip()
    if not data_manutenzione_clean:
        raise ValueError("Inserisci la data della manutenzione.")
    try:
        datetime.strptime(data_manutenzione_clean, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Data manutenzione non valida. Usa il formato YYYY-MM-DD.")

    tipo_manutenzione_clean = _normalize_manutenzione_tipo(tipo_manutenzione)
    if tipo_manutenzione_clean not in ("ORDINARIA", "STRAORDINARIA"):
        raise ValueError("Tipo manutenzione non valido. Scegli tra ordinaria e straordinaria.")

    descrizione_clean = (descrizione or "").strip()
    if not descrizione_clean:
        raise ValueError("Inserisci una descrizione della manutenzione.")

    costo_value = None
    if costo not in (None, ""):
        try:
            costo_value = float(costo)
        except (TypeError, ValueError):
            raise ValueError("Costo non valido. Inserisci un numero.")
        if costo_value < 0:
            raise ValueError("Costo non valido. Inserisci un valore positivo.")

    fornitore_clean = (fornitore or "").strip()
    note_clean = (note or "").strip()

    return (
        macchinario_id_value,
        data_manutenzione_clean,
        tipo_manutenzione_clean,
        descrizione_clean,
        costo_value,
        fornitore_clean,
        note_clean,
    )


def add_manutenzione_macchinario_entry(
    user_id: int,
    macchinario_id: int,
    data_manutenzione: str,
    tipo_manutenzione: str,
    descrizione: str,
    costo=None,
    fornitore: str = "",
    note: str = "",
) -> int:
    (
        macchinario_id_value,
        data_manutenzione_clean,
        tipo_manutenzione_clean,
        descrizione_clean,
        costo_value,
        fornitore_clean,
        note_clean,
    ) = _normalize_manutenzione_payload(
        macchinario_id=macchinario_id,
        data_manutenzione=data_manutenzione,
        tipo_manutenzione=tipo_manutenzione,
        descrizione=descrizione,
        costo=costo,
        fornitore=fornitore,
        note=note,
    )

    now_text = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        c = conn.cursor()

        c.execute(
            '''
            SELECT COUNT(1)
            FROM macchinari
            WHERE id=? AND user_id=?
        ''',
            (macchinario_id_value, user_id),
        )
        row = c.fetchone()
        if int((row[0] if row else 0) or 0) <= 0:
            raise ValueError("Macchinario non disponibile.")

        c.execute(
            '''
            INSERT INTO manutenzioni_macchinari
                (user_id, macchinario_id, data_manutenzione, tipo_manutenzione,
                 descrizione, costo, fornitore, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
            (
                user_id,
                macchinario_id_value,
                data_manutenzione_clean,
                tipo_manutenzione_clean,
                descrizione_clean,
                costo_value,
                fornitore_clean,
                note_clean,
                now_text,
                now_text,
            ),
        )

        return int(c.lastrowid or 0)


def update_manutenzione_macchinario_entry(
    user_id: int,
    manutenzione_id: int,
    macchinario_id: int,
    data_manutenzione: str,
    tipo_manutenzione: str,
    descrizione: str,
    costo=None,
    fornitore: str = "",
    note: str = "",
) -> bool:
    manutenzione_id_value = _to_non_negative_int(manutenzione_id)
    if manutenzione_id_value <= 0:
        raise ValueError("Manutenzione non valida.")

    (
        macchinario_id_value,
        data_manutenzione_clean,
        tipo_manutenzione_clean,
        descrizione_clean,
        costo_value,
        fornitore_clean,
        note_clean,
    ) = _normalize_manutenzione_payload(
        macchinario_id=macchinario_id,
        data_manutenzione=data_manutenzione,
        tipo_manutenzione=tipo_manutenzione,
        descrizione=descrizione,
        costo=costo,
        fornitore=fornitore,
        note=note,
    )

    now_text = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        c = conn.cursor()

        c.execute(
            '''
            SELECT COUNT(1)
            FROM macchinari
            WHERE id=? AND user_id=?
        ''',
            (macchinario_id_value, user_id),
        )
        row = c.fetchone()
        if int((row[0] if row else 0) or 0) <= 0:
            raise ValueError("Macchinario non disponibile.")

        c.execute(
            '''
            UPDATE manutenzioni_macchinari
            SET macchinario_id=?, data_manutenzione=?, tipo_manutenzione=?,
                descrizione=?, costo=?, fornitore=?, note=?, updated_at=?
            WHERE id=? AND user_id=?
        ''',
            (
                macchinario_id_value,
                data_manutenzione_clean,
                tipo_manutenzione_clean,
                descrizione_clean,
                costo_value,
                fornitore_clean,
                note_clean,
                now_text,
                manutenzione_id_value,
                user_id,
            ),
        )

        return int(c.rowcount or 0) > 0


def delete_manutenzione_macchinario_entry(user_id: int, manutenzione_id: int) -> bool:
    manutenzione_id_value = _to_non_negative_int(manutenzione_id)
    if manutenzione_id_value <= 0:
        raise ValueError("Manutenzione non valida.")

    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "DELETE FROM manutenzioni_macchinari WHERE id=? AND user_id=?",
            (manutenzione_id_value, user_id),
        )
        return int(c.rowcount or 0) > 0


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

        # Informazioni aziendali principali.
        #c.execute(
        #    '''CREATE TABLE IF NOT EXISTS azienda_info
        #             (user_id INTEGER PRIMARY KEY,
        #              nome_azienda TEXT NOT NULL DEFAULT '',
        #              piva TEXT NOT NULL DEFAULT '',
        #              occupazione TEXT NOT NULL DEFAULT '',
        #              data_creazione TEXT NOT NULL DEFAULT '',
        #              updated_at TEXT NOT NULL DEFAULT '',
        #              FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE)'''
        #)

        # --- ANAGRAFICA SOGGETTI (CRM) ---
        c.execute('''
            CREATE TABLE IF NOT EXISTS anagrafica (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tipo TEXT NOT NULL DEFAULT 'Fornitore', 
                ragione_sociale TEXT NOT NULL,
                partita_iva TEXT,
                codice_fiscale TEXT,
                indirizzo TEXT,
                email TEXT,
                telefono TEXT,
                note TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        ''')

        c.execute("PRAGMA table_info(azienda_info)")
        colonne_azienda_info = {row[1] for row in c.fetchall()}
        if colonne_azienda_info and "nome_azienda" not in colonne_azienda_info:
            c.execute("ALTER TABLE azienda_info ADD COLUMN nome_azienda TEXT NOT NULL DEFAULT ''")
        if colonne_azienda_info and "piva" not in colonne_azienda_info:
            c.execute("ALTER TABLE azienda_info ADD COLUMN piva TEXT NOT NULL DEFAULT ''")
        if colonne_azienda_info and "occupazione" not in colonne_azienda_info:
            c.execute("ALTER TABLE azienda_info ADD COLUMN occupazione TEXT NOT NULL DEFAULT ''")
        if colonne_azienda_info and "data_creazione" not in colonne_azienda_info:
            c.execute("ALTER TABLE azienda_info ADD COLUMN data_creazione TEXT NOT NULL DEFAULT ''")
        if colonne_azienda_info and "updated_at" not in colonne_azienda_info:
            c.execute("ALTER TABLE azienda_info ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")

        # Configurazione azienda: tipi animali allevati.
        c.execute('''CREATE TABLE IF NOT EXISTS azienda_animali
                     (user_id INTEGER PRIMARY KEY,
                      bovini INTEGER NOT NULL DEFAULT 0,
                      bovini_capi INTEGER NOT NULL DEFAULT 0,
                      ovini INTEGER NOT NULL DEFAULT 0,
                      ovini_capi INTEGER NOT NULL DEFAULT 0,
                      caprini INTEGER NOT NULL DEFAULT 0,
                      caprini_capi INTEGER NOT NULL DEFAULT 0,
                      altro_text TEXT NOT NULL DEFAULT '',
                      altro_capi INTEGER NOT NULL DEFAULT 0,
                      updated_at TEXT NOT NULL DEFAULT '',
                      FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE)''')

        c.execute("PRAGMA table_info(azienda_animali)")
        colonne_animali = {row[1] for row in c.fetchall()}
        if colonne_animali and "bovini" not in colonne_animali:
            c.execute("ALTER TABLE azienda_animali ADD COLUMN bovini INTEGER NOT NULL DEFAULT 0")
        if colonne_animali and "bovini_capi" not in colonne_animali:
            c.execute("ALTER TABLE azienda_animali ADD COLUMN bovini_capi INTEGER NOT NULL DEFAULT 0")
        if colonne_animali and "ovini" not in colonne_animali:
            c.execute("ALTER TABLE azienda_animali ADD COLUMN ovini INTEGER NOT NULL DEFAULT 0")
        if colonne_animali and "ovini_capi" not in colonne_animali:
            c.execute("ALTER TABLE azienda_animali ADD COLUMN ovini_capi INTEGER NOT NULL DEFAULT 0")
        if colonne_animali and "caprini" not in colonne_animali:
            c.execute("ALTER TABLE azienda_animali ADD COLUMN caprini INTEGER NOT NULL DEFAULT 0")
        if colonne_animali and "caprini_capi" not in colonne_animali:
            c.execute("ALTER TABLE azienda_animali ADD COLUMN caprini_capi INTEGER NOT NULL DEFAULT 0")
        if colonne_animali and "altro_text" not in colonne_animali:
            c.execute("ALTER TABLE azienda_animali ADD COLUMN altro_text TEXT NOT NULL DEFAULT ''")
        if colonne_animali and "altro_capi" not in colonne_animali:
            c.execute("ALTER TABLE azienda_animali ADD COLUMN altro_capi INTEGER NOT NULL DEFAULT 0")
        if colonne_animali and "updated_at" not in colonne_animali:
            c.execute("ALTER TABLE azienda_animali ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")

        # Dettaglio animali allevati: una riga per tipo/finalita.
        c.execute(
            '''
            CREATE TABLE IF NOT EXISTS azienda_animali_dettaglio
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER NOT NULL,
                 tipo_animale TEXT NOT NULL,
                 finalita TEXT NOT NULL DEFAULT '',
                 altro_label TEXT NOT NULL DEFAULT '',
                 group_name TEXT NOT NULL DEFAULT '',
                 riproduzione INTEGER NOT NULL DEFAULT 0,
                 capi INTEGER NOT NULL DEFAULT 0 CHECK(capi >= 0),
                 created_at TEXT NOT NULL DEFAULT '',
                 updated_at TEXT NOT NULL DEFAULT '',
                 merged_into_entry_id INTEGER,
                 merge_date TEXT NOT NULL DEFAULT '',
                 UNIQUE(user_id, tipo_animale, finalita, altro_label, group_name),
                 FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE)
        '''
        )

        c.execute("PRAGMA table_info(azienda_animali_dettaglio)")
        colonne_animali_det = {row[1] for row in c.fetchall()}
        if colonne_animali_det and "finalita" not in colonne_animali_det:
            c.execute("ALTER TABLE azienda_animali_dettaglio ADD COLUMN finalita TEXT NOT NULL DEFAULT ''")
        if colonne_animali_det and "altro_label" not in colonne_animali_det:
            c.execute("ALTER TABLE azienda_animali_dettaglio ADD COLUMN altro_label TEXT NOT NULL DEFAULT ''")
        if colonne_animali_det and "group_name" not in colonne_animali_det:
            c.execute("ALTER TABLE azienda_animali_dettaglio ADD COLUMN group_name TEXT NOT NULL DEFAULT ''")
        if colonne_animali_det and "riproduzione" not in colonne_animali_det:
            c.execute("ALTER TABLE azienda_animali_dettaglio ADD COLUMN riproduzione INTEGER NOT NULL DEFAULT 0")
        if colonne_animali_det and "capi" not in colonne_animali_det:
            c.execute("ALTER TABLE azienda_animali_dettaglio ADD COLUMN capi INTEGER NOT NULL DEFAULT 0")
        if colonne_animali_det and "created_at" not in colonne_animali_det:
            c.execute("ALTER TABLE azienda_animali_dettaglio ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
        if colonne_animali_det and "updated_at" not in colonne_animali_det:
            c.execute("ALTER TABLE azienda_animali_dettaglio ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
        if colonne_animali_det and "merged_into_entry_id" not in colonne_animali_det:
            c.execute("ALTER TABLE azienda_animali_dettaglio ADD COLUMN merged_into_entry_id INTEGER")
        if colonne_animali_det and "merge_date" not in colonne_animali_det:
            c.execute("ALTER TABLE azienda_animali_dettaglio ADD COLUMN merge_date TEXT NOT NULL DEFAULT ''")

        _ensure_animali_dettaglio_unique_on_group_name(c)

        c.execute('''CREATE INDEX IF NOT EXISTS idx_animali_dettaglio_user
                     ON azienda_animali_dettaglio(user_id)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_animali_dettaglio_tipo
                     ON azienda_animali_dettaglio(user_id, tipo_animale, finalita)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_animali_dettaglio_nome
                 ON azienda_animali_dettaglio(user_id, group_name)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_animali_dettaglio_merge
                 ON azienda_animali_dettaglio(user_id, merged_into_entry_id, merge_date)''')

        # Storico eventi gruppi animali (aggiunte/rimozioni capi, divisioni, unioni).
        c.execute(
            '''CREATE TABLE IF NOT EXISTS azienda_animali_storico
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  event_type TEXT NOT NULL DEFAULT '',
                  event_time TEXT NOT NULL DEFAULT '',
                  gruppo_entry_id INTEGER,
                  gruppo_nome TEXT NOT NULL DEFAULT '',
                  tipo_animale TEXT NOT NULL DEFAULT '',
                  finalita TEXT NOT NULL DEFAULT '',
                  capi_prima INTEGER,
                  capi_variazione INTEGER NOT NULL DEFAULT 0,
                  capi_dopo INTEGER,
                  gruppo_correlato_entry_id INTEGER,
                  gruppo_correlato_nome TEXT NOT NULL DEFAULT '',
                  note TEXT NOT NULL DEFAULT '',
                  FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE)'''
        )

        c.execute("PRAGMA table_info(azienda_animali_storico)")
        colonne_animali_storico = {row[1] for row in c.fetchall()}
        if colonne_animali_storico and "event_type" not in colonne_animali_storico:
            c.execute("ALTER TABLE azienda_animali_storico ADD COLUMN event_type TEXT NOT NULL DEFAULT ''")
        if colonne_animali_storico and "event_time" not in colonne_animali_storico:
            c.execute("ALTER TABLE azienda_animali_storico ADD COLUMN event_time TEXT NOT NULL DEFAULT ''")
        if colonne_animali_storico and "gruppo_entry_id" not in colonne_animali_storico:
            c.execute("ALTER TABLE azienda_animali_storico ADD COLUMN gruppo_entry_id INTEGER")
        if colonne_animali_storico and "gruppo_nome" not in colonne_animali_storico:
            c.execute("ALTER TABLE azienda_animali_storico ADD COLUMN gruppo_nome TEXT NOT NULL DEFAULT ''")
        if colonne_animali_storico and "tipo_animale" not in colonne_animali_storico:
            c.execute("ALTER TABLE azienda_animali_storico ADD COLUMN tipo_animale TEXT NOT NULL DEFAULT ''")
        if colonne_animali_storico and "finalita" not in colonne_animali_storico:
            c.execute("ALTER TABLE azienda_animali_storico ADD COLUMN finalita TEXT NOT NULL DEFAULT ''")
        if colonne_animali_storico and "capi_prima" not in colonne_animali_storico:
            c.execute("ALTER TABLE azienda_animali_storico ADD COLUMN capi_prima INTEGER")
        if colonne_animali_storico and "capi_variazione" not in colonne_animali_storico:
            c.execute("ALTER TABLE azienda_animali_storico ADD COLUMN capi_variazione INTEGER NOT NULL DEFAULT 0")
        if colonne_animali_storico and "capi_dopo" not in colonne_animali_storico:
            c.execute("ALTER TABLE azienda_animali_storico ADD COLUMN capi_dopo INTEGER")
        if colonne_animali_storico and "gruppo_correlato_entry_id" not in colonne_animali_storico:
            c.execute("ALTER TABLE azienda_animali_storico ADD COLUMN gruppo_correlato_entry_id INTEGER")
        if colonne_animali_storico and "gruppo_correlato_nome" not in colonne_animali_storico:
            c.execute("ALTER TABLE azienda_animali_storico ADD COLUMN gruppo_correlato_nome TEXT NOT NULL DEFAULT ''")
        if colonne_animali_storico and "note" not in colonne_animali_storico:
            c.execute("ALTER TABLE azienda_animali_storico ADD COLUMN note TEXT NOT NULL DEFAULT ''")

        c.execute('''CREATE INDEX IF NOT EXISTS idx_animali_storico_user_time
                 ON azienda_animali_storico(user_id, event_time DESC, id DESC)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_animali_storico_user_gruppo
                 ON azienda_animali_storico(user_id, gruppo_entry_id, event_time DESC, id DESC)''')

        # Statistiche media nascite/genitori per tipo animale.
        c.execute(
            '''CREATE TABLE IF NOT EXISTS azienda_animali_nascite_media
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  tipo_animale TEXT NOT NULL,
                  altro_label TEXT NOT NULL DEFAULT '',
                  media_nascite_per_capo REAL NOT NULL DEFAULT 0,
                  campioni INTEGER NOT NULL DEFAULT 0,
                  updated_at TEXT NOT NULL DEFAULT '',
                  UNIQUE(user_id, tipo_animale, altro_label),
                  FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE)'''
        )

        c.execute("PRAGMA table_info(azienda_animali_nascite_media)")
        colonne_animali_nascite_media = {row[1] for row in c.fetchall()}
        if colonne_animali_nascite_media and "tipo_animale" not in colonne_animali_nascite_media:
            c.execute("ALTER TABLE azienda_animali_nascite_media ADD COLUMN tipo_animale TEXT NOT NULL DEFAULT ''")
        if colonne_animali_nascite_media and "altro_label" not in colonne_animali_nascite_media:
            c.execute("ALTER TABLE azienda_animali_nascite_media ADD COLUMN altro_label TEXT NOT NULL DEFAULT ''")
        if colonne_animali_nascite_media and "media_nascite_per_capo" not in colonne_animali_nascite_media:
            c.execute(
                "ALTER TABLE azienda_animali_nascite_media ADD COLUMN media_nascite_per_capo REAL NOT NULL DEFAULT 0"
            )
        if colonne_animali_nascite_media and "campioni" not in colonne_animali_nascite_media:
            c.execute("ALTER TABLE azienda_animali_nascite_media ADD COLUMN campioni INTEGER NOT NULL DEFAULT 0")
        if colonne_animali_nascite_media and "updated_at" not in colonne_animali_nascite_media:
            c.execute("ALTER TABLE azienda_animali_nascite_media ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")

        c.execute('''CREATE INDEX IF NOT EXISTS idx_animali_nascite_media_user
                 ON azienda_animali_nascite_media(user_id, tipo_animale, altro_label)''')

        _migrate_legacy_azienda_animali_to_dettaglio(c)
        _backfill_missing_group_names(c)

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
        # Migrazione: aggiunge colonna stato_pagamento se manca.
        if "stato_pagamento" not in colonne_movimenti:
            c.execute("ALTER TABLE movimenti ADD COLUMN stato_pagamento TEXT NOT NULL DEFAULT 'PAGATO'")
        if "economia_colture_id" not in colonne_movimenti:
            c.execute("ALTER TABLE movimenti ADD COLUMN economia_colture_id INTEGER DEFAULT NULL")

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

        # Collegamento movimenti <-> gruppi animali (molti-a-molti).
        c.execute(
            '''
            CREATE TABLE IF NOT EXISTS movimenti_animali_link
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER NOT NULL,
                 movimento_id INTEGER NOT NULL,
                 animale_entry_id INTEGER NOT NULL,
                 created_at TEXT NOT NULL DEFAULT '',
                 UNIQUE(user_id, movimento_id, animale_entry_id),
                 FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE,
                 FOREIGN KEY(movimento_id) REFERENCES movimenti(id) ON DELETE CASCADE,
                 FOREIGN KEY(animale_entry_id) REFERENCES azienda_animali_dettaglio(id) ON DELETE CASCADE)
        '''
        )

        c.execute('''CREATE INDEX IF NOT EXISTS idx_mov_animali_link_movimento
                 ON movimenti_animali_link(user_id, movimento_id)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_mov_animali_link_entry
                 ON movimenti_animali_link(user_id, animale_entry_id)''')

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

        # Ripartizione litri produzione latte per gruppo animale.
        c.execute(
            '''CREATE TABLE IF NOT EXISTS produzione_latte_gruppi
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER NOT NULL,
                      produzione_id INTEGER NOT NULL,
                      movimento_id INTEGER,
                      animale_entry_id INTEGER NOT NULL,
                      litri REAL NOT NULL CHECK(litri >= 0),
                      created_at TEXT NOT NULL DEFAULT '',
                      updated_at TEXT NOT NULL DEFAULT '',
                      UNIQUE(user_id, produzione_id, animale_entry_id),
                      FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE,
                      FOREIGN KEY(produzione_id) REFERENCES produzione_latte(id) ON DELETE CASCADE,
                      FOREIGN KEY(movimento_id) REFERENCES movimenti(id) ON DELETE SET NULL,
                      FOREIGN KEY(animale_entry_id) REFERENCES azienda_animali_dettaglio(id) ON DELETE CASCADE)'''
        )

        c.execute("PRAGMA table_info(produzione_latte_gruppi)")
        colonne_produzione_gruppi = {row[1] for row in c.fetchall()}
        if colonne_produzione_gruppi and "movimento_id" not in colonne_produzione_gruppi:
            c.execute("ALTER TABLE produzione_latte_gruppi ADD COLUMN movimento_id INTEGER")
        if colonne_produzione_gruppi and "updated_at" not in colonne_produzione_gruppi:
            c.execute("ALTER TABLE produzione_latte_gruppi ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")

        c.execute('''CREATE INDEX IF NOT EXISTS idx_prod_gruppi_user_produzione
                 ON produzione_latte_gruppi(user_id, produzione_id)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_prod_gruppi_user_movimento
                 ON produzione_latte_gruppi(user_id, movimento_id)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_prod_gruppi_user_entry
                 ON produzione_latte_gruppi(user_id, animale_entry_id)''')

        # Se viene eliminato un movimento latte, elimina anche la produzione collegata.
        c.execute('''CREATE TRIGGER IF NOT EXISTS trg_movimenti_delete_produzione_latte
                     BEFORE DELETE ON movimenti
                     FOR EACH ROW
                     BEGIN
                         DELETE FROM produzione_latte WHERE movimento_id = OLD.id;
                     END''')

        # Tabella Produzione Carne (quantita salvata in kg, prezzo in EUR/kg)
        c.execute('''CREATE TABLE IF NOT EXISTS produzione_carne
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER NOT NULL,
                      data_op TEXT NOT NULL, -- ISO: YYYY-MM-DD
                      kg REAL NOT NULL CHECK(kg > 0),
                      prezzo_kg REAL NOT NULL DEFAULT 0,
                      movimento_id INTEGER,
                      FOREIGN KEY(movimento_id) REFERENCES movimenti(id) ON DELETE SET NULL,
                      FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE)''')

        c.execute("PRAGMA table_info(produzione_carne)")
        colonne_produzione_carne = {row[1] for row in c.fetchall()}
        if colonne_produzione_carne and "prezzo_kg" not in colonne_produzione_carne:
            c.execute("ALTER TABLE produzione_carne ADD COLUMN prezzo_kg REAL NOT NULL DEFAULT 0")
        if colonne_produzione_carne and "movimento_id" not in colonne_produzione_carne:
            c.execute("ALTER TABLE produzione_carne ADD COLUMN movimento_id INTEGER")

        c.execute('''CREATE INDEX IF NOT EXISTS idx_prod_carne_user_date
                     ON produzione_carne(user_id, data_op)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_prod_carne_user_movimento
                 ON produzione_carne(user_id, movimento_id)''')

        # Se viene eliminato un movimento carne, elimina anche la produzione collegata.
        c.execute('''CREATE TRIGGER IF NOT EXISTS trg_movimenti_delete_produzione_carne
                     BEFORE DELETE ON movimenti
                     FOR EACH ROW
                     BEGIN
                         DELETE FROM produzione_carne WHERE movimento_id = OLD.id;
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


        # =====================================================================
        # SINCRONIZZAZIONE AUTOMATICA: ECONOMIA COLTURE -> MOVIMENTI GLOBALI
        # =====================================================================

        # 1. Backfill: Sincronizza eventuali dati passati già presenti in economia_colture
        #    che non sono ancora stati inseriti nei movimenti.
        c.execute('''
            INSERT INTO movimenti (user_id, data_op, tipo, categoria, descrizione, importo, stato_pagamento, iva_importo, economia_colture_id)
            SELECT 
                user_id, 
                data_operazione, 
                CASE WHEN tipo='RICAVO' THEN 'ENTRATA' ELSE 'USCITA' END, 
                categoria, 
                COALESCE(descrizione, 'Operazione su campo'), 
                importo, 
                'PAGATO', 
                0, 
                id
            FROM economia_colture e
            WHERE NOT EXISTS (
                SELECT 1 FROM movimenti m WHERE m.economia_colture_id = e.id
            )
        ''')

        # 2. Trigger: Alla CREAZIONE di una nuova operazione agricola
        c.execute('''
            CREATE TRIGGER IF NOT EXISTS trg_economia_insert
            AFTER INSERT ON economia_colture
            BEGIN
                INSERT INTO movimenti 
                    (user_id, data_op, tipo, categoria, descrizione, importo, stato_pagamento, iva_importo, economia_colture_id)
                VALUES 
                    (NEW.user_id, NEW.data_operazione, 
                     CASE WHEN NEW.tipo='RICAVO' THEN 'ENTRATA' ELSE 'USCITA' END, 
                     NEW.categoria, COALESCE(NEW.descrizione, 'Operazione su campo'), NEW.importo, 'PAGATO', 0, NEW.id);
            END
        ''')

        # 3. Trigger: All'AGGIORNAMENTO di un'operazione agricola
        c.execute('''
            CREATE TRIGGER IF NOT EXISTS trg_economia_update
            AFTER UPDATE ON economia_colture
            BEGIN
                UPDATE movimenti
                SET data_op = NEW.data_operazione,
                    tipo = CASE WHEN NEW.tipo='RICAVO' THEN 'ENTRATA' ELSE 'USCITA' END,
                    categoria = NEW.categoria,
                    descrizione = COALESCE(NEW.descrizione, 'Operazione su campo'),
                    importo = NEW.importo
                WHERE economia_colture_id = NEW.id;
            END
        ''')

        # 4. Trigger: All'ELIMINAZIONE di un'operazione agricola
        c.execute('''
            CREATE TRIGGER IF NOT EXISTS trg_economia_delete
            AFTER DELETE ON economia_colture
            BEGIN
                DELETE FROM movimenti WHERE economia_colture_id = OLD.id;
            END
        ''')



        # --- SEZIONE AGRICOLTURA 4.0 ---
        
        # Tabella Campi Agricoli (Salva il poligono della mappa)
        c.execute(
            '''CREATE TABLE IF NOT EXISTS campi_agricoli
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  nome TEXT NOT NULL,
                  area_ettari REAL NOT NULL DEFAULT 0,
                  geojson TEXT NOT NULL DEFAULT '',
                  colore TEXT NOT NULL DEFAULT '#3388ff',
                  created_at TEXT NOT NULL DEFAULT '',
                  updated_at TEXT NOT NULL DEFAULT '',
                  FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE)'''
        )

        # Tabella Storico Colture (Quaderno di campagna)
        c.execute(
            '''CREATE TABLE IF NOT EXISTS storico_colture
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  campo_id INTEGER NOT NULL,
                  coltura TEXT NOT NULL,
                  data_semina TEXT NOT NULL DEFAULT '',
                  data_raccolto TEXT NOT NULL DEFAULT '',
                  resa_quintali REAL NOT NULL DEFAULT 0,
                  note TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL DEFAULT '',
                  updated_at TEXT NOT NULL DEFAULT '',
                  FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE,
                  FOREIGN KEY(campo_id) REFERENCES campi_agricoli(id) ON DELETE CASCADE)'''
        )
        # --- TABELLA ECONOMIA COLTURE (Fase 1) ---
        c.execute('''
            CREATE TABLE IF NOT EXISTS economia_colture (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                storico_id INTEGER NOT NULL,
                tipo TEXT NOT NULL,          
                categoria TEXT NOT NULL,
                descrizione TEXT,
                importo REAL NOT NULL,
                data_operazione TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(storico_id) REFERENCES storico_colture(id) ON DELETE CASCADE
            )
        ''')

        # --- AGGIORNAMENTO STRUTTURA CAMPI (Uliveti/Vigneti) ---
        try:
            c.execute("PRAGMA table_info(campi_agricoli)")
            colonne_esistenti = [row[1] for row in c.fetchall()]
            if "tipo_campo" not in colonne_esistenti:
                c.execute("ALTER TABLE campi_agricoli ADD COLUMN tipo_campo TEXT NOT NULL DEFAULT 'Seminativo'")
                c.execute("ALTER TABLE campi_agricoli ADD COLUMN varieta TEXT DEFAULT ''")
                c.execute("ALTER TABLE campi_agricoli ADD COLUMN num_piante INTEGER DEFAULT 0")
                c.execute("ALTER TABLE campi_agricoli ADD COLUMN anno_impianto INTEGER DEFAULT 0")
        except Exception as e:
            print(f"Errore aggiornamento campi_agricoli: {e}")

        # --- TABELLA REGISTRO METEO E PIOGGE ---
        c.execute('''
            CREATE TABLE IF NOT EXISTS registro_meteo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                data_rilevazione TEXT NOT NULL,
                pioggia_mm REAL NOT NULL DEFAULT 0.0,
                temperatura_max REAL,
                temperatura_min REAL
            )
        ''')
        # Anagrafica macchinari.
        c.execute(
            '''CREATE TABLE IF NOT EXISTS macchinari
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  nome TEXT NOT NULL,
                  marca TEXT NOT NULL DEFAULT '',
                  modello TEXT NOT NULL DEFAULT '',
                  identificativo TEXT NOT NULL DEFAULT '',
                  anno INTEGER,
                  note TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL DEFAULT '',
                  updated_at TEXT NOT NULL DEFAULT '',
                  FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE)'''
        )

        c.execute("PRAGMA table_info(macchinari)")
        colonne_macchinari = {row[1] for row in c.fetchall()}
        if colonne_macchinari and "nome" not in colonne_macchinari:
            c.execute("ALTER TABLE macchinari ADD COLUMN nome TEXT NOT NULL DEFAULT ''")
        if colonne_macchinari and "marca" not in colonne_macchinari:
            c.execute("ALTER TABLE macchinari ADD COLUMN marca TEXT NOT NULL DEFAULT ''")
        if colonne_macchinari and "modello" not in colonne_macchinari:
            c.execute("ALTER TABLE macchinari ADD COLUMN modello TEXT NOT NULL DEFAULT ''")
        if colonne_macchinari and "identificativo" not in colonne_macchinari:
            c.execute("ALTER TABLE macchinari ADD COLUMN identificativo TEXT NOT NULL DEFAULT ''")
        if colonne_macchinari and "anno" not in colonne_macchinari:
            c.execute("ALTER TABLE macchinari ADD COLUMN anno INTEGER")
        if colonne_macchinari and "note" not in colonne_macchinari:
            c.execute("ALTER TABLE macchinari ADD COLUMN note TEXT NOT NULL DEFAULT ''")
        if colonne_macchinari and "created_at" not in colonne_macchinari:
            c.execute("ALTER TABLE macchinari ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
        if colonne_macchinari and "updated_at" not in colonne_macchinari:
            c.execute("ALTER TABLE macchinari ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")

        c.execute('''CREATE INDEX IF NOT EXISTS idx_macchinari_user_nome
                 ON macchinari(user_id, nome, id DESC)''')

        # Manutenzioni macchinari.
        c.execute(
            '''CREATE TABLE IF NOT EXISTS manutenzioni_macchinari
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  macchinario_id INTEGER NOT NULL,
                  data_manutenzione TEXT NOT NULL,
                  tipo_manutenzione TEXT NOT NULL DEFAULT 'ORDINARIA'
                      CHECK(tipo_manutenzione IN ('ORDINARIA', 'STRAORDINARIA')),
                  descrizione TEXT NOT NULL DEFAULT '',
                  costo REAL,
                  fornitore TEXT NOT NULL DEFAULT '',
                  note TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL DEFAULT '',
                  updated_at TEXT NOT NULL DEFAULT '',
                  FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE,
                  FOREIGN KEY(macchinario_id) REFERENCES macchinari(id) ON DELETE CASCADE)'''
        )

        c.execute("PRAGMA table_info(manutenzioni_macchinari)")
        colonne_manutenzioni = {row[1] for row in c.fetchall()}
        if colonne_manutenzioni and "macchinario_id" not in colonne_manutenzioni:
            c.execute("ALTER TABLE manutenzioni_macchinari ADD COLUMN macchinario_id INTEGER NOT NULL DEFAULT 0")
        if colonne_manutenzioni and "data_manutenzione" not in colonne_manutenzioni:
            c.execute("ALTER TABLE manutenzioni_macchinari ADD COLUMN data_manutenzione TEXT NOT NULL DEFAULT ''")
        if colonne_manutenzioni and "tipo_manutenzione" not in colonne_manutenzioni:
            c.execute(
                "ALTER TABLE manutenzioni_macchinari ADD COLUMN tipo_manutenzione TEXT NOT NULL DEFAULT 'ORDINARIA'"
            )
        if colonne_manutenzioni and "descrizione" not in colonne_manutenzioni:
            c.execute("ALTER TABLE manutenzioni_macchinari ADD COLUMN descrizione TEXT NOT NULL DEFAULT ''")
        if colonne_manutenzioni and "costo" not in colonne_manutenzioni:
            c.execute("ALTER TABLE manutenzioni_macchinari ADD COLUMN costo REAL")
        if colonne_manutenzioni and "fornitore" not in colonne_manutenzioni:
            c.execute("ALTER TABLE manutenzioni_macchinari ADD COLUMN fornitore TEXT NOT NULL DEFAULT ''")
        if colonne_manutenzioni and "note" not in colonne_manutenzioni:
            c.execute("ALTER TABLE manutenzioni_macchinari ADD COLUMN note TEXT NOT NULL DEFAULT ''")
        if colonne_manutenzioni and "created_at" not in colonne_manutenzioni:
            c.execute("ALTER TABLE manutenzioni_macchinari ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
        if colonne_manutenzioni and "updated_at" not in colonne_manutenzioni:
            c.execute("ALTER TABLE manutenzioni_macchinari ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")

        c.execute('''CREATE INDEX IF NOT EXISTS idx_manutenzioni_user_data
                 ON manutenzioni_macchinari(user_id, data_manutenzione DESC, id DESC)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_manutenzioni_user_macchinario
                 ON manutenzioni_macchinari(user_id, macchinario_id, data_manutenzione DESC, id DESC)''')
# ==========================================
# FUNZIONI PER ANAGRAFICA (CRM)
# ==========================================
def add_soggetto(user_id, tipo, ragione_sociale, partita_iva="", codice_fiscale="", indirizzo="", email="", telefono="", note=""):
    now_text = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO anagrafica (user_id, tipo, ragione_sociale, partita_iva, codice_fiscale, indirizzo, email, telefono, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, tipo, ragione_sociale, partita_iva, codice_fiscale, indirizzo, email, telefono, note, now_text, now_text))
        return c.lastrowid

def update_soggetto(user_id, soggetto_id, tipo, ragione_sociale, partita_iva="", codice_fiscale="", indirizzo="", email="", telefono="", note=""):
    now_text = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE anagrafica 
            SET tipo=?, ragione_sociale=?, partita_iva=?, codice_fiscale=?, indirizzo=?, email=?, telefono=?, note=?, updated_at=?
            WHERE id=? AND user_id=?
        """, (tipo, ragione_sociale, partita_iva, codice_fiscale, indirizzo, email, telefono, note, now_text, soggetto_id, user_id))
        return c.rowcount > 0

def delete_soggetto(user_id, soggetto_id):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM anagrafica WHERE id=? AND user_id=?", (soggetto_id, user_id))
        return c.rowcount > 0

def list_soggetti(user_id):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM anagrafica WHERE user_id=? ORDER BY ragione_sociale ASC", (user_id,))
        cols = [desc[0] for desc in c.description]
        return [dict(zip(cols, row)) for row in c.fetchall()]