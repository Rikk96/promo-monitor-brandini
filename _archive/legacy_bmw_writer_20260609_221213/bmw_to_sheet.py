from playwright.sync_api import sync_playwright
import re, hashlib
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"
BRAND = "BMW"
HUB_URL = "https://www.bmw.it/it/topics/offerte-bmw/panoramica.html"

HEADERS = [
    "Brand","Modello","Titolo Promo","Motorizzazione","Rata","Intero","TAN (%)","TAEG (%)",
    "Scadenza","Note Legali","Fonte URL","Offer URL","Data Aggiornamento","Data Scansione",
    "Last Seen","Stato","Alert Type","Promo Hash","Extraction Confidence","Run ID","Note Tecniche"
]

URLS = [
    ("Serie 3 Touring", "BMW Serie 3 Touring 320d xDrive M Sport", "diesel", "https://www.bmw.it/it/gamma/serie-3/bmw-serie-3-touring/bmw-serie-3-touring.html#offerta"),
    ("X1", "BMW X1 sDrive18d M Sport", "diesel", "https://www.bmw.it/it/gamma/x/x1/bmw-x1.html#offerta"),
    ("X3", "BMW X3 xDrive20d M Sport", "diesel", "https://www.bmw.it/it/gamma/x/x3/bmw-x3.html#offerta"),
    ("X5", "BMW X5 xDrive30d M Sport", "diesel", "https://www.bmw.it/it/gamma/x/x5/bmw-x5.html#offerta"),
    ("X6", "BMW X6 xDrive30d M Sport", "diesel", "https://www.bmw.it/it/gamma/x/x6/bmw-x6.html#offerta"),
    ("iX", "BMW iX xDrive45 M Sport", "elettrica", "https://www.bmw.it/it/gamma/i-series/ix/bmw-ix.html#offerta"),
    ("i4", "BMW i4 eDrive40 M Sport Edition", "elettrica", "https://www.bmw.it/it/gamma/i-series/i4/bmw-i4-gran-coupe.html#offerta"),
    ("iX1", "BMW iX1 eDrive20 M Sport", "elettrica", "https://www.bmw.it/it/gamma/i-series/ix1/bmw-ix1.html#offerta"),
    ("iX3", "Nuova BMW iX3 50 xDrive M Sport", "elettrica", "https://www.bmw.it/it/gamma/x/ix3/bmw-ix3.html#offerta"),
]

def parse_num(s):
    if not s:
        return None
    s = str(s).replace("€", "").strip()
    m = re.search(r"\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?", s)
    if not m:
        return None
    n = m.group(0).replace(".", "").replace(",", ".")
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

def find1(patterns, text):
    for pat in patterns:
        m = re.search(pat, text, re.I | re.S)
        if m:
            return m.group(1)
    return ""

def active(scad):
    try:
        return datetime.strptime(scad, "%d/%m/%Y").date() >= datetime.now().date()
    except:
        return True

def extract_note(body):
    low = body.lower()

    start = low.find("*un esempio rappresentativo")
    if start == -1:
        start = low.find("un esempio rappresentativo")
    if start == -1:
        start = low.find("leasing finanziario")

    if start == -1:
        return ""

    sub = body[start:]

    stops = [
        "\nNoleggio a lungo termine",
        "\nBack to Navigation",
        "\nCostruita per",
        "\nPiacere di guidare",
        "\nBMW SERVICE",
        "\nL'App My BMW",
    ]

    end = len(sub)
    for stop in stops:
        i = sub.find(stop)
        if i != -1 and i > 500:
            end = min(end, i)

    return sub[:end].strip()

def parse_page(page, modello, title, motore, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(9000)

    body = page.evaluate("() => document.body.innerText")
    note = extract_note(body)
    source = note if note else body

    rata_raw = find1([
        r"A\s+partire\s+da\s*([\d\.,]+)\s*€\s+al\s+mese",
        r"Primo\s+canone[^€]{0,80}€\s*([\d\.,]+)",
        r"canoni\s+mensili[^€]{0,80}€\s*([\d\.,]+)",
    ], source)

    intero_raw = find1([
        r"Prezzo\s+auto\s+proposto\s+dalle\s+Concessionarie\s+aderenti\s*€\s*([\d\.,]+)",
    ], source)

    tan_raw = find1([
        r"Tasso\s+Leasing\s*([\d\.,]+)\s*%",
    ], source)

    taeg_raw = find1([
        r"TAEG\s*([\d\.,]+)\s*%",
    ], source)

    scad = find1([
        r"Offerta\s+valida\s+fino\s+al\s+(\d{2}/\d{2}/\d{4})",
        r"Offerta\s+valida\s+fino\s+al\s+(\d{2}\.\d{2}\.\d{4})",
    ], source).replace(".", "/") or "30/06/2026"

    extras = []

    anticipo = find1([r"Anticipo\s+o\s+eventuale\s+permuta\s*€\s*([\d\.,]+)"], source)
    if anticipo:
        extras.append("anticipo € " + anticipo)

    durata = find1([r"Durata\s+di\s+(\d+)\s+mesi", r"Durata:\s*(\d+)\s+mesi"], source)
    if durata:
        extras.append(durata + " mesi")

    canoni = find1([r"con\s+(\d+)\s+canoni\s+mensili"], source)
    if canoni:
        extras.append(canoni + " canoni")

    finale = find1([
        r"valore\s+futuro\s+garantito[^€]{0,120}€\s*([\d\.,]+)",
        r"Opzione\s+di\s+acquisto[^€]{0,120}€\s*([\d\.,]+)",
    ], source)
    if finale:
        extras.append("rata_finale € " + finale)

    credito = find1([r"Importo\s+totale\s+del\s+credito\s*€\s*([\d\.,]+)"], source)
    if credito:
        extras.append("importo_totale_credito € " + credito)

    dovuto = find1([r"Importo\s+totale\s+dovuto\s+dal\s+Cliente\s*€\s*([\d\.,]+)"], source)
    if dovuto:
        extras.append("importo_totale_dovuto € " + dovuto)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
        "Offer URL": page.url,
        "Data Aggiornamento": now,
        "Data Scansione": now,
        "Last Seen": now,
        "Stato": "attiva",
        "Alert Type": "",
        "Promo Hash": "",
        "Extraction Confidence": "high",
        "Run ID": run_id,
        "Note Tecniche": "",
    }

    missing = []
    if not row["Rata"]: missing.append("missing_rata")
    if not row["Intero"]: missing.append("missing_intero")
    if not row["TAN (%)"]: missing.append("missing_tan")
    if not row["TAEG (%)"]: missing.append("missing_taeg")
    if not row["Note Legali"]: missing.append("missing_note_legali")

    if missing:
        row["Stato"] = "incompleta"
        row["Extraction Confidence"] = "medium"

    row["Note Tecniche"] = "; ".join(extras + missing)

    raw = "|".join([row["Brand"], row["Modello"], row["Titolo Promo"], row["Rata"], row["Intero"], row["TAN (%)"], row["TAEG (%)"], row["Scadenza"], row["Offer URL"]])
    row["Promo Hash"] = hashlib.md5(raw.encode("utf-8")).hexdigest()

    return row

def build_rows():
    run_id = "bmw_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,args=["--no-sandbox"])
        page = browser.new_page(viewport={"width":1366,"height":5200})

        for modello, title, motore, url in URLS:
            r = parse_page(page, modello, title, motore, url, run_id)
            rows.append(r)
            print(
                r["Modello"], "|",
                r["Rata"], "|",
                r["Intero"], "|",
                r["TAN (%)"], "|",
                r["TAEG (%)"], "|",
                r["Scadenza"], "|",
                r["Stato"], "|",
                r["Offer URL"], "|",
                r["Note Tecniche"]
            )

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
    print("RIGHE BMW SCRITTE:", len(rows))
    print("SHEET AGGIORNATO")
