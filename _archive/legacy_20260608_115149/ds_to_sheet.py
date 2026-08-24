from playwright.sync_api import sync_playwright
import re, hashlib, html
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"
BRAND = "DS"

HUB_URL = "https://www.dsautomobiles.it/acquisto-noleggio/offerte-privati.html"

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

def active(scad):
    try:
        return datetime.strptime(scad, "%d/%m/%Y").date() >= datetime.now().date()
    except:
        return False

def normalize_motor(t):
    l = t.lower()
    if "plug-in" in l or "plug in" in l:
        return "plug-in"
    if "hybrid" in l or "ibrid" in l:
        return "hybrid"
    if "elettrico" in l or "elettrica" in l or "e-tense" in l or "100%" in l:
        return "elettrica"
    if "diesel" in l or "bluehdi" in l:
        return "diesel"
    return ""

def model_from_title(t):
    u = t.upper()
    if "DS 3" in u:
        return "DS 3"
    if "DS 7" in u:
        return "DS 7"
    if "N°4" in u or "N° 4" in u:
        return "N°4"
    if "N°8" in u or "N° 8" in u:
        return "N°8"
    return ""

def extract_links(page):
    links = page.locator("a").evaluate_all("""
        els => [...new Set(
            els.map(a => String(a.href || '')).filter(h =>
                h.includes('/acquisto-noleggio/offerte-privati/')
                && h.endsWith('.html')
            )
        )]
    """)
    return list(dict.fromkeys(links))

def get_consumption_block(hub_text, modello, titolo):
    text = hub_text

    # prende la sezione "Note consumi" fino alle FAQ/footer
    idx = text.lower().find("note consumi")
    if idx == -1:
        return ""

    sub = text[idx:]
    end_markers = [
        "\nOfferte disponibili",
        "\nRottamazione e permuta",
        "\nQuali sono le offerte",
        "\nIscrizione newsletter",
    ]

    end = len(sub)
    for marker in end_markers:
        i = sub.find(marker)
        if i != -1 and i > 100:
            end = min(end, i)
    sub = sub[:end]

    key_options = []

    t = titolo.upper()
    if "DS 3" in t and "E-TENSE" in t:
        key_options = ["DS 3 E-TENSE"]
    elif "DS 3" in t:
        key_options = ["DS 3 HYBRID"]
    elif "DS 7" in t and "PLUG" in t:
        key_options = ["DS 7 E-TENSE", "DS 7 PLUG"]
    elif "DS 7" in t and ("BLUEHDI" in t or "DIESEL" in t):
        key_options = ["DS 7 BLUEHDI"]
    elif "N°4" in t or "N° 4" in t:
        if "BLUEHDI" in t or "DIESEL" in t:
            key_options = ["N° 4 BLUEHDI", "N°4 BLUEHDI", "DS 4 BLUEHDI"]
        elif "PLUG" in t:
            key_options = ["N° 4 PLUG", "N°4 PLUG", "DS 4 PLUG"]
        else:
            key_options = ["N° 4 HYBRID", "N°4 HYBRID", "DS 4 HYBRID"]
    elif "N°8" in t or "N° 8" in t:
        key_options = ["N° 8", "N°8"]

    starts = []
    upper_sub = sub.upper()
    for key in key_options:
        pos = upper_sub.find(key.upper())
        if pos != -1:
            starts.append(pos)

    if not starts:
        return ""

    start = min(starts)

    # blocco fino al prossimo titolo consumo probabile
    title_patterns = [
        "\nDS 3 ",
        "\nDS 4 ",
        "\nDS 7 ",
        "\nN° 4 ",
        "\nN°4 ",
        "\nN° 8 ",
        "\nN°8 ",
    ]

    block = sub[start:]
    end = len(block)
    for p in title_patterns:
        i = block.find(p, 10)
        if i != -1:
            end = min(end, i)

    return clean(block[:end])


def html_to_clean_text(src):
    txt = re.sub(r"<[^>]+>", " ", src or "")
    txt = html.unescape(txt)
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()

def extract_ds_legal_from_html(src):
    txt = html_to_clean_text(src)
    low = txt.lower()

    idx = low.find("dettaglio promozione")
    if idx == -1:
        return "", ""

    sub = txt[idx:]

    end_markers = [
        "SELEZIONA IL MODELLO DESIDERATO",
        "INSERISCI I TUOI DATI",
        "LA TUA PRIVACY",
        "Iscrizione newsletter",
        "Modelli DS",
        "Chatta con noi"
    ]

    end = len(sub)
    for marker in end_markers:
        i = sub.find(marker)
        if i != -1 and i > 300:
            end = min(end, i)

    sub = sub[:end].strip()

    cidx = -1
    for p in ["Consumo di", "100% Elettrica", "Emissioni CO2", "emissioni CO2"]:
        i = sub.find(p)
        if i != -1 and i > 100:
            if cidx == -1 or i < cidx:
                cidx = i

    if cidx != -1:
        promo = sub[:cidx].strip()
        consumi = sub[cidx:].strip()
        note = promo + "\n\nCONSUMI ED EMISSIONI\n\n" + consumi
    else:
        note = sub

    intero = ""
    m = re.search(r"Prezzo\s+Promo\s*([\d\.,]+)\s*€", sub, re.I)
    if not m:
        m = re.search(r"Prezzo\s+promo\s*€\s*([\d\.,]+)", sub, re.I)

    if m:
        intero = euro_from_str(m.group(1))

    return note.strip(), intero



def clean_ds_title(model, raw_title):
    title = clean(raw_title)
    model = clean(model)

    # Caso sporco prima card hub: contiene menu/ancore prima del vero titolo.
    for marker in ["Contatta il concessionario", "Seleziona il modello"]:
        if marker.lower() in title.lower():
            parts = re.split(marker, title, flags=re.I)
            title = clean(parts[-1])

    # rimuove eventuali modelli/ancore rimasti in testa
    junk = ["DS 3 DS 7 N°4 N°8", "DS 3 DS 7 N°4 N°8 Contatta il concessionario"]
    for j in junk:
        if title.upper().startswith(j.upper()):
            title = clean(title[len(j):])

    # rimuove doppio modello iniziale
    while title.upper().startswith(model.upper() + " "):
        title = clean(title[len(model):])

    return clean(model + " " + title)


def parse_hub_rows(hub_text, links):
    # parte solo dalla zona offerte, prima delle note consumi
    cut = hub_text.lower().find("note consumi")
    offers_text = hub_text[:cut] if cut != -1 else hub_text

    # split sulle card, partendo da righe modello
    pattern = re.compile(
        r"(?P<model>DS 3|DS 7|N°4|N°8)\s+"
        r"(?P<title>.*?)(?=Da\s+€\s*[\d\.,]+)"
        r"Da\s+€\s*(?P<rata>[\d\.,]+).*?"
        r"Motorizzazione:\s*(?P<motor>.*?)\s+"
        r"TAN\s*\(fisso\)\s*(?P<tan>[\d\.,]+)%\s+"
        r"TAEG\s*(?P<taeg>[\d\.,]+)%\s+"
        r"(?:Anticipo|Primo canone anticipato)\s*€\s*(?P<anticipo>[\d\.,]+).*?"
        r"L'offerta è valida fino al\s*(?P<scad>\d{2}/\d{2}/\d{4})",
        re.I | re.S
    )

    matches = list(pattern.finditer(offers_text))
    rows = []

    for idx, m in enumerate(matches):
        modello = clean(m.group("model"))
        raw_title = clean(m.group("title"))
        title = clean_ds_title(modello, raw_title)
        motor = normalize_motor(m.group("motor") + " " + title)

        offer_url = links[idx] if idx < len(links) else ""

        rows.append({
            "Brand": BRAND,
            "Modello": modello,
            "Titolo Promo": title,
            "Motorizzazione": motor,
            "Rata": euro_from_str(m.group("rata")),
            "Intero": "",
            "TAN (%)": perc(m.group("tan")),
            "TAEG (%)": perc(m.group("taeg")),
            "Scadenza": clean(m.group("scad")),
            "Note Legali": "",
            "Fonte URL": HUB_URL,
            "Offer URL": offer_url,
        })

    return rows

def build_rows():
    run_id = "ds_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,args=["--no-sandbox"])
        page = browser.new_page(viewport={"width":1366,"height":2600})
        page.goto(HUB_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)

        hub_text = page.locator("body").inner_text(timeout=30000)
        links = extract_links(page)

        print("LINK DS:", len(links))
        rows = parse_hub_rows(hub_text, links)

        detail = browser.new_page(viewport={"width":1366,"height":2600})

        for r in rows:
            if r.get("Offer URL"):
                try:
                    detail.goto(r["Offer URL"], wait_until="domcontentloaded", timeout=60000)
                    detail.wait_for_timeout(3500)
                    src = detail.content()
                    note_html, intero_html = extract_ds_legal_from_html(src)
                    if note_html:
                        r["Note Legali"] = note_html
                    if intero_html:
                        r["Intero"] = intero_html
                except Exception as e:
                    r["Note Tecniche"] = "errore_dettaglio_html:" + str(e)[:80]

        final = []
        for r in rows:
            missing = []
            for k in ["Rata","TAN (%)","TAEG (%)","Scadenza","Offer URL"]:
                if not r.get(k):
                    missing.append(k.lower().replace(" (%)",""))

            note_tecniche = []
            if not r.get("Note Legali"):
                note_tecniche.append("missing_note_legali")
            if not r.get("Intero"):
                note_tecniche.append("missing_intero")
            note_tecniche += [f"missing_{x}" for x in missing]

            stato = "attiva" if active(r["Scadenza"]) else "scaduta"
            if missing and stato == "attiva":
                stato = "incompleta"

            r.update({
                "Data Aggiornamento": now,
                "Data Scansione": now,
                "Last Seen": now,
                "Stato": stato,
                "Alert Type": "",
                "Promo Hash": "",
                "Extraction Confidence": "high" if not note_tecniche else "medium",
                "Run ID": run_id,
                "Note Tecniche": "; ".join(note_tecniche)
            })

            raw = "|".join([r["Brand"], r["Modello"], r["Titolo Promo"], r["Rata"], r["TAN (%)"], r["TAEG (%)"], r["Scadenza"], r["Offer URL"]])
            r["Promo Hash"] = hashlib.md5(raw.encode("utf-8")).hexdigest()

            final.append(r)

            print(r["Modello"], "|", r["Titolo Promo"], "|", r["Motorizzazione"], "|", r["Rata"], "|", r["TAN (%)"], "|", r["TAEG (%)"], "|", r["Scadenza"], "|", r["Note Tecniche"])

        browser.close()
        return final

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
    print("RIGHE DS SCRITTE:", len(rows))
    print("SHEET AGGIORNATO")
