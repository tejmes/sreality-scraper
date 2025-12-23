from typing import Optional


def to_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        return int(s.strip())
    except ValueError:
        return None


def to_float(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return float(s.strip())
    except ValueError:
        return None


def clean_str(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    return v if v else None


def split_keywords(description_search: Optional[str]) -> list[str]:
    if not description_search:
        return []
    return [w.strip() for w in description_search.replace(";", ",").split(",") if w.strip()]
