import re

from app_utils import parse_decimal

PRODUCT_ROW_PATTERN = re.compile(
    (
        r"^(?P<description>.*?)\s*-\s*qta\s+(?P<quantity>.*?)"
        r"(?:\s*-\s*prezzo\s+(?P<price>.*?))?"
        r"(?:\s*-\s*prezzo_unit\s+(?P<unit_price>.*?))?"
        r"(?:\s*-\s*iva\s+(?P<vat_rate>.*?))?"
        r"\s*-\s*tot\s+(?P<line_total>.*?)"
        r"(?:\s*-\s*costi\s+(?P<cost_type>.*?))?"
        r"(?:\s*-\s*categoria\s+(?P<category>.*?))?"
        r"(?:\s*-\s*gruppi\s+(?P<groups>.*))?$"
    ),
    re.IGNORECASE,
)

PRODUCT_CATEGORY_OPTIONS = (
    "Mangimi",
    "Foraggi",
    "Integratori",
    "Veterinaria",
    "Igiene",
    "Manutenzione",
    "Trasporti",
    "Servizi",
    "Altro",
)


def normalize_cost_type(raw_value):
    value = str(raw_value or "").strip().lower()
    if value.startswith("fiss"):
        return "Fissi"
    return "Variabili"


def normalize_product_category(raw_value):
    text = str(raw_value or "").strip()
    if not text or text == "-":
        return "Altro"

    normalized_by_lower = {option.lower(): option for option in PRODUCT_CATEGORY_OPTIONS}
    text_lower = text.lower()
    if text_lower in normalized_by_lower:
        return normalized_by_lower[text_lower]

    alias_map = {
        "mangime": "Mangimi",
        "foraggio": "Foraggi",
        "integratore": "Integratori",
        "farmaci": "Veterinaria",
        "farmaco": "Veterinaria",
        "sanificazione": "Igiene",
        "pulizia": "Igiene",
        "ricambi": "Manutenzione",
        "trasporto": "Trasporti",
        "servizio": "Servizi",
    }
    return alias_map.get(text_lower, "Altro")


def normalize_product_description_for_storage(raw_description):
    description = str(raw_description or "").strip()
    normalized = re.sub(r"\s*\n+\s*", " ", description).strip()
    return normalized or "-"


def build_basic_product_storage_line(description, quantity_text, total_text):
    desc = normalize_product_description_for_storage(description)
    return f"{desc} - qta {quantity_text} - tot {total_text}"


def build_detailed_product_storage_line(
    description,
    quantity_text,
    total_text,
    cost_type,
    category_text,
    groups_text,
    price_text=None,
    unit_price_text=None,
    vat_rate_text=None,
):
    desc = normalize_product_description_for_storage(description)
    category = normalize_product_category(category_text)
    parts = [f"{desc}", f"qta {quantity_text}"]

    if str(price_text or "").strip() and str(price_text).strip() != "-":
        parts.append(f"prezzo {price_text}")
    if str(unit_price_text or "").strip() and str(unit_price_text).strip() != "-":
        parts.append(f"prezzo_unit {unit_price_text}")
    if str(vat_rate_text or "").strip() and str(vat_rate_text).strip() != "-":
        parts.append(f"iva {vat_rate_text}")

    parts.append(f"tot {total_text}")
    parts.append(f"costi {cost_type}")
    parts.append(f"categoria {category}")
    parts.append(f"gruppi {groups_text}")

    return " - ".join(parts)


def serialize_product_storage_lines(lines, separator="\n"):
    if not lines:
        return ""

    clean_lines = []
    for line in lines:
        text = str(line or "").strip()
        if text:
            clean_lines.append(text)

    if not clean_lines:
        return ""
    return str(separator).join(clean_lines)


def extract_products_rows_from_parser_text(products_text):
    testo = str(products_text or "").strip()
    if not testo:
        return []

    righe = []
    testo_norm = testo.replace("\r\n", "\n").replace("\r", "\n")
    raw_blocchi = testo_norm.split("\n") if "\n" in testo_norm else testo_norm.split(" | ")
    blocchi = [blocco.strip() for blocco in raw_blocchi if blocco and blocco.strip()]

    for blocco in blocchi:
        match = PRODUCT_ROW_PATTERN.match(blocco)
        if not match:
            continue

        tipo_costo = normalize_cost_type(match.group("cost_type"))
        quantita = (match.group("quantity") or "").strip() or "-"
        totale = (match.group("line_total") or "").strip() or "-"

        quantita_num = parse_decimal(quantita, allow_zero=True, allow_negative=False)
        totale_num = parse_decimal(totale, allow_zero=True, allow_negative=False)
        if quantita_num is None or totale_num is None:
            continue
        if quantita_num <= 0 or totale_num <= 0:
            continue

        righe.append(
            {
                "description": (match.group("description") or "").strip() or "-",
                "quantity": quantita,
                "price": (match.group("price") or "").strip() or "-",
                "unit_price": (match.group("unit_price") or "").strip() or "-",
                "vat_rate": (match.group("vat_rate") or "").strip() or "-",
                "line_total": totale,
                "cost_type": tipo_costo,
                "category": normalize_product_category(match.group("category")),
                "groups": (match.group("groups") or "").strip() or "-",
            }
        )

    return righe


def normalize_multiline_display_text(raw_text):
    testo = str(raw_text or "").strip()
    if not testo:
        return ""

    if "\n" in testo:
        return testo

    return testo.replace(" | ", "\n")
