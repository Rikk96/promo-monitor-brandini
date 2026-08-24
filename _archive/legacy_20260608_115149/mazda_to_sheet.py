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
    ("MX-30", "MAZDA MX-30", "elettrica", "https://www.mazda.it/offerte/offerte-privati/mazda-mx-30-offerte/"),
    ("Mazda3 Sedan", "MAZDA3 SEDAN", "hybrid", "https://www.mazda.it/offerte/offerte-privati/mazda3-sedan-offerte/"),
]

def parse_num(s):
    if not s:
        return None
    s = str(s).replace("€","").replace(".", "").replace(",", ".").strip()
    try:
        return float(s)
    except:
        return None

def euro_from_str(s):
    n = parse_num(s)
    if n is None:
        return ""
    return "€ " + f"{int(round(n)):,}".replace(",", ".")

def perc(s):
    if not s:
        return ""
    return str(s).replace(".", ",").strip() + "%"

def active(scad):
    try:
        return datetime.strptime(scad, "%d/%m/%Y").date() >= datetime.now().date()
    except:
        return True

def extract_note(body):
    low = body.lower()

    # preferisci la nota legale/finanziaria estesa
    starts = [
        "annuncio pubblicitario",
        "annuncio promozionale",
        "esempio di finanziamento",
        "mazda advantage:",
    ]

    start = -1
    for marker in starts:
        i = low.find(marker)
        if i != -1:
            start = i
            break

    if start == -1:
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
    for s in stops:
        i = sub.find(s)
        if i != -1 and i > 500:
            end = min(end, i)

    return sub[:end].strip()

def parse_detail(page, modello, title, motore, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)

    body = page.locator("body").inner_text(timeout=30000)
    note = extract_note(body)
    source = note if note else body

    def first_match(patterns, txt):
        for pat in patterns:
            m = re.search(pat, txt, re.I | re.S)
            if m:
                return m.group(1)
        return ""

    intero_raw = first_match([
        r"Prezzo\s+promo(?:zionale)?[^€]{0,180}€\s*([\d\.,]+)",
        r"Prezzo\s+promozionale\s+da\s*([\d\.,]+)\s*€",
        r"A\s+partire\s+da\s*([\d\.,]+)\s*€",
    ], source)

    if not intero_raw:
        intero_raw = first_match([
            r"Prezzo\s+promo(?:zionale)?[^€]{0,180}€\s*([\d\.,]+)",
            r"Prezzo\s+promozionale\s+da\s*([\d\.,]+)\s*€",
            r"A\s+partire\s+da\s*([\d\.,]+)\s*€",
        ], body)

    intero = euro_from_str(intero_raw) if intero_raw else ""

    rata_raw = first_match([
        r"\b\d+\s+rate\s+mensili\s+ognuna\s+di\s*€\s*([\d\.,]+)",
        r"\b\d+\s+rate\s+mensili\s+ognuna\s+di\s*([\d\.,]+)\s*€",
        r"Con\s+Mazda\s+Advantage\s+da\s*([\d\.,]+)\s*€/MESE",
        r"da\s*([\d\.,]+)\s*€/MESE",
    ], source)

    if not rata_raw:
        rata_raw = first_match([
            r"\b\d+\s+rate\s+mensili\s+ognuna\s+di\s*€\s*([\d\.,]+)",
            r"\b\d+\s+rate\s+mensili\s+ognuna\s+di\s*([\d\.,]+)\s*€",
            r"Con\s+Mazda\s+Advantage\s+da\s*([\d\.,]+)\s*€/MESE",
            r"da\s*([\d\.,]+)\s*€/MESE",
        ], body)

    rata = euro_from_str(rata_raw) if rata_raw else ""

    tan_raw = first_match([r"TAN\s*([\d\.,]+)%"], source)
    taeg_raw = first_match([r"TAEG\s*([\d\.,]+)%"], source)

    tan = perc(tan_raw) if tan_raw else ""
    taeg = perc(taeg_raw) if taeg_raw else ""

    scad = first_match([r"fino\s+al\s+(\d{2}/\d{2}/\d{4})"], source) or "30/06/2026"

    extras = []
    anticipo = first_match([r"anticipo\s*€\s*([\d\.,]+)"], source)
    if anticipo:
        extras.append("anticipo € " + anticipo)

    rate_n = first_match([r"\b(\d+)\s+rate\s+mensili", r"\b(\d+)\s+rate\b"], source)
    if rate_n:
        extras.append(f"{rate_n} rate")

    finale = first_match([
        r"(?:VFG|maxi[- ]?rata finale|maxirata finale)[^€]{0,100}€\s*([\d\.,]+)",
        r"saldarla\s+a\s*([\d\.,]+)\s*€",
    ], source)
    if finale:
        extras.append("rata_finale € " + finale)

    credito = first_match([r"importo\s+totale\s+del\s+credito\s*€\s*([\d\.,]+)"], source)
    if credito:
        extras.append("importo_totale_credito € " + credito)

    dovuto = first_match([r"importo\s+totale\s+dovuto\s+dal\s+consumatore\s*€\s*([\d\.,]+)"], source)
    if dovuto:
        extras.append("importo_totale_dovuto € " + dovuto)

    missing = []
    if not intero: missing.append("intero")
    if not rata: missing.append("rata")
    if not tan: missing.append("tan")
    if not taeg: missing.append("taeg")
    if not note: missing.append("note_legali")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stato = "attiva" if active(scad) else "scaduta"
    if missing and stato == "attiva":
        stato = "incompleta"

    row = {
        "Brand": BRAND,
        "Modello": modello,
        "Titolo Promo": title,
        "Motorizzazione": motore,
        "Rata": rata,
        "Intero": intero,
        "TAN (%)": tan,
        "TAEG (%)": taeg,
        "Scadenza": scad,
        "Note Legali": note,
        "Fonte URL": HUB_URL,
        "Offer URL": url,
        "Data Aggiornamento": now,
        "Data Scansione": now,
        "Last Seen": now,
        "Stato": stato,
        "Alert Type": "",
        "Promo Hash": "",
        "Extraction Confidence": "high" if not missing else "medium",
        "Run ID": run_id,
        "Note Tecniche": "; ".join(extras + [f"missing_{x}" for x in missing])
    }

    raw = "|".join([
        row["Brand"], row["Modello"], row["Titolo Promo"], row["Rata"],
        row["Intero"], row["TAN (%)"], row["TAEG (%)"], row["Scadenza"], row["Offer URL"]
    ])
    row["Promo Hash"] = hashlib.md5(raw.encode("utf-8")).hexdigest()

    return row

def build_rows():
    run_id = "mazda_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,args=["--no-sandbox"])
        page = browser.new_page(viewport={"width":1366,"height":4200})

        for modello, title, motore, url in URLS:
            r = parse_detail(page, modello, title, motore, url, run_id)
            rows.append(r)
            print(
                r["Modello"], "|",
                r["Titolo Promo"], "|",
                r["Motorizzazione"], "|",
                r["Rata"], "|",
                r["Intero"], "|",
                r["TAN (%)"], "|",
                r["TAEG (%)"], "|",
                r["Scadenza"], "|",
                r["Stato"], "|",
                r["Note Tecniche"]
            )

        browser.close()

    return rows

def write_to_sheet(rows):
    creds = Credentials.from_service_account_file(
        KEY_PATH,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
    )

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
