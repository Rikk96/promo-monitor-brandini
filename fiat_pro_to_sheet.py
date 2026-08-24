from playwright.sync_api import sync_playwright
import re

HUB="https://www.fiat.it/professional/offerte"

def clean(t):
    return re.sub(r"\s+", " ", t or "").strip()

def parse_num(s):
    if not s:
        return None
    s=s.replace("€","").replace(".","").replace(",",".").strip()
    try:
        return float(s)
    except:
        return None


def perc(value):
    if not value:
        return ""
    return str(value).replace(".", ",") + "%"

def euro(
n):
    if n is None:
        return ""
    return "€ " + f"{int(round(n)):,}".replace(",", ".")

def slug(url):
    return url.rstrip("/").split("/")[-1].lower()

def modello(url):
    s=slug(url)
    if "doblo" in s:
        return "Doblò"
    if "ducato" in s:
        return "Ducato"
    if "scudo" in s:
        return "Scudo"
    return s.replace("-", " ").title()

def motore(url, body):
    s=(slug(url)+" "+body[:1200]).lower()
    if "elettric" in s or "e-scudo" in s or "e-ducato" in s or "e-doblo" in s or "bev" in s:
        return "elettrica"
    if "diesel" in s or "multijet" in s or "bluehdi" in s:
        return "diesel"
    if "benzina" in s:
        return "benzina"
    return ""

def extract_offer_note(body):
    lines=[x.strip() for x in body.splitlines() if x.strip()]
    text="\n".join(lines)

    starts=[
        "Offerta valida per",
        "L'offerta include",
        "Offerta valida fino",
    ]

    start=-1
    for s in starts:
        idx=text.find(s)
        if idx!=-1:
            start=idx
            break

    if start==-1:
        return ""

    stops=[
        "\nConsumo di carburante",
        "\nConsumo di energia elettrica",
        "\nConsumo combinato",
        "\nConsumi",
        "\nCONSUMO",
        "\nRichiedi preventivo",
        "\nConfigura e ordina",
        "\nTrova concessionario",
        "\nFIAT SERVIZIO CLIENTI",
        "\nFACEBOOK",
    ]

    sub=text[start:]
    end=len(sub)
    for s in stops:
        idx=sub.find(s)
        if idx!=-1:
            end=min(end,idx)

    return sub[:end].strip()

def extract_consumi(body):
    idx=body.lower().find("consumo")
    if idx==-1:
        return ""
    sub=body[idx:]
    stops=[
        "Richiedi preventivo",
        "Configura e ordina",
        "Trova concessionario",
        "FIAT SERVIZIO CLIENTI",
    ]
    end=len(sub)
    for s in stops:
        i=sub.find(s)
        if i!=-1:
            end=min(end,i)
    return sub[:end].strip()

def extract_title(body, url):
    lines=[x.strip() for x in body.splitlines() if x.strip()]
    for l in lines[:40]:
        ll=l.lower()
        if any(x in ll for x in ["dobl", "ducato", "scudo"]):
            if len(l)<100 and "modelli" not in ll:
                return clean(l)
    return slug(url).replace("-", " ").title()


def extract_intero_fiatpro(source):
    for pat in [
        r"Prezzo di Listino.*?([\d\.,]+)\s*€",
        r"Prezzo Listino.*?([\d\.,]+)\s*€",
        r"Listino.*?([\d\.,]+)\s*€",
        r"Prezzo Promo.*?([\d\.,]+)\s*€",
        r"Prezzo promo.*?([\d\.,]+)\s*€",
    ]:
        m = re.search(pat, source, re.I)
        if m:
            return euro(parse_num(m.group(1)))
    return ""

def extract_tan_taeg_fiatpro(source):
    tan = ""
    taeg = ""

    m = re.search(r"TAN\s*(?:\(fisso\))?\s*([\d\.,]+)\s*%", source, re.I)
    if m:
        tan = perc(m.group(1))

    m = re.search(r"TAEG\s*([\d\.,]+)\s*%", source, re.I)
    if m:
        taeg = perc(m.group(1))

    return tan, taeg

def parse_detail(page,url):
    page.goto(url,wait_until="domcontentloaded",timeout=45000)
    page.wait_for_timeout(3000)

    body=page.locator("body").inner_text(timeout=30000)

    title=extract_title(body,url)
    note=extract_offer_note(body)
    consumi=extract_consumi(body)

    full_note=""
    if note:
        full_note="DETTAGLIO PROMOZIONE\n\n"+note
    if consumi:
        full_note=(full_note+"\n\nCONSUMI ED EMISSIONI\n\n"+consumi).strip()

    source=note+"\n"+body[:1500]

    rata=None
    for pat in [
        r"([\d\.,]+)\s*€\s*al mese",
        r"(?:rate|canoni)\s+(?:mensili\s+)?da\s*([\d\.,]+)\s*€",
        r"n°\s*\d+\s*(?:rate|canoni)\s*da\s*([\d\.,]+)\s*€",
    ]:
        m=re.search(pat, source, re.I)
        if m:
            rata=parse_num(m.group(1))
            break

    anticipo=None
    m=re.search(r"Anticipo\s*([\d\.,]+)\s*€", source, re.I)
    if m:
        anticipo=parse_num(m.group(1))

    scad=""
    m=re.search(r"Fino al\s*(\d{2}/\d{2}/\d{4})", source, re.I)
    if m:
        scad=m.group(1)
    else:
        m=re.search(r"Offerta valida fino al\s*(\d{2}/\d{2}/\d{4})", source, re.I)
        if m:
            scad=m.group(1)
        else:
            mesi={"gennaio":"01","febbraio":"02","marzo":"03","aprile":"04","maggio":"05","giugno":"06","luglio":"07","agosto":"08","settembre":"09","ottobre":"10","novembre":"11","dicembre":"12"}
            m=re.search(r"(?:fino al|valida fino al)\s*(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})", source, re.I)
            if m and m.group(2).lower() in mesi:
                scad=f"{m.group(1).zfill(2)}/{mesi[m.group(2).lower()]}/{m.group(3)}"

    return {
        "modello": modello(url),
        "title": title,
        "motore": motore(url,body),
        "rata": euro(rata),
        "anticipo": euro(anticipo),
        "scadenza": scad,
        "note_start": clean(full_note[:160]),
        "url": url
    }

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
    page=browser.new_page(viewport={"width":1366,"height":1800})

    page.goto(HUB,wait_until="domcontentloaded",timeout=60000)
    page.wait_for_timeout(5000)

    urls=page.locator("a").evaluate_all("""
        els => [...new Set(
            els.map(a => String(a.href || '')).filter(h =>
                h.includes('/professional/offerte/')
                && !h.endsWith('/offerte')
                && !h.endsWith('/offerte#')
            )
        )]
    """)

    print("URL:",len(urls))

    detail=browser.new_page(viewport={"width":1366,"height":1800})
    for u in urls:
        r=parse_detail(detail,u)
        print(r["modello"],"|",r["title"],"|",r["motore"],"|",r["rata"],"| anticipo",r["anticipo"],"|",r["scadenza"])
        print("NOTE:",r["note_start"])
        print("URL:",r["url"])
        print("-"*100)

    browser.close()

# --- WRITE TO SHEET ---

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import hashlib

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"
BRAND = "Fiat Professional"

HEADERS = [
    "Brand","Modello","Titolo Promo","Motorizzazione","Rata","Intero","TAN (%)","TAEG (%)",
    "Scadenza","Note Legali","Fonte URL","Offer URL","Data Aggiornamento","Data Scansione",
    "Last Seen","Stato","Alert Type","Promo Hash","Extraction Confidence","Run ID","Note Tecniche"
]

def make_hash(row):
    raw = "|".join([
        row.get("Brand",""), row.get("Modello",""), row.get("Titolo Promo",""),
        row.get("Rata",""), row.get("Intero",""), row.get("Scadenza",""), row.get("Offer URL","")
    ])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def active(scad):
    try:
        return datetime.strptime(scad, "%d/%m/%Y").date() >= datetime.now().date()
    except:
        return False


def extract_hub_cards_fiatpro(page):
    body = page.locator("body").inner_text(timeout=30000)
    lines = [x.strip() for x in body.splitlines() if x.strip()]
    cards = {}

    models = ["Ducato", "E-Ducato", "Scudo", "E-Scudo", "Scudo S-Design", "E-Scudo S-Design", "Doblò"]

    for i, line in enumerate(lines):
        title = line.strip()

        if title not in models:
            continue

        chunk = "\n".join(lines[i:i+18])

        rata = ""
        intero = ""
        tan = ""
        taeg = ""
        scad = ""

        m = re.search(r"Prezzo promo da\s*([\d\.,]+)\s*€", chunk, re.I)
        if m:
            intero = euro(parse_num(m.group(1)))

        m = re.search(r"(?:canoni|rate)\s+da\s*([\d\.,]+)\s*€", chunk, re.I)
        if m:
            rata = euro(parse_num(m.group(1)))

        m = re.search(r"TAN\s*(?:\(fisso\))?\s*([\d\.,]+)\s*%", chunk, re.I)
        if m:
            tan = perc(m.group(1))

        m = re.search(r"TAEG\s*([\d\.,]+)\s*%", chunk, re.I)
        if m:
            taeg = perc(m.group(1))

        m = re.search(r"(?:Validità|Validità sui veicoli in pronta consegna)\s*:?\s*(\d{2}/\d{2}/\d{4})", chunk, re.I)
        if m:
            scad = m.group(1)

        cards[title.lower().replace(" ", "").replace("-", "")] = {
            "Rata": rata,
            "Intero": intero,
            "TAN (%)": tan,
            "TAEG (%)": taeg,
            "Scadenza": scad,
            "raw": chunk
        }

    return cards

def fiatpro_card_key(model, title, url):
    s = (model + " " + title + " " + url).lower()
    if "e-scudo s-design" in s or "escudosdesign" in s:
        return "escudosdesign"
    if "scudo s-design" in s or "scudosdesign" in s:
        return "scudosdesign"
    if "e-ducato" in s or "educato" in s:
        return "educato"
    if "ducato" in s:
        return "ducato"
    if "e-scudo" in s or "escudo" in s:
        return "escudo"
    if "scudo" in s:
        return "scudo"
    if "doblo" in s or "doblò" in s:
        return "doblò"
    return ""

def build_rows():
    rows = []
    run_id = "fiatpro_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
        page=browser.new_page(viewport={"width":1366,"height":1800})

        page.goto(HUB,wait_until="domcontentloaded",timeout=60000)
        page.wait_for_timeout(5000)

        urls=page.locator("a").evaluate_all("""
            els => [...new Set(
                els.map(a => String(a.href || '')).filter(h =>
                    h.includes('/professional/offerte/')
                    && !h.endsWith('/offerte')
                    && !h.endsWith('/offerte#')
                )
            )]
        """)

        print("URL FIAT PRO:", len(urls))

        hub_cards = extract_hub_cards_fiatpro(page)

        print("CARD HUB:", len(hub_cards))

        detail=browser.new_page(viewport={"width":1366,"height":1800})

        for u in urls:
            r=parse_detail(detail,u)

            missing = []
            if not r["motore"]: missing.append("motorizzazione")
            if not r["rata"]: missing.append("rata")
            if not r["scadenza"]: missing.append("scadenza")
            if not r["note_start"]: missing.append("note_legali")

            stato = "attiva" if active(r["scadenza"]) else "scaduta"
            if missing:
                stato = "incompleta" if stato == "attiva" else stato

            note = ""
            # recupera nota completa ricalcolandola dalla pagina
            detail.goto(u,wait_until="domcontentloaded",timeout=45000)
            detail.wait_for_timeout(2500)
            body=detail.locator("body").inner_text(timeout=30000)
            base=extract_offer_note(body)
            consumi=extract_consumi(body)

            if base:
                note = "DETTAGLIO PROMOZIONE\n\n" + base
            if consumi:
                note = (note + "\n\nCONSUMI ED EMISSIONI\n\n" + consumi).strip()

            intero = extract_intero_fiatpro(note)
            tan, taeg = extract_tan_taeg_fiatpro(note)

            key = fiatpro_card_key(r["modello"], r["title"], u)
            card = hub_cards.get(key, {})

            row = {
                "Brand": BRAND,
                "Modello": r["modello"],
                "Titolo Promo": r["title"],
                "Motorizzazione": r["motore"],
                "Rata": card.get("Rata") or r["rata"],
                "Intero": card.get("Intero") or intero,
                "TAN (%)": card.get("TAN (%)") or tan,
                "TAEG (%)": card.get("TAEG (%)") or taeg,
                "Scadenza": card.get("Scadenza") or r["scadenza"],
                "Note Legali": note,
                "Fonte URL": HUB,
                "Offer URL": u,
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

            row["Promo Hash"] = make_hash(row)
            rows.append(row)

            print(row["Modello"], "|", row["Titolo Promo"], "|", row["Motorizzazione"], "|", row["Rata"], "|", row["Scadenza"])

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
    print("RIGHE FIAT PROFESSIONAL SCRITTE:", len(rows))
    print("SHEET AGGIORNATO")
