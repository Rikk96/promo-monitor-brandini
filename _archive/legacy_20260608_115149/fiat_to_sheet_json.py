from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials
from html import unescape
import gspread
from google.cloud import bigquery
import json
import re
import hashlib
from datetime import datetime

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
SOURCE_URL = "https://www.fiat.it/offerte-privati"
BASE_URL = "https://www.fiat.it"
KEY_PATH = "/tmp/key.json"

HEADERS = [
    "Brand","Modello","Titolo Promo","Motorizzazione","Rata","Intero",
    "TAN (%)","TAEG (%)","Scadenza","Note Legali","Fonte URL","Offer URL",
    "Data Aggiornamento","Data Scansione","Last Seen","Stato","Alert Type",
    "Promo Hash","Extraction Confidence","Run ID","Note Tecniche"
]

def clean_text(t):
    return re.sub(r"\s+", " ", t or "").strip()

def html_to_text(value):
    if not value:
        return ""
    soup = BeautifulSoup(unescape(value), "html.parser")
    return clean_text(soup.get_text(" "))

def parse_number_it(value):
    if not value:
        return ""
    value = value.replace(".", "").replace(",", ".")
    try:
        return float(value)
    except:
        return ""





def format_euro_output(value):
    if value == "" or value is None:
        return ""

    s = str(value).strip().replace("€", "").strip()
    if not s:
        return ""

    # Se arriva già rovinato dal vecchio formatter: € 1.990,00 => 199
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{2}", s):
        n = round(float(s.replace(".", "").replace(",", ".")) / 10)

    # Python float corretto: 199.0, 19950.0
    elif re.fullmatch(r"\d+\.0", s):
        n = int(float(s))

    # Python float generico
    elif re.fullmatch(r"\d+\.\d+", s):
        n = round(float(s))

    # Italiano con virgola
    elif "," in s:
        n = round(float(s.replace(".", "").replace(",", ".")))

    # Intero puro
    else:
        cleaned = re.sub(r"[^\d]", "", s)
        if not cleaned:
            return ""
        n = int(cleaned)

        # Correzione se arriva già moltiplicato x10
        if 800 < n < 10000:
            n = round(n / 10)
        elif n > 70000:
            n = round(n / 10)

    return "€ " + f"{n:,}".replace(",", ".")


def euro_to_float(value):
    if value == "" or value is None:
        return None

    s = str(value).strip().replace("€", "").strip()
    if not s:
        return None

    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{2}", s):
        n = float(s.replace(".", "").replace(",", ".")) / 10
    elif re.fullmatch(r"\d+\.0", s):
        n = float(s)
    elif re.fullmatch(r"\d+\.\d+", s):
        n = float(s)
    elif "," in s:
        n = float(s.replace(".", "").replace(",", "."))
    else:
        cleaned = re.sub(r"[^\d]", "", s)
        if not cleaned:
            return None
        n = float(cleaned)
        if 800 < n < 10000:
            n = n / 10
        elif n > 70000:
            n = n / 10

    return n


def percent_to_float(value):
    if value == "" or value is None:
        return None

    s = str(value).strip().replace("%", "").replace(",", ".")
    try:
        n = float(s)
    except:
        return None

    if n >= 100:
        n = n / 100

    return n

def normalize_percent_output(value):
    if value == "" or value is None:
        return ""

    s = str(value).strip()
    if not s:
        return ""

    if s.endswith("%"):
        return s

    s = s.replace(",", ".")
    try:
        n = float(s)
    except:
        return s

    # Caso Google Sheet/gspread: 599 significa 5,99
    if n >= 100:
        n = n / 100

    out = f"{n:.2f}".replace(".", ",")
    out = out.rstrip("0").rstrip(",")
    return out + "%"

def extract_price(text):
    m = re.search(r"Da\s*([\d\.\,]+)\s*€", text, re.I)
    return parse_number_it(m.group(1)) if m else ""

def extract_rate(text):
    m = re.search(r"rate\s+da\s*([\d\.\,]+)\s*€", text, re.I)
    return parse_number_it(m.group(1)) if m else ""

def parse_percent(value):
    if not value:
        return ""
    value = value.strip().replace(",", ".")
    try:
        return float(value)
    except:
        return ""

def extract_tan_taeg(text):
    tan = ""
    taeg = ""
    m = re.search(r"TAN.*?([\d\.,]+)\s*%", text, re.I)
    if m:
        tan = parse_percent(m.group(1))
    m = re.search(r"TAEG\s*([\d\.,]+)\s*%", text, re.I)
    if m:
        taeg = parse_percent(m.group(1))
    return tan, taeg

def extract_scadenza(text):
    m = re.search(r"(\d{2}/\d{2}/\d{4})", text)
    return m.group(1) if m else ""

def extract_motorizzazione(title, url):
    t = (title + " " + url).lower()
    if "elettrica" in t or "electric" in t or "500e" in t or "600e" in t or "topolino" in t:
        return "elettrica"
    if "plug-in" in t or "plugin" in t:
        return "plug-in"
    if "hybrid" in t or "ibrida" in t or "ibrido" in t:
        return "hybrid"
    if "diesel" in t:
        return "diesel"
    if "benzina" in t:
        return "benzina"
    return ""

def extract_model(title):
    t = title.lower()
    if "grande panda" in t:
        return "Grande Panda"
    if "pandina" in t:
        return "Pandina"
    if "topolino" in t:
        return "Topolino"
    if "qubo" in t:
        return "Qubo"
    if "600" in t:
        return "600"
    if "500e" in t:
        return "500e"
    if "500" in t:
        return "500 Hybrid"
    return title

def extract_legal_notes(page):
    raw = page.locator("body").inner_text(timeout=30000)
    start = raw.lower().find("dettaglio promozione")
    if start == -1:
        return ""
    end_candidates = []
    for marker in ["test drive", "richiedi informazioni", "1 modello", "i tuoi dati"]:
        idx = raw.lower().find(marker, start)
        if idx != -1:
            end_candidates.append(idx)
    end = min(end_candidates) if end_candidates else len(raw)
    return clean_text(raw[start:end])

def get_cards(page):
    soup = BeautifulSoup(page.content(), "html.parser")
    component = soup.find(attrs={"data-component": "CPSAllPromotions"})
    if not component:
        return []
    props = json.loads(unescape(component.get("data-props")))
    return props.get("cards", [])

def row_from_card(card, note_legali, run_id):
    cta = card.get("ctas") or {}
    href = cta.get("href") or ""
    offer_url = href if href.startswith("http") else BASE_URL + href

    title = clean_text(card.get("headline") or "")
    modello = extract_model(title)
    motorizzazione = extract_motorizzazione(title, offer_url)

    short_text = html_to_text(card.get("shortAbstract"))
    rate_text = html_to_text(card.get("monthlyRate"))
    installment_text = html_to_text(card.get("installment"))
    validity_text = html_to_text(card.get("validityEndDate"))

    intero = extract_price(short_text)
    rata = extract_rate(rate_text)
    tan, taeg = extract_tan_taeg(installment_text)
    scadenza = extract_scadenza(validity_text)

    missing = []
    if not title: missing.append("titolo")
    if not modello: missing.append("modello")
    if not motorizzazione: missing.append("motorizzazione")
    if not scadenza: missing.append("scadenza")
    if not note_legali: missing.append("note_legali")
    if not rata and not intero: missing.append("rata/intero")
    if rata and (not tan or not taeg): missing.append("tan/taeg")

    stato = "incompleta" if missing else "attiva"
    confidence = max(0, 100 - len(missing) * 15)

    hash_base = f"Fiat|{modello}|{title}|{motorizzazione}|{rata}|{intero}|{tan}|{taeg}|{scadenza}|{offer_url}"
    promo_hash = hashlib.sha256(hash_base.encode("utf-8")).hexdigest()

    now = datetime.now()

    return {
        "Brand": "Fiat",
        "Modello": modello,
        "Titolo Promo": title,
        "Motorizzazione": motorizzazione,
        "Rata": format_euro_output(rata),
        "Intero": format_euro_output(intero),
        "TAN (%)": normalize_percent_output(tan),
        "TAEG (%)": normalize_percent_output(taeg),
        "Scadenza": scadenza,
        "Note Legali": note_legali,
        "Fonte URL": SOURCE_URL,
        "Offer URL": offer_url,
        "Data Aggiornamento": now.strftime("%d/%m/%Y"),
        "Data Scansione": now.strftime("%Y-%m-%d %H:%M:%S"),
        "Last Seen": now.strftime("%d/%m/%Y"),
        "Stato": stato,
        "Alert Type": "",
        "Promo Hash": promo_hash,
        "Extraction Confidence": confidence,
        "Run ID": run_id,
        "Note Tecniche": "; ".join(missing)
    }

def scrape_fiat():
    run_id = "manual_test_fiat_json_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1366, "height": 1200})

        page.goto(SOURCE_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        cards = get_cards(page)
        print("PROMO JSON TROVATE:", len(cards))

        for card in cards:
            cta = card.get("ctas") or {}
            href = cta.get("href") or ""
            offer_url = href if href.startswith("http") else BASE_URL + href

            title = clean_text(card.get("headline") or "")
            print("Scraping note:", title, "|", offer_url)

            note_legali = ""
            try:
                page.goto(offer_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
                note_legali = extract_legal_notes(page)
            except Exception as e:
                note_legali = ""

            rows.append(row_from_card(card, note_legali, run_id))

        browser.close()

    return rows

def write_to_sheet(rows):
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
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

    new_rows = [[r.get(h, "") for h in HEADERS] for r in rows]
    final_values = [HEADERS] + kept_rows + new_rows

    ws.clear()
    ws.update("A1", final_values)

    print("RIGHE FIAT SCRITTE:", len(new_rows))
    print("SHEET AGGIORNATO")

def save_to_bigquery(rows):
    client = bigquery.Client(project="brandini-promo-monitor")
    table_id = "brandini-promo-monitor.promo_monitor.promo_clean"

    bq_rows = []

    for r in rows:
        bq_rows.append({
            "run_id": r.get("Run ID"),
            "promo_hash": r.get("Promo Hash"),
            "brand": r.get("Brand"),
            "modello": r.get("Modello"),
            "titolo_promo": r.get("Titolo Promo"),
            "motorizzazione": r.get("Motorizzazione"),
            "rata": r.get("Rata") or None,
            "intero": r.get("Intero") or None,
            "tan": r.get("TAN (%)") or None,
            "taeg": r.get("TAEG (%)") or None,
            "scadenza": None,
            "note_legali": r.get("Note Legali"),
            "fonte_url": r.get("Fonte URL"),
            "offer_url": r.get("Offer URL"),
            "data_aggiornamento": None,
            "data_scansione": None,
            "last_seen": None,
            "stato": r.get("Stato"),
            "alert_type": r.get("Alert Type"),
            "extraction_confidence": r.get("Extraction Confidence"),
            "note_tecniche": r.get("Note Tecniche"),
        })

    errors = client.insert_rows_json(table_id, bq_rows)

    if errors:
        print("ERRORI BIGQUERY:", errors)
    else:
        print("BIGQUERY AGGIORNATO:", len(bq_rows))


if __name__ == "__main__":
    rows = scrape_fiat()
    write_to_sheet(rows)
    save_to_bigquery(rows)
