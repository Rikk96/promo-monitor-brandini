from playwright.sync_api import sync_playwright
import re, hashlib
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"
BRAND_MAIN = "Omoda & Jaecoo"
HUB_URL = "https://www.omodajaecooitalia.com/promozioni"

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
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", s)
    if m:
        return f"{m.group(1).zfill(2)}/{m.group(2).zfill(2)}/{m.group(3)}"
    return ""

def active(scad):
    try:
        return datetime.strptime(scad, "%d/%m/%Y").date() >= datetime.now().date()
    except:
        return False

def brand_from_title(t):
    u = t.upper()
    if "OMODA" in u:
        return "Omoda"
    if "JAECOO" in u:
        return "Jaecoo"
    return BRAND_MAIN

def modello_from_title(t):
    u = t.upper()
    for m in ["OMODA 9", "OMODA 7", "OMODA 5", "JAECOO 8", "JAECOO 7", "JAECOO 5"]:
        if m in u:
            return m.title().replace("Omoda", "Omoda").replace("Jaecoo", "Jaecoo")
    return t.split()[0] if t else ""

def motore_from_title(t):
    u = t.upper()
    if "SHS-P" in u:
        return "plug-in"
    if "SHS-H" in u:
        return "hybrid"
    if "EV" in u:
        return "elettrica"
    return ""

def extract_links(page):
    page.goto(HUB_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)

    links = page.locator("a").evaluate_all("""
        els => [...new Set(
            els.map(a => String(a.href || '')).filter(h =>
                h.includes('/promozioni/')
                && h.includes('-promo')
            ).map(h => h.split('#')[0])
        )]
    """)

    links = [u if u.endswith("/") else u + "/" for u in links]

    # Escludo promo noleggio: hanno struttura diversa e generano righe incomplete.
    links = [
        u for u in links
        if "noleggio" not in u.lower()
        and "business" not in u.lower()
        and "privati" not in u.lower()
    ]

    return list(dict.fromkeys(links))

def title_from_body(body, url):
    lines = [x.strip() for x in body.splitlines() if x.strip()]
    for l in lines[:60]:
        u = l.upper()
        if u.startswith("OMODA ") or u.startswith("JAECOO "):
            if "TUA DA" not in u and "TUO DA" not in u and "PROMO" not in u:
                return clean(l)
    slug = url.rstrip("/").split("/")[-1].replace("-promo", "").replace("-", " ").upper()
    return clean(slug)

def extract_note(body):
    starts = [
        "Es. di finanziamento",
        "Prezzo Listino",
        "Prezzo Promo",
        "Offerta CA AUTO BANK",
    ]

    start = -1
    for marker in starts:
        i = body.find(marker)
        if i != -1:
            if start == -1 or i < start:
                start = i

    if start == -1:
        return ""

    sub = body[start:]

    stops = [
        "\nRichiedi informazioni",
        "\nCompleta i seguenti campi",
        "\nIl periodo di garanzia",
        "\nProva su strada",
        "\nTrova concessionario",
        "\nModelli",
        "\nServizi",
    ]

    end = len(sub)
    for s in stops:
        i = sub.find(s)
        if i != -1 and i > 250:
            end = min(end, i)

    return sub[:end].strip()

def parse_detail(page, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)

    body = page.locator("body").inner_text(timeout=30000)

    titolo = title_from_body(body, url)
    brand = brand_from_title(titolo)
    modello = modello_from_title(titolo)
    motore = motore_from_title(titolo)
    note = extract_note(body)

    rata = ""
    m = re.search(r"Tua?o?\s+da\s*([\d\.,]+)\s*€", body, re.I)
    if not m:
        m = re.search(r"rate\s+mensili\s+di\s*([\d\.,]+)\s*€", body, re.I)
    if m:
        rata = euro_from_str(m.group(1))

    intero = ""
    m = re.search(r"Prezzo\s+Promo\s*:?\s*€?\s*([\d\.,]+)\s*€?", body, re.I)
    if not m:
        m = re.search(r"Prezzo\s+promo\s+valido[^€\d]{0,80}€?\s*([\d\.,]+)", body, re.I)
    if m:
        intero = euro_from_str(m.group(1))

    tan = ""
    taeg = ""
    m = re.search(r"TAN\s*(?:fisso)?\s*([\d\.,]+)\s*%", body, re.I)
    if m:
        tan = perc(m.group(1))
    m = re.search(r"TAEG\s*([\d\.,]+)\s*%", body, re.I)
    if m:
        taeg = perc(m.group(1))

    scad = ""
    m = re.search(r"Fino\s+al\s+(\d{1,2}[./]\d{1,2}[./]\d{4})", body, re.I)
    if not m:
        m = re.search(r"valida\s+fino\s+al\s+(\d{1,2}[./]\d{1,2}[./]\d{4})", body, re.I)
    if m:
        scad = normalize_date(m.group(1))

    extras = []
    m = re.search(r"Anticipo\s*([\d\.,]+)\s*€", body, re.I)
    if m:
        extras.append("anticipo € " + m.group(1))
    m = re.search(r"(\d+)\s+rate\s+mensili", body, re.I)
    if m:
        extras.append(f"{m.group(1)} rate")
    m = re.search(r"Maxi\s+Rata\s*([\d\.,]+)\s*€", body, re.I)
    if m:
        extras.append("maxi_rata € " + m.group(1))
    m = re.search(r"Importo\s+Totale\s+del\s+Credito\s*([\d\.,]+)\s*€", body, re.I)
    if m:
        extras.append("importo_totale_credito € " + m.group(1))
    m = re.search(r"Importo\s+Totale\s+Dovuto[^\\d]*([\d\.,]+)\s*€", body, re.I)
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
        "Brand": brand,
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
    run_id = "omodajaecoo_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,args=["--no-sandbox"])
        hub = browser.new_page(viewport={"width":1366,"height":3000})
        detail = browser.new_page(viewport={"width":1366,"height":3000})

        links = extract_links(hub)
        print("LINK OMODA/JAECOO:", len(links))

        rows = []
        for u in links:
            r = parse_detail(detail, u, run_id)
            rows.append(r)
            print(
                r["Brand"], "|",
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
    kept = [r for r in existing if r.get("Brand") not in ["Omoda", "Jaecoo", BRAND_MAIN]]

    final_rows = kept + rows
    values = [HEADERS] + [[r.get(h, "") for h in HEADERS] for r in final_rows]

    ws.clear()
    ws.update("A1", values)

if __name__ == "__main__":
    rows = build_rows()
    write_to_sheet(rows)
    print("RIGHE OMODA/JAECOO SCRITTE:", len(rows))
    print("SHEET AGGIORNATO")
