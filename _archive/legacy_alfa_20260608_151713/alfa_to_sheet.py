from playwright.sync_api import sync_playwright
import re, hashlib
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"
BRAND = "Alfa Romeo"

HEADERS = [
    "Brand","Modello","Titolo Promo","Motorizzazione","Rata","Intero","TAN (%)","TAEG (%)",
    "Scadenza","Note Legali","Fonte URL","Offer URL","Data Aggiornamento","Data Scansione",
    "Last Seen","Stato","Alert Type","Promo Hash","Extraction Confidence","Run ID","Note Tecniche"
]

MODEL_URLS = [
    "https://www.alfaromeo.it/offerte/junior",
    "https://www.alfaromeo.it/offerte/tonale",
    "https://www.alfaromeo.it/offerte/stelvio",
    "https://www.alfaromeo.it/offerte/giulia",
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

def normalize_date(s):
    if not s:
        return ""
    s = s.strip()
    mesi = {
        "gennaio":"01","febbraio":"02","marzo":"03","aprile":"04","maggio":"05","giugno":"06",
        "luglio":"07","agosto":"08","settembre":"09","ottobre":"10","novembre":"11","dicembre":"12"
    }

    m = re.search(r"(\d{2})/(\d{2})/(\d{2,4})", s)
    if m:
        y = m.group(3)
        if len(y) == 2:
            y = "20" + y
        return f"{m.group(1)}/{m.group(2)}/{y}"

    m = re.search(r"(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})", s, re.I)
    if m and m.group(2).lower() in mesi:
        return f"{m.group(1).zfill(2)}/{mesi[m.group(2).lower()]}/{m.group(3)}"

    return ""

def active(scad):
    try:
        return datetime.strptime(scad, "%d/%m/%Y").date() >= datetime.now().date()
    except:
        return False

def motore_from_text(t):
    l = t.lower()
    if "elettrica" in l or "elettrico" in l:
        return "elettrica"
    if "plug-in" in l or "plugin" in l:
        return "plug-in"
    if "ibrida" in l or "hybrid" in l:
        return "hybrid"
    if "diesel" in l:
        return "diesel"
    if "benzina" in l:
        return "benzina"
    return ""

def modello_from_url(url):
    u = url.lower()
    if "junior" in u:
        return "Junior"
    if "tonale" in u:
        return "Tonale"
    if "stelvio" in u:
        return "Stelvio"
    if "giulia" in u:
        return "Giulia"
    return ""

def title_from_body(body, url):
    lines = [x.strip() for x in body.splitlines() if x.strip()]
    promo_lines = []
    grab = False

    for l in lines[:40]:
        if l.upper() == "FINANZIAMENTO":
            grab = True
            continue
        if grab:
            if l.startswith("DA ") or "Validità:" in l or "Anticipo:" in l:
                break
            if l.upper() not in ["ALFA ROMEO"]:
                promo_lines.append(l)

    title = " ".join(promo_lines)
    title = clean(title)
    if title:
        return title

    return modello_from_url(url)

def extract_note(body):
    idx = body.find("DETTAGLIO PROMOZIONE")
    if idx == -1:
        return ""

    sub = body[idx:]
    stops = [
        "\nTEST DRIVE",
        "\nRICHIEDI INFORMAZIONI",
        "\nTORNA ALLE PROMOZIONI",
        "\nSEGUICI",
    ]

    end = len(sub)
    for s in stops:
        i = sub.find(s)
        if i != -1:
            end = min(end, i)

    note = sub[:end].strip()

    # standardizza consumi
    note = note.replace("\n\n\nConsumo", "\n\nCONSUMI ED EMISSIONI\n\nConsumo")
    note = note.replace("\n\nConsumo", "\n\nCONSUMI ED EMISSIONI\n\nConsumo")

    return note

def parse_detail(page, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    body = page.locator("body").inner_text(timeout=30000)
    note = extract_note(body)
    source = note or body

    titolo = title_from_body(body, url)
    modello = modello_from_url(url)
    motore = motore_from_text(titolo + " " + note)

    rata = ""
    m = re.search(r"(?:rate|canoni)\s+mensili\s*:?\s*da\s*([\d\.,]+)\s*€", body, re.I)
    if not m:
        m = re.search(r"da\s*([\d\.,]+)\s*€\s*/?\s*(?:mese|35 rate)", body, re.I)
    if m:
        rata = euro_from_str(m.group(1))

    intero = ""
    m = re.search(r"Prezzo Promo\s*([\d\.,]+)\s*€", source, re.I)
    if not m:
        m = re.search(r"Prezzo di Listino.*?([\d\.,]+)\s*€", source, re.I)
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

    scad = ""
    m = re.search(r"Validità:\s*(\d{2}/\d{2}/\d{2,4})", body, re.I)
    if m:
        scad = normalize_date(m.group(1))
    if not scad:
        m = re.search(r"(?:valida fino al|fino al)\s*(\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4})", source, re.I)
        if m:
            scad = normalize_date(m.group(1))

    missing = []
    if not rata: missing.append("rata")
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
        "Fonte URL": f"https://www.alfaromeo.it/offerte/{modello.lower()}",
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

def extract_links(page, model_url):
    page.goto(model_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    links = page.locator("a").evaluate_all("""
        els => [...new Set(
            els.map(a => String(a.href || '')).filter(h =>
                h.includes('/offerte/promozione/')
            ).map(h => h.split('#')[0])
        )]
    """)

    return links

def build_rows():
    run_id = "alfa_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,args=["--no-sandbox"])
        page = browser.new_page(viewport={"width":1366,"height":2200})
        detail = browser.new_page(viewport={"width":1366,"height":2200})

        all_links = []
        for mu in MODEL_URLS:
            links = extract_links(page, mu)
            print(mu, "| link:", len(links))
            all_links += links

        all_links = list(dict.fromkeys(all_links))
        print("LINK ALFA TOTALI:", len(all_links))

        for u in all_links:
            r = parse_detail(detail, u, run_id)
            rows.append(r)
            print(r["Modello"], "|", r["Titolo Promo"], "|", r["Motorizzazione"], "|", r["Rata"], "|", r["Intero"], "|", r["TAN (%)"], "|", r["TAEG (%)"], "|", r["Scadenza"])

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
    print("RIGHE ALFA ROMEO SCRITTE:", len(rows))
    print("SHEET AGGIORNATO")
