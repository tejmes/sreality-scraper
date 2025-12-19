from src.infrastructure.sreality_client import to_card


def build_new_ads_email(routine: dict, new_items: list[dict]) -> str:
    routine_name = routine["name"]
    routine_id = routine["id"]
    count = len(new_items)

    # odkaz do tvojí aplikace na nové inzeráty
    link_my_app = f"http://91.99.156.98:8000/routines/{routine_id}/new"

    lines = []
    for i, item in enumerate(new_items, start=1):
        card = to_card(item)  # získá title, cenu a Sreality URL
        title = card["title"]
        price = card["price"]
        url = card["url"]

        price_str = f"{price:,}".replace(",", " ") if price else "-"
        lines.append(f"{i}) {title} – {price_str} Kč\n   {url}")

    body = (
            f"Rutina: {routine_name}\n"
            f"Počet nových inzerátů: {count}\n\n"
            f"Zobrazit nové inzeráty v aplikaci:\n{link_my_app}\n\n"
            f"Nové inzeráty:\n\n" +
            "\n\n".join(lines)
    )

    return body
