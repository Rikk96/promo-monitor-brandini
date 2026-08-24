from datetime import datetime
import re
import hashlib
from playwright.sync_api import sync_playwright

from promo_common import HEADERS, clean

BRAND = "Dongfeng"
HUB = "https://www.dongfeng-italia.it/promo"
MIN_EXPECTED_ROWS = 1

def norm(t):
    return clean(str(t or "").replace("\ufffd", ""))

def euro(x):
    x = str(x or "").replace("€", "").strip().rstrip(".,")
    if not x:
        return ""
    intpart = x.split(",")[0]
    return "€ " + intpart

def parse_scadenza(text):
    m = re.search(r"[Vv]alida\s+fino\s+al\s*(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?", text)
    if not m:
        return ""
    gg, mm = m.group(1).zfill(2), m.group(2).zfill(2)
    aa = m.group(3) if m.group(3) else str(datetime.now().year)
    try:
        d = datetime.strptime(f"{gg}/{mm}/{aa}", "%d/%m/%Y").date()
        if d < datetime.now().date():
            aa = str(int(aa) + 1)
    except Exception:
        pass
    return f"{gg}/{mm}/{aa}"

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
    page.wait_for_timeout(4000)
    all_links = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
    promo_links = [l for l in all_links if "dongfeng-italia.it/promo/" in l]
    urls = sorted(set(l for l in promo_links if "?" not in l))
    return urls

def parse_page(page, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    raw_body = page.evaluate("() => document.body ? document.body.innerText : ''")
    lines = [l.strip() for l in raw_body.split("\n")]  # split PRIMA di normalizzare
    body = norm(raw_body)  # versione normalizzata solo per le regex su blocco intero

    # Modello: prima riga non vuota subito DOPO la riga breadcrumb "...Promozioni vendita..."
    model = url.rstrip("/").split("/")[-1]
    for i, l in enumerate(lines):
        if "promozioni vendita" in l.lower():
            for j in range(i + 1, len(lines)):
                if lines[j].strip():
                    model = norm(lines[j].strip())
                    break
            break

    m_price = re.search(r"Tua\s+da\s*€\s*([\d\.,]+)", body, re.I)
    intero = m_price.group(1) if m_price else ""

    claim = "chiavi in mano" if "chiavi in mano" in body.lower() else ""

    scad = parse_scadenza(body)

    mot = "plug-in" if "phev" in model.lower() or "plug" in body.lower() else ""

    m_promo_sentence = re.search(
        re.escape(model) + r"\.[^\n]*Offerta valida fino al[^\n]*?\.",
        body
    )
    nota = norm(m_promo_sentence.group(0)) if m_promo_sentence else f"{model}. Tua da {euro(intero)}."

    row = {
        "Brand": BRAND,
        "Modello": model,
        "Motorizzazione": mot,
        "Titolo Promo": model,
        "Claim Promo": claim,
        "Rata": "",
        "Intero": euro(intero),
        "Anticipo": "",
        "Rata Finale / VFG": "",
        "Importo Totale Credito": "",
        "Importo Totale Dovuto": "",
        "TAN (%)": "",
        "TAEG (%)": "",
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
        "Legal Source Status": "card_only_no_legal",
        "Note Tecniche": "source=detail_card; no_financial_legal_found",
    }
    row["Promo Hash"] = promo_hash(row)
    return [row]

def build_rows():
    run_id = "dongfeng_v1_" + datetime.now().strftime("%Y%m%d_%H%M%S")
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
        for col in ["Brand","Modello","Titolo Promo","Intero","Scadenza","Note Legali","Offer URL"]:
            if not str(r.get(col, "")).strip():
                flags.append("missing_" + col)
        for col in ["Rata","Anticipo","Rata Finale / VFG","Importo Totale Credito","Importo Totale Dovuto","TAN (%)","TAEG (%)"]:
            if str(r.get(col, "")).strip():
                flags.append("unexpected_financial_" + col)
        print(f"{i}/{len(rows)} | {r['Modello']} | {r['Motorizzazione']} | Intero {r['Intero']} | Scad {r['Scadenza']} | FLAGS: {flags}")
        if flags:
            bad.append((r["Titolo Promo"], flags))

    print("RIGHE DONGFENG:", len(rows))
    print("BAD:", bad)
    print("DEBUG ONLY: nessun push su Google Sheet")
    return rows

if __name__ == "__main__":
    build_rows()
