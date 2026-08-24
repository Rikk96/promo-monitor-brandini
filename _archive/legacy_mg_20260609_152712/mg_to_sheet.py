from playwright.sync_api import sync_playwright
import re, hashlib
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"
BRAND = "MG"
HUB_URL = "https://www.mgmotor.it/campaign"

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

def normalize_date(s):
    if not s:
        return ""
    s = s.strip()
    m = re.search(r"(\d{2})/(\d{2})/(\d{2,4})", s)
    if m:
        y = m.group(3)
        if len(y) == 2:
            y = "20" + y
        return f"{m.group(1)}/{m.group(2)}/{y}"
    return ""

def active(scad):
    try:
        return datetime.strptime(scad, "%d/%m/%Y").date() >= datetime.now().date()
    except:
        return False

def motore_from_text(t):
    l = t.lower()

    # MG: dedurre solo dal titolo promo, non dal menu pagina.
    if "phev" in l or "plug-in" in l or "plug in" in l:
        return "plug-in"

    if "benzina" in l:
        return "benzina"

    if "hybrid+" in l or "hybrid" in l or "hev" in l:
        return "hybrid"

    if "ev" in l or "kwh" in l or "urban" in l or "elettrica" in l:
        return "elettrica"

    return ""

def modello_from_title(title):
    u = title.upper()
    if "MGS5" in u:
        return "MGS5"
    if "MG4" in u:
        return "MG4"
    if "MG HS" in u:
        return "MG HS"
    if "MG ZS" in u:
        return "MG ZS"
    if "MG3" in u:
        return "MG3"
    return "MG"

def extract_links(page):
    page.goto(HUB_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)

    links = page.locator("a").evaluate_all("""
        els => [...new Set(
            els.map(a => String(a.href || '')).filter(h =>
                h.includes('/campaign/')
                && !h.endsWith('/campaign')
                && !h.includes('#')
            )
        )]
    """)

    # tieni solo link promozione, non test drive/configuratori
    bad = ["request-test-drive", "configurator"]
    out = []
    for u in links:
        if any(b in u for b in bad):
            continue
        out.append(u.split("#")[0])

    return list(dict.fromkeys(out))

def title_from_body(body, url):
    lines = [x.strip() for x in body.splitlines() if x.strip()]

    # cerca titolo dopo "Scopri le Offerte MG"
    for i, l in enumerate(lines[:80]):
        if l == "Scopri le Offerte MG" and i + 1 < len(lines):
            return clean(lines[i+1].replace("*", ""))

    # fallback: prima riga con MG significativa
    for l in lines[:100]:
        if l.upper().startswith("MG") or l.upper().startswith("NUOVA MG"):
            if "MOTOR" not in l.upper():
                return clean(l.replace("*", ""))

    slug = url.rstrip("/").split("/")[-1].replace("-", " ").title()
    return clean(slug)

def extract_note(body):
    start = body.find("Annuncio pubblicitario con finalità promozionale")
    if start == -1:
        start = body.find("Esempio di finanziamento")

    if start == -1:
        return ""

    sub = body[start:]

    stops = [
        "\nRichiedi maggiori informazioni",
        "\nNome *",
        "\nMODELLI",
        "\nPOST VENDITA",
    ]

    end = len(sub)
    for s in stops:
        i = sub.find(s)
        if i != -1 and i > 200:
            end = min(end, i)

    sub = sub[:end].strip()

    # aggiungi consumi se presenti subito dopo il form o nella pagina
    cons = ""
    for marker in ["*NUOVA", "*MG", "MG MG3", "MG ZS", "NUOVA MG"]:
        idx = body.find(marker)
        if idx != -1 and idx > start:
            tail = body[idx:]
            end2 = len(tail)
            for stop in ["\nMODELLI", "\nPOST VENDITA", "\nPROMOZIONI E TERMINI"]:
                j = tail.find(stop)
                if j != -1 and j > 100:
                    end2 = min(end2, j)
            cons = tail[:end2].strip()
            break

    if cons:
        sub += "\n\nCONSUMI ED EMISSIONI\n\n" + cons

    return sub.strip()

def parse_detail(page, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)

    body = page.locator("body").inner_text(timeout=30000)

    titolo = title_from_body(body, url)
    modello = modello_from_title(titolo)
    motore = motore_from_text(titolo)
    note = extract_note(body)

    rata = ""
    m = re.search(r"Da\s*€\s*([\d\.,]+)\s+al\s+mese", body, re.I)
    if not m:
        m = re.search(r"rate\s+mensili\s+da\s*€\s*([\d\.,]+)", body, re.I)
    if m:
        rata = euro_from_str(m.group(1))

    intero = ""
    m = re.search(r"Prezzo\s+(?:in\s+)?promozione:\s*€\s*([\d\.,]+)", body, re.I)
    if not m:
        m = re.search(r"Prezzo\s+promo\s*€\s*([\d\.,]+)", body, re.I)
    if m:
        intero = euro_from_str(m.group(1))

    tan = ""
    taeg = ""
    m = re.search(r"TAN\s*([\d\.,]+)\s*%", body, re.I)
    if m:
        tan = perc(m.group(1))

    m = re.search(r"TAEG\s*([\d\.,]+)\s*%", body, re.I)
    if m:
        taeg = perc(m.group(1))

    scad = ""
    m = re.search(r"fino\s+al\s*(\d{2}/\d{2}/\d{2,4})", body, re.I)
    if m:
        scad = normalize_date(m.group(1))

    extras = []
    m = re.search(r"(\d+)\s+rate\s+mensili", body, re.I)
    if m:
        extras.append(f"{m.group(1)} rate")
    m = re.search(r"Anticipo:\s*€\s*([\d\.,]+)", body, re.I)
    if m:
        extras.append("anticipo € " + m.group(1))
    m = re.search(r"(?:VFG|Valore futuro garantito).*?€\s*([\d\.,]+)", body, re.I | re.S)
    if m:
        extras.append("rata_finale € " + m.group(1))
    m = re.search(r"Importo totale dovuto[^:]*:\s*€\s*([\d\.,]+)", body, re.I)
    if m:
        extras.append("importo_totale_dovuto € " + m.group(1))

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
        "Note Tecniche": "; ".join(extras + [f"missing_{x}" for x in missing])
    }

    raw = "|".join([
        row["Brand"], row["Modello"], row["Titolo Promo"], row["Rata"],
        row["Intero"], row["TAN (%)"], row["TAEG (%)"], row["Scadenza"], row["Offer URL"]
    ])
    row["Promo Hash"] = hashlib.md5(raw.encode("utf-8")).hexdigest()

    return row

def build_rows():
    run_id = "mg_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,args=["--no-sandbox"])
        hub = browser.new_page(viewport={"width":1366,"height":2600})
        detail = browser.new_page(viewport={"width":1366,"height":2600})

        links = extract_links(hub)
        print("LINK MG:", len(links))

        rows = []
        for u in links:
            r = parse_detail(detail, u, run_id)
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
    print("RIGHE MG SCRITTE:", len(rows))
    print("SHEET AGGIORNATO")
