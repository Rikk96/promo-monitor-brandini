from playwright.sync_api import sync_playwright
import re, hashlib
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"
BRAND = "Leapmotor"
HUB_URL = "https://www.leapmotor.net/it"

HEADERS = [
    "Brand","Modello","Titolo Promo","Motorizzazione","Rata","Intero","TAN (%)","TAEG (%)",
    "Scadenza","Note Legali","Fonte URL","Offer URL","Data Aggiornamento","Data Scansione",
    "Last Seen","Stato","Alert Type","Promo Hash","Extraction Confidence","Run ID","Note Tecniche"
]

MODEL_URLS = {
    "T03": "https://www.leapmotor.net/it/t03",
    "B10": "https://www.leapmotor.net/it/b10-reev-hybrid",
    "C10": "https://www.leapmotor.net/it/c10-reev-hybrid",
    "B05": "https://www.leapmotor.net/it/b05",
}

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
        return False

def modello_from_block(block):
    u = block.upper()
    if "T03" in u:
        return "T03"
    if "B10" in u:
        return "B10"
    if "C10" in u:
        return "C10"
    if "B05" in u:
        return "B05"
    return "Leapmotor"

def motore_from_block(block):
    u = block.upper()
    if "REEV" in u or "HYBRID" in u:
        return "hybrid"
    return "elettrica"

def split_note_consumi(block):
    cidx = -1
    for p in ["Consumo di energia", "Consumo"]:
        i = block.find(p)
        if i != -1:
            if cidx == -1 or i < cidx:
                cidx = i

    if cidx != -1:
        promo = block[:cidx].strip()
        consumi = block[cidx:].strip()
        return promo + "\n\nCONSUMI ED EMISSIONI\n\n" + consumi

    return block.strip()

def parse_home_block(block, run_id):
    modello = modello_from_block(block)
    motore = motore_from_block(block)

    if modello == "T03":
        titolo = "T03"
    elif modello == "B10":
        titolo = "B10 REEV HYBRID Life"
    elif modello == "C10":
        titolo = "C10 REEV HYBRID Life"
    elif modello == "B05":
        titolo = "B05 Life"
    else:
        titolo = modello

    intero = ""
    m = re.search(r"Prezzo\s+Promo\s*([\d\.,]+)\s*€", block, re.I)
    if m:
        intero = euro_from_str(m.group(1))

    scad = ""
    m = re.search(r"fino\s+al\s*(\d{2}/\d{2}/\d{4})", block, re.I)
    if m:
        scad = m.group(1)

    note = split_note_consumi(block)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "Brand": BRAND,
        "Modello": modello,
        "Titolo Promo": titolo,
        "Motorizzazione": motore,
        "Rata": "",
        "Intero": intero,
        "TAN (%)": "",
        "TAEG (%)": "",
        "Scadenza": scad,
        "Note Legali": note,
        "Fonte URL": HUB_URL,
        "Offer URL": MODEL_URLS.get(modello, HUB_URL),
        "Data Aggiornamento": now,
        "Data Scansione": now,
        "Last Seen": now,
        "Stato": "",
        "Alert Type": "",
        "Promo Hash": "",
        "Extraction Confidence": "medium",
        "Run ID": run_id,
        "Note Tecniche": ""
    }

def extract_financial(page, modello):
    url = MODEL_URLS.get(modello, HUB_URL)
    out = {
        "rata": "",
        "tan": "",
        "taeg": "",
        "scadenza": "",
        "extra": "",
        "url": url,
    }

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    text = page.locator("body").inner_text(timeout=30000)

    m = re.search(r"(\d+)\s*€\s*/\s*mese", text, re.I)
    if m:
        out["rata"] = euro_from_str(m.group(1))

    if not out["rata"]:
        m = re.search(r"(\d+)\s*rate\s+da\s+(\d+)\s*€", text, re.I)
        if m:
            out["rata"] = euro_from_str(m.group(2))

    m = re.search(r"TAN\s*\(fisso\)\s*([\d\.,]+)\s*%", text, re.I)
    if m:
        out["tan"] = perc(m.group(1))

    m = re.search(r"TAEG\s*([\d\.,]+)\s*%", text, re.I)
    if m:
        out["taeg"] = perc(m.group(1))

    m = re.search(r"Valida\s+fino\s+al\s*(\d{2}/\d{2}/\d{4})", text, re.I)
    if m:
        out["scadenza"] = m.group(1)

    extras = []
    m = re.search(r"(\d+)\s*rate\s+da\s+(\d+)\s*€", text, re.I)
    if m:
        extras.append(f"{m.group(1)} rate")
    m = re.search(r"Anticipo\s*([\d\.,]+)\s*€", text, re.I)
    if m:
        extras.append("anticipo € " + m.group(1))
    m = re.search(r"Rata\s+Finale\s*([\d\.,]+)\s*€", text, re.I)
    if m:
        extras.append("rata_finale € " + m.group(1))

    out["extra"] = "; ".join(extras)
    return out

def build_rows():
    run_id = "leapmotor_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,args=["--no-sandbox"])
        hub = browser.new_page(viewport={"width":1366,"height":2600})
        detail = browser.new_page(viewport={"width":1366,"height":2600})

        hub.goto(HUB_URL, wait_until="domcontentloaded", timeout=60000)
        hub.wait_for_timeout(7000)

        text = hub.locator("body").inner_text(timeout=30000)
        starts = [m.start() for m in re.finditer(r"DETTAGLIO PROMOZIONE", text, re.I)]
        print("BLOCCHI LEAPMOTOR:", len(starts))

        rows = []

        for idx, s in enumerate(starts):
            e = starts[idx+1] if idx+1 < len(starts) else len(text)
            block = text[s:e].strip()

            for stop in ["Data Act", "Informazioni Legali", "Chatta con noi", "CONTINUA SENZA ACCETTARE"]:
                j = block.find(stop)
                if j != -1 and j > 300:
                    block = block[:j].strip()

            row = parse_home_block(block, run_id)
            fin = extract_financial(detail, row["Modello"])

            row["Rata"] = fin["rata"]
            row["TAN (%)"] = fin["tan"]
            row["TAEG (%)"] = fin["taeg"]
            row["Scadenza"] = fin["scadenza"] or row["Scadenza"]
            row["Offer URL"] = fin["url"]

            missing = []
            if not row["Rata"]: missing.append("rata")
            if not row["TAN (%)"]: missing.append("tan")
            if not row["TAEG (%)"]: missing.append("taeg")
            if not row["Intero"]: missing.append("intero")
            if not row["Scadenza"]: missing.append("scadenza")
            if not row["Note Legali"]: missing.append("note_legali")

            tecniche = []
            if fin["extra"]:
                tecniche.append(fin["extra"])
            tecniche += [f"missing_{x}" for x in missing]

            row["Note Tecniche"] = "; ".join(tecniche)
            row["Stato"] = "attiva" if active(row["Scadenza"]) else "scaduta"
            if missing and row["Stato"] == "attiva":
                row["Stato"] = "incompleta"

            row["Extraction Confidence"] = "high" if not missing else "medium"

            raw = "|".join([
                row["Brand"], row["Modello"], row["Titolo Promo"], row["Rata"],
                row["Intero"], row["TAN (%)"], row["TAEG (%)"], row["Scadenza"], row["Offer URL"]
            ])
            row["Promo Hash"] = hashlib.md5(raw.encode("utf-8")).hexdigest()

            rows.append(row)

            print(
                row["Modello"], "|",
                row["Titolo Promo"], "|",
                row["Motorizzazione"], "|",
                row["Rata"], "|",
                row["Intero"], "|",
                row["TAN (%)"], "|",
                row["TAEG (%)"], "|",
                row["Scadenza"], "|",
                row["Note Tecniche"]
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
    print("RIGHE LEAPMOTOR SCRITTE:", len(rows))
    print("SHEET AGGIORNATO")
