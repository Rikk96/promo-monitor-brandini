from playwright.sync_api import sync_playwright
import re, hashlib
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"
BRAND = "Hyundai"
HUB_URL = "https://www.hyundai.com/it/it/promozioni-offerte/Promozioni/offerte-hyundai-plus.html"

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

def active(scad):
    try:
        return datetime.strptime(scad, "%d/%m/%Y").date() >= datetime.now().date()
    except:
        return True

def normalize_date(s):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    if m:
        return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return ""

def modello_from_title(title):
    u = title.upper()
    if "IONIQ 9" in u:
        return "IONIQ 9"
    if "SANTA FE" in u:
        return "SANTA FE"
    if "TUCSON" in u:
        return "TUCSON"
    if "KONA" in u:
        return "KONA"
    if "BAYON" in u:
        return "BAYON"
    if "INSTER" in u:
        return "INSTER"
    if "I20" in u:
        return "i20"
    return "Hyundai"

def motore_from_title(title):
    l = title.lower()
    if "plug-in" in l or "plugin" in l or "phev" in l:
        return "plug-in"
    if "hybrid" in l or "hev" in l or "full hybrid" in l:
        return "hybrid"
    if "electric" in l or "elettrica" in l or "ioniq" in l or "inster" in l:
        return "elettrica"
    return "benzina"

def title_from_body(body, url):
    lines = [x.strip() for x in body.splitlines() if x.strip()]

    candidates = []
    for l in lines[:140]:
        u = l.upper()
        if any(x in u for x in ["INSTER", "I20", "BAYON", "KONA", "TUCSON", "SANTA FE", "IONIQ 9"]):
            if len(l) <= 90 and not any(b in u for b in ["MODELLI", "TUTTI I MODELLI", "KONA ELECTRIC", "CONFIGURATORE"]):
                candidates.append(l)

    # preferisci titoli con Hyundai/Nuova o nomi modello chiari
    for c in candidates:
        if any(x in c.upper() for x in ["HYUNDAI", "NUOVA", "TUCSON", "SANTA FE", "IONIQ 9", "KONA FULL"]):
            return clean(c.replace(".", ""))

    if candidates:
        return clean(candidates[0].replace(".", ""))

    slug = url.rstrip("/").split("/")[-1].replace(".html","").replace("promozione-","").replace("-", " ").title()
    return clean(slug)

def extract_links(page):
    page.goto(HUB_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(8000)

    links = page.locator("a").evaluate_all("""
        els => [...new Set(
            els.map(a => String(a.href || '')).filter(h =>
                h.includes('/promozioni-offerte/Promozioni/')
                && h.includes('promozione')
                && h.endsWith('.html')
            )
        )]
    """)

    # Escludo solo noleggio/renting, NON business perché Tucson Plug-in Business è promo valida.
    out = []
    for u in links:
        low = u.lower()
        if "renting" in low or "noleggio" in low:
            continue
        out.append(u.split("#")[0])

    return list(dict.fromkeys(out))

def lines_from_body(body):
    return [x.strip() for x in body.splitlines() if x.strip()]

def value_after_label(lines, label):
    label_l = label.lower()

    for i, line in enumerate(lines):
        if label_l in line.lower():
            # Caso stesso blocco, ma evita di prendere TAN/TAEG o rata nella riga label.
            if label_l == "anticipo" and re.fullmatch(r"(?i)\s*anticipo\s*", line):
                pass
            else:
                m = re.search(r"€\s*([\d\.,]+)", line)
                if m and not ("tan" in line.lower() or "taeg" in line.lower()):
                    return m.group(1)

            # Cerca nelle righe successive, saltando righe descrittive e TAN/TAEG.
            for j in range(i+1, min(i+15, len(lines))):
                lj = lines[j].strip()
                low = lj.lower()

                if not lj:
                    continue

                if "tan" in low or "taeg" in low:
                    continue

                # se incontro un'altra label economica prima del valore, stop
                other_labels = [
                    "prezzo listino",
                    "vantaggio totale",
                    "prezzo in promozione senza",
                    "anticipo",
                    "valore futuro garantito",
                    "importo totale dovuto",
                    "rata mensile",
                    "equipaggiamenti",
                    "condizioni offerta",
                    "nota legale"
                ]

                if j > i+1 and any(x in low for x in other_labels):
                    break

                m = re.search(r"€\s*([\d\.,]+)", lj)
                if m:
                    return m.group(1)

    return ""

def extract_note(body):
    start = body.find("La nostra offerta.")
    if start == -1:
        start = body.find("Tua da")
    if start == -1:
        start = body.find("Prezzo listino")
    if start == -1:
        return ""

    sub = body[start:]

    stops = [
        "\nRichiedi un preventivo",
        "\nRichiedi subito",
        "\nModelli",
        "\nScarica il listino",
        "\nStiamo utilizzando i cookie",
        "\nSelect Country",
    ]

    end = len(sub)
    for s in stops:
        i = sub.find(s)
        if i != -1 and i > 700:
            end = min(end, i)

    return sub[:end].strip()

def parse_detail(page, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)

    body = page.locator("body").inner_text(timeout=30000)
    lines = lines_from_body(body)

    title = title_from_body(body, url)
    modello = modello_from_title(title)
    motore = motore_from_title(title)
    note = extract_note(body)

    rata = ""
    m = re.search(r"35\s+rate\s+da\s*€\s*([\d\.,]+)", body, re.I)
    if not m:
        m = re.search(r"da\s*€\s*([\d\.,]+)\s+al\s+mese", body, re.I)
    if m:
        rata = euro_from_str(m.group(1))

    intero_raw = ""
    m = re.search(
        r"Prezzo\s+in\s+promozione\s+con\s+finanziamento\s+Hyundai\s+Plus[\s\S]{0,180}?€\s*([\d\.,]+)",
        body,
        re.I
    )
    if m:
        intero_raw = m.group(1)
    else:
        intero_raw = value_after_label(lines, "Prezzo in promozione con finanziamento")
    intero = euro_from_str(intero_raw) if intero_raw else ""

    tan = ""
    taeg = ""
    m = re.search(r"TAN\s*([\d\.,]+)\s*%", body, re.I)
    if m:
        tan = perc(m.group(1))
    m = re.search(r"TAEG\s*([\d\.,]+)\s*%", body, re.I)
    if m:
        taeg = perc(m.group(1))

    scad = ""
    m = re.search(r"fino\s+al\s+(\d{2}/\d{2}/\d{4})", body, re.I)
    if m:
        scad = normalize_date(m.group(1))
    if not scad:
        scad = "30/06/2026"

    extras = []
    anticipo = value_after_label(lines, "Anticipo")
    if anticipo:
        extras.append("anticipo € " + anticipo)

    m = re.search(r"(\d+)\s+rate\s+da\s*€\s*([\d\.,]+)", body, re.I)
    if m:
        extras.append(f"{m.group(1)} rate")

    finale = value_after_label(lines, "Valore Futuro Garantito")
    if finale:
        extras.append("rata_finale € " + finale)

    totale = value_after_label(lines, "Importo totale dovuto")
    if totale:
        extras.append("importo_totale_dovuto € " + totale)

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
        "Titolo Promo": title,
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
    run_id = "hyundai_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,args=["--no-sandbox"])
        hub = browser.new_page(viewport={"width":1366,"height":3600})
        detail = browser.new_page(viewport={"width":1366,"height":3600})

        links = extract_links(hub)
        print("LINK HYUNDAI:", len(links))

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
    raise RuntimeError("DISABLED: hyundai_to_sheet_legacy_dependency.py è dependency-only. Usa hyundai_push_to_sheet.py per scrivere su Google Sheet.")


if __name__ == "__main__":
    print("Legacy dependency only: usa hyundai_push_to_sheet.py per scrivere su Google Sheet.")
    raise SystemExit(0)

# DISABLED ORIGINAL MAIN:
    rows = build_rows()
    write_to_sheet(rows)
    print("RIGHE HYUNDAI SCRITTE:", len(rows))
    print("SHEET AGGIORNATO")
