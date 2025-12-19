import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/autocomplete")
def autocomplete(q: str):
    if not q or len(q.strip()) < 2:
        return JSONResponse([])

    url = (
            "https://www.sreality.cz/api/v1/localities/suggest"
            "?phrase=" + q.strip() +
            "&category=region_cz,district_cz,municipality_cz,quarter_cz,ward_cz,street_cz,area_cz"
            "&locality_country_id=112"
            "&lang=cs"
            "&limit=10"
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.sreality.cz/",
        "Accept": "application/json, text/plain, */*",
    }

    try:
        with httpx.Client(headers=headers, timeout=10.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        suggestions = []

        for item in results:
            user = item.get("userData", {})
            name = user.get("suggestFirstRow")
            second = user.get("suggestSecondRow")

            if name:
                suggestions.append({
                    "name": name,
                    "second_row": second,
                    "entity_type": user.get("entityType"),
                    "entity_id": user.get("id"),
                })

        return JSONResponse(suggestions)

    except Exception as e:
        print(f"[autocomplete] error: {e}")
        return JSONResponse([])
