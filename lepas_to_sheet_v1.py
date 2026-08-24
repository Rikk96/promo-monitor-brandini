from datetime import datetime
import re
import hashlib
from playwright.sync_api import sync_playwright

from promo_common import HEADERS, clean, perc

BRAND = "LEPAS"
HUB = "https://www.lepasautoitalia.com/promozioni/"
MIN_EXPECTED_ROWS = 1

def norm(t):
    return clean(str(t or "").replace("\ufffd", ""))

def euro_from_raw(x):
    x = str(x or "").replace("€", "").strip()
    if not x:
        return ""
    intpart = x.split(",")[0]
    return "€ " + intpart

def parse_scadenza(text):
    m = re.search(r"(?:Offerta valida sino al|Fino al)\s*(\d{1,2})[./](\d{1,2})[./](\d{4})", text, re.I)
    if m:
        gg, mm, aa = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
        return f"{gg}/{mm}/{aa}"
    return ""

def active(scadenza):
    try:
        d = datetime.strptime(scadenza, "%d/%m/%Y").date()
        return "attiva" if d >= datetime.now().date() else "scaduta"
    except Exception:
        return ""

def promo_hash(row):
    raw = "|".join([row.get(k, "") for k in ["Brand","Modello","Titolo Promo","Intero","Scadenza","Offer URL"]])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def discover_urls(page):
    page.goto(HUB, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    links = page.eval_on_selector_all(
        "a[href*='lepasautoitalia.com/promozioni/']",
        "els => els.map(e => e.href)"
    )
    urls = sorted(set(l for l in links if l.rstrip("/") != HUB.rstrip("/")))
    return urls

def parse_page(page, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    raw_body = page.evaluate("() => document.body ? document.body.innerText : ''")
    lines = [l.strip() for l in raw_body.split("\n")]  # split PRIMA di normalizzare
    body = norm(raw_body)  # versione normalizzata solo per le regex su blocco intero

    # Modello: prima riga non vuota immediatamente sopra "Tua da"
    model = BRAND
    for i, l in enumerate(lines):
        if re.match(r"^Tua\s+da", l, re.I):
            for j in range(i - 1, -1, -1):
                if lines[j].strip():
                    model = norm(lines[j].strip())
                    break
            break

    m_rata = re.search(r"Tua\s+da\s*([\d\.,]+)\s*€\s*al\s*mese", body, re.I)
    rata = m_rata.group(1) if m_rata else ""

    m_prezzo = re.search(r"Prezzo\s+del\s+bene\s*€\s*(\d{1,3}(?:\.\d{3})*(?:,\d+)?)", body, re.I)
    intero = m_prezzo.group(1) if m_prezzo else ""

    m_anticipo = re.search(r"Anticipo\s*€\s*(\d{1,3}(?:\.\d{3})*(?:,\d+)?)", body, re.I)
    anticipo = m_anticipo.group(1) if m_anticipo else ""

    m_credito = re.search(r"Importo\s+totale\s+del\s+credito\s*€\s*(\d{1,3}(?:\.\d{3})*(?:,\d+)?)", body, re.I)
    credito = m_credito.group(1) if m_credito else ""

    m_maxirata = re.search(r"Maxi\s*rata\s+finale.*?pari\s+a\s*€\s*(\d{1,3}(?:\.\d{3})*(?:,\d+)?)", body, re.I)
    maxirata = m_maxirata.group(1) if m_maxirata else ""

    m_dovuto = re.search(r"Importo\s+totale\s+dovuto.*?maxirata\s*€\s*(\d{1,3}(?:\.\d{3})*(?:,\d+)?)", body, re.I)
    dovuto = m_dovuto.group(1) if m_dovuto else ""

    m_tan = re.search(r"Tan\s+fisso\s*([\d,]+)\s*%", body, re.I)
    tan = m_tan.group(1) if m_tan else ""

    m_taeg = re.search(r"Taeg\s*([\d,]+)\s*%", body, re.I)
    taeg = m_taeg.group(1) if m_taeg else ""

    scad = parse_scadenza(body)

    m_esempio = re.search(r"(Esempio:.*?(?:per saldi superiori a\s*€\s*77,47\.))", body, re.I | re.S)
    nota = norm(m_esempio.group(1)) if m_esempio else norm(body[:1500])

    m_primarata = re.search(r"Prima\s+rata\s+(?:tra|a)\s*(\d+)\s*g", body, re.I)
    claims = ["leasing/finanziamento"]
    if m_primarata:
        claims.append(f"prima rata a {m_primarata.group(1)} giorni")

    row = {
        "Brand": BRAND,
        "Modello": model,
        "Motorizzazione": "hybrid",
        "Titolo Promo": model,
        "Claim Promo": "; ".join(claims),
        "Rata": euro_from_raw(rata),
        "Intero": euro_from_raw(intero),
        "Anticipo": euro_from_raw(anticipo),
        "Rata Finale / VFG": euro_from_raw(maxirata),
        "Importo Totale Credito": euro_from_raw(credito),
        "Importo Totale Dovuto": euro_from_raw(dovuto),
        "TAN (%)": perc(tan),
        "TAEG (%)": perc(taeg),
        "Scadenza": scad,
        "Note Legali": nota,
        "Fonte URL": HUB,
        "Offer URL": url,
        "Data Aggiornamento": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Data Scansione": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Last Seen": datetime.now().strftime("%Y-%m-%d"),
        "Stato": active(scad),
        "Alert Type": "",
        "Promo Hash": "",
        "Extraction Confidence": "medium",
        "Run ID": run_id,
        "Legal Source Status": "extended_legal_found",
        "Note Tecniche": "source=detail_legal; leasing_fiditalia",
    }
    row["Promo Hash"] = promo_hash(row)
    return [row]

def build_rows():
    run_id = "lepas_v1_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 9000})
        urls = discover_urls(page)
        print(f"URL scoperti dinamicamente dalla hub: {len(urls)}")
        for u in urls:
            print("  -", u)
        for url in urls:
            rows.extend(parse_page(page, url, run_id))
        browser.close()

    bad = []
    for i, r in enumerate(rows, start=1):
        flags = []
        for col in ["Brand","Modello","Titolo Promo","Intero","Scadenza","Note Legali","Offer URL","TAN (%)","TAEG (%)"]:
            if not str(r.get(col, "")).strip():
                flags.append("missing_" + col)
        print(f"{i}/{len(rows)} | {r['Modello']} | Rata {r['Rata']} | Intero {r['Intero']} | TAN {r['TAN (%)']} TAEG {r['TAEG (%)']} | Scad {r['Scadenza']} | FLAGS: {flags}")
        if flags:
            bad.append((r["Titolo Promo"], flags))

    print("RIGHE LEPAS:", len(rows))
    print("BAD:", bad)
    print("DEBUG ONLY: nessun push su Google Sheet")
    return rows

if __name__ == "__main__":
    build_rows()
