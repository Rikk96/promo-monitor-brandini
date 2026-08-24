from playwright.sync_api import sync_playwright
import re, hashlib
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"
BRAND = "Nissan"
HUB_URL = "https://www.nissan.it/offerte.html#category=Vetture"

HEADERS = [
    "Brand","Modello","Titolo Promo","Motorizzazione","Rata","Intero","TAN (%)","TAEG (%)",
    "Scadenza","Note Legali","Fonte URL","Offer URL","Data Aggiornamento","Data Scansione",
    "Last Seen","Stato","Alert Type","Promo Hash","Extraction Confidence","Run ID","Note Tecniche"
]

MODEL_URLS = {
    "JUKE": "https://www.nissan.it/offerte.html#category=Vetture&model=JUKEF16B",
    "QASHQAI": "https://www.nissan.it/offerte.html#category=Vetture&model=QASHQAIJ12B",
    "X-TRAIL": "https://www.nissan.it/offerte.html#category=Vetture&model=XTRAILT33",
    "MICRA": "https://www.nissan.it/offerte.html#category=Vetture&model=MICRAK151",
    "LEAF": "https://www.nissan.it/offerte.html#category=Vetture&model=LEAF",
    "TOWNSTAR": "https://www.nissan.it/offerte.html#category=Vetture&model=TOWNSTAR",
    "ARIYA": "https://www.nissan.it/offerte.html#category=Vetture&model=ARIYA",
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

def normalize_date(s):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    if m:
        return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return ""

def active(scad):
    try:
        return datetime.strptime(scad, "%d/%m/%Y").date() >= datetime.now().date()
    except:
        return True

def modello_from_card(card):
    u = card.upper()
    if "QASHQAI" in u:
        return "Qashqai"
    if "X-TRAIL" in u:
        return "X-Trail"
    if "MICRA" in u:
        return "Micra"
    if "LEAF" in u:
        return "Leaf"
    if "TOWNSTAR" in u:
        return "Townstar"
    if "ARIYA" in u:
        return "Ariya"
    if "JUKE" in u:
        return "Juke"
    return "Nissan"

def motore_from_card(card):
    u = card.upper()
    if "100% ELETTR" in u or "KWH" in u or "LEAF" in u or "MICRA" in u or "ARIYA" in u:
        return "elettrica"
    if "E-POWER" in u or "HYBRID" in u:
        return "hybrid"
    return "benzina"

def title_from_card(card):
    lines = [x.strip() for x in card.splitlines() if x.strip()]
    model = ""
    variant = ""
    for i, l in enumerate(lines[:12]):
        u = l.upper()
        if any(m in u for m in ["JUKE","QASHQAI","X-TRAIL","MICRA","LEAF","TOWNSTAR","ARIYA"]):
            model = l
            if i + 1 < len(lines):
                variant = lines[i+1]
            break
    if model and variant and variant.upper() not in ["FOTO A TITOLO DI ESEMPIO", "DETTAGLI OFFERTA"]:
        return clean(model + " " + variant)
    return clean(model or modello_from_card(card))

def split_cards(text):
    # Ogni card termina con "DETTAGLI OFFERTA"; prendiamo blocchi tra una card e la successiva.
    parts = text.split("DETTAGLI OFFERTA")
    cards = []

    for i in range(len(parts)-1):
        block = parts[i]
        # prendi parte finale del blocco, dalla riga modello più vicina
        markers = ["\nJUKE\n", "\nQASHQAI\n", "\nX-TRAIL\n", "\nNUOVA MICRA\n", "\nNUOVA LEAF\n", "\nTOWNSTAR COMBI\n", "\nARIYA\n"]
        starts = [block.rfind(m) for m in markers]
        start = max(starts)
        if start == -1:
            continue

        card = block[start:].strip()
        card = card + "\nDETTAGLI OFFERTA"
        cards.append(card)

    return cards

def parse_card(card, base_url, idx, run_id):
    modello = modello_from_card(card)
    titolo = title_from_card(card)
    motore = motore_from_card(card)

    rata = ""
    m = re.search(r"(?:TUA|TUO|OPPURE)\s+(?:A\s+|DA\s+)?€\s*([\d\.,]+)\s+AL\s+MESE", card, re.I)
    if not m:
        m = re.search(r"O\s+DA\s+€\s*([\d\.,]+)\s+AL\s+MESE", card, re.I)
    if m:
        rata = euro_from_str(m.group(1))

    intero = ""
    m = re.search(r"(?:GAMMA\s+(?:HYBRID\s+)?DA|TUA\s+DA|TUA\s+A\s+PARTIRE\s+DA|TUO\s+A\s+PARTIRE\s+DA|SUBITO\s+TUO\s+A|TUO\s+DA)\s+€\s*([\d\.,]+)", card, re.I)
    if m:
        # evita di prendere la rata quando c'è "TUA DA € 299 AL MESE"
        after = card[m.end():m.end()+30].upper()
        if "AL MESE" not in after:
            intero = euro_from_str(m.group(1))

    tan = ""
    taeg = ""
    m = re.search(r"TAN\s*([\d\.,]+)\s*%", card, re.I)
    if m:
        tan = perc(m.group(1))
    m = re.search(r"TAEG\s*([\d\.,]+)\s*%", card, re.I)
    if m:
        taeg = perc(m.group(1))

    scad = ""
    m = re.search(r"Offerta valida fino al\s*(\d{2}/\d{2}/\d{4})", card, re.I)
    if m:
        scad = normalize_date(m.group(1))
    if not scad:
        scad = "30/06/2026"

    extras = []
    m = re.search(r"ANTICIPO\s*€\s*([\d\.,]+)", card, re.I)
    if m:
        extras.append("anticipo € " + m.group(1))
    m = re.search(r"(\d+)\s+RATE", card, re.I)
    if m:
        extras.append(f"{m.group(1)} rate")
    m = re.search(r"(?:VALORE FUTURO GARANTITO\s*\(RATA FINALE\)|RATA FINALE)\s*€\s*([\d\.,]+)", card, re.I)
    if m:
        extras.append("rata_finale € " + m.group(1))

    missing = []
    if not intero and not rata:
        missing.append("intero_o_rata")
    if rata and not tan:
        missing.append("tan")
    if rata and not taeg:
        missing.append("taeg")
    if not scad:
        missing.append("scadenza")
    if not card:
        missing.append("note_legali")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stato = "attiva" if active(scad) else "scaduta"
    if missing and stato == "attiva":
        stato = "incompleta"

    offer_url = base_url + f"&card={idx}"

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
        "Note Legali": card,
        "Fonte URL": HUB_URL,
        "Offer URL": offer_url,
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
    run_id = "nissan_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,args=["--no-sandbox"])
        for model, url in MODEL_URLS.items():
            print("\nMODELLO:", model, url)

            page = browser.new_page(viewport={"width":1366,"height":5000})
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(9000)

            # forza reload/hash state su pagina nuova
            try:
                page.reload(wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
            except Exception:
                pass

            text = page.locator("body").inner_text(timeout=30000)
            cards = split_cards(text)

            print("CARD TROVATE:", len(cards))

            for idx, card in enumerate(cards, 1):
                if "NOLEGGIO" in card.upper():
                    continue

                # tengo finanziamenti o prezzo secco
                if not any(x in card.upper() for x in ["TAN", "TAEG", "TUA", "TUO", "GAMMA DA", "SUBITO TUO"]):
                    continue

                r = parse_card(card, url, idx, run_id)
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

            page.close()

        browser.close()

    # dedup su titolo+rata+intero
    dedup = {}
    for r in rows:
        key = (r["Modello"], r["Titolo Promo"], r["Rata"], r["Intero"], r["TAN (%)"], r["TAEG (%)"])
        dedup[key] = r

    return list(dedup.values())

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
    print("RIGHE NISSAN SCRITTE:", len(rows))
    print("SHEET AGGIORNATO")
