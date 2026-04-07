from app_utils import parse_decimal
from database import LITRI_PER_QUINTALE


def ripartizione_litri_produzione_per_gruppo(litri_totali, linked_ids, allocazioni_esplicite, capi_map):
    litri = float(litri_totali or 0)
    if litri <= 0:
        return {}

    ids = []
    seen = set()
    for raw_id in linked_ids or []:
        try:
            entry_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if entry_id <= 0 or entry_id in seen:
            continue
        ids.append(entry_id)
        seen.add(entry_id)

    if not ids:
        return {}
    if len(ids) == 1:
        return {ids[0]: litri}

    quote_esplicite = {}
    for entry_id, raw_litri in (allocazioni_esplicite or {}).items():
        try:
            normalized_id = int(entry_id)
        except (TypeError, ValueError):
            continue
        if normalized_id not in seen:
            continue

        litri_value = parse_decimal(raw_litri, allow_zero=True, allow_negative=False)
        if litri_value is None or litri_value <= 0:
            continue
        quote_esplicite[normalized_id] = float(litri_value)

    risultato = {entry_id: 0.0 for entry_id in ids}
    totale_esplicito = sum(quote_esplicite.values())
    if totale_esplicito > litri and totale_esplicito > 0:
        fattore = litri / totale_esplicito
        for entry_id, litri_value in quote_esplicite.items():
            risultato[entry_id] = litri_value * fattore
        totale_esplicito = litri
    else:
        for entry_id, litri_value in quote_esplicite.items():
            risultato[entry_id] = litri_value

    litri_residui = max(litri - totale_esplicito, 0.0)
    ids_senza_esplicita = [entry_id for entry_id in ids if entry_id not in quote_esplicite]

    if litri_residui > 0:
        if ids_senza_esplicita:
            somma_capi = sum(max(int(capi_map.get(entry_id, 0) or 0), 0) for entry_id in ids_senza_esplicita)
            if somma_capi > 0:
                for entry_id in ids_senza_esplicita:
                    capi = max(int(capi_map.get(entry_id, 0) or 0), 0)
                    risultato[entry_id] += litri_residui * (capi / somma_capi)
            else:
                quota = litri_residui / len(ids_senza_esplicita)
                for entry_id in ids_senza_esplicita:
                    risultato[entry_id] += quota
        else:
            base_ids = [entry_id for entry_id in ids if risultato.get(entry_id, 0.0) > 0]
            if not base_ids:
                base_ids = ids
            quota = litri_residui / len(base_ids)
            for entry_id in base_ids:
                risultato[entry_id] += quota

    total_assigned = sum(risultato.values())
    if ids and abs(total_assigned - litri) > 1e-6:
        risultato[ids[0]] += litri - total_assigned

    return {entry_id: value for entry_id, value in risultato.items() if value > 0}


def costruisci_quote_litri_produzioni(produzione_rows, link_map, allocazioni_esplicite_map, capi_map):
    quote_per_produzione = {}
    quote_litri_per_movimento = {}

    for produzione_id_raw, movimento_id_raw, litri_raw, _prezzo_raw in produzione_rows:
        try:
            produzione_id = int(produzione_id_raw or 0)
            movimento_id = int(movimento_id_raw or 0)
        except (TypeError, ValueError):
            continue

        if produzione_id <= 0 or movimento_id <= 0:
            continue

        linked_ids = link_map.get(movimento_id, [])
        if not linked_ids:
            continue

        allocazioni_esplicite = allocazioni_esplicite_map.get(produzione_id, {})
        quote = ripartizione_litri_produzione_per_gruppo(
            litri_raw,
            linked_ids,
            allocazioni_esplicite,
            capi_map,
        )
        if not quote:
            continue

        quote_per_produzione[produzione_id] = quote
        movimento_quote = quote_litri_per_movimento.setdefault(movimento_id, {})
        for entry_id, litri_value in quote.items():
            movimento_quote[entry_id] = movimento_quote.get(entry_id, 0.0) + float(litri_value)

    quote_ratio_per_movimento = {}
    for movimento_id, litri_map in quote_litri_per_movimento.items():
        totale_litri_mov = sum(float(v or 0) for v in litri_map.values())
        if totale_litri_mov <= 0:
            continue
        quote_ratio_per_movimento[movimento_id] = {
            entry_id: float(litri_value) / totale_litri_mov
            for entry_id, litri_value in litri_map.items()
            if float(litri_value or 0) > 0
        }

    return quote_per_produzione, quote_ratio_per_movimento


def calcola_metriche_latte_da_totali(
    *,
    periodo,
    movimenti_estratti,
    qta_produzioni,
    tot_entrate,
    tot_uscite,
    totale_iva,
    tot_litri,
    totale_valore_latte,
    totale_capi=0,
    totale_costi_fissi=0.0,
    totale_costi_variabili=0.0,
):
    saldo = tot_entrate - tot_uscite

    giorni_periodo = (periodo["fine"] - periodo["inizio"]).days + 1
    media_litri_giorno = (tot_litri / giorni_periodo) if giorni_periodo > 0 else 0.0
    media_litri_registrazione = (tot_litri / qta_produzioni) if qta_produzioni > 0 else 0.0

    tot_quintali = tot_litri / LITRI_PER_QUINTALE
    media_quintali_giorno = media_litri_giorno / LITRI_PER_QUINTALE
    media_quintali_registrazione = media_litri_registrazione / LITRI_PER_QUINTALE
    prezzo_medio_litro = (totale_valore_latte / tot_litri) if tot_litri > 0 else 0.0
    costo_produzione_litro = (tot_uscite / tot_litri) if tot_litri > 0 else 0.0
    utile_litro = (saldo / tot_litri) if tot_litri > 0 else 0.0
    media_litri_per_capo_giorno = (media_litri_giorno / totale_capi) if totale_capi > 0 else 0.0
    incidenza_costi_fissi_pct = (totale_costi_fissi / tot_uscite * 100.0) if tot_uscite > 0 else 0.0
    incidenza_costi_variabili_pct = (totale_costi_variabili / tot_uscite * 100.0) if tot_uscite > 0 else 0.0

    return {
        "periodo": f"{periodo['inizio'].strftime('%d/%m/%Y')} - {periodo['fine'].strftime('%d/%m/%Y')}",
        "movimenti_estratti": int(movimenti_estratti or 0),
        "qta_produzioni": int(qta_produzioni or 0),
        "tot_entrate": float(tot_entrate or 0),
        "tot_uscite": float(tot_uscite or 0),
        "totale_iva": float(totale_iva or 0),
        "totale_capi": int(totale_capi or 0),
        "totale_costi_fissi": float(totale_costi_fissi or 0),
        "totale_costi_variabili": float(totale_costi_variabili or 0),
        "incidenza_costi_fissi_pct": incidenza_costi_fissi_pct,
        "incidenza_costi_variabili_pct": incidenza_costi_variabili_pct,
        "saldo": float(saldo or 0),
        "tot_quintali": tot_quintali,
        "tot_litri": float(tot_litri or 0),
        "media_litri_per_capo_giorno": media_litri_per_capo_giorno,
        "media_quintali_giorno": media_quintali_giorno,
        "media_quintali_registrazione": media_quintali_registrazione,
        "prezzo_medio_litro": prezzo_medio_litro,
        "costo_produzione_litro": costo_produzione_litro,
        "utile_litro": utile_litro,
    }
