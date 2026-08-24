from playwright.sync_api import sync_playwright
import re
import hashlib
from datetime import datetime
from google.oauth2.service_account import Credentials
import gspread

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
SOURCE_URL = "https://www.fiat.it/offerte-privati"
KEY_PATH = "/tmp/key.json"

HEADERS = [
    "Brand",
    "Modello",
    "Titolo Promo",
    "Motorizzazione",
    "Rata",
    "Intero",
    "TAN (%)",
    "TAEG (%)",
    "Scadenza",
    "Note Legali",
    "Fonte URL",
    "Offer URL",
    "Data Aggiornamento",
    "Data Scansione",
    "Last Seen",
    "Stato",
    "Alert Type",
    "Promo Hash",
    "Extraction Confidence",
    "Run ID",
    "Note Tecniche",
]

def clean_text(t):
    return re.sub(r"\s+", " ", t or "").strip()

def parse_number_it(value):
    if not value:
        return None
    value = value.replace(".", "").replace(",", ".")
    try:
        return float(value)
    except:
        return None

def title_from_url(url):
    u = url.lower()
    if "nuova-fiat-pandina" in u:
        return "Pandina"
    if "fiat-500-ibrida-pop" in u:
        return "500 Hybrid POP"
    if "finanziamento-fiat-500-hybrid-dolcevita" in u:
        return "500 Hybrid Dolcevita"
    if "500-elettrica-red" in u:
        return "500e RED"
    if "grande-panda-benzina" in u:
        return "Grande Panda Benzina Turbo 100"
    if "grande-panda-hybrid" in u:
        return "Grande Panda Hybrid"
    return None

def extract_model_from_title(title):
    if not title:
        return None
    if "Grande Panda" in title:
        return "Grande Panda"
    if "Pandina" in title:
        return "Pandina"
    if "500e" in title:
        return "500e"
    if "500 Hybrid" in title:
        return "500 Hybrid"
    if title.startswith("500"):
        return "500"
    return title

def extract_motorizzazione(text, url):
    t = (text + " " + url).lower()
    if "elettrica" in t or "electric" in t or "500e" in t or "500-elettrica" in t:
        return "elettrica"
    if "plug-in" in t or "plugin" in t:
        return "plug-in"
    if "hybrid" in t or "ibrida" in t or "ibrido" in t:
        return "hybrid"
    if "diesel" in t:
        return "diesel"
    if "benzina" in t:
        return "benzina"
    return None

def extract_fields(text, url):
    raw = text
    title = title_from_url(url)
    modello = extract_model_from_title(title)

    intero = None
    m = re.search(r"Da\s+([\d\.\,]+)\s*€", raw, re.IGNORECASE)
    if m:
        intero = parse_number_it(m.group(1))

    rata = None
    m = re.search(r"rate\s+da\s+([\d\.\,]+)\s*€", raw, re.IGNORECASE)
    if not m:
        m = re.search(r"([\d\.\,]+)\s*€\s*/\s*mese", raw, re.IGNORECASE)
    if m:
        rata = parse_number_it(m.group(1))

    tan = None
    m = re.search(r"TAN\s*(?:\(fisso\))?\s*([\d\,\.]+)\s*%", raw, re.IGNORECASE)
    if m:
        tan = parse_number_it(m.group(1))

    taeg = None
    m = re.search(r"TAEG\s*([\d\,\.]+)\s*%", raw, re.IGNORECASE)
    if m:
        taeg = parse_number_it(m.group(1))

    scadenza = None
    m = re.search(r"Validità:\s*(\d{2}/\d{2}/\d{4})", raw, re.IGNORECASE)
    if m:
        scadenza = m.group(1)

    note_legali = None
    start = raw.lower().find("dettaglio promozione")
    if start != -1:
        end_candidates = []
        for marker in ["test drive", "richiedi informazioni", "1 modello", "i tuoi dati"]:
            idx = raw.lower().find(marker, start)
            if idx != -1:
                end_candidates.append(idx)
        end = min(end_candidates) if end_candidates else len(raw)
        note_legali = raw[start:end].strip()

    motorizzazione = extract_motorizzazione((title or "") + " " + raw[:1500], url)

    missing = []
    if not title:
        missing.append("titolo")
    if not modello:
        missing.append("modello")
    if not motorizzazione:
        missing.append("motorizzazione")
    if not scadenza:
        missing.append("scadenza")
    if not note_legali:
        missing.append("note_legali")
    if rata is None and intero is None:
        missing.append("rata/intero")
    if rata is not None and (tan is None or taeg is None):
        missing.append("tan/taeg")

    stato = "incompleta" if missing else "attiva"

    hash_base = f"Fiat|{modello}|{title}|{motorizzazione}|{rata}|{intero}|{tan}|{taeg}|{scadenza}|{url}"
    promo_hash = hashlib.sha256(hash_base.encode("utf-8")).hexdigest()

    confidence = max(0, 100 - (len(missing) * 15))
    now = datetime.now()

    return {
        "Brand": "Fiat",
        "Modello": modello,
        "Titolo Promo": title,
        "Motorizzazione": motorizzazione,
        "Rata": rata if rata is not None else "",
        "Intero": intero if intero is not None else "",
        "TAN (%)": tan if tan is not None else "",
        "TAEG (%)": taeg if taeg is not None else "",
        "Scadenza": scadenza or "",
        "Note Legali": clean_text(note_legali) if note_legali else "",
        "Fonte URL": SOURCE_URL,
        "Offer URL": url,
        "Data Aggiornamento": now.strftime("%d/%m/%Y"),
        "Data Scansione": now.strftime("%Y-%m-%d %H:%M:%S"),
        "Last Seen": now.strftime("%d/%m/%Y"),
        "Stato": stato,
        "Alert Type": "",
        "Promo Hash": promo_hash,
        "Extraction Confidence": confidence,
        "Run ID": "manual_test_fiat",
        "Note Tecniche": "; ".join(missing) if missing else "",
    }

def scrape_fiat():
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1366, "height": 900})

        page.goto(SOURCE_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        links = page.locator("a").evaluate_all("""
            els => els.map(a => ({
                text: (a.innerText || '').trim().replace(/\\s+/g, ' '),
                href: a.href
            }))
        """)

        offer_urls = []
        seen = set()

        for item in links:
            href = item.get("href") or ""
            if "/offerte-privati/" in href and href != SOURCE_URL and href not in seen:
                seen.add(href)
                offer_urls.append(href)

        print("OFFERTE TROVATE:", len(offer_urls))

        for url in offer_urls:
            print("Scraping:", url)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
            text = page.locator("body").inner_text(timeout=30000)
            results.append(extract_fields(text, url))

        browser.close()

    return results

def write_to_sheet(rows):
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = Credentials.from_service_account_file(KEY_PATH, scopes=scopes)
    gc = gspread.authorize(creds)

    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet("Promo_Output")

    existing = ws.get_all_values()

    kept_rows = []
    if existing:
        for row in existing[1:]:
            if row and row[0].strip().lower() != "fiat":
                kept_rows.append(row)

    new_rows = []
    for r in rows:
        new_rows.append([r.get(h, "") for h in HEADERS])

    final_values = [HEADERS] + kept_rows + new_rows

    ws.clear()
    ws.update("A1", final_values)

    print("RIGHE FIAT SCRITTE:", len(new_rows))
    print("SHEET AGGIORNATO")

if __name__ == "__main__":
    rows = scrape_fiat()
    write_to_sheet(rows)
