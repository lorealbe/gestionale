import os
from pathlib import Path
from peewee import *

APP_NAME = "Gestionale"
DB_NAME = "gestionale.db"
DATA_ROOT = Path(os.getenv("APPDATA", str(Path.home()))) / APP_NAME
DB_PATH = DATA_ROOT / DB_NAME

# Connessione al database SQLite con Foreign Keys attive (1 riga)
db = SqliteDatabase(str(DB_PATH), pragmas={'foreign_keys': 1})

class BaseModel(Model):
    class Meta:
        database = db

# --- AUTENTICAZIONE E PROFILI ---

class Utente(BaseModel):
    username = CharField(unique=True)
    password_hash = CharField()
    class Meta:
        table_name = 'utenti'

class Profilo(BaseModel):
    user = ForeignKeyField(Utente, primary_key=True, column_name='user_id', on_delete='CASCADE', backref='profilo')
    nome = CharField(null=True)
    piva = CharField(null=True)
    professione = CharField(null=True)
    class Meta:
        table_name = 'profili'

class AziendaInfo(BaseModel):
    user = ForeignKeyField(Utente, primary_key=True, column_name='user_id', on_delete='CASCADE', backref='azienda_info')
    nome_azienda = CharField(default='')
    piva = CharField(default='')
    occupazione = CharField(default='')
    data_creazione = CharField(default='')
    updated_at = CharField(default='')
    class Meta:
        table_name = 'azienda_info'

# --- CRM (ANAGRAFICA SOGGETTI) ---

class Anagrafica(BaseModel):
    user = ForeignKeyField(Utente, column_name='user_id', on_delete='CASCADE', backref='anagrafiche')
    tipo = CharField(default='Fornitore')
    ragione_sociale = CharField()
    partita_iva = CharField(null=True)
    codice_fiscale = CharField(null=True)
    indirizzo = CharField(null=True)
    email = CharField(null=True)
    telefono = CharField(null=True)
    note = TextField(null=True)
    created_at = CharField(null=True)
    updated_at = CharField(null=True)
    class Meta:
        table_name = 'anagrafica'

# --- ZOOTECNIA (CONFIGURAZIONE GLOBALE E DETTAGLI) ---

class AziendaAnimali(BaseModel):
    user = ForeignKeyField(Utente, primary_key=True, column_name='user_id', on_delete='CASCADE', backref='azienda_animali')
    bovini = IntegerField(default=0)
    bovini_capi = IntegerField(default=0)
    ovini = IntegerField(default=0)
    ovini_capi = IntegerField(default=0)
    caprini = IntegerField(default=0)
    caprini_capi = IntegerField(default=0)
    altro_text = CharField(default='')
    altro_capi = IntegerField(default=0)
    updated_at = CharField(default='')
    class Meta:
        table_name = 'azienda_animali'

class AziendaAnimaliDettaglio(BaseModel):
    user = ForeignKeyField(Utente, column_name='user_id', on_delete='CASCADE')
    tipo_animale = CharField()
    finalita = CharField(default='')
    altro_label = CharField(default='')
    group_name = CharField(default='')
    riproduzione = IntegerField(default=0)
    capi = IntegerField(default=0)
    created_at = CharField(default='')
    updated_at = CharField(default='')
    merged_into_entry_id = IntegerField(null=True)
    merge_date = CharField(default='')
    class Meta:
        table_name = 'azienda_animali_dettaglio'
        indexes = ((('user', 'tipo_animale', 'finalita', 'altro_label', 'group_name'), True),)

class AziendaAnimaliStorico(BaseModel):
    user = ForeignKeyField(Utente, column_name='user_id', on_delete='CASCADE')
    event_type = CharField(default='')
    event_time = CharField(default='')
    gruppo_entry_id = IntegerField(null=True)
    gruppo_nome = CharField(default='')
    tipo_animale = CharField(default='')
    finalita = CharField(default='')
    capi_prima = IntegerField(null=True)
    capi_variazione = IntegerField(default=0)
    capi_dopo = IntegerField(null=True)
    gruppo_correlato_entry_id = IntegerField(null=True)
    gruppo_correlato_nome = CharField(default='')
    note = CharField(default='')
    class Meta:
        table_name = 'azienda_animali_storico'

class AziendaAnimaliNasciteMedia(BaseModel):
    user = ForeignKeyField(Utente, column_name='user_id', on_delete='CASCADE')
    tipo_animale = CharField()
    altro_label = CharField(default='')
    media_nascite_per_capo = DoubleField(default=0.0)
    campioni = IntegerField(default=0)
    updated_at = CharField(default='')
    class Meta:
        table_name = 'azienda_animali_nascite_media'
        indexes = ((('user', 'tipo_animale', 'altro_label'), True),)

# --- CONTABILITÀ E MOVIMENTI ---

class Movimento(BaseModel):
    user = ForeignKeyField(Utente, column_name='user_id', on_delete='CASCADE', backref='movimenti')
    data_op = CharField()
    tipo = CharField()  # ENTRATA, USCITA
    categoria = CharField(null=True)
    descrizione = CharField(null=True)
    importo = DoubleField()
    iva_importo = DoubleField(default=0.0)
    stato_pagamento = CharField(default='PAGATO')
    economia_colture_id = IntegerField(null=True)
    
    # Campi estratti dal Parser 
    parser_invoice_number = CharField(null=True)
    parser_invoice_date = CharField(null=True)
    parser_due_date = CharField(null=True)
    parser_supplier_name = CharField(null=True)
    parser_supplier_vat = CharField(null=True)
    parser_customer_name = CharField(null=True)
    parser_customer_vat = CharField(null=True)
    parser_total_amount = CharField(null=True)
    parser_taxable_total = CharField(null=True)
    parser_vat_total = CharField(null=True)
    parser_payment_terms = CharField(null=True)
    parser_warnings = CharField(null=True)
    parser_products = CharField(null=True)
    parser_fields_view = CharField(null=True)
    class Meta:
        table_name = 'movimenti'

class MovimentiAnimaliLink(BaseModel):
    user = ForeignKeyField(Utente, column_name='user_id', on_delete='CASCADE')
    movimento = ForeignKeyField(Movimento, column_name='movimento_id', on_delete='CASCADE')
    animale_entry = ForeignKeyField(AziendaAnimaliDettaglio, column_name='animale_entry_id', on_delete='CASCADE')
    created_at = CharField(default='')
    class Meta:
        table_name = 'movimenti_animali_link'
        indexes = ((('user', 'movimento', 'animale_entry'), True),)

# --- PRODUZIONE (LATTE E CARNE) ---

class ProduzioneLatte(BaseModel):
    user = ForeignKeyField(Utente, column_name='user_id', on_delete='CASCADE')
    data_op = CharField()
    litri = DoubleField()
    prezzo_litro = DoubleField(default=0.0)
    movimento = ForeignKeyField(Movimento, column_name='movimento_id', on_delete='SET NULL', null=True)
    class Meta:
        table_name = 'produzione_latte'

class ProduzioneLatteGruppi(BaseModel):
    user = ForeignKeyField(Utente, column_name='user_id', on_delete='CASCADE')
    produzione = ForeignKeyField(ProduzioneLatte, column_name='produzione_id', on_delete='CASCADE')
    movimento = ForeignKeyField(Movimento, column_name='movimento_id', on_delete='SET NULL', null=True)
    animale_entry = ForeignKeyField(AziendaAnimaliDettaglio, column_name='animale_entry_id', on_delete='CASCADE')
    litri = DoubleField()
    created_at = CharField(default='')
    updated_at = CharField(default='')
    class Meta:
        table_name = 'produzione_latte_gruppi'
        indexes = ((('user', 'produzione', 'animale_entry'), True),)

class ProduzioneCarne(BaseModel):
    user = ForeignKeyField(Utente, column_name='user_id', on_delete='CASCADE')
    data_op = CharField()
    kg = DoubleField()
    prezzo_kg = DoubleField(default=0.0)
    movimento = ForeignKeyField(Movimento, column_name='movimento_id', on_delete='SET NULL', null=True)
    class Meta:
        table_name = 'produzione_carne'

# --- FILE E FATTURE ALLEGATE ---

class Fattura(BaseModel):
    user = ForeignKeyField(Utente, column_name='user_id', on_delete='CASCADE')
    origine = CharField()
    movimento = ForeignKeyField(Movimento, column_name='movimento_id', on_delete='SET NULL', null=True)
    produzione = ForeignKeyField(ProduzioneLatte, column_name='produzione_id', on_delete='SET NULL', null=True)
    nome_originale = CharField()
    percorso_file = CharField()
    data_caricamento = CharField()
    class Meta:
        table_name = 'fatture'

# --- AGRICOLTURA 4.0, METEO E CAMPI ---

class CampoAgricolo(BaseModel):
    user = ForeignKeyField(Utente, column_name='user_id', on_delete='CASCADE')
    nome = CharField()
    area_ettari = DoubleField(default=0.0)
    geojson = TextField(default='')
    colore = CharField(default='#3388ff')
    created_at = CharField(default='')
    updated_at = CharField(default='')
    tipo_campo = CharField(default='Seminativo')
    varieta = CharField(default='')
    num_piante = IntegerField(default=0)
    anno_impianto = IntegerField(default=0)
    class Meta:
        table_name = 'campi_agricoli'

class StoricoColtura(BaseModel):
    user = ForeignKeyField(Utente, column_name='user_id', on_delete='CASCADE')
    campo = ForeignKeyField(CampoAgricolo, column_name='campo_id', on_delete='CASCADE')
    coltura = CharField()
    data_semina = CharField(default='')
    data_raccolto = CharField(default='')
    resa_quintali = DoubleField(default=0.0)
    note = TextField(default='')
    created_at = CharField(default='')
    updated_at = CharField(default='')
    class Meta:
        table_name = 'storico_colture'

class EconomiaColtura(BaseModel):
    user = ForeignKeyField(Utente, column_name='user_id', on_delete='CASCADE')
    storico = ForeignKeyField(StoricoColtura, column_name='storico_id', on_delete='CASCADE')
    tipo = CharField()
    categoria = CharField()
    descrizione = CharField(null=True)
    importo = DoubleField()
    data_operazione = CharField()
    created_at = CharField()
    class Meta:
        table_name = 'economia_colture'

class RegistroMeteo(BaseModel):
    user = ForeignKeyField(Utente, column_name='user_id', on_delete='CASCADE')
    data_rilevazione = CharField()
    pioggia_mm = DoubleField(default=0.0)
    temperatura_max = DoubleField(null=True)
    temperatura_min = DoubleField(null=True)
    class Meta:
        table_name = 'registro_meteo'

# --- MACCHINARI E MANUTENZIONI ---

class Macchinario(BaseModel):
    user = ForeignKeyField(Utente, column_name='user_id', on_delete='CASCADE')
    nome = CharField()
    marca = CharField(default='')
    modello = CharField(default='')
    identificativo = CharField(default='')
    anno = IntegerField(null=True)
    note = TextField(default='')
    created_at = CharField(default='')
    updated_at = CharField(default='')
    class Meta:
        table_name = 'macchinari'

class ManutenzioneMacchinario(BaseModel):
    user = ForeignKeyField(Utente, column_name='user_id', on_delete='CASCADE')
    macchinario = ForeignKeyField(Macchinario, column_name='macchinario_id', on_delete='CASCADE')
    data_manutenzione = CharField()
    tipo_manutenzione = CharField(default='ORDINARIA')
    descrizione = CharField(default='')
    costo = DoubleField(null=True)
    fornitore = CharField(default='')
    note = TextField(default='')
    created_at = CharField(default='')
    updated_at = CharField(default='')
    class Meta:
        table_name = 'manutenzioni_macchinari'


# --- FUNZIONE DI INIZIALIZZAZIONE ---

def init_tables():
    # Elenco ordinato di modelli (quelli dipendenti dalle foreign key per ultimi)
    modelli = [
        Utente, Profilo, AziendaInfo, Anagrafica, AziendaAnimali, 
        AziendaAnimaliDettaglio, AziendaAnimaliStorico, AziendaAnimaliNasciteMedia,
        Movimento, MovimentiAnimaliLink, ProduzioneLatte, ProduzioneLatteGruppi,
        ProduzioneCarne, Fattura, CampoAgricolo, StoricoColtura,
        EconomiaColtura, RegistroMeteo, Macchinario, ManutenzioneMacchinario
    ]
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    db.create_tables(modelli, safe=True)