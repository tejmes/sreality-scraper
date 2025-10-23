from __future__ import annotations

from src.filters_map import (
    category_main_cb,
    category_type_cb,
    locality_country_id,
    locality_region_id,
)
from src.sreality_client import (
    build_query,
    fetch_page,
    extract_items,
    extract_pagination,
    format_item_brief,
    save_json,  # ← přidáno
)

from src.storage import upsert_items

PRINT_LIMIT = 10


def main():
    url = build_query(
        category_main_cb=category_main_cb["pozemky"],
        category_type_cb=category_type_cb["prodej"],
        locality_country_id=locality_country_id["cesko"],
        locality_region_id=locality_region_id["stredocesky"],
        description_search="trvalé bydlení",
        estate_area_from=2500,
        limit=60,
        offset=0,
    )

    data = fetch_page(url)

    # --- NOVÉ: uložení surové odpovědi, ať si ji můžeš kdykoli otevřít ---
    out_path = save_json(data, "snapshots/last_search.json")
    print(f"JSON uložen do: {out_path}\n")

    pag = extract_pagination(data)
    items = extract_items(data)

    print("Pagination:", f"total={pag.get('total')}", f"limit={pag.get('limit')}", f"offset={pag.get('offset')}")
    print(f"Items returned: {len(items)}\n")

    for it in (items if PRINT_LIMIT is None else items[:PRINT_LIMIT]):
        print(format_item_brief(it))


    upsert_items(items)
    print(f"\nUloženo/aktualizováno v databázi: {len(items)} položek.")
    print("Soubor DB:", "data/estates.sqlite3")

if __name__ == "__main__":
    main()
