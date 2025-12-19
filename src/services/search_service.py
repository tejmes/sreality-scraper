from typing import Optional

from src.sreality_client import (
    build_query,
    fetch_page,
    fetch_all_pages,
    extract_items,
    extract_pagination,
)

from src.core.utils import _clean_str, _split_keywords


def search_multiple_keywords(
        *,
        base_filters: dict,
        description_search: Optional[str] = None,
        fetch_all: bool = False,
) -> tuple[list[dict], dict]:
    """
    Spustí jedno nebo více vyhledávání na Sreality.cz podle klíčových slov
    a sjednotí výsledky bez duplicit. Používá stejné filtry pro ruční i plánované rutiny.
    """

    # Pokud description_search není explicitně předáno, vezmi ho z filtrů rutiny
    if description_search is None and "description_search" in base_filters:
        description_search = base_filters["description_search"]

    # Odstraň klíče, které API nezná nebo které jsou interní
    INVALID_KEYS = {
        "description_search",  # zpracovává se zvlášť
        "price_mode",  # jen interní přepínač
        "limit", "offset",  # API má vlastní stránkování
        "user_id",  # rutina metadata
        "id", "name", "created_at", "last_run", "schedule"  # další meta-informace
    }
    base_filters = {k: v for k, v in base_filters.items() if k not in INVALID_KEYS}

    # Rozdělení popisu na víc klíčových slov
    keywords = _split_keywords(description_search)
    all_results = []
    last_limit = base_filters.get("limit", 60)
    total_from_api = 0
    multi_search = len(keywords) > 1

    for kw in (keywords or [None]):
        url = build_query(description_search=_clean_str(kw), **base_filters)
        if fetch_all:
            data = fetch_all_pages(url)
            items = data
            pag = {"total": len(items), "limit": base_filters.get("limit", 60)}
        else:
            data = fetch_page(url)
            items = extract_items(data)
            pag = extract_pagination(data)

        last_limit = pag.get("limit", last_limit)
        total_from_api = max(total_from_api, pag.get("total", 0))
        all_results.extend(items)

    # Odstranění duplicit podle hash_id
    seen = set()
    unique = []
    for r in all_results:
        hid = r.get("hash_id")
        if hid and hid not in seen:
            unique.append(r)
            seen.add(hid)

    total_final = len(unique) if multi_search else total_from_api or len(unique)
    return unique, {"total": total_final, "limit": last_limit}
