from playwright.sync_api import sync_playwright
import re
import hashlib
from datetime import datetime

SOURCE_URL = "https://www.fiat.it/offerte-privati"

def clean_text(t):
    return re.sub(r"\s+", " ", t or "").strip()

def parse_number_it(value):
    if not value:
        return None
    value = value.replace(".", "").replace(",", ".")
    try:
        return float(value)
    except:
        return None

def title_from_url(url):
    u = url.lower()

    if "nuova-fiat-pandina" in u:
        return "Pandina"

    if "fiat-500-ibrida-pop" in u:
        return "500 Hybrid POP"

    if "finanziamento-fiat-500-hybrid-dolcevita" in u:
        return "500 Hybrid Dolcevita"

    if "500-elettrica-red" in u:
        return "500e RED"

    if "grande-panda-benzina" in u:
        return "Grande Panda Benzina Turbo 100"

    if "grande-panda-hybrid" in u:
        return "Grande Panda Hybrid"

    return None

def extract_title(text, url):
    title = title_from_url(url)
    if title:
        return title

    lines = [clean_text(x) for x in text.splitlines() if clean_text(x)]

    bad_terms = [
        "skip",
        "modelli",
        "veicoli fiat professional",
        "configura",
        "contatti",
        "servizio clienti",
        "privacy",
        "cookie",
        "acconsento",
        "non acconsento"
    ]

    for line in lines[:60]:
        low = line.lower()

        if any(bad in low for bad in bad_terms):
            continue

        if (
            "panda" in low
            or "pandina" in low
            or "500" in low
            or "500e" in low
        ):
            if len(line) <= 90:
                return line

    return None

def extract_model_from_title(title):
    if not title:
        return None

    t = title.strip()

    if "Grande Panda" in t:
        return "Grande Panda"

    if "Pandina" in t:
        return "Pandina"

    if "500e" in t:
        return "500e"

    if "500 Hybrid" in t or "500 Ibrida" in t:
        return "500 Hybrid"

    if t.startswith("500"):
        return "500"

    return t

def extract_motorizzazione(text, url):
    t = (text + " " + url).lower()

    if "elettrica" in t or "electric" in t or "500e" in t or "500-elettrica" in t:
        return "elettrica"

    if "plug-in" in t or "plugin" in t:
        return "plug-in"

    if "hybrid" in t or "ibrida" in t or "ibrido" in t:
        return "hybrid"

    if "diesel" in t:
        return "diesel"

    if "benzina" in t:
        return "benzina"

    return None

def extract_fields(text, url):
    raw = text

    title = extract_title(raw, url)
    modello = extract_model_from_title(title)

    intero = None
    m = re.search(r"Da\s+([\d\.\,]+)\s*€", raw, re.IGNORECASE)
    if m:
        intero = parse_number_it(m.group(1))

    rata = None
    m = re.search(r"rate\s+da\s+([\d\.\,]+)\s*€", raw, re.IGNORECASE)
    if not m:
        m = re.search(r"([\d\.\,]+)\s*€\s*/\s*mese", raw, re.IGNORECASE)
    if m:
        rata = parse_number_it(m.group(1))

    tan = None
    m = re.search(r"TAN\s*(?:\(fisso\))?\s*([\d\,\.]+)\s*%", raw, re.IGNORECASE)
    if m:
        tan = parse_number_it(m.group(1))

    taeg = None
    m = re.search(r"TAEG\s*([\d\,\.]+)\s*%", raw, re.IGNORECASE)
    if m:
        taeg = parse_number_it(m.group(1))

    scadenza = None
    m = re.search(r"Validità:\s*(\d{2}/\d{2}/\d{4})", raw, re.IGNORECASE)
    if m:
        scadenza = m.group(1)

    note_legali = None
    start = raw.lower().find("dettaglio promozione")
    if start != -1:
        end_candidates = []
        for marker in ["test drive", "richiedi informazioni", "1 modello", "i tuoi dati"]:
            idx = raw.lower().find(marker, start)
            if idx != -1:
                end_candidates.append(idx)
        end = min(end_candidates) if end_candidates else len(raw)
        note_legali = raw[start:end].strip()

    motorizzazione = extract_motorizzazione((title or "") + " " + raw[:1500], url)

    stato = "attiva"
    missing = []

    if not title:
        missing.append("titolo")
    if not modello:
        missing.append("modello")
    if not motorizzazione:
        missing.append("motorizzazione")
    if not scadenza:
        missing.append("scadenza")
    if not note_legali:
        missing.append("note_legali")
    if rata is None and intero is None:
        missing.append("rata/intero")
    if rata is not None and (tan is None or taeg is None):
        missing.append("tan/taeg")

    if missing:
        stato = "incompleta"

    hash_base = f"Fiat|{modello}|{title}|{motorizzazione}|{rata}|{intero}|{tan}|{taeg}|{scadenza}|{url}"
    promo_hash = hashlib.sha256(hash_base.encode("utf-8")).hexdigest()

    confidence = 100 - (len(missing) * 15)
    if confidence < 0:
        confidence = 0

    return {
        "Brand": "Fiat",
        "Modello": modello,
        "Titolo Promo": title,
        "Motorizzazione": motorizzazione,
        "Rata": rata,
        "Intero": intero,
        "TAN (%)": tan,
        "TAEG (%)": taeg,
        "Scadenza": scadenza,
        "Note Legali": clean_text(note_legali) if note_legali else None,
        "Fonte URL": SOURCE_URL,
        "Offer URL": url,
        "Data Aggiornamento": datetime.now().strftime("%d/%m/%Y"),
        "Data Scansione": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Last Seen": datetime.now().strftime("%d/%m/%Y"),
        "Stato": stato,
        "Alert Type": "",
        "Promo Hash": promo_hash,
        "Extraction Confidence": confidence,
        "Run ID": "manual_test_fiat",
        "Note Tecniche": "; ".join(missing) if missing else ""
    }

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1366, "height": 900})

    page.goto(SOURCE_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    links = page.locator("a").evaluate_all("""
        els => els.map(a => ({
            text: (a.innerText || '').trim().replace(/\\s+/g, ' '),
            href: a.href
        }))
    """)

    offer_urls = []
    seen = set()

    for item in links:
        href = item.get("href") or ""
        if "/offerte-privati/" in href and href != SOURCE_URL and href not in seen:
            seen.add(href)
            offer_urls.append(href)

    print("OFFERTE TROVATE:", len(offer_urls))

    results = []

    for url in offer_urls:
        print("\\n---", url)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)

        text = page.locator("body").inner_text(timeout=30000)
        row = extract_fields(text, url)
        results.append(row)

        print("Modello:", row["Modello"])
        print("Titolo:", row["Titolo Promo"])
        print("Motorizzazione:", row["Motorizzazione"])
        print("Rata:", row["Rata"])
        print("Intero:", row["Intero"])
        print("TAN:", row["TAN (%)"])
        print("TAEG:", row["TAEG (%)"])
        print("Scadenza:", row["Scadenza"])
        print("Stato:", row["Stato"])
        print("Confidence:", row["Extraction Confidence"])
        print("Note tecniche:", row["Note Tecniche"])

    browser.close()

print("\\n\\n=== RISULTATI FINALI ===\\n")
for r in results:
    print(
        r["Brand"],
        "| modello:", r["Modello"],
        "| titolo:", r["Titolo Promo"],
        "|", r["Motorizzazione"],
        "| rata:", r["Rata"],
        "| intero:", r["Intero"],
        "| TAN:", r["TAN (%)"],
        "| TAEG:", r["TAEG (%)"],
        "| scad:", r["Scadenza"],
        "|", r["Stato"]
    )
