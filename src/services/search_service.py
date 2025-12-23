from typing import Optional

from src.infrastructure.sreality_client import (
    build_query,
    fetch_page,
    fetch_all_pages,
    extract_items,
    extract_pagination,
)

from src.core.utils import clean_str, split_keywords


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

    if description_search is None and "description_search" in base_filters:
        description_search = base_filters["description_search"]

    INVALID_KEYS = {
        "description_search",
        "price_mode",
        "limit", "offset",
        "user_id",
        "id", "name", "created_at", "last_run", "schedule"
    }
    base_filters = {k: v for k, v in base_filters.items() if k not in INVALID_KEYS}

    keywords = split_keywords(description_search)
    all_results = []
    last_limit = base_filters.get("limit", 60)
    total_from_api = 0
    multi_search = len(keywords) > 1

    for kw in (keywords or [None]):
        url = build_query(description_search=clean_str(kw), **base_filters)
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

    seen = set()
    unique = []
    for r in all_results:
        hid = r.get("hash_id")
        if hid and hid not in seen:
            unique.append(r)
            seen.add(hid)

    total_final = len(unique) if multi_search else total_from_api or len(unique)
    return unique, {"total": total_final, "limit": last_limit}
