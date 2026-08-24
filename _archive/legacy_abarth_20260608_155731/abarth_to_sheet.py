from playwright.sync_api import sync_playwright
import re, hashlib
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"
BRAND = "Abarth"
HUB_URL = "https://www.abarth.it/offerte"

HEADERS = [
    "Brand","Modello","Titolo Promo","Motorizzazione","Rata","Intero","TAN (%)","TAEG (%)",
    "Scadenza","Note Legali","Fonte URL","Offer URL","Data Aggiornamento","Data Scansione",
    "Last Seen","Stato","Alert Type","Promo Hash","Extraction Confidence","Run ID","Note Tecniche"
]

def clean(t):
    return re.sub(r"\s+", " ", t or "").strip()

def parse_num(s):
    if not s:
        return None
    s = str(s).replace("€","").replace(".","").replace(",",".").strip()
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

def normalize_date_from_text(t):
    mesi = {
        "gennaio":"01","febbraio":"02","marzo":"03","aprile":"04","maggio":"05","giugno":"06",
        "luglio":"07","agosto":"08","settembre":"09","ottobre":"10","novembre":"11","dicembre":"12"
    }

    m = re.search(r"fino\s+al\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})", t, re.I)
    if m and m.group(2).lower() in mesi:
        return f"{m.group(1).zfill(2)}/{mesi[m.group(2).lower()]}/{m.group(3)}"

    m = re.search(r"fino\s+al\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]+)", t, re.I)
    if m and m.group(2).lower() in mesi:
        return f"{m.group(1).zfill(2)}/{mesi[m.group(2).lower()]}/{datetime.now().year}"

    return ""

def active(scad):
    try:
        return datetime.strptime(scad, "%d/%m/%Y").date() >= datetime.now().date()
    except:
        return False

def motore_from_text(t):
    l = t.lower()
    if "elettrica" in l or "elettrico" in l or "500e" in l or "600e" in l:
        return "elettrica"
    return ""

def modello_from_url_title(url, body):
    s = (url + " " + body[:500]).lower()
    if "600e" in s:
        return "600e"
    if "500e" in s:
        return "500e"
    return ""

def title_from_body(body, url):
    lines = [x.strip() for x in body.splitlines() if x.strip()]
    for i, l in enumerate(lines[:30]):
        u = l.upper()
        if u in ["500E", "NUOVA ABARTH 600E"]:
            return "Abarth " + l.replace("NUOVA ABARTH ", "")
    model = modello_from_url_title(url, body)
    return "Abarth " + model if model else "Abarth"

def extract_note(body):
    idx = body.find("DETTAGLIO PROMOZIONE")
    if idx == -1:
        return ""

    sub = body[idx:]

    stops = [
        "\nDESIDERO RICHIEDERE",
        "\nALTRE PROMOZIONI",
        "\nMODELLI",
        "\nACQUISTO",
        "\nCLIENTI",
    ]

    end = len(sub)
    for s in stops:
        i = sub.find(s)
        if i != -1 and i > 200:
            end = min(end, i)

    sub = sub[:end].strip()

    cidx = -1
    for p in ["Consumo di", "Consumo energia", "Emissioni CO2"]:
        i = sub.find(p)
        if i != -1 and i > 100:
            if cidx == -1 or i < cidx:
                cidx = i

    if cidx != -1:
        promo = sub[:cidx].strip()
        consumi = sub[cidx:].strip()
        return promo + "\n\nCONSUMI ED EMISSIONI\n\n" + consumi

    return sub

def extract_links(page):
    page.goto(HUB_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)

    links = page.locator("a").evaluate_all("""
        els => [...new Set(
            els.map(a => String(a.href || '')).filter(h =>
                h.includes('/offerte/')
                && !h.endsWith('/offerte')
                && !h.endsWith('/offerte#')
                && !h.includes('domande')
            ).map(h => h.split('#')[0])
        )]
    """)

    return list(dict.fromkeys(links))

def parse_detail(page, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)

    body = page.locator("body").inner_text(timeout=30000)
    note = extract_note(body)
    source = note or body

    modello = modello_from_url_title(url, body)
    titolo = title_from_body(body, url)
    motore = motore_from_text(titolo + " " + source)

    rata = ""
    m = re.search(r"(\d+)\s*€\s*AL\s*MESE", body, re.I)
    if not m:
        m = re.search(r"rate\s+da\s*([\d\.,]+)\s*€", source, re.I)
    if m:
        rata = euro_from_str(m.group(1))

    intero = ""
    m = re.search(r"promo\s*:?\s*€\s*([\d\.,]+)", source, re.I)
    if not m:
        m = re.search(r"promo\s*:?\s*([\d\.,]+)\s*€", source, re.I)
    if m:
        intero = euro_from_str(m.group(1))

    tan = ""
    taeg = ""
    m = re.search(r"TAN\s*\(?(?:fisso)?\)?\s*([\d\.,]+)\s*%", source, re.I)
    if m:
        tan = perc(m.group(1))
    m = re.search(r"TAEG\s*([\d\.,]+)\s*%", source, re.I)
    if m:
        taeg = perc(m.group(1))

    scad = normalize_date_from_text(source or body)

    missing = []
    if not rata: missing.append("rata")
    if not intero: missing.append("intero")
    if not tan: missing.append("tan")
    if not taeg: missing.append("taeg")
    if not scad: missing.append("scadenza")
    if not note: missing.append("note_legali")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stato = "attiva" if active(scad) else "scaduta"
    if missing and stato == "attiva":
        stato = "incompleta"

    row = {
        "Brand": BRAND,
        "Modello": modello,
        "Titolo Promo": titolo,
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
        "Note Tecniche": "; ".join([f"missing_{x}" for x in missing])
    }

    raw = "|".join([row["Brand"], row["Modello"], row["Titolo Promo"], row["Rata"], row["Intero"], row["Scadenza"], row["Offer URL"]])
    row["Promo Hash"] = hashlib.md5(raw.encode("utf-8")).hexdigest()

    return row

def build_rows():
    run_id = "abarth_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,args=["--no-sandbox"])
        page = browser.new_page(viewport={"width":1366,"height":2400})
        detail = browser.new_page(viewport={"width":1366,"height":2400})

        links = extract_links(page)
        print("LINK ABARTH:", len(links))

        for u in links:
            r = parse_detail(detail, u, run_id)
            rows.append(r)
            print(r["Modello"], "|", r["Titolo Promo"], "|", r["Rata"], "|", r["Intero"], "|", r["TAN (%)"], "|", r["TAEG (%)"], "|", r["Scadenza"], "|", r["Note Tecniche"])

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
    print("RIGHE ABARTH SCRITTE:", len(rows))
    print("SHEET AGGIORNATO")
