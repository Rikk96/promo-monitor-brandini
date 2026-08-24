from playwright.sync_api import sync_playwright
from google.oauth2.service_account import Credentials
import gspread
import re
import hashlib
from datetime import datetime

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"
HUB = "https://www.citroen.it/acquista/offerte-privati.html"
BRAND = "Citroen"

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
    s = s.replace("€", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(s)
    except:
        return None

def euro(n):
    if n is None:
        return ""
    return "€ " + f"{int(round(n)):,}".replace(",", ".")

def perc(s):
    if not s:
        return ""
    return s.replace(".", ",") + "%"

def slug_from_url(url):
    return url.rstrip("/").split("/")[-1].replace(".html", "").lower()

def title_from_slug(url):
    slug = slug_from_url(url)
    title = slug.replace("finanziamento", "").replace("leasing", "").replace("acquisto", "")
    title = title.replace("nuova", "nuova ").replace("nuovo", "nuovo ")
    title = title.replace("-", " ")
    title = clean(title).title()
    title = title.replace("E C3", "Ë-C3").replace("E C4", "Ë-C4").replace("E Berlingo", "Ë-Berlingo")
    return title

def model_from_url(url):
    s = slug_from_url(url)
    if "jumpy" in s:
        return "Jumpy Combi"
    if "berlingo" in s:
        return "Nuovo Berlingo"
    if "spacetourer" in s:
        return "Spacetourer"
    if "c5x" in s or "c5-x" in s:
        return "C5 X"
    if "c5-aircross" in s:
        return "Nuovo Suv C5 Aircross"
    if "c3-aircross" in s:
        return "C3 Aircross"
    if "c4x" in s or "c4-x" in s:
        return "C4 X"
    if "c4" in s:
        return "C4"
    if "c3" in s:
        return "C3"
    if "ami" in s:
        return "NUOVA AMI"
    return title_from_slug(url)

def motore_from_url_and_text(url, body):
    s = (slug_from_url(url) + " " + body[:1200]).lower()
    if "plug-in" in s or "plug in" in s or "phev" in s:
        return "plug-in"
    if "elettric" in s or "100% elettrica" in s or " ë-" in s or "e-" in s or "bev" in s:
        return "elettrica"
    if "hybrid" in s or "mhev" in s:
        return "hybrid"
    if "diesel" in s or "bluehdi" in s:
        return "diesel"
    if "benzina" in s or "turbo" in s or "puretech" in s:
        return "benzina"
    return ""

def extract_legal(body):
    low = body.lower()
    start = low.find("dettaglio promozione")
    if start == -1:
        return ""

    sub = body[start:]
    stops = [
        "Configura e ordina",
        "Prenota un test drive",
        "Scopri le offerte",
        "Pronta Consegna",
        "VETTURE PER USO PRIVATO",
        "SELEZIONA IL MODELLO",
        "INSERISCI I TUOI DATI",
        "LA TUA PRIVACY",
        "CONTINUA SENZA ACCETTARE",
    ]

    end = len(sub)
    for s in stops:
        idx = sub.find(s)
        if idx != -1:
            end = min(end, idx)

    return sub[:end].strip()

def extract_title(body, url):
    lines = [x.strip() for x in body.splitlines() if x.strip()]

    # Titolo promo desiderato: allestimento + motore, es. "YOU Turbo 100 Manuale".
    trims = ["YOU", "PLUS", "MAX", "BUSINESS", "FEEL", "SHINE", "LIVE", "PACK", "ë-Series", "E-SERIES"]
    for i, l in enumerate(lines[:120]):
        if l.strip().upper() in [x.upper() for x in trims]:
            parts = [l.strip()]
            for j in range(i + 1, min(i + 5, len(lines))):
                nxt = lines[j].strip()
                low = nxt.lower()
                if not nxt:
                    continue
                if any(stop in low for stop in ["n°", "tan", "taeg", "anticipo", "rata finale", "valida", "prezzo promo", "listino", "sconto", "scopri"]):
                    break
                if len(nxt) <= 80:
                    parts.append(nxt)
            if len(parts) >= 2:
                return clean(" ".join(parts))

    # Fallback: se non trova allestimento/motore, usa slug pulito.
    return title_from_slug(url)

def extract_rata(source):
    for pat in [
        r"(?:rate|canoni)\s+(?:mensili\s+)?da\s*([\d\.,]+)\s*€",
        r"(\d{1,3})\s*€\s*al mese",
        r"CANONI MENSILI DA\s*([\d\.,]+)\s*€",
    ]:
        m = re.search(pat, source, re.I)
        if m:
            return parse_num(m.group(1))
    return None

def extract_intero(source):
    for pat in [
        r"Prezzo Promo\s*([\d\.,]+)\s*€",
        r"Prezzo promo da\s*([\d\.,]+)\s*€",
        r"Prezzo di Listino.*?([\d\.,]+)\s*€",
        r"Prezzo Listino.*?([\d\.,]+)\s*€",
        r"Listino\s*([\d\.,]+)\s*€",
    ]:
        m = re.search(pat, source, re.I)
        if m:
            return parse_num(m.group(1))
    return None

def extract_tan_taeg(source):
    tan = ""
    taeg = ""
    m = re.search(r"TAN\s*(?:\(fisso\))?\s*([\d\.,]+)\s*%", source, re.I)
    if m:
        tan = perc(m.group(1))
    m = re.search(r"TAEG\s*([\d\.,]+)\s*%", source, re.I)
    if m:
        taeg = perc(m.group(1))
    return tan, taeg

def extract_scadenza(source):
    mesi = {
        "gennaio":"01","febbraio":"02","marzo":"03","aprile":"04","maggio":"05","giugno":"06",
        "luglio":"07","agosto":"08","settembre":"09","ottobre":"10","novembre":"11","dicembre":"12"
    }

    m = re.search(r"(?:fino al|entro il|immatricolazioni fino al|valid[ao] fino al|termini di validità)\s*(\d{2}/\d{2}/\d{4})", source, re.I)
    if m:
        return m.group(1)

    m = re.search(r"(?:fino al|entro il|immatricolazioni fino al|contratti stipulati.*?fino al|termini di validità)\s*(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})", source, re.I)
    if m:
        mese = mesi.get(m.group(2).lower(), "")
        if mese:
            return f"{m.group(1).zfill(2)}/{mese}/{m.group(3)}"

    return ""

def is_active(scad):
    if not scad:
        return False
    try:
        d = datetime.strptime(scad, "%d/%m/%Y").date()
        return d >= datetime.now().date()
    except:
        return False

def promo_hash(row):
    raw = "|".join([
        row.get("Brand",""), row.get("Titolo Promo",""), row.get("Rata",""), row.get("Intero",""),
        row.get("TAN (%)",""), row.get("TAEG (%)",""), row.get("Scadenza",""), row.get("Offer URL","")
    ])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def parse_detail(page, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3500)

    # Prassi: aprire sempre la nota legale/dettaglio prima di estrarre.
    for label in ["Dettaglio Promozione", "Dettaglio promozione", "Nota legale", "Condizioni"]:
        try:
            loc = page.get_by_text(label, exact=False)
            if loc.count() > 0:
                loc.first.click(timeout=5000, force=True)
                page.wait_for_timeout(1800)
        except Exception:
            pass

    body = page.locator("body").inner_text(timeout=30000)
    legal = extract_legal(body)
    source = legal

    title = extract_title(body, url)
    model = model_from_url(url)
    mot = motore_from_url_and_text(url, body)

    rata = euro(extract_rata(source)) if legal else ""
    intero = euro(extract_intero(source)) if legal else ""
    tan, taeg = extract_tan_taeg(source) if legal else ("", "")
    scad = extract_scadenza(source) if legal else ""

    missing = []
    if not mot: missing.append("motorizzazione")
    if not rata and "acquisto" not in url: missing.append("rata")
    if not intero: missing.append("intero")
    if not tan and "acquisto" not in url: missing.append("tan")
    if not taeg and "acquisto" not in url: missing.append("taeg")
    if not scad: missing.append("scadenza")
    if not legal:
        missing.append("note_legali")
        missing.append("legal_source_required_no_card_fallback")

    stato = "attiva" if is_active(scad) else "scaduta"
    if missing:
        stato = "incompleta" if stato == "attiva" else stato

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    row = {
        "Brand": BRAND,
        "Modello": model,
        "Titolo Promo": title,
        "Motorizzazione": mot,
        "Rata": rata,
        "Intero": intero,
        "TAN (%)": tan,
        "TAEG (%)": taeg,
        "Scadenza": scad,
        "Note Legali": legal,
        "Fonte URL": HUB,
        "Offer URL": url,
        "Data Aggiornamento": now,
        "Data Scansione": now,
        "Last Seen": now,
        "Stato": stato,
        "Alert Type": "",
        "Promo Hash": "",
        "Extraction Confidence": "high" if not missing else "medium",
        "Run ID": run_id,
        "Note Tecniche": "; ".join([f"missing_{m}" for m in missing])
    }
    row["Promo Hash"] = promo_hash(row)
    return row

def get_urls(page):
    page.goto(HUB, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(5000)

    urls = page.locator("a").evaluate_all("""
        els => [...new Set(els.map(a => a.href).filter(h =>
            h.includes('/acquista/offerte-privati/')
            && h.endsWith('.html')
            && h.toLowerCase().includes('finanziamento')
            && !h.toLowerCase().includes('acquisto')
        ))]
    """)
    return urls

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

def main():
    run_id = "citroen_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        hub_page = browser.new_page(viewport={"width": 1366, "height": 1800})

        urls = get_urls(hub_page)
        print(f"URL CITROEN TROVATI: {len(urls)}")

        detail = browser.new_page(viewport={"width": 1366, "height": 1800})

        for i, url in enumerate(urls, start=1):
            try:
                r = parse_detail(detail, url, run_id)

                # Regola ferrea: se non c'è DETTAGLIO PROMOZIONE / nota legale estesa,
                # non scrivere la riga prendendo valori da card/body.
                if not r.get("Note Legali"):
                    print(f"SKIP NO LEGAL | {url} | {r['Modello']} | {r['Titolo Promo']}")
                    continue

                rows.append(r)
                print(f"{i}/{len(urls)} | {r['Modello']} | {r['Titolo Promo']} | {r['Rata']} | {r['Intero']} | {r['TAN (%)']} | {r['TAEG (%)']} | {r['Scadenza']}")
            except Exception as e:
                print(f"ERRORE URL: {url} | {e}")

        browser.close()

    write_to_sheet(rows)
    print(f"RIGHE CITROEN SCRITTE: {len(rows)}")
    print("SHEET AGGIORNATO")

if __name__ == "__main__":
    main()
