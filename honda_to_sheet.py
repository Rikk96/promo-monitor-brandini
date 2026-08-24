from playwright.sync_api import sync_playwright
import re, hashlib
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"
BRAND = "Honda"
HUB_URL = "https://www.honda.it/cars/offers.html"

HEADERS = [
    "Brand","Modello","Titolo Promo","Motorizzazione","Rata","Intero","TAN (%)","TAEG (%)",
    "Scadenza","Note Legali","Fonte URL","Offer URL","Data Aggiornamento","Data Scansione",
    "Last Seen","Stato","Alert Type","Promo Hash","Extraction Confidence","Run ID","Note Tecniche"
]

URLS = [
    ("Jazz", "NUOVA JAZZ FULL HYBRID", "hybrid", "https://www.honda.it/cars/new/jazz-hybrid/offers/jazz-hybrid.html"),
    ("Jazz Crosstar", "NUOVA JAZZ CROSSTAR FULL HYBRID", "hybrid", "https://www.honda.it/cars/new/jazz-hybrid/offers/jazz-crosstar.html"),
    ("HR-V", "HONDA HR-V FULL HYBRID", "hybrid", "https://www.honda.it/cars/new/hr-v-hybrid/offers/offerte.html"),
    ("Civic", "HONDA CIVIC FULL HYBRID", "hybrid", "https://www.honda.it/cars/new/civic-hybrid/offers/offerte.html"),
    ("ZR-V", "HONDA ZR-V FULL HYBRID", "hybrid", "https://www.honda.it/cars/new/zr-v-hybrid-suv/offers/zr-v.html"),
    ("CR-V", "HONDA CR-V FULL HYBRID", "hybrid", "https://www.honda.it/cars/new/cr-v-hybrid-suv/offers/cr-v-full-hybrid.html"),
    ("CR-V", "HONDA CR-V PLUG-IN HYBRID", "plug-in", "https://www.honda.it/cars/new/cr-v-hybrid-suv/offers/cr-v-plug-in-hybrid.html"),
]

def clean(t):
    return re.sub(r"\s+", " ", t or "").strip()

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
    start = low.find("*esempio di offerta")
    if start == -1:
        start = low.find("esempio di offerta")
    if start == -1:
        start = low.find("offerta valida fino")
    if start == -1:
        return ""

    sub = body[start:]

    stops = [
        "\nRichiedi subito",
        "\nRICHIEDI UNA PROVA",
        "\nRICHIEDI PREVENTIVO",
        "\nVuoi saperne",
        "\nConfiguratore",
        "\nHonda\nAuto",
        "\nInformativa",
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

    intero = ""
    m = re.search(r"prezzo\s+promozionale\s+([\d\.,]+)\s*€", note, re.I)
    if m:
        intero = euro_from_str(m.group(1))

    rata = ""
    m = re.search(r"(\d+)\s+rate\s+da\s+([\d\.,]+)\s*€", note, re.I)
    if m:
        rata = euro_from_str(m.group(2))

    tan = ""
    taeg = ""
    m = re.search(r"TAN\s+FISSO\s+([\d\.,]+)\s*%", note, re.I)
    if m:
        tan = perc(m.group(1))
    m = re.search(r"TAEG\s+([\d\.,]+)\s*%", note, re.I)
    if m:
        taeg = perc(m.group(1))

    scad = ""
    m = re.search(r"Offerta valida fino al\s+(\d{2}/\d{2}/\d{4})", note, re.I)
    if m:
        scad = m.group(1)
    if not scad:
        scad = "30/06/2026"

    extras = []
    m = re.search(r"anticipo\s+di\s+([\d\.,]+)\s*€", note, re.I)
    if m:
        extras.append("anticipo € " + m.group(1))
    m = re.search(r"(\d+)\s+rate\s+da\s+([\d\.,]+)\s*€", note, re.I)
    if m:
        extras.append(f"{m.group(1)} rate")
    m = re.search(r"Maxirata\s+finale\s+([\d\.,]+)\s*€", note, re.I)
    if m:
        extras.append("rata_finale € " + m.group(1))
    m = re.search(r"importo\s+totale\s+dovuto[^:]*Opzione\s+Maxirata\s+([\d\.,]+)\s*€", note, re.I)
    if m:
        extras.append("totale_dovuto € " + m.group(1))
    m = re.search(r"importo\s+totale\s+del\s+credito\)\s+in", note, re.I)
    m2 = re.search(r"Finanziamento\s+di\s+([\d\.,]+)\s*€", note, re.I)
    if m2:
        extras.append("importo_totale_credito € " + m2.group(1))

    missing = []
    if not intero: missing.append("intero")
    if "Finanziamento di" in note:
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
    run_id = "honda_" + datetime.now().strftime("%Y%m%d_%H%M%S")
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
    print("RIGHE HONDA SCRITTE:", len(rows))
    print("SHEET AGGIORNATO")
