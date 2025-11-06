import os
import random

# Seznam běžných UA.
# Volíme kombinaci Windows/Mac + Chrome/Firefox/Edge.
_BROWSER_UAS = [
    # Chrome (Windows 10/11)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    # Chrome (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    # Firefox (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    # Firefox (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13.6; rv:128.0) Gecko/20100101 Firefox/128.0",
    # Edge (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0",
]


def _pick_user_agent() -> str:
    """
    Vybere UA:
    1) pokud je nastavena proměnná USER_AGENT, použij ji
    2) jinak náhodně vyber z běžných prohlížečových UA
    """
    override = os.getenv("USER_AGENT")
    if override:
        return override.strip()
    return random.choice(_BROWSER_UAS)


# UA zvolíme 1× při importu modulu, aby v rámci jednoho běhu zůstal stabilní.
_CHOSEN_UA = _pick_user_agent()


def build_browser_like_headers() -> dict[str, str]:
    """
    Vytvoří sadu hlaviček podobných reálnému prohlížeči.
    Vysvětlení:
      - User-Agent: běžný prohlížeč (ne 'python-httpx/…').
      - Accept: co prohlížeče běžně akceptují (HTML i JSON).
      - Accept-Language: preferuj češtinu, pak angličtinu (logické pro CZ web).
      - Referer: odkazujeme se na 'hledani' (působí přirozeněji).
    """
    return {
        "User-Agent": _CHOSEN_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
        "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
        # Accept-Encoding záměrně neuvádíme – httpx to řeší a někdy je lepší nechat knihovnu.
        "Referer": "https://www.sreality.cz/hledani/filtr/pozemky",
        # Connection/Upgrade-Insecure-Requests/Sec-Fetch-* necháváme být – httpx a HTTPS to zvládnou.
    }
