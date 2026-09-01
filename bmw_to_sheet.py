from playwright.sync_api import sync_playwright
import re, hashlib
from datetime import datetime

BRAND = "BMW"
HUB_URL = "https://offerte.bmw.it/embedded"
FONTE_URL = "https://www.bmw.it/it/topics/offerte-bmw/panoramica.html"

def parse_num(s):
    if not s:
        return None
    s = str(s).replace("€", "").strip()
    m = re.search(r"\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?", s)
    if not m:
        return None
    n = m.group(0).replace(".", "").replace(",", ".")
    try:
        return float(n)
    except Exception:
        return None

def euro(s):
    n = parse_num(s)
    if n is None:
        return ""
    return "€ " + f"{int(round(n)):,}".replace(",", ".")

def pct(s):
    if not s:
        return ""
    return s.replace(".", ",").strip() + "%"

def find1(patterns, text):
    for pat in patterns:
        m = re.search(pat, text, re.I | re.S)
        if m:
            return m.group(1)
    return ""

def active(scad):
    try:
        return "attiva" if datetime.strptime(scad, "%d/%m/%Y").date() >= datetime.now().date() else "scaduta"
    except Exception:
        return ""

def motore_da_path(path):
    p = path.lower()
    if "plug-in" in p or "edrive" in p:
        return "plug-in"
    if "/bmw-i/" in p or "/i" in p.split("/")[-1][:2]:
        return "elettrica"
    return "diesel"

def discover_urls(page):
    page.goto(HUB_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    hrefs = page.eval_on_selector_all(
        "a[data-href]",
        "els => els.map(e => e.getAttribute('data-href'))"
    )
    paths = sorted(set(
        h for h in hrefs
        if h and not h.startswith("/embedded") and h.count("/") >= 2
    ))
    return [(p, "https://offerte.bmw.it/embedded" + p) for p in paths]

def extract_note(body):
    low = body.lower()
    start = low.find("*un esempio rappresentativo")
    if start == -1:
        start = low.find("un esempio rappresentativo")
    if start == -1:
        start = low.find("leasing finanziario")
    if start == -1:
        return ""

    sub = body[start:]
    stops = [
        "\nNoleggio a lungo termine",
        "\nBack to Navigation",
        "\nCostruita per",
        "\nPiacere di guidare",
        "\nBMW SERVICE",
        "\nL'App My BMW",
    ]
    end = len(sub)
    for stop in stops:
        i = sub.find(stop)
        if i != -1 and i > 500:
            end = min(end, i)
    return sub[:end].strip()

def parse_page(page, path, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)

    body = page.evaluate("() => document.body.innerText")
    note = extract_note(body)
    source = note if note else body

    m_title = re.search(r"BMW\s+[A-Za-z0-9 ]+?\n[A-Za-z0-9 ]+?\nBMW\s+WHY-BUY", body)
    modello = path.strip("/").split("/")[-1].replace("-", " ").upper()
    title_match = re.search(r"BMW\s+([A-Za-z0-9 ]+?)\n([^\n]+)\nBMW\s+WHY-BUY", body)
    if title_match:
        modello = title_match.group(1)
        title = f"BMW {title_match.group(1)} {title_match.group(2)}"
    else:
        title = f"BMW {modello}"

    motore = motore_da_path(path)

    rata_raw = find1([
        r"A\s+partire\s+da\s*([\d\.,]+)\s*€\s+al\s+mese",
        r"Primo\s+canone[^€]{0,80}€\s*([\d\.,]+)",
    ], source)

    intero_raw = find1([
        r"Prezzo\s+auto\s+proposto\s+dalle\s+Concessionarie\s+aderenti\s*€\s*([\d\.,]+)",
    ], source)

    tan_raw = find1([r"Tasso\s+Leasing\s*([\d\.,]+)\s*%"], source)
    taeg_raw = find1([r"TAEG\s*([\d\.,]+)\s*%"], source)

    scad = find1([
        r"Offerta\s+valida\s+fino\s+al\s+(\d{2}/\d{2}/\d{4})",
        r"Offerta\s+valida\s+fino\s+al\s+(\d{2}\.\d{2}\.\d{4})",
        r"acquistate\s+entro\s+il\s+(\d{2}/\d{2}/\d{4})",
        r"acquistate\s+entro\s+il\s+(\d{2}\.\d{2}\.\d{4})",
    ], source).replace(".", "/")

    extras = []
    anticipo = find1([r"Anticipo\s+o\s+eventuale\s+permuta\s*€\s*([\d\.,]+)"], source)
    if anticipo:
        extras.append("anticipo € " + anticipo)

    durata = find1([r"Durata\s*:?\s*(\d+)\s+mesi"], source)
    if durata:
        extras.append(durata + " mesi")

    canoni = find1([r"con\s+(\d+)\s+canoni\s+mensili"], source)
    if canoni:
        extras.append(canoni + " canoni")

    finale = find1([
        r"Opzione\s+di\s+acquisto[^€]{0,120}€\s*([\d\.,]+)",
    ], source)
    if finale:
        extras.append("rata_finale € " + finale)

    credito = find1([r"Importo\s+totale\s+del\s+credito\s*€\s*([\d\.,]+)"], source)
    if credito:
        extras.append("importo_totale_credito € " + credito)

    dovuto = find1([r"Importo\s+totale\s+dovuto\s+dal\s+Cliente\s*€\s*([\d\.,]+)"], source)
    if dovuto:
        extras.append("importo_totale_dovuto € " + dovuto)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    row = {
        "Brand": BRAND,
        "Modello": modello,
        "Titolo Promo": title,
        "Motorizzazione": motore,
        "Rata": euro(rata_raw),
        "Intero": euro(intero_raw),
        "TAN (%)": pct(tan_raw),
        "TAEG (%)": pct(taeg_raw),
        "Scadenza": scad,
        "Note Legali": note,
        "Fonte URL": FONTE_URL,
        "Offer URL": url,
        "Data Aggiornamento": now,
        "Data Scansione": now,
        "Last Seen": now,
        "Stato": active(scad) if scad else "incompleta",
        "Alert Type": "",
        "Promo Hash": "",
        "Extraction Confidence": "high",
        "Run ID": run_id,
        "Note Tecniche": "",
    }

    missing = []
    if not row["Rata"]: missing.append("missing_rata")
    if not row["Intero"]: missing.append("missing_intero")
    if not row["TAN (%)"]: missing.append("missing_tan")
    if not row["TAEG (%)"]: missing.append("missing_taeg")
    if not row["Scadenza"]: missing.append("missing_scadenza")
    if not row["Note Legali"]: missing.append("missing_note_legali")

    if missing:
        row["Stato"] = "incompleta"
        row["Extraction Confidence"] = "medium"

    row["Note Tecniche"] = "; ".join(["source=offerte.bmw.it_embedded"] + extras + missing)

    raw = "|".join([row["Brand"], row["Modello"], row["Titolo Promo"], row["Rata"], row["Intero"], row["TAN (%)"], row["TAEG (%)"], row["Scadenza"], row["Offer URL"]])
    row["Promo Hash"] = hashlib.md5(raw.encode("utf-8")).hexdigest()

    return row

def build_rows():
    run_id = "bmw_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        hub_page = browser.new_page(viewport={"width": 1366, "height": 5200})
        targets = discover_urls(hub_page)
        print("BMW URL scoperti dinamicamente:", len(targets))
        for path, url in targets:
            print(" -", path, "->", url)

        page = browser.new_page(viewport={"width": 1366, "height": 5200})
        for path, url in targets:
            r = parse_page(page, path, url, run_id)
            rows.append(r)
            print(
                r["Modello"], "|", r["Motorizzazione"], "|",
                r["Rata"], "|", r["Intero"], "|",
                r["TAN (%)"], "|", r["TAEG (%)"], "|",
                r["Scadenza"], "|", r["Stato"], "|",
                r["Note Tecniche"]
            )

        browser.close()

    return rows

if __name__ == "__main__":
    rows = build_rows()
    print("\nRIGHE BMW TOTALI:", len(rows))
