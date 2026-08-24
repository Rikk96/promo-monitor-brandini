from playwright.sync_api import sync_playwright
import re, hashlib
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"
BRAND = "Opel"
URL = "https://www.opel.it/offerte/privati.html"

HEADERS = [
    "Brand","Modello","Titolo Promo","Motorizzazione","Rata","Intero","TAN (%)","TAEG (%)",
    "Scadenza","Note Legali","Fonte URL","Offer URL","Data Aggiornamento","Data Scansione",
    "Last Seen","Stato","Alert Type","Promo Hash","Extraction Confidence","Run ID","Note Tecniche"
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

def motore(title, block=""):
    t = (title + " " + block[:250]).lower()
    if "electric" in t or "elettrica" in t:
        return "elettrica"
    if "plug" in t:
        return "plug-in"
    if "hybrid" in t:
        return "hybrid"
    if "diesel" in t:
        return "diesel"
    if "benzina" in t:
        return "benzina"
    return ""

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

def extract_offer_blocks(text):
    raw = re.split(r"Scopri l'offerta", text, flags=re.I)
    blocks = []

    for chunk in raw:
        chunk = chunk.strip()
        if not chunk:
            continue

        # tieni solo offerte finanziarie reali, non menu/footer
        if "TAN" not in chunk or "TAEG" not in chunk:
            continue
        if "Fino al" not in chunk and "fino al" not in chunk:
            continue

        lines = [x.strip() for x in chunk.splitlines() if x.strip()]
        title = ""

        # Titolo: di solito è la riga subito prima di "Edition".
        for i, line in enumerate(lines):
            if line.lower() == "edition" and i > 0:
                title = lines[i-1]
                break

        # Fallback/forzature: evita di prendere voci menu sopra il primo blocco.
        if "Corsa Benzina" in chunk:
            title = "Corsa Benzina"

        if not title:
            candidates = []
            for line in lines[:20]:
                low = line.lower()
                if any(x in low for x in ["corsa", "mokka", "frontera", "astra", "grandland", "zafira", "combo"]):
                    candidates.append(line)
            if candidates:
                title = candidates[-1]
            elif lines:
                title = lines[0]

        # escludi noleggi/canoni vecchi al 30/04/2026 senza TAN/TAEG finanziario utile
        scad = find1([r"Fino al\s*(\d{2}/\d{2}/\d{4})"], chunk)
        if scad and scad != "30/06/2026":
            continue

        blocks.append((title, chunk))

    return blocks

def parse_block(title, block):
    rata_raw = find1([
        r"n[°º]?\s*\d+\s+rate\s+da\s*([\d\.,]+)\s*€",
        r"Da\s*([\d\.,]+)\s*€\s+al\s+mese",
        r"([\d\.,]+)\s*€\s+al\s+mese",
    ], block)

    intero_raw = find1([
        r"Prezzo\s+promo\s+oltre\s+oneri\s+finanziari:\s*([\d\.,]+)\s*€",
        r"Prezzo\s+promo[^€]{0,120}€\s*([\d\.,]+)",
        r"Prezzo\s+promozionale[^€]{0,120}€\s*([\d\.,]+)",
    ], block)

    tan_raw = find1([
        r"TAN\s*\(Fisso\)\s*([\d\.,]+)\s*%",
        r"TAN\s*([\d\.,]+)\s*%",
    ], block)

    taeg_raw = find1([
        r"TAEG\s*([\d\.,]+)\s*%",
    ], block)

    scad = find1([
        r"Fino al\s*(\d{2}/\d{2}/\d{4})",
        r"fino al\s*(\d{2}/\d{2}/\d{4})",
    ], block) or "30/06/2026"

    extras = []
    anticipo = find1([r"Anticipo\s*([\d\.,]+)\s*€"], block)
    if anticipo:
        extras.append("anticipo € " + anticipo)

    rate_n = find1([r"n[°º]?\s*(\d+)\s+rate", r"(\d+)\s+rate\s+mensili", r"(\d+)\s+canoni\s+mensili"], block)
    if rate_n:
        extras.append(rate_n + " rate")

    finale = find1([
        r"Rata\s+finale\s*([\d\.,]+)\s*€",
        r"Valore\s+di\s+Riscatto\s*([\d\.,]+)\s*€",
        r"Valore\s+Futuro\s+Garantito[^€]{0,120}€\s*([\d\.,]+)",
    ], block)
    if finale:
        extras.append("rata_finale € " + finale)

    return {
        "title": title,
        "motorizzazione": motore(title, block),
        "rata": rata_raw,
        "intero": intero_raw,
        "tan": tan_raw,
        "taeg": taeg_raw,
        "scadenza": scad,
        "note": block,
        "extras": extras
    }

def build_rows():
    run_id = "opel_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    out = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,args=["--no-sandbox"])
        page = browser.new_page(viewport={"width":1366,"height":5200})
        page.goto(URL, wait_until="networkidle", timeout=90000)
        text = page.evaluate("() => document.body.innerText")
        browser.close()

    blocks = extract_offer_blocks(text)
    print("BLOCCHI OPEL:", len(blocks))

    for title, block in blocks:
        r = parse_block(title, block)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        row = {
            "Brand": BRAND,
            "Modello": r["title"],
            "Titolo Promo": r["title"],
            "Motorizzazione": r["motorizzazione"],
            "Rata": euro(r["rata"]),
            "Intero": euro(r["intero"]),
            "TAN (%)": perc(r["tan"]),
            "TAEG (%)": perc(r["taeg"]),
            "Scadenza": r["scadenza"],
            "Note Legali": r["note"],
            "Fonte URL": URL,
            "Offer URL": URL,
            "Data Aggiornamento": now,
            "Data Scansione": now,
            "Last Seen": now,
            "Stato": "attiva" if active(r["scadenza"]) else "scaduta",
            "Alert Type": "",
            "Promo Hash": "",
            "Extraction Confidence": "high",
            "Run ID": run_id,
            "Note Tecniche": "",
        }

        missing = []
        if not row["Rata"]: missing.append("missing_rata")
        # per alcune Opel Blitz/elettriche può mancare prezzo promo nella nota; lasciamo incompleta
        if not row["Intero"]: missing.append("missing_intero")
        if not row["TAN (%)"]: missing.append("missing_tan")
        if not row["TAEG (%)"]: missing.append("missing_taeg")
        if not row["Note Legali"]: missing.append("missing_note_legali")

        if missing and row["Stato"] == "attiva":
            row["Stato"] = "incompleta"
            row["Extraction Confidence"] = "medium"

        row["Note Tecniche"] = "; ".join(r["extras"] + missing)

        raw = "|".join([row["Brand"], row["Modello"], row["Titolo Promo"], row["Rata"], row["Intero"], row["TAN (%)"], row["TAEG (%)"], row["Scadenza"], row["Offer URL"]])
        row["Promo Hash"] = hashlib.md5(raw.encode("utf-8")).hexdigest()

        out.append(row)

        print(row["Modello"], "|", row["Rata"], "|", row["Intero"], "|", row["TAN (%)"], "|", row["TAEG (%)"], "|", row["Scadenza"], "|", row["Stato"], "|", row["Note Tecniche"])

    return out

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
    print("RIGHE OPEL SCRITTE:", len(rows))
    print("SHEET AGGIORNATO")
