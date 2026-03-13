# Sreality Scraper

Webová aplikace pro vyhledávání nemovitostí na **Sreality.cz**, ukládání výsledků a vytváření automatických rutin pro pravidelné sledování nových inzerátů. Projekt je postavený na **FastAPI** a kombinuje ruční vyhledávání přes webové rozhraní s plánovaným spouštěním úloh, lokální persistencí výsledků a e-mailovými notifikacemi.

---

# Hlavní funkce

- Vyhledávání inzerátů na Sreality.cz přes vlastní webové rozhraní
- Filtrování podle typu nemovitosti, dispozice, lokality, rozlohy, ceny, ceny za m² a stáří inzerátu
- Našeptávání lokality přes endpoint `/autocomplete` napojený na Sreality API
- Vyhledávání podle více klíčových slov v popisu inzerátu s deduplikací výsledků podle `hash_id`
- Ukládání výsledků posledního vyhledávání do JSON snapshotu
- Zakládání rutin nad stejnými filtry jako při ručním hledání
- Pravidelné plánované spouštění rutin pomocí **APScheduleru**
- Evidence nových inzerátů oproti dříve uloženým výsledkům
- Odesílání e-mailu při nalezení nových inzerátů
- Přihlášení uživatelů, admin účet, týmová správa přístupu k rutinám
- Diagnostické endpointy `/health` a `/debug/scheduler`

---

# Použité technologie

- Python
- FastAPI
- Jinja2 templates
- Uvicorn
- APScheduler
- SQLite
- httpx
- passlib / bcrypt
- python-dotenv

---

# Architektura projektu

Projekt je rozdělený do několika logických částí:

- **app.py** – vstupní bod aplikace, registrace routerů, statických souborů, session middleware a startup logiky  
- **src/routes** – HTTP endpointy pro vyhledávání, autentizaci, administraci a práci s rutinami  
- **src/services** – aplikační logika (např. sjednocení výsledků z více vyhledávání nebo generování e-mailového obsahu)  
- **src/infrastructure** – komunikace s externími službami, zejména Sreality API a SMTP  
- **src/persistence** – lokální ukládání uživatelů, týmů, rutin a výsledků  
- **src/scheduler** – plánování a obnovování naplánovaných úloh po startu aplikace  
- **templates** a **static** – server-rendered UI přes HTML šablony a CSS  

---

# Jak projekt funguje

Aplikace staví URL dotazy pro veřejné API **Sreality.cz**, stahuje výsledky přes `httpx`, převádí je do interní reprezentace a zobrazuje je v HTML rozhraní.

Pro hromadné nebo plánované zpracování dokáže stáhnout všechny stránky výsledků, odstranit duplicity a uložit data do lokální databáze konkrétní rutiny.

Každá rutina reprezentuje uložený vyhledávací profil. Má vlastní identifikátor, filtry, volitelný plán spuštění, seznam e-mailových adres a vlastní SQLite databázi s historickými výsledky.

Při opakovaném spuštění se porovnají nově stažené inzeráty s již známými záznamy a nově objevené položky lze zobrazit odděleně nebo odeslat e-mailem.

---

# Uživatelské role a přístup

Projekt podporuje přihlášení přes session.

Při startu se inicializuje uživatelská databáze a vytvoří se **admin účet podle hodnot z `.env`**. Přihlášený uživatel má přístup ke svým rutinám, admin má přístup ke správě aplikace a podle implementace oprávnění lze sdílet přístup k rutinám i v rámci stejného týmu.

---

# Instalace

## 1. Klonování repozitáře

```bash
git clone https://github.com/tejmes/sreality-scraper.git
cd sreality-scraper
```

## 2. Vytvoření virtuálního prostředí

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

Linux/macOS:

```bash
source .venv/bin/activate
```

## 3. Instalace závislostí

```bash
pip install -r requirements.txt
```

## 4. Vytvoření .env

Aplikace očekává .env soubor v kořeni projektu. Bez něj start selže.
Povinné proměnné jsou SECRET_KEY, ADMIN_USERNAME a ADMIN_PASSWORD.
Pro e-mailové notifikace se navíc používají EMAIL_FROM, SMTP_HOST, SMTP_PORT, SMTP_USER a SMTP_PASS.

Příklad:
```bash
SECRET_KEY=change_me
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123

ENV=development

EMAIL_FROM=example@example.cz
SMTP_HOST=smtp.seznam.cz
SMTP_PORT=587
SMTP_USER=example@example.cz
SMTP_PASS=your_password
```

## 5. Spuštění aplikace

```bash
uvicorn app:app --reload --port 8000
```
