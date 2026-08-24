from playwright.sync_api import sync_playwright
import re, hashlib
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"
BRAND = "Peugeot"
HUB_URL = "https://www.peugeot.it/acquista/offerte-privati.html"

HEADERS = [
    "Brand","Modello","Titolo Promo","Motorizzazione","Rata","Intero","TAN (%)","TAEG (%)",
    "Scadenza","Note Legali","Fonte URL","Offer URL","Data Aggiornamento","Data Scansione",
    "Last Seen","Stato","Alert Type","Promo Hash","Extraction Confidence","Run ID","Note Tecniche"
]

URLS = [
    ("208", "Peugeot 208 Turbo Benzina 100 Style", "benzina", "https://www.peugeot.it/acquista/offerte-privati/208.html"),
    ("208 Hybrid", "Peugeot 208 Hybrid 100 e-DCS6 Style", "hybrid", "https://www.peugeot.it/acquista/offerte-privati/208-hybrid.html"),
    ("e-208", "Peugeot e-208 Motore 100% elettrica 136cv Style", "elettrica", "https://www.peugeot.it/acquista/offerte-privati/e-208.html"),
    ("2008", "Peugeot 2008 Benzina Turbo 100 Style", "benzina", "https://www.peugeot.it/acquista/offerte-privati/2008.html"),
    ("2008 Hybrid", "Peugeot 2008 Hybrid 110 e-DCS6 Style", "hybrid", "https://www.peugeot.it/acquista/offerte-privati/2008-hybrid.html"),
    ("e-2008", "Peugeot e-2008 100% elettrica 156cv Style", "elettrica", "https://www.peugeot.it/acquista/offerte-privati/e-2008.html"),
    ("308", "Peugeot 308 BL Bluehdi 130 S&S EAT8 Style", "diesel", "https://www.peugeot.it/acquista/offerte-privati/308.html"),
    ("308 Hybrid", "Peugeot 308 Hybrid 145 e-DCS6 Style", "hybrid", "https://www.peugeot.it/acquista/offerte-privati/308-hybrid.html"),
    ("e-308", "Peugeot E-308 BL 100% elettrica 156cv Allure", "elettrica", "https://www.peugeot.it/acquista/offerte-privati/e-308.html"),
    ("308 SW", "Peugeot 308 SW BlueHDi 130 S&S EAT8 Style", "diesel", "https://www.peugeot.it/acquista/offerte-privati/308-sw.html"),
    ("308 SW Hybrid", "Peugeot 308 SW Hybrid 145 e-DCS6 Style", "hybrid", "https://www.peugeot.it/acquista/offerte-privati/308-sw-hybrid.html"),
    ("e-308 SW", "Peugeot E-308 SW 100% elettrica 156cv Allure", "elettrica", "https://www.peugeot.it/acquista/offerte-privati/e-308-sw.html"),
    ("408 Hybrid", "Peugeot 408 Hybrid 145 e-DSC6 Allure", "hybrid", "https://www.peugeot.it/acquista/offerte-privati/408-hybrid.html"),
    ("3008 Hybrid", "Peugeot SUV 3008 Hybrid 145 e-DSC6 - Allure", "hybrid", "https://www.peugeot.it/acquista/offerte-privati/3008-hybrid.html"),
    ("3008 Plug-in Hybrid", "Peugeot SUV 3008 Plug-in Hybrid 195 HP e-DCS7 - Allure", "plug-in", "https://www.peugeot.it/acquista/offerte-privati/3008-plug-in-hybrid.html"),
    ("e-3008", "E-3008 Motore 100% elettrico 210cv Allure", "elettrica", "https://www.peugeot.it/acquista/offerte-privati/e-3008.html"),
    ("5008 Hybrid", "Peugeot SUV 5008 Hybrid 145 e-DSC6 - Allure", "hybrid", "https://www.peugeot.it/acquista/offerte-privati/5008-hybrid.html"),
    ("5008 Plug-in Hybrid", "Peugeot 5008 Plug-in Hybrid 195 HP Allure", "plug-in", "https://www.peugeot.it/acquista/offerte-privati/5008-plug-in-hybrid.html"),
    ("e-5008", "Peugeot e-5008 100% elettrica 210cv Allure", "elettrica", "https://www.peugeot.it/acquista/offerte-privati/e-5008.html"),
    ("Rifter", "Peugeot Rifter STANDARD Blue HDi 1.5 100 cv S&S Allure", "diesel", "https://www.peugeot.it/acquista/offerte-privati/rifter.html"),
]

def parse_number(value):
    if not value:
        return None
    value = str(value).replace("€", "").strip()
    m = re.search(r"\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?", value)
    if not m:
        return None
    n = m.group(0).replace(".", "").replace(",", ".")
    try:
        return float(n)
    except:
        return None

def euro(value):
    n = parse_number(value)
    if n is None:
        return ""
    return "€ " + f"{int(round(n)):,}".replace(",", ".")

def perc(value):
    if value is None or value == "":
        return ""
    return str(value).replace(".", ",").strip() + "%"

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

def normalize_scadenza(text):
    m = re.search(r"Valida\s+fino\s+al\s*(\d{2}/\d{2}/\d{4})", text, re.I)
    if m:
        return m.group(1)
    if re.search(r"Valida\s+fino\s+al\s*30\s+Giugno\s+2026", text, re.I):
        return "30/06/2026"
    return "30/06/2026"

def extract_detail_note(body):
    low = body.lower()

    starts = []
    for needle in ["tua da", "n°", "nº", "tan"]:
        i = low.find(needle)
        if i != -1:
            starts.append(i)

    if not starts:
        return ""

    start = min(starts)
    sub = body[start:]

    end = len(sub)
    for stop in ["\nNota legale e consumi", "\n TROVA UN PUNTO VENDITA", "\nTROVA UN PUNTO VENDITA"]:
        i = sub.find(stop)
        if i != -1 and i > 80:
            end = min(end, i)

    return sub[:end].strip()

def parse_page(page, modello, title, motore, url, run_id):
    page.goto(url, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(4000)

    # prova standard: click nota, ma Peugeot non espande nota finanziaria in headless.
    try:
        loc = page.get_by_text("Nota legale e consumi", exact=False)
        if loc.count() > 0:
            loc.first.click(timeout=5000, force=True)
            page.wait_for_timeout(1500)
    except Exception:
        pass

    body = page.evaluate("() => document.body.innerText")
    note = extract_detail_note(body)
    source = note if note else body

    rata_raw = find1([
        r"n[°º]?\s*\d+\s+rate\s+da\s*([\d\.,]+)\s*€",
        r"n[°º]?\s*\d+\s+canoni\s+da\s*([\d\.,]+)\s*€",
        r"\d+\s+rate\s+da\s*([\d\.,]+)\s*€",
        r"\d+\s+canoni\s+da\s*([\d\.,]+)\s*€",
        r"Da\s*([\d\.,]+)\s*€\s+al\s+mese",
    ], source)

    intero_raw = find1([
        r"Tua\s+da\s*([\d\.,]+)\s*€",
        r"Subito\s+tua\s+da\s*([\d\.,]+)\s*€",
        r"Prezzo\s+promo[^€]{0,140}€\s*([\d\.,]+)",
    ], source)

    tan_raw = find1([
        r"TAN\s*\(fisso\)\s*([\d\.,]+)\s*%",
        r"TAN\s*([\d\.,]+)\s*%",
    ], source)

    taeg_raw = find1([
        r"TAEG\s*([\d\.,]+)\s*%",
    ], source)

    scad = normalize_scadenza(source)

    extras = ["detail_page_checked"]
    if not re.search(r"Importo\s+Totale|Messaggio\s+Pubblicitario|Annuncio\s+pubblicitario", body, re.I):
        extras.append("detail_page_no_extended_legal_found")

    anticipo = find1([r"Anticipo\s*([\d\.,]+)\s*€", r"Primo\s+Canone\s+Anticipato\s*([\d\.,]+)\s*€"], source)
    if anticipo:
        extras.append("anticipo € " + anticipo)

    rate_n = find1([
        r"n[°º]?\s*(\d+)\s+rate",
        r"n[°º]?\s*(\d+)\s+canoni",
        r"(\d+)\s+rate\s+da",
        r"(\d+)\s+canoni\s+da",
    ], source)
    if rate_n:
        extras.append(rate_n + " rate")

    finale = find1([
        r"Rata\s+Finale\s*([\d\.,]+)\s*€",
        r"Valore\s+di\s+Riscatto\s*([\d\.,]+)\s*€",
    ], source)
    if finale:
        extras.append("rata_finale € " + finale)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = {
        "Brand": BRAND,
        "Modello": modello,
        "Titolo Promo": title,
        "Motorizzazione": motore,
        "Rata": euro(rata_raw),
        "Intero": euro(intero_raw),
        "TAN (%)": perc(tan_raw),
        "TAEG (%)": perc(taeg_raw),
        "Scadenza": scad,
        "Note Legali": note,
        "Fonte URL": HUB_URL,
        "Offer URL": url,
        "Data Aggiornamento": now,
        "Data Scansione": now,
        "Last Seen": now,
        "Stato": "attiva" if active(scad) else "scaduta",
        "Alert Type": "",
        "Promo Hash": "",
        "Extraction Confidence": "high",
        "Run ID": run_id,
        "Note Tecniche": "",
    }

    missing = []
    if not row["Rata"]: missing.append("missing_rata")
    if not row["TAN (%)"]: missing.append("missing_tan")
    if not row["TAEG (%)"]: missing.append("missing_taeg")
    if not row["Note Legali"]: missing.append("missing_note_legali")
    # Intero può mancare nelle formule canone/elettriche: non lo usiamo per stato incompleta.
    if not row["Intero"]:
        extras.append("missing_intero_not_declared_in_detail")

    if missing and row["Stato"] == "attiva":
        row["Stato"] = "incompleta"
        row["Extraction Confidence"] = "medium"

    row["Note Tecniche"] = "; ".join(extras + missing)

    raw = "|".join([row["Brand"], row["Modello"], row["Titolo Promo"], row["Rata"], row["Intero"], row["TAN (%)"], row["TAEG (%)"], row["Scadenza"], row["Offer URL"]])
    row["Promo Hash"] = hashlib.md5(raw.encode("utf-8")).hexdigest()

    return row

def build_rows():
    run_id = "peugeot_detail_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,args=["--no-sandbox"])
        page = browser.new_page(viewport={"width":1366,"height":7000})

        for modello, title, motore, url in URLS:
            r = parse_page(page, modello, title, motore, url, run_id)
            rows.append(r)
            print(r["Modello"], "|", r["Rata"], "|", r["Intero"], "|", r["TAN (%)"], "|", r["TAEG (%)"], "|", r["Scadenza"], "|", r["Stato"], "|", r["Note Tecniche"])

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
    print("RIGHE PEUGEOT SCRITTE:", len(rows))
    print("SHEET AGGIORNATO")
