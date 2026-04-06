import os
import json
import shutil
import sqlite3
from datetime import datetime
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

ANIMAL_TYPE_OPTIONS = ("BOVINI", "OVINI", "CAPRINI", "SUINI", "AVICOLI", "EQUINI", "ALTRO")
ANIMAL_PURPOSE_OPTIONS = ("LATTE", "CARNE")


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


def _to_non_negative_int(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number >= 0 else 0


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
                    (user_id, tipo_animale, finalita, altro_label, group_name, capi, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
                (user_id, tipo, finalita, altro_label, group_name, capi, now_text, now_text),
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

    cursor.execute(
        '''
        SELECT id, user_id, tipo_animale, finalita, altro_label, group_name, capi, created_at, updated_at
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
             capi INTEGER NOT NULL DEFAULT 0 CHECK(capi >= 0),
             created_at TEXT NOT NULL DEFAULT '',
             updated_at TEXT NOT NULL DEFAULT '',
             UNIQUE(user_id, tipo_animale, finalita, altro_label, group_name),
             FOREIGN KEY(user_id) REFERENCES utenti(id) ON DELETE CASCADE)
    '''
    )

    now_text = datetime.now().isoformat(timespec="seconds")
    for row_id, user_id, tipo_animale, finalita, altro_label, group_name, capi, created_at, updated_at in rows:
        tipo_norm = _normalize_tipo_animale(tipo_animale)
        finalita_norm = _normalize_finalita_animale(finalita)
        altro_clean = (altro_label or "").strip()
        group_name_clean = (group_name or "").strip() or _default_group_name(tipo_norm, finalita_norm, altro_clean)
        created_at_clean = (created_at or "").strip() or now_text
        updated_at_clean = (updated_at or "").strip() or now_text

        cursor.execute(
            '''
            INSERT INTO azienda_animali_dettaglio_new
                (id, user_id, tipo_animale, finalita, altro_label, group_name, capi, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
            (
                int(row_id),
                int(user_id),
                tipo_norm,
                finalita_norm,
                altro_clean,
                group_name_clean,
                _to_non_negative_int(capi),
                created_at_clean,
                updated_at_clean,
            ),
        )

    cursor.execute("DROP TABLE azienda_animali_dettaglio")
    cursor.execute("ALTER TABLE azienda_animali_dettaglio_new RENAME TO azienda_animali_dettaglio")


def list_azienda_animali_entries(user_id: int) -> list[dict]:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            SELECT id, tipo_animale, finalita, altro_label, capi, group_name
            FROM azienda_animali_dettaglio
            WHERE user_id=?
            ORDER BY
                COALESCE(NULLIF(TRIM(group_name), ''), tipo_animale) COLLATE NOCASE,
                tipo_animale,
                finalita,
                altro_label,
                id
        ''',
            (user_id,),
        )
        rows = c.fetchall()

    entries = []
    for row_id, tipo_animale, finalita, altro_label, capi, group_name in rows:
        group_name_clean = (group_name or "").strip()
        if not group_name_clean:
            group_name_clean = _default_group_name(tipo_animale, finalita, altro_label)

        entries.append(
            {
                "id": int(row_id),
                "tipo_animale": (tipo_animale or "").strip().upper(),
                "finalita": (finalita or "").strip().upper(),
                "altro_label": (altro_label or "").strip(),
                "capi": _to_non_negative_int(capi),
                "group_name": group_name_clean,
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


def add_azienda_animale_entry(
    user_id: int,
    tipo_animale: str,
    capi: int,
    finalita: str = "",
    altro_label: str = "",
    group_name: str = "",
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

    now_text = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO azienda_animali_dettaglio
                (user_id, tipo_animale, finalita, altro_label, group_name, capi, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, tipo_animale, finalita, altro_label, group_name) DO UPDATE SET
                capi = azienda_animali_dettaglio.capi + excluded.capi,
                updated_at = excluded.updated_at
        ''',
            (user_id, tipo, finalita_norm, altro_clean, group_name_clean, capi_value, now_text, now_text),
        )


def remove_azienda_animale_capi(user_id: int, entry_id: int, capi_da_rimuovere: int) -> bool:
    entry_id_value = _to_non_negative_int(entry_id)
    if entry_id_value <= 0:
        raise ValueError("Categoria animale non valida.")

    capi_value = _to_non_negative_int(capi_da_rimuovere)
    if capi_value <= 0:
        raise ValueError("Il numero capi da rimuovere deve essere maggiore di zero.")

    now_text = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            SELECT capi
            FROM azienda_animali_dettaglio
            WHERE id=? AND user_id=?
        ''',
            (entry_id_value, user_id),
        )
        row = c.fetchone()

        if not row:
            raise ValueError("Categoria animale non trovata.")

        capi_attuali = _to_non_negative_int(row[0])
        if capi_value > capi_attuali:
            raise ValueError("Non puoi rimuovere piu capi di quelli presenti nella categoria selezionata.")

        if capi_value == capi_attuali:
            c.execute(
                "DELETE FROM azienda_animali_dettaglio WHERE id=? AND user_id=?",
                (entry_id_value, user_id),
            )
            return True

        c.execute(
            '''
            UPDATE azienda_animali_dettaglio
            SET capi=?, updated_at=?
            WHERE id=? AND user_id=?
        ''',
            (capi_attuali - capi_value, now_text, entry_id_value, user_id),
        )
    return False


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
            SELECT 1
            FROM azienda_animali_dettaglio
            WHERE id=? AND user_id=?
        ''',
            (entry_id_value, user_id),
        )
        if not c.fetchone():
            raise ValueError("Categoria animale non trovata.")

        if nuovo_capi_value == 0:
            c.execute(
                "DELETE FROM azienda_animali_dettaglio WHERE id=? AND user_id=?",
                (entry_id_value, user_id),
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
    return False


def set_azienda_animale_finalita(user_id: int, entry_id: int, nuova_finalita: str) -> bool:
    entry_id_value = _to_non_negative_int(entry_id)
    if entry_id_value <= 0:
        raise ValueError("Categoria animale non valida.")

    finalita_norm = _normalize_finalita_animale(nuova_finalita)
    if finalita_norm not in ANIMAL_PURPOSE_OPTIONS:
        raise ValueError("Destinazione non valida. Seleziona 'Da Latte' o 'Da Carne'.")

    now_text = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            '''
            SELECT id, tipo_animale, finalita, altro_label, capi, group_name
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
        if not current_group_name:
            current_group_name = _default_group_name(tipo_animale, current_finalita, altro_label)

        if tipo_animale not in ("BOVINI", "OVINI"):
            raise ValueError("La destinazione e modificabile solo per Bovini e Ovini.")

        if current_finalita == finalita_norm:
            return False

        c.execute(
            '''
            SELECT id, capi, group_name
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
            merged_group_name = conflict_group_name or current_group_name or _default_group_name(
                tipo_animale,
                finalita_norm,
                altro_label,
            )

            c.execute(
                '''
                UPDATE azienda_animali_dettaglio
                SET capi=?, group_name=?, updated_at=?
                WHERE id=? AND user_id=?
            ''',
                (conflict_capi + capi_value, merged_group_name, now_text, conflict_id, user_id),
            )
            c.execute(
                "DELETE FROM azienda_animali_dettaglio WHERE id=? AND user_id=?",
                (current_id, user_id),
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
    return False


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
            SELECT tipo_animale, finalita, altro_label, group_name, capi
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
                    (user_id, tipo_animale, finalita, altro_label, group_name, capi, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
                (
                    user_id,
                    tipo_animale,
                    finalita,
                    altro_label,
                    new_group_name_clean,
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

    return capi_restanti


def merge_azienda_animale_groups(
    user_id: int,
    entry_id_principale: int,
    entry_id_secondario: int,
    nuovo_group_name: str,
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

    now_text = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        c = conn.cursor()

        c.execute(
            '''
            SELECT id, tipo_animale, finalita, altro_label, capi
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
        capi_principale = _to_non_negative_int(principale[4])

        tipo_secondario = (secondario[1] or "").strip().upper()
        finalita_secondario = (secondario[2] or "").strip().upper()
        altro_secondario = (secondario[3] or "").strip()
        capi_secondario = _to_non_negative_int(secondario[4])

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
            WHERE user_id=? AND animale_entry_id=?
        ''',
            (entry_id_principale_value, user_id, entry_id_secondario_value),
        )
        c.execute(
            "DELETE FROM movimenti_animali_link WHERE user_id=? AND animale_entry_id=?",
            (user_id, entry_id_secondario_value),
        )

        c.execute(
            "DELETE FROM azienda_animali_dettaglio WHERE id=? AND user_id=?",
            (entry_id_secondario_value, user_id),
        )

        try:
            c.execute(
                '''
                UPDATE azienda_animali_dettaglio
                SET capi=?, group_name=?, updated_at=?
                WHERE id=? AND user_id=?
            ''',
                (capi_totali, new_group_name_clean, now_text, entry_id_principale_value, user_id),
            )
        except sqlite3.IntegrityError:
            raise ValueError("Esiste gia un gruppo con questo nome per la stessa categoria.")

    return capi_totali


def delete_azienda_animale_entry(user_id: int, entry_id: int):
    entry_id_value = _to_non_negative_int(entry_id)
    if entry_id_value <= 0:
        raise ValueError("Categoria animale non valida.")

    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT 1 FROM azienda_animali_dettaglio WHERE id=? AND user_id=?",
            (entry_id_value, user_id),
        )
        if not c.fetchone():
            raise ValueError("Categoria animale non trovata.")

        c.execute(
            "DELETE FROM azienda_animali_dettaglio WHERE id=? AND user_id=?",
            (entry_id_value, user_id),
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
                 capi INTEGER NOT NULL DEFAULT 0 CHECK(capi >= 0),
                 created_at TEXT NOT NULL DEFAULT '',
                 updated_at TEXT NOT NULL DEFAULT '',
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
        if colonne_animali_det and "capi" not in colonne_animali_det:
            c.execute("ALTER TABLE azienda_animali_dettaglio ADD COLUMN capi INTEGER NOT NULL DEFAULT 0")
        if colonne_animali_det and "created_at" not in colonne_animali_det:
            c.execute("ALTER TABLE azienda_animali_dettaglio ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
        if colonne_animali_det and "updated_at" not in colonne_animali_det:
            c.execute("ALTER TABLE azienda_animali_dettaglio ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")

        _ensure_animali_dettaglio_unique_on_group_name(c)

        c.execute('''CREATE INDEX IF NOT EXISTS idx_animali_dettaglio_user
                     ON azienda_animali_dettaglio(user_id)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_animali_dettaglio_tipo
                     ON azienda_animali_dettaglio(user_id, tipo_animale, finalita)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_animali_dettaglio_nome
                 ON azienda_animali_dettaglio(user_id, group_name)''')

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
