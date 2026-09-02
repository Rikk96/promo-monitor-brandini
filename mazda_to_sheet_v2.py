from playwright.sync_api import sync_playwright
import re, hashlib
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"
BRAND = "Mazda"
HUB_URL = "https://www.mazda.it/offerte/offerte-privati/"

HEADERS = [
    "Brand","Modello","Titolo Promo","Motorizzazione","Rata","Intero","TAN (%)","TAEG (%)",
    "Scadenza","Note Legali","Fonte URL","Offer URL","Data Aggiornamento","Data Scansione",
    "Last Seen","Stato","Alert Type","Promo Hash","Extraction Confidence","Run ID","Note Tecniche"
]

URLS = [
    ("CX-5", "NUOVA MAZDA CX-5", "hybrid", "https://www.mazda.it/offerte/offerte-privati/mazda-cx-5-offerte/"),
    ("CX-30", "MAZDA CX-30", "hybrid", "https://www.mazda.it/offerte/offerte-privati/mazda-cx-30-offerte/"),
    ("Mazda3", "MAZDA3 5 PORTE", "hybrid", "https://www.mazda.it/offerte/offerte-privati/mazda3-offerte/"),
    ("CX-6e", "MAZDA CX-6e", "elettrica", "https://www.mazda.it/offerte/offerte-privati/mazda-cx-6e-offerte/"),
    ("Mazda6e", "MAZDA6e", "elettrica", "https://www.mazda.it/offerte/offerte-privati/mazda6e-offerte/"),
    ("CX-60", "MAZDA CX-60", "plug-in", "https://www.mazda.it/offerte/offerte-privati/mazda-cx-60-offerte/"),
    ("CX-80", "MAZDA CX-80", "plug-in", "https://www.mazda.it/offerte/offerte-privati/mazda-cx-80-offerte/"),
    ("Mazda2 Hybrid", "MAZDA2 HYBRID", "hybrid", "https://www.mazda.it/offerte/offerte-privati/mazda2-hybrid/"),
    ("MX-5", "MAZDA MX-5 SOFT TOP", "benzina", "https://www.mazda.it/offerte/offerte-privati/mazda-mx-5-soft-top-offerte/"),
    ("MX-5 RF", "MAZDA MX-5 RF", "benzina", "https://www.mazda.it/offerte/offerte-privati/mazda-mx-5-rf-offerte/"),
]

def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def parse_num(s):
    if not s:
        return None

    s = str(s).replace("€", "").strip()

    # tieni solo la prima cifra italiana valida, es: 32.900,00 oppure 278,64
    m = re.search(r"\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?", s)
    if not m:
        return None

    n = m.group(0)
    n = n.replace(".", "").replace(",", ".")

    try:
        return float(n)
    except:
        return None

def euro(s):
    n = parse_num(s)
    if n is None:
        return ""
    return "€ " + f"{int(round(n)):,}".replace(",", ".")

def pct(s):
    if not s:
        return ""
    return s.replace(".", ",").strip() + "%"

def active(scad):
    try:
        return datetime.strptime(scad, "%d/%m/%Y").date() >= datetime.now().date()
    except:
        return True

def find1(patterns, text):
    for pat in patterns:
        m = re.search(pat, text, re.I | re.S)
        if m:
            return m.group(1)
    return ""

def extract_note(body):
    low = body.lower()
    positions = []
    for marker in ["annuncio pubblicitario", "annuncio promozionale", "esempio di finanziamento"]:
        i = low.find(marker)
        if i != -1:
            positions.append(i)

    if positions:
        start = min(positions)
    else:
        start = low.find("tan fisso")

    if start == -1:
        return ""

    sub = body[start:]
    stops = [
        "\nAPPROFONDISCI",
        "\nACCESSORI ORIGINALI",
        "\nMY MAZDA",
        "\nSEGUICI",
        "\nSeleziona un paese",
        "\nQUESTO SITO WEB UTILIZZA COOKIE",
    ]

    end = len(sub)
    for stop in stops:
        i = sub.find(stop)
        if i != -1 and i > 400:
            end = min(end, i)

    return sub[:end].strip()

def parse_page(page, modello, title, motore, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)

    body = page.locator("body").inner_text(timeout=30000)
    body = body.replace("\u00ad", "")
    note = extract_note(body)
    text = note if note else body

    intero_raw = find1([
        r"Prezzo\s+promozionale\s+da\s*([\d\.,]{4,})\s*€",
        r"A\s+partire\s+da\s*([\d\.,]{4,})\s*€",
        r"Prezzo\s+promo(?:zionale)?[^€]{0,180}€\s*([\d\.,]{4,})",
    ], text)

    if not intero_raw:
        intero_raw = find1([
            r"Prezzo\s+promozionale\s+da\s*([\d\.,]{4,})\s*€",
            r"A\s+partire\s+da\s*([\d\.,]{4,})\s*€",
            r"Prezzo\s+promo(?:zionale)?[^€]{0,180}€\s*([\d\.,]{4,})",
        ], body)

    rata_raw = find1([
        r"\b\d+\s+rate\s+mensili\s+ognuna\s+di\s*€\s*([\d\.,]+)",
        r"\b\d+\s+rate\s+mensili\s+ognuna\s+di\s*([\d\.,]+)\s*€",
        r"Con\s+Mazda\s+Advantage\s+da\s*([\d\.,]+)\s*€/MESE",
        r"da\s*([\d\.,]+)\s*€/MESE",
    ], text)

    if not rata_raw:
        rata_raw = find1([
            r"\b\d+\s+rate\s+mensili\s+ognuna\s+di\s*€\s*([\d\.,]+)",
            r"\b\d+\s+rate\s+mensili\s+ognuna\s+di\s*([\d\.,]+)\s*€",
            r"Con\s+Mazda\s+Advantage\s+da\s*([\d\.,]+)\s*€/MESE",
            r"da\s*([\d\.,]+)\s*€/MESE",
        ], body)

    tan_raw = find1([r"TAN\s*(?:FISSO)?\s*([\d\.,]+)\s*%"], text)
    taeg_raw = find1([r"TAEG\s*(?:FISSO)?\s*([\d\.,]+)\s*%"], text)
    scad = find1([r"fino\s+al\s+(\d{2}/\d{2}/\d{4})"], text) or "30/06/2026"

    extras = []
    anticipo = find1([r"anticipo\s*€\s*([\d\.,]+)"], text)
    if anticipo:
        extras.append("anticipo € " + anticipo)

    rate_n = find1([r"\b(\d+)\s+rate\s+mensili", r"\b(\d+)\s+rate\b"], text)
    if rate_n:
        extras.append(rate_n + " rate")

    finale = find1([
        r"(?:VFG|maxi[- ]?rata finale|maxirata finale)[^€]{0,100}€\s*([\d\.,]+)",
        r"saldarla\s+a\s*([\d\.,]+)\s*€",
    ], text)
    if finale:
        extras.append("rata_finale € " + finale)

    credito = find1([r"importo\s+totale\s+del\s+credito\s*€\s*([\d\.,]+)"], text)
    if credito:
        extras.append("importo_totale_credito € " + credito)

    dovuto = find1([r"importo\s+totale\s+dovuto\s+dal\s+consumatore\s*€\s*([\d\.,]+)"], text)
    if dovuto:
        extras.append("importo_totale_dovuto € " + dovuto)

    row = {
        "Brand": BRAND,
        "Modello": modello,
        "Titolo Promo": title,
        "Motorizzazione": motore,
        "Rata": euro(rata_raw),
        "Intero": euro(intero_raw),
        "TAN (%)": pct(tan_raw),
        "TAEG (%)": pct(taeg_raw),
        "Scadenza": scad,
        "Note Legali": note,
        "Fonte URL": HUB_URL,
        "Offer URL": url,
        "Data Aggiornamento": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Data Scansione": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Last Seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Stato": "attiva",
        "Alert Type": "",
        "Promo Hash": "",
        "Extraction Confidence": "high",
        "Run ID": run_id,
        "Note Tecniche": "",
    }

    missing = []
    if not row["Intero"]: missing.append("missing_intero")
    if not row["Rata"]: missing.append("missing_rata")
    if not row["TAN (%)"]: missing.append("missing_tan")
    if not row["TAEG (%)"]: missing.append("missing_taeg")
    if not row["Note Legali"]: missing.append("missing_note_legali")

    if missing:
        row["Stato"] = "incompleta"

    row["Note Tecniche"] = "; ".join(extras + missing)

    raw = "|".join([row["Brand"], row["Modello"], row["Titolo Promo"], row["Rata"], row["Intero"], row["TAN (%)"], row["TAEG (%)"], row["Scadenza"], row["Offer URL"]])
    row["Promo Hash"] = hashlib.md5(raw.encode("utf-8")).hexdigest()

    return row

def build_rows():
    run_id = "mazda_v2_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,args=["--no-sandbox"])
        page = browser.new_page(viewport={"width":1366,"height":4200})

        for modello, title, motore, url in URLS:
            r = parse_page(page, modello, title, motore, url, run_id)
            rows.append(r)
            print(r["Modello"], "|", r["Rata"], "|", r["Intero"], "|", r["TAN (%)"], "|", r["TAEG (%)"], "|", r["Stato"], "|", r["Note Tecniche"])

        browser.close()

    return rows

def write_to_sheet(rows):
    creds = Credentials.from_service_account_file(KEY_PATH, scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ])

    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SPREADSHEET_ID).worksheet("Promo_Output")

    existing = ws.get_all_records()
    kept = [r for r in existing if r.get("Brand") != BRAND]

    final_rows = kept + rows
    values = [HEADERS] + [[r.get(h, "") for h in HEADERS] for r in final_rows]

    ws.clear()
    ws.update("A1", values)

if __name__ == "__main__":
    rows = build_rows()
    write_to_sheet(rows)
    print("RIGHE MAZDA SCRITTE:", len(rows))
    print("SHEET AGGIORNATO")
