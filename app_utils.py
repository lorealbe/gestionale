def is_blank(s: str) -> bool:
    return s is None or s.strip() == ""


def format_number(value, decimals: int = 2, thousands_sep: str = "'", decimal_sep: str = ",") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0

    formatted = f"{number:,.{decimals}f}"
    return formatted.replace(",", "__THOUSANDS__").replace(".", decimal_sep).replace("__THOUSANDS__", thousands_sep)


def format_eur(value, decimals: int = 2) -> str:
    return f"EUR {format_number(value, decimals=decimals)}"
