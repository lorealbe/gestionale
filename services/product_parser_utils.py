import re
from app_utils import parse_decimal

PRODUCT_ROW_PATTERN = re.compile(
    r"^(?P<description>.*?)\s*-\s*qta\s+(?P<quantity>.*?)(?:\s*-\s*prezzo\s+(?P<price>.*?))?(?:\s*-\s*prezzo_unit\s+(?P<unit_price>.*?))?(?:\s*-\s*iva\s+(?P<vat_rate>.*?))?\s*-\s*tot\s+(?P<line_total>.*?)(?:\s*-\s*costi\s+(?P<cost_type>.*?))?(?:\s*-\s*categoria\s+(?P<category>.*?))?(?:\s*-\s*gruppi\s+(?P<groups>.*))?$",
    re.IGNORECASE,
)

PRODUCT_CATEGORY_OPTIONS = ("Mangimi", "Foraggi", "Integratori", "Veterinaria", "Igiene", "Manutenzione", "Trasporti", "Servizi", "Altro")

def normalize_cost_type(raw_value):
    return "Fissi" if str(raw_value or "").strip().lower().startswith("fiss") else "Variabili"

def normalize_product_category(raw_value):
    text_lower = str(raw_value or "").strip().lower()
    alias_map = {"mangime": "Mangimi", "foraggio": "Foraggi", "integratore": "Integratori", "farmaci": "Veterinaria", "farmaco": "Veterinaria", "sanificazione": "Igiene", "pulizia": "Igiene", "ricambi": "Manutenzione", "trasporto": "Trasporti", "servizio": "Servizi"}
    return next((opt for opt in PRODUCT_CATEGORY_OPTIONS if opt.lower() == text_lower), alias_map.get(text_lower, "Altro"))

def normalize_product_description_for_storage(raw_description):
    return re.sub(r"\s*\n+\s*", " ", str(raw_description or "").strip()).strip() or "-"

def build_basic_product_storage_line(description, quantity_text, total_text):
    return f"{normalize_product_description_for_storage(description)} - qta {quantity_text} - tot {total_text}"

def build_detailed_product_storage_line(description, quantity_text, total_text, cost_type, category_text, groups_text, price_text=None, unit_price_text=None, vat_rate_text=None):
    # Funzione lambda inline per non inserire voci vuote (es. se l'IVA non c'è, non la scrive)
    _p = lambda v, p: f"{p} {v}" if str(v or "").strip() and str(v).strip() != "-" else ""
    
    parts = [
        normalize_product_description_for_storage(description), f"qta {quantity_text}", 
        _p(price_text, "prezzo"), _p(unit_price_text, "prezzo_unit"), _p(vat_rate_text, "iva"),
        f"tot {total_text}", f"costi {cost_type}", f"categoria {normalize_product_category(category_text)}", f"gruppi {groups_text}"
    ]
    return " - ".join(filter(None, parts))

def serialize_product_storage_lines(lines, separator="\n"):
    return str(separator).join(filter(None, (str(line or "").strip() for line in (lines or []))))

def normalize_multiline_display_text(raw_text):
    testo = str(raw_text or "").strip()
    return testo if "\n" in testo else testo.replace(" | ", "\n")

def extract_products_rows_from_parser_text(products_text):
    testo = str(products_text or "").strip()
    if not testo: return []

    righe = []
    testo_norm = testo.replace("\r\n", "\n").replace("\r", "\n")
    blocchi = [b.strip() for b in (testo_norm.split("\n") if "\n" in testo_norm else testo_norm.split(" | ")) if b and b.strip()]

    for blocco in blocchi:
        match = PRODUCT_ROW_PATTERN.match(blocco)
        if not match: continue

        qta = (match.group("quantity") or "").strip() or "-"
        tot = (match.group("line_total") or "").strip() or "-"
        qta_num = parse_decimal(qta, allow_zero=True, allow_negative=False)
        tot_num = parse_decimal(tot, allow_zero=True, allow_negative=False)
        
        if qta_num is None or tot_num is None or qta_num <= 0 or tot_num <= 0: continue

        righe.append({
            "description": (match.group("description") or "").strip() or "-",
            "quantity": qta, "price": (match.group("price") or "").strip() or "-",
            "unit_price": (match.group("unit_price") or "").strip() or "-",
            "vat_rate": (match.group("vat_rate") or "").strip() or "-",
            "line_total": tot, "cost_type": normalize_cost_type(match.group("cost_type")),
            "category": normalize_product_category(match.group("category")),
            "groups": (match.group("groups") or "").strip() or "-"
        })
    return righe