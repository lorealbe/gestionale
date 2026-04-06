def is_blank(value: str | None) -> bool:
    return value is None or str(value).strip() == ""


def format_number(value, decimals: int = 2, thousands_sep: str = "'", decimal_sep: str = ",") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0

    formatted = f"{number:,.{decimals}f}"
    return formatted.replace(",", "__THOUSANDS__").replace(".", decimal_sep).replace("__THOUSANDS__", thousands_sep)


def format_eur(value, decimals: int = 2) -> str:
    return f"EUR {format_number(value, decimals=decimals)}"


def parse_decimal(raw_value, *, allow_zero: bool = True, allow_negative: bool = False) -> float | None:
    if raw_value is None:
        return None

    if isinstance(raw_value, (int, float)):
        number = float(raw_value)
    else:
        s = str(raw_value).strip()
        if not s:
            return None

        s = s.replace("€", "").replace(" ", "").replace("'", "").replace("’", "")

        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")

        try:
            number = float(s)
        except ValueError:
            return None

    if number < 0 and not allow_negative:
        return None
    if number == 0 and not allow_zero:
        return None
    return number


def clear_treeview(tree) -> None:
    children = tree.get_children()
    if children:
        tree.delete(*children)
