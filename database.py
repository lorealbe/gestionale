import os
import re
import json
import shutil
from datetime import datetime
from pathlib import Path

# NUOVO: Importiamo il database e i modelli dal nostro file ORM
from models import (
    db, init_tables, Utente, Profilo, AziendaInfo, Anagrafica,
    AziendaAnimali, AziendaAnimaliDettaglio, AziendaAnimaliStorico,
    AziendaAnimaliNasciteMedia, Movimento, MovimentiAnimaliLink,
    ProduzioneLatte, ProduzioneLatteGruppi, ProduzioneCarne, Fattura,
    Macchinario, ManutenzioneMacchinario, CampoAgricolo, StoricoColtura,
    EconomiaColtura, RegistroMeteo
)
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
    "bovini": False, "bovini_capi": 0, "ovini": False, "ovini_capi": 0,
    "caprini": False, "caprini_capi": 0, "altro_text": "", "altro_capi": 0,
}

DEFAULT_AZIENDA_INFO = {
    "nome_azienda": "", "piva": "", "occupazione": "", "data_creazione": "",
}

ANIMAL_TYPE_OPTIONS = ("BOVINI", "OVINI", "CAPRINI", "SUINI", "AVICOLI", "EQUINI", "ALTRO")
ANIMAL_PURPOSE_OPTIONS = ("LATTE", "CARNE")
GROUPS_DESCRIPTION_PATTERN = re.compile(r"\s*\|\s*Gruppi:\s*.*$", re.IGNORECASE)

# --- FUNZIONI DI SETUP E PATH ---

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

    # Inizializza tutte le tabelle del database in modo sicuro (sostituisce init_db)
    init_tables()
    _DATA_READY = True

def get_db_path() -> Path:
    ensure_data_paths()
    return DB_PATH

def get_fatture_root() -> Path:
    ensure_data_paths()
    return FATTURE_ROOT

def get_fatture_user_dir(user_id: int) -> Path:
    user_dir = get_fatture_root() / f"user_{user_id}"
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir

def resolve_fattura_path(stored_path: str) -> Path:
    p = Path(stored_path)
    return p if p.is_absolute() else get_fatture_root() / p

def to_storage_fattura_path(file_path: Path) -> str:
    try:
        return file_path.resolve().relative_to(get_fatture_root().resolve()).as_posix()
    except Exception:
        return str(file_path)

def get_conn():
    # Manteniamo questo metodo temporaneamente per compatibilità con le funzioni
    # che non abbiamo ancora migrato a Peewee.
    return db.connection()


def get_azienda_info(user_id: int) -> dict:
    # Usiamo .dicts() per estrarre direttamente i dati dal modello in un dizionario nativo
    row = AziendaInfo.select().where(AziendaInfo.user == user_id).dicts().first()
    return row if row else dict(DEFAULT_AZIENDA_INFO)

def save_azienda_info(user_id: int, nome_azienda: str, piva: str, occupazione: str, data_creazione: str):
    # .replace() in SQLite (tramite Peewee) gestisce l'ON CONFLICT(user_id) DO UPDATE in automatico
    AziendaInfo.replace(
        user=user_id,
        nome_azienda=(nome_azienda or "").strip(),
        piva=(piva or "").strip(),
        occupazione=(occupazione or "").strip(),
        data_creazione=(data_creazione or "").strip(),
        updated_at=datetime.now().isoformat(timespec="seconds")
    ).execute()

def get_azienda_animali(user_id: int) -> dict:
    row = AziendaAnimali.select().where(AziendaAnimali.user == user_id).dicts().first()
    if not row:
        return dict(DEFAULT_AZIENDA_ANIMALI)
    
    # SQLite salva i boolean come 1/0, li ritrasformiamo in True/False per la GUI
    row['bovini'] = bool(row['bovini'])
    row['ovini'] = bool(row['ovini'])
    row['caprini'] = bool(row['caprini'])
    return row

def save_azienda_animali(
    user_id: int, bovini: bool, bovini_capi: int, ovini: bool, ovini_capi: int, 
    caprini: bool, caprini_capi: int, altro_text: str, altro_capi: int
):
    AziendaAnimali.replace(
        user=user_id,
        bovini=int(bovini),
        bovini_capi=_to_non_negative_int(bovini_capi),
        ovini=int(ovini),
        ovini_capi=_to_non_negative_int(ovini_capi),
        caprini=int(caprini),
        caprini_capi=_to_non_negative_int(caprini_capi),
        altro_text=(altro_text or "").strip(),
        altro_capi=_to_non_negative_int(altro_capi),
        updated_at=datetime.now().isoformat(timespec="seconds")
    ).execute()

def _log_azienda_animali_storico(
    cursor, user_id: int, event_type: str, event_time: str, gruppo_entry_id=None, 
    gruppo_nome: str = "", tipo_animale: str = "", finalita: str = "", 
    capi_prima=None, capi_variazione=0, capi_dopo=None, 
    gruppo_correlato_entry_id=None, gruppo_correlato_nome: str = "", note: str = ""
):
    # Nota: il parametro 'cursor' è mantenuto solo per retrocompatibilità con eventuali chiamate GUI, ma ignorato.
    AziendaAnimaliStorico.insert(
        user=user_id,
        event_type=(event_type or "AGGIUNTA_CAPI").strip().upper(),
        event_time=(event_time or "").strip() or datetime.now().isoformat(timespec="seconds"),
        gruppo_entry_id=_to_non_negative_int(gruppo_entry_id) if gruppo_entry_id else None,
        gruppo_nome=(gruppo_nome or "").strip(),
        tipo_animale=(tipo_animale or "").strip().upper(),
        finalita=(finalita or "").strip().upper(),
        capi_prima=_to_non_negative_int(capi_prima) if capi_prima is not None else None,
        capi_variazione=int(capi_variazione or 0),
        capi_dopo=_to_non_negative_int(capi_dopo) if capi_dopo is not None else None,
        gruppo_correlato_entry_id=_to_non_negative_int(gruppo_correlato_entry_id) if gruppo_correlato_entry_id else None,
        gruppo_correlato_nome=(gruppo_correlato_nome or "").strip(),
        note=(note or "").strip()
    ).execute()

def list_azienda_animali_entries(user_id: int, include_merged: bool = False) -> list[dict]:
    query = AziendaAnimaliDettaglio.select().where(AziendaAnimaliDettaglio.user == user_id)
    if not include_merged:
        query = query.where(AziendaAnimaliDettaglio.merged_into_entry_id.is_null())
    
    entries = []
    # .dicts() è il metodo più efficiente per passare dati dal DB alla UI senza overhead
    for row in query.dicts():
        row['riproduzione'] = bool(row['riproduzione'])
        row['group_name'] = row.get('group_name') or _default_group_name(row['tipo_animale'], row['finalita'], row['altro_label'])
        entries.append(row)
        
    # Ordinamento pythonico (più veloce di clausole ORDER BY complesse con COALESCE)
    return sorted(entries, key=lambda x: (x['group_name'].lower(), x['tipo_animale'], x['id']))

def add_azienda_animale_entry(
    user_id: int, tipo_animale: str, capi: int, finalita: str = "", 
    altro_label: str = "", group_name: str = "", riproduzione: bool = False, cursor=None
):
    tipo = _normalize_tipo_animale(tipo_animale)
    if tipo not in ANIMAL_TYPE_OPTIONS: raise ValueError("Tipo animale non valido.")
    
    capi_value = _to_non_negative_int(capi)
    if capi_value <= 0: raise ValueError("Il numero capi deve essere maggiore di zero.")
    
    finalita_norm = _normalize_finalita_animale(finalita)
    altro_clean = (altro_label or "").strip()
    group_name_clean = (group_name or "").strip() or _default_group_name(tipo, finalita_norm, altro_clean)
    now_text = datetime.now().isoformat(timespec="seconds")
    
    with db.atomic(): # Garantisce che salvataggio e log avvengano assieme
        entry, created = AziendaAnimaliDettaglio.get_or_create(
            user=user_id, tipo_animale=tipo, finalita=finalita_norm, altro_label=altro_clean, group_name=group_name_clean,
            defaults={'capi': capi_value, 'riproduzione': _to_bool_int(riproduzione), 'created_at': now_text, 'updated_at': now_text}
        )
        
        capi_prima = 0 if created else entry.capi
        if not created:
            entry.capi += capi_value
            entry.riproduzione = entry.riproduzione or _to_bool_int(riproduzione)
            entry.updated_at = now_text
            entry.save()
            
        note = "Creato nuovo gruppo." if created else "Aggiunti capi al gruppo."
        _log_azienda_animali_storico(
            None, user_id=user_id, event_type="AGGIUNTA_CAPI", event_time=now_text,
            gruppo_entry_id=entry.id, gruppo_nome=group_name_clean, tipo_animale=tipo,
            finalita=finalita_norm, capi_prima=capi_prima, capi_variazione=capi_value,
            capi_dopo=entry.capi, note=note
        )

def remove_azienda_animale_capi(user_id: int, entry_id: int, capi_da_rimuovere: int, cursor=None) -> bool:
    entry_id_value = _to_non_negative_int(entry_id)
    capi_value = _to_non_negative_int(capi_da_rimuovere)
    if entry_id_value <= 0 or capi_value <= 0: raise ValueError("Dati non validi.")
    now_text = datetime.now().isoformat(timespec="seconds")

    with db.atomic():
        entry = AziendaAnimaliDettaglio.get_or_none(id=entry_id_value, user=user_id)
        if not entry: raise ValueError("Categoria animale non trovata.")
        if capi_value > entry.capi: raise ValueError("Non puoi rimuovere più capi di quelli presenti.")
        
        capi_prima = entry.capi
        
        # Caso 1: Rimozione totale (il gruppo viene eliminato)
        if capi_value == entry.capi:
            # Sgancia eventuali gruppi che erano stati "fusi" (merged) in questo
            AziendaAnimaliDettaglio.update(merged_into_entry_id=None, merge_date='', updated_at=now_text).where(AziendaAnimaliDettaglio.merged_into_entry_id == entry.id).execute()
            entry.delete_instance()
            
            _log_azienda_animali_storico(
                None, user_id=user_id, event_type="RIMOZIONE_CAPI", event_time=now_text,
                gruppo_entry_id=entry.id, gruppo_nome=entry.group_name, tipo_animale=entry.tipo_animale,
                finalita=entry.finalita, capi_prima=capi_prima, capi_variazione=-capi_value,
                capi_dopo=0, note="Rimozione completa capi: gruppo eliminato."
            )
            return True
            
        # Caso 2: Rimozione parziale
        entry.capi -= capi_value
        entry.updated_at = now_text
        entry.save()
        
        _log_azienda_animali_storico(
            None, user_id=user_id, event_type="RIMOZIONE_CAPI", event_time=now_text,
            gruppo_entry_id=entry.id, gruppo_nome=entry.group_name, tipo_animale=entry.tipo_animale,
            finalita=entry.finalita, capi_prima=capi_prima, capi_variazione=-capi_value,
            capi_dopo=entry.capi, note="Rimozione capi dal gruppo."
        )
        return False

def set_azienda_animale_capi(user_id: int, entry_id: int, nuovo_capi: int) -> bool:
    # Metodo ultra-efficiente: usiamo la logica già scritta per aggiungere o rimuovere la differenza
    entry = AziendaAnimaliDettaglio.get_or_none(id=_to_non_negative_int(entry_id), user=user_id)
    if not entry: raise ValueError("Categoria animale non trovata.")
    
    nuovo_capi_value = _to_non_negative_int(nuovo_capi)
    if nuovo_capi_value == entry.capi: return False
    
    if nuovo_capi_value > entry.capi:
        add_azienda_animale_entry(user_id, entry.tipo_animale, nuovo_capi_value - entry.capi, entry.finalita, entry.altro_label, entry.group_name, entry.riproduzione)
        return False
    else:
        return remove_azienda_animale_capi(user_id, entry.id, entry.capi - nuovo_capi_value)
    
def set_azienda_animale_finalita(user_id: int, entry_id: int, nuova_finalita: str) -> bool:
    finalita_norm = _normalize_finalita_animale(nuova_finalita)
    if finalita_norm not in ANIMAL_PURPOSE_OPTIONS: raise ValueError("Destinazione non valida.")
    now = datetime.now().isoformat(timespec="seconds")

    with db.atomic():
        current = AziendaAnimaliDettaglio.get_or_none(id=entry_id, user=user_id)
        if not current: raise ValueError("Categoria animale non trovata.")
        if current.tipo_animale not in ("BOVINI", "OVINI"): raise ValueError("La destinazione è modificabile solo per Bovini e Ovini.")
        if current.finalita == finalita_norm: return False

        # Cerca conflitti per auto-merge
        conflict = AziendaAnimaliDettaglio.get_or_none(
            user=user_id, tipo_animale=current.tipo_animale, finalita=finalita_norm, 
            altro_label=current.altro_label, group_name=current.group_name
        )

        if conflict and conflict.id != current.id:
            capi_dopo = conflict.capi + current.capi
            conflict.capi = capi_dopo
            conflict.riproduzione = conflict.riproduzione or current.riproduzione
            conflict.updated_at = now
            conflict.save()

            current.delete_instance()
            _log_azienda_animali_storico(None, user_id, "CAMBIO_DESTINAZIONE", now, conflict.id, conflict.group_name, current.tipo_animale, finalita_norm, conflict.capi - current.capi, current.capi, capi_dopo, current.id, current.group_name, note="Cambio destinazione con accorpamento gruppo.")
            return True

        current.finalita = finalita_norm
        current.updated_at = now
        current.save()
        _log_azienda_animali_storico(None, user_id, "CAMBIO_DESTINAZIONE", now, current.id, current.group_name, current.tipo_animale, finalita_norm, current.capi, 0, current.capi, note="Cambio destinazione.")
        return False

def set_azienda_animale_riproduzione(user_id: int, entry_id: int, destinato_riproduzione) -> bool:
    nuova = _to_bool_int(destinato_riproduzione)
    now = datetime.now().isoformat(timespec="seconds")
    with db.atomic():
        entry = AziendaAnimaliDettaglio.get_or_none(id=entry_id, user=user_id)
        if not entry or entry.riproduzione == nuova: return False

        entry.riproduzione = nuova
        entry.updated_at = now
        entry.save()
        _log_azienda_animali_storico(None, user_id, "CAMBIO_RIPRODUZIONE", now, entry.id, entry.group_name, entry.tipo_animale, entry.finalita, entry.capi, 0, entry.capi, note=f"Destinazione riproduzione {'attivata' if nuova else 'disattivata'}.")
        return True

def set_azienda_animale_group_name(user_id: int, entry_id: int, nuovo_group_name: str) -> bool:
    group_name_clean = (nuovo_group_name or "").strip()
    if not group_name_clean: raise ValueError("Inserisci un nome gruppo valido.")
    now = datetime.now().isoformat(timespec="seconds")

    with db.atomic():
        entry = AziendaAnimaliDettaglio.get_or_none(id=entry_id, user=user_id)
        if not entry: raise ValueError("Categoria animale non trovata.")
        if entry.group_name == group_name_clean: return False

        if AziendaAnimaliDettaglio.get_or_none(user=user_id, tipo_animale=entry.tipo_animale, finalita=entry.finalita, altro_label=entry.altro_label, group_name=group_name_clean):
            raise ValueError("Esiste già un gruppo con questo nome per la stessa categoria.")

        entry.group_name = group_name_clean
        entry.updated_at = now
        entry.save()

        movs = [l.movimento_id for l in MovimentiAnimaliLink.select().where(MovimentiAnimaliLink.animale_entry == entry.id)]
        _refresh_linked_group_descriptions(user_id, movs)
        return True

def split_azienda_animale_group(user_id: int, entry_id: int, capi_nuovo_gruppo: int, nuovo_group_name: str) -> int:
    with db.atomic():
        entry = AziendaAnimaliDettaglio.get_or_none(id=entry_id, user=user_id)
        if not entry: raise ValueError("Categoria animale non trovata.")
        
        capi_nuovo = _to_non_negative_int(capi_nuovo_gruppo)
        if entry.capi <= 1 or capi_nuovo >= entry.capi: raise ValueError("Operazione non valida (capi insufficienti).")
        if nuovo_group_name.strip() == entry.group_name: raise ValueError("Il nuovo gruppo deve avere un nome diverso.")

        now = datetime.now().isoformat(timespec="seconds")
        capi_restanti = entry.capi - capi_nuovo
        
        entry.capi = capi_restanti
        entry.updated_at = now
        entry.save()
        
        nuovo_gruppo = AziendaAnimaliDettaglio.create(
            user=user_id, tipo_animale=entry.tipo_animale, finalita=entry.finalita, altro_label=entry.altro_label,
            group_name=nuovo_group_name.strip(), riproduzione=entry.riproduzione, capi=capi_nuovo,
            created_at=now, updated_at=now
        )
        
        links = MovimentiAnimaliLink.select().where(MovimentiAnimaliLink.animale_entry == entry.id)
        for link in links:
            MovimentiAnimaliLink.get_or_create(user=user_id, movimento=link.movimento_id, animale_entry=nuovo_gruppo.id, defaults={'created_at': now})
        
        _refresh_linked_group_descriptions(user_id, [link.movimento_id for link in links])
        
        _log_azienda_animali_storico(None, user_id, "DIVISIONE_GRUPPO", now, entry.id, entry.group_name, entry.tipo_animale, entry.finalita, entry.capi + capi_nuovo, -capi_nuovo, capi_restanti, nuovo_gruppo.id, nuovo_group_name.strip(), note=f"Creato nuovo gruppo '{nuovo_group_name.strip()}' con {capi_nuovo} capi.")
        return capi_restanti

def merge_azienda_animale_groups(user_id: int, entry_id_principale: int, entry_id_secondario: int, nuovo_group_name: str, merge_date: str = None) -> int:
    if entry_id_principale == entry_id_secondario: raise ValueError("Seleziona due gruppi diversi da unire.")
    new_group_name_clean = (nuovo_group_name or "").strip()
    if not new_group_name_clean: raise ValueError("Inserisci un nome per il gruppo unificato.")
    merge_date_clean = (merge_date or datetime.now().strftime("%Y-%m-%d")).strip()
    now = datetime.now().isoformat(timespec="seconds")

    with db.atomic():
        p = AziendaAnimaliDettaglio.get_or_none(id=entry_id_principale, user=user_id)
        s = AziendaAnimaliDettaglio.get_or_none(id=entry_id_secondario, user=user_id)
        if not p or not s: raise ValueError("Uno o più gruppi non sono disponibili.")
        if p.merged_into_entry_id or s.merged_into_entry_id: raise ValueError("Un gruppo risulta già unito ad un altro gruppo.")
        if p.tipo_animale != s.tipo_animale or p.finalita != s.finalita or p.altro_label != s.altro_label:
            raise ValueError("Puoi unire solo gruppi compatibili dello stesso tipo animale.")

        capi_totali = p.capi + s.capi

        # 1. Sposta i movimenti animali competenti
        links = MovimentiAnimaliLink.select(MovimentiAnimaliLink, Movimento).join(Movimento).where(MovimentiAnimaliLink.animale_entry == s.id)
        movs_to_refresh = []
        for link in links:
            movs_to_refresh.append(link.movimento_id)
            if link.movimento.data_op >= merge_date_clean:
                MovimentiAnimaliLink.get_or_create(user=user_id, movimento=link.movimento_id, animale_entry=p.id, defaults={'created_at': now})
                link.delete_instance()

        # 2. Sposta la produzione latte competente
        prod_links = ProduzioneLatteGruppi.select(ProduzioneLatteGruppi, ProduzioneLatte).join(ProduzioneLatte).where(ProduzioneLatteGruppi.animale_entry == s.id)
        for pl in prod_links:
            if pl.produzione.data_op >= merge_date_clean:
                pl_principale, _ = ProduzioneLatteGruppi.get_or_create(user=user_id, produzione=pl.produzione_id, animale_entry=p.id, defaults={'litri': 0, 'movimento': pl.movimento_id, 'created_at': now, 'updated_at': now})
                pl_principale.litri += pl.litri
                pl_principale.updated_at = now
                pl_principale.save()
                pl.delete_instance()

        # 3. Disabilita il secondario e aggiorna il principale
        s.merged_into_entry_id = p.id
        s.merge_date = merge_date_clean
        s.updated_at = now
        s.save()

        p.capi = capi_totali
        p.group_name = new_group_name_clean
        p.riproduzione = p.riproduzione or s.riproduzione
        p.updated_at = now
        p.save()

        _log_azienda_animali_storico(None, user_id, "UNIONE_GRUPPI", now, p.id, p.group_name, p.tipo_animale, p.finalita, p.capi - s.capi, s.capi, capi_totali, s.id, s.group_name, note=f"Unione gruppi con competenza dal {merge_date_clean}.")
        
        movs_to_refresh.extend([l.movimento_id for l in MovimentiAnimaliLink.select().where(MovimentiAnimaliLink.animale_entry == p.id)])
        _refresh_linked_group_descriptions(user_id, list(set(movs_to_refresh)))
        return capi_totali

def delete_azienda_animale_entry(user_id: int, entry_id: int):
    with db.atomic():
        entry = AziendaAnimaliDettaglio.get_or_none(id=entry_id, user=user_id)
        if not entry: raise ValueError("Categoria animale non trovata.")
        
        now = datetime.now().isoformat(timespec="seconds")
        AziendaAnimaliDettaglio.update(merged_into_entry_id=None, merge_date='', updated_at=now).where(AziendaAnimaliDettaglio.merged_into_entry_id == entry.id).execute()
        
        _log_azienda_animali_storico(None, user_id, "RIMOZIONE_CAPI", now, entry.id, entry.group_name, entry.tipo_animale, entry.finalita, entry.capi, -entry.capi, 0, note="Eliminazione gruppo.")
        entry.delete_instance()

def _refresh_linked_group_descriptions(user_id: int, movimento_ids, cursor=None) -> int:
    if not movimento_ids: return 0
    updated_rows = 0
    with db.atomic():
        for mov_id in set(movimento_ids):
            mov = Movimento.get_or_none(id=mov_id, user=user_id)
            if not mov or not mov.descrizione: continue

            links = MovimentiAnimaliLink.select(MovimentiAnimaliLink, AziendaAnimaliDettaglio).join(AziendaAnimaliDettaglio).where(MovimentiAnimaliLink.movimento == mov_id)
            group_names = [l.animale_entry.group_name or _default_group_name(l.animale_entry.tipo_animale, l.animale_entry.finalita, l.animale_entry.altro_label) for l in links]

            base_desc = GROUPS_DESCRIPTION_PATTERN.sub("", mov.descrizione).rstrip()
            if base_desc:
                groups_text = ", ".join(set(group_names)) if group_names else "Nessun gruppo"
                nuova_desc = f"{base_desc} | Gruppi: {groups_text}"
                if mov.descrizione != nuova_desc:
                    mov.descrizione = nuova_desc
                    mov.save()
                    updated_rows += 1
    return updated_rows

# ==========================================
# 5. ALLOCAZIONI PRODUZIONE LATTE E NASCITE
# ==========================================

def set_produzione_latte_group_allocations(user_id: int, produzione_id: int, movimento_id: int, allocations, cursor=None):
    with db.atomic():
        # Pulizia sicura delle vecchie allocazioni per questa produzione
        ProduzioneLatteGruppi.delete().where(ProduzioneLatteGruppi.user == user_id, ProduzioneLatteGruppi.produzione == produzione_id).execute()
        now = datetime.now().isoformat(timespec="seconds")
        
        # Supporta sia dizionari che liste di tuple per retrocompatibilità
        iterable = allocations.items() if isinstance(allocations, dict) else allocations
        for item in iterable:
            entry_id, litri = (item.get("animale_entry_id"), item.get("litri")) if isinstance(item, dict) else (item[0], item[1])
            
            if _to_non_negative_int(entry_id) > 0 and float(litri) > 0:
                ProduzioneLatteGruppi.create(
                    user=user_id, produzione=produzione_id, movimento=movimento_id, 
                    animale_entry=entry_id, litri=float(litri), created_at=now, updated_at=now
                )

def get_produzione_latte_group_allocations(user_id: int, produzione_id: int) -> dict[int, float]:
    # Metodo super-efficiente in una riga (Dictionary Comprehension)
    return {
        p.animale_entry_id: p.litri 
        for p in ProduzioneLatteGruppi.select().where(ProduzioneLatteGruppi.user == user_id, ProduzioneLatteGruppi.produzione == produzione_id)
    }

def upsert_azienda_animali_nascite_media(user_id: int, tipo_animale: str, altro_label: str, rapporto_nascite_genitori: float, cursor=None) -> dict:
    tipo = _normalize_tipo_animale(tipo_animale)
    altro = (altro_label or "").strip()
    now = datetime.now().isoformat(timespec="seconds")
    
    with db.atomic():
        entry, created = AziendaAnimaliNasciteMedia.get_or_create(user=user_id, tipo_animale=tipo, altro_label=altro)
        
        # Calcolo della media mobile
        nuovi_campioni = entry.campioni + 1
        entry.media_nascite_per_capo = ((entry.media_nascite_per_capo * entry.campioni) + float(rapporto_nascite_genitori)) / nuovi_campioni
        entry.campioni = nuovi_campioni
        entry.updated_at = now
        entry.save()
        
        return {
            "tipo_animale": tipo, "altro_label": altro, 
            "media_nascite_per_capo": entry.media_nascite_per_capo, 
            "campioni": entry.campioni, "updated_at": now
        }

def list_azienda_animali_nascite_media(user_id: int) -> list[dict]:
    return list(AziendaAnimaliNasciteMedia.select().where(AziendaAnimaliNasciteMedia.user == user_id, AziendaAnimaliNasciteMedia.campioni > 0).dicts())

# ==========================================
# 6. COLLEGAMENTI MOVIMENTI <-> ANIMALI
# ==========================================

def set_movimento_animali_links(user_id: int, movimento_id: int, animale_entry_ids, cursor=None):
    with db.atomic():
        MovimentiAnimaliLink.delete().where(MovimentiAnimaliLink.user == user_id, MovimentiAnimaliLink.movimento == movimento_id).execute()
        now = datetime.now().isoformat(timespec="seconds")
        
        for e_id in animale_entry_ids:
            if _to_non_negative_int(e_id) > 0:
                MovimentiAnimaliLink.create(user=user_id, movimento=movimento_id, animale_entry=e_id, created_at=now)

def get_movimento_animali_entry_ids(user_id: int, movimento_id: int) -> list[int]:
    # List comprehension velocissima
    return [
        link.animale_entry_id 
        for link in MovimentiAnimaliLink.select().where(MovimentiAnimaliLink.user == user_id, MovimentiAnimaliLink.movimento == movimento_id)
    ]

def get_movimento_animali_group_labels(user_id: int, movimento_id: int) -> list[str]:
    # Sostituisce la vecchia INNER JOIN in SQL stringa
    links = MovimentiAnimaliLink.select(MovimentiAnimaliLink, AziendaAnimaliDettaglio).join(AziendaAnimaliDettaglio).where(
        MovimentiAnimaliLink.user == user_id, MovimentiAnimaliLink.movimento == movimento_id
    )
    
    labels = []
    for link in links:
        g = link.animale_entry
        nome = g.group_name or _default_group_name(g.tipo_animale, g.finalita, g.altro_label)
        labels.append(f"{nome} ({g.tipo_animale.title()}, {g.finalita.title() or 'N/D'}, {g.capi} capi)")
    return labels

# ==========================================
# 7. CRM: ANAGRAFICA SOGGETTI
# ==========================================

def add_soggetto(user_id, tipo, ragione_sociale, partita_iva="", codice_fiscale="", indirizzo="", email="", telefono="", note=""):
    now = datetime.now().isoformat(timespec="seconds")
    return Anagrafica.insert(
        user=user_id, tipo=tipo, ragione_sociale=ragione_sociale, partita_iva=partita_iva,
        codice_fiscale=codice_fiscale, indirizzo=indirizzo, email=email, telefono=telefono,
        note=note, created_at=now, updated_at=now
    ).execute()

def update_soggetto(user_id, soggetto_id, tipo, ragione_sociale, partita_iva="", codice_fiscale="", indirizzo="", email="", telefono="", note=""):
    return Anagrafica.update(
        tipo=tipo, ragione_sociale=ragione_sociale, partita_iva=partita_iva, codice_fiscale=codice_fiscale,
        indirizzo=indirizzo, email=email, telefono=telefono, note=note, updated_at=datetime.now().isoformat(timespec="seconds")
    ).where(Anagrafica.id == soggetto_id, Anagrafica.user == user_id).execute() > 0

def delete_soggetto(user_id, soggetto_id):
    return Anagrafica.delete().where(Anagrafica.id == soggetto_id, Anagrafica.user == user_id).execute() > 0

def list_soggetti(user_id):
    return list(Anagrafica.select().where(Anagrafica.user == user_id).order_by(Anagrafica.ragione_sociale).dicts())

# ==========================================
# 8. MACCHINARI E MANUTENZIONI
# ==========================================

def list_macchinari_entries(user_id: int) -> list[dict]:
    return list(Macchinario.select().where(Macchinario.user == user_id).order_by(Macchinario.nome).dicts())

def add_macchinario_entry(user_id: int, nome: str, marca: str = "", modello: str = "", identificativo: str = "", anno=None, note: str = "") -> int:
    return Macchinario.insert(
        user=user_id, nome=nome.strip(), marca=marca.strip(), modello=modello.strip(),
        identificativo=identificativo.strip(), anno=anno, note=note.strip(),
        created_at=datetime.now().isoformat(timespec="seconds"), updated_at=datetime.now().isoformat(timespec="seconds")
    ).execute()

def update_macchinario_entry(user_id: int, macchinario_id: int, nome: str, marca: str = "", modello: str = "", identificativo: str = "", anno=None, note: str = "") -> bool:
    return Macchinario.update(
        nome=nome.strip(), marca=marca.strip(), modello=modello.strip(),
        identificativo=identificativo.strip(), anno=anno, note=note.strip(),
        updated_at=datetime.now().isoformat(timespec="seconds")
    ).where(Macchinario.id == macchinario_id, Macchinario.user == user_id).execute() > 0

def delete_macchinario_entry(user_id: int, macchinario_id: int) -> int:
    # Nota: il CASCADE in models.py elimina automaticamente anche le manutenzioni collegate!
    return Macchinario.delete().where(Macchinario.id == macchinario_id, Macchinario.user == user_id).execute()

def list_manutenzioni_macchinari_entries(user_id: int, macchinario_id: int = None) -> list[dict]:
    # Unisce la tabella Macchinari per avere il nome e l'identificativo nella UI
    query = ManutenzioneMacchinario.select(
        ManutenzioneMacchinario, 
        Macchinario.nome.alias('macchinario_nome'), 
        Macchinario.identificativo.alias('macchinario_identificativo')
    ).join(Macchinario).where(ManutenzioneMacchinario.user == user_id)
    
    if macchinario_id: 
        query = query.where(ManutenzioneMacchinario.macchinario == macchinario_id)
        
    return list(query.order_by(ManutenzioneMacchinario.data_manutenzione.desc()).dicts())

def add_manutenzione_macchinario_entry(user_id, macchinario_id, data_manutenzione, tipo_manutenzione, descrizione, costo=None, fornitore="", note=""):
    return ManutenzioneMacchinario.insert(
        user=user_id, macchinario=macchinario_id, data_manutenzione=data_manutenzione,
        tipo_manutenzione=tipo_manutenzione.upper(), descrizione=descrizione, costo=costo,
        fornitore=fornitore, note=note, 
        created_at=datetime.now().isoformat(timespec="seconds"), updated_at=datetime.now().isoformat(timespec="seconds")
    ).execute()

def delete_manutenzione_macchinario_entry(user_id: int, manutenzione_id: int) -> bool:
    return ManutenzioneMacchinario.delete().where(ManutenzioneMacchinario.id == manutenzione_id, ManutenzioneMacchinario.user == user_id).execute() > 0

# ==========================================
# 9. STORICO EVENTI ANIMALI (LETTURA E CANCELLAZIONE)
# ==========================================

def list_azienda_animali_storico_entries(user_id: int, limit: int = 300) -> list[dict]:
    return list(AziendaAnimaliStorico.select().where(AziendaAnimaliStorico.user == user_id).order_by(AziendaAnimaliStorico.event_time.desc()).limit(limit).dicts())

def delete_azienda_animali_storico_entry(user_id: int, storico_id: int) -> bool:
    return AziendaAnimaliStorico.delete().where(AziendaAnimaliStorico.id == storico_id, AziendaAnimaliStorico.user == user_id).execute() > 0


# ==========================================
# 10. MOVIMENTI ECONOMICI
# ==========================================

def list_movimenti(user_id: int) -> list[dict]:
    return list(Movimento.select().where(Movimento.user == user_id).order_by(Movimento.data_op.desc()).dicts())

def add_movimento(user_id, data_op, tipo, categoria, descrizione, importo, iva_importo=0.0, stato_pagamento="PAGATO", parser_kwargs=None):
    pk = parser_kwargs or {}
    return Movimento.insert(
        user=user_id, data_op=data_op, tipo=tipo, categoria=categoria, descrizione=descrizione,
        importo=importo, iva_importo=iva_importo, stato_pagamento=stato_pagamento, **pk
    ).execute()

def update_movimento(user_id, movimento_id, data_op, tipo, categoria, descrizione, importo, iva_importo=0.0, stato_pagamento="PAGATO"):
    return Movimento.update(
        data_op=data_op, tipo=tipo, categoria=categoria, descrizione=descrizione,
        importo=importo, iva_importo=iva_importo, stato_pagamento=stato_pagamento
    ).where(Movimento.id == movimento_id, Movimento.user == user_id).execute() > 0

def delete_movimento(user_id, movimento_id):
    # Grazie a Peewee (CASCADE), si cancellano automaticamente i link_animali e si mette a NULL l'id nelle fatture
    return Movimento.delete().where(Movimento.id == movimento_id, Movimento.user == user_id).execute() > 0

# ==========================================
# 11. PRODUZIONE LATTE E CARNE (CRUD Base)
# ==========================================

def list_produzione_latte(user_id: int) -> list[dict]:
    return list(ProduzioneLatte.select().where(ProduzioneLatte.user == user_id).order_by(ProduzioneLatte.data_op.desc()).dicts())

def add_produzione_latte(user_id, data_op, litri, prezzo_litro, movimento_id=None):
    return ProduzioneLatte.insert(user=user_id, data_op=data_op, litri=litri, prezzo_litro=prezzo_litro, movimento=movimento_id).execute()

def delete_produzione_latte(user_id, produzione_id):
    return ProduzioneLatte.delete().where(ProduzioneLatte.id == produzione_id, ProduzioneLatte.user == user_id).execute() > 0

def list_produzione_carne(user_id: int) -> list[dict]:
    return list(ProduzioneCarne.select().where(ProduzioneCarne.user == user_id).order_by(ProduzioneCarne.data_op.desc()).dicts())

def add_produzione_carne(user_id, data_op, kg, prezzo_kg, movimento_id=None):
    return ProduzioneCarne.insert(user=user_id, data_op=data_op, kg=kg, prezzo_kg=prezzo_kg, movimento=movimento_id).execute()

def delete_produzione_carne(user_id, produzione_id):
    return ProduzioneCarne.delete().where(ProduzioneCarne.id == produzione_id, ProduzioneCarne.user == user_id).execute() > 0

# ==========================================
# 12. FATTURE E FILE ALLEGATI
# ==========================================

def save_fattura_record(user_id, origine, movimento_id, produzione_id, nome_originale, percorso_file, data_caricamento):
    return Fattura.insert(
        user=user_id, origine=origine, movimento=movimento_id, produzione=produzione_id,
        nome_originale=nome_originale, percorso_file=percorso_file, data_caricamento=data_caricamento
    ).execute()

def get_fatture_by_movimento(user_id, movimento_id):
    return list(Fattura.select().where(Fattura.movimento == movimento_id, Fattura.user == user_id).dicts())

def get_fattura_by_id(user_id, fattura_id):
    return Fattura.select().where(Fattura.id == fattura_id, Fattura.user == user_id).dicts().first()

def delete_fattura_record(user_id, fattura_id):
    return Fattura.delete().where(Fattura.id == fattura_id, Fattura.user == user_id).execute() > 0

# ==========================================
# 13. AGRICOLTURA 4.0, CAMPI E METEO
# ==========================================

def list_campi_agricoli(user_id):
    return list(CampoAgricolo.select().where(CampoAgricolo.user == user_id).order_by(CampoAgricolo.nome).dicts())

def add_campo_agricolo(user_id, nome, area_ettari, geojson="", colore="", tipo_campo="Seminativo", varieta="", num_piante=0, anno_impianto=0):
    now = datetime.now().isoformat(timespec="seconds")
    return CampoAgricolo.insert(
        user=user_id, nome=nome, area_ettari=area_ettari, geojson=geojson, colore=colore, 
        tipo_campo=tipo_campo, varieta=varieta, num_piante=num_piante, anno_impianto=anno_impianto, 
        created_at=now, updated_at=now
    ).execute()

def update_campo_agricolo(user_id, campo_id, nome, area_ettari, geojson="", colore="", tipo_campo="", varieta="", num_piante=0, anno_impianto=0):
    return CampoAgricolo.update(
        nome=nome, area_ettari=area_ettari, geojson=geojson, colore=colore, 
        tipo_campo=tipo_campo, varieta=varieta, num_piante=num_piante, anno_impianto=anno_impianto, 
        updated_at=datetime.now().isoformat(timespec="seconds")
    ).where(CampoAgricolo.id == campo_id, CampoAgricolo.user == user_id).execute() > 0

def delete_campo_agricolo(user_id, campo_id):
    return CampoAgricolo.delete().where(CampoAgricolo.id == campo_id, CampoAgricolo.user == user_id).execute() > 0

# ==========================================
# 14. STORICO COLTURE
# ==========================================

def list_storico_colture(user_id: int, campo_id: int = None) -> list[dict]:
    query = StoricoColtura.select().where(StoricoColtura.user == user_id)
    if campo_id: 
        query = query.where(StoricoColtura.campo == campo_id)
    return list(query.order_by(StoricoColtura.data_semina.desc()).dicts())

def add_storico_coltura(user_id: int, campo_id: int, coltura: str, data_semina: str = "", data_raccolto: str = "", resa_quintali: float = 0.0, note: str = ""):
    now = datetime.now().isoformat(timespec="seconds")
    return StoricoColtura.insert(
        user=user_id, campo=campo_id, coltura=coltura, data_semina=data_semina, 
        data_raccolto=data_raccolto, resa_quintali=resa_quintali, note=note, 
        created_at=now, updated_at=now
    ).execute()

def update_storico_coltura(user_id: int, storico_id: int, coltura: str, data_semina: str = "", data_raccolto: str = "", resa_quintali: float = 0.0, note: str = "") -> bool:
    return StoricoColtura.update(
        coltura=coltura, data_semina=data_semina, data_raccolto=data_raccolto, 
        resa_quintali=resa_quintali, note=note, updated_at=datetime.now().isoformat(timespec="seconds")
    ).where(StoricoColtura.id == storico_id, StoricoColtura.user == user_id).execute() > 0

def delete_storico_coltura(user_id: int, storico_id: int) -> bool:
    # Il CASCADE eliminerà automaticamente l'economia collegata a questa coltura
    return StoricoColtura.delete().where(StoricoColtura.id == storico_id, StoricoColtura.user == user_id).execute() > 0

# ==========================================
# 15. ECONOMIA COLTURE
# ==========================================

def list_economia_colture(user_id: int, storico_id: int = None) -> list[dict]:
    query = EconomiaColtura.select().where(EconomiaColtura.user == user_id)
    if storico_id: 
        query = query.where(EconomiaColtura.storico == storico_id)
    return list(query.order_by(EconomiaColtura.data_operazione.desc()).dicts())

def add_economia_coltura(user_id: int, storico_id: int, tipo: str, categoria: str, descrizione: str, importo: float, data_operazione: str):
    return EconomiaColtura.insert(
        user=user_id, storico=storico_id, tipo=tipo, categoria=categoria, 
        descrizione=descrizione, importo=importo, data_operazione=data_operazione, 
        created_at=datetime.now().isoformat(timespec="seconds")
    ).execute()

def update_economia_coltura(user_id: int, economia_id: int, tipo: str, categoria: str, descrizione: str, importo: float, data_operazione: str) -> bool:
    return EconomiaColtura.update(
        tipo=tipo, categoria=categoria, descrizione=descrizione, 
        importo=importo, data_operazione=data_operazione
    ).where(EconomiaColtura.id == economia_id, EconomiaColtura.user == user_id).execute() > 0

def delete_economia_coltura(user_id: int, economia_id: int) -> bool:
    return EconomiaColtura.delete().where(EconomiaColtura.id == economia_id, EconomiaColtura.user == user_id).execute() > 0

# ==========================================
# 16. REGISTRO METEO
# ==========================================

def list_registro_meteo(user_id: int) -> list[dict]:
    return list(RegistroMeteo.select().where(RegistroMeteo.user == user_id).order_by(RegistroMeteo.data_rilevazione.desc()).dicts())

def add_registro_meteo(user_id: int, data_rilevazione: str, pioggia_mm: float = 0.0, temperatura_max: float = None, temperatura_min: float = None):
    return RegistroMeteo.insert(
        user=user_id, data_rilevazione=data_rilevazione, pioggia_mm=pioggia_mm, 
        temperatura_max=temperatura_max, temperatura_min=temperatura_min
    ).execute()

def update_registro_meteo(user_id: int, meteo_id: int, data_rilevazione: str, pioggia_mm: float = 0.0, temperatura_max: float = None, temperatura_min: float = None) -> bool:
    return RegistroMeteo.update(
        data_rilevazione=data_rilevazione, pioggia_mm=pioggia_mm, 
        temperatura_max=temperatura_max, temperatura_min=temperatura_min
    ).where(RegistroMeteo.id == meteo_id, RegistroMeteo.user == user_id).execute() > 0

def delete_registro_meteo(user_id: int, meteo_id: int) -> bool:
    return RegistroMeteo.delete().where(RegistroMeteo.id == meteo_id, RegistroMeteo.user == user_id).execute() > 0






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