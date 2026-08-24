from datetime import datetime
import re
import hashlib
from playwright.sync_api import sync_playwright

from promo_common import HEADERS, clean

BRAND = "Nissan"
BASE = "https://www.nissan.it/offerte.html#category=Vetture"
MIN_EXPECTED_ROWS = 7

MODELS = {
    "JUKE": "JUKEF16B",
    "QASHQAI": "QASHQAIJ12B",
    "X-TRAIL": "XTRAILT33C",
    "NUOVA MICRA": "MICRAK151",
    "NUOVA LEAF": "LEAFZE2A",
}

def norm(t):
    return re.sub(r"\s+", " ", clean(t or "")).strip()

def euro(x):
    x = str(x or "").strip()
    if not x:
        return ""
    x = x.replace("€", "").strip()
    return "€ " + x

def perc(x):
    x = str(x or "").strip().replace(".", ",")
    return x + "%" if x and not x.endswith("%") else x

def accept_cookie(page):
    for txt in ["Accetta e chiudi", "Accetta solo necessari"]:
        try:
            loc = page.locator(f"text={txt}").first
            if loc.count() > 0:
                loc.click(timeout=2000, force=True)
                page.wait_for_timeout(500)
                return
        except Exception:
            pass

def get_offer_ids(browser, model_name, model_value):
    page = browser.new_page(viewport={"width": 1440, "height": 5200})
    page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    accept_cookie(page)

    page.locator("select").nth(1).select_option(model_value)
    page.wait_for_timeout(5000)

    body = norm(page.locator("body").inner_text(timeout=30000))
    m = re.search(r"(\d+)\s+Offerte corrispondenti", body)
    declared = int(m.group(1)) if m else 0

    links = page.locator("a[href*='offerId=']")
    ids = []
    for i in range(links.count()):
        href = links.nth(i).get_attribute("href") or ""
        mm = re.search(r"offerId=([^&]+)", href)
        if mm and mm.group(1) not in ids:
            ids.append(mm.group(1))

    page.close()
    return declared, ids

def read_modal(browser, model_name, model_value, offer_id):
    page = browser.new_page(viewport={"width": 1440, "height": 5200})
    page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    accept_cookie(page)

    page.locator("select").nth(1).select_option(model_value)
    page.wait_for_timeout(5000)

    links = page.locator("a[href*='offerId=']")
    target = None
    for i in range(links.count()):
        href = links.nth(i).get_attribute("href") or ""
        if offer_id in href:
            target = links.nth(i)
            break

    if target is None:
        page.close()
        return "", "target_not_found"

    target.scroll_into_view_if_needed(timeout=5000)
    page.wait_for_timeout(500)
    target.click(timeout=8000, force=True)
    page.wait_for_timeout(3500)

    modals = page.locator(".offer-detail-modal.open, .modal.open")
    if modals.count() == 0:
        txt = page.locator("body").inner_text(timeout=30000)
        status = "modal_not_found_body_used"
    else:
        txt = modals.first.inner_text(timeout=10000)
        status = "modal_found"

    page.close()
    return norm(txt), status

def extract_scadenza(note):
    m = re.search(r"Offerta valida fino al\s*(\d{2}/\d{2}/\d{4})", note, re.I)
    return m.group(1) if m else ""

def extract_rata(note):
    patterns = [
        r"(?:TUO|TUA|SUBITO TUO|GAMMA DA).*?€\s*([\d\.,]+)\s+AL\s+MESE",
        r"(\d+)\s+rate\s+da\s*€\s*([\d\.,]+)",
        r"canone\s+di\s*€\s*([\d\.,]+)",
    ]
    for pat in patterns:
        m = re.search(pat, note, re.I)
        if m:
            val = m.group(2) if len(m.groups()) >= 2 and m.group(2) else m.group(1)
            return euro(val.split(",")[0])
    return ""


def parse_amount_int(x):
    try:
        return int(str(x or "").replace(".", "").replace(",", "").strip())
    except Exception:
        return None

def extract_intero(note):
    # 1) Prezzo reale nelle note legali: "... a € XX prezzo chiavi in mano"
    matches = re.findall(r"a\s*€\s*([\d\.,]+)\s+prezzo chiavi in mano", note, re.I)
    if matches:
        # prende l'importo più plausibile, escludendo rate piccole
        nums = []
        for x in matches:
            raw = x.split(",")[0]
            n = parse_amount_int(raw)
            if n and n >= 10000:
                nums.append(raw)
        if nums:
            return euro(nums[0])

    # 2) Prezzo secco esplicito, non seguito da "al mese"
    patterns = [
        r"(?:SUBITO TUO A|GAMMA DA)\s*€\s*([\d\.,]+)(?!\s+AL\s+MESE)",
        r"(?:TUO DA|TUA DA)\s*€\s*([\d\.,]+)\s+O\s+(?:DA\s+)?€\s*[\d\.,]+\s+AL\s+MESE",
    ]

    for pat in patterns:
        m = re.search(pat, note, re.I)
        if m:
            raw = m.group(1).split(",")[0]
            n = parse_amount_int(raw)
            if n and n >= 10000:
                return euro(raw)

    return ""

def extract_anticipo(note):
    if "ANTICIPO Ø" in note.upper():
        return "€ 0"
    m = re.search(r"ANTICIPO\s*€\s*([\d\.,]+)", note, re.I)
    if m:
        return euro(m.group(1).split(",")[0])
    m = re.search(r"anticipo\s*€\s*([\d\.,]+)", note, re.I)
    if m:
        return euro(m.group(1).split(",")[0])
    return ""

def extract_vfg(note):
    m = re.search(r"VALORE FUTURO GARANTITO.*?€\s*([\d\.,]+)", note, re.I)
    if m:
        return euro(m.group(1).split(",")[0])
    m = re.search(r"Valore Futuro Garantito\s*€\s*([\d\.,]+)", note, re.I)
    if m:
        return euro(m.group(1).split(",")[0])
    return ""

def extract_credito(note):
    m = re.search(r"Importo Totale del Credito\s*€\s*([\d\.,]+)", note, re.I)
    return euro(m.group(1).split(",")[0]) if m else ""

def extract_dovuto(note):
    m = re.search(r"Importo totale dovuto dal consumatore\s*€\s*([\d\.,]+)", note, re.I)
    return euro(m.group(1).split(",")[0]) if m else ""

def extract_tan_taeg(note):
    tan = ""
    taeg = ""
    m = re.search(r"TAN\s*([\d\.,]+)\s*%", note, re.I)
    if m:
        tan = perc(m.group(1))
    m = re.search(r"TAEG\s*([\d\.,]+)\s*%", note, re.I)
    if m:
        taeg = perc(m.group(1))
    return tan, taeg

def motore_from_note(model_name, note):
    s = (model_name + " " + note[:900]).lower()
    if "e-power" in s or "full hybrid" in s or "hybrid" in s:
        return "hybrid"
    if "elettric" in s or "emissioni co2: 0" in s or "40kw/h" in s or "leaf" in s:
        return "elettrica"
    if "benzina" in s or "dig-t" in s:
        return "benzina"
    return ""

def title_from_note(model_name, note):
    upper_model = model_name
    lines = [x.strip() for x in str(note).split(" ") if x.strip()]
    if "NOLEGGIO" in note[:500].upper():
        if "e-POWER HYBRID" in note[:900]:
            return f"{upper_model} e-POWER Hybrid Noleggio"
        if "FULL HYBRID" in note[:900].upper():
            return f"{upper_model} Full Hybrid Noleggio"
        if "BENZINA" in note[:900].upper():
            return f"{upper_model} Benzina Noleggio"
        return f"{upper_model} Noleggio"
    if "GAMMA HYBRID" in note[:900].upper():
        return f"{upper_model} Gamma Hybrid"
    if "E-POWER HYBRID" in note[:900].upper():
        return f"{upper_model} e-POWER Hybrid"
    if "ENGAGE" in note[:900].upper():
        return f"{upper_model} Engage"
    if "SUBITO TUO" in note[:700].upper():
        return f"{upper_model} Incentivi"
    return upper_model

def claim_from_note(note):
    low = note.lower()
    claims = []
    if "nissan pop summer" in low:
        claims.append("Nissan Pop Summer")
    if "incentivi nissan" in low or "incentivi" in low:
        claims.append("incentivi Nissan")
    if "noleggio" in low:
        claims.append("noleggio")
    if "intelligent buy" in low or "valore futuro garantito" in low:
        claims.append("finanziamento Intelligent Buy")
    if "pronta consegna" in low:
        claims.append("pronta consegna")
    if "permuta" in low:
        claims.append("permuta")
    if "rottamazione" in low:
        claims.append("rottamazione")
    if "partita iva" in low:
        claims.append("partita IVA")
    return "; ".join(dict.fromkeys(claims))

def active(scadenza):
    try:
        d = datetime.strptime(scadenza, "%d/%m/%Y").date()
        return "attiva" if d >= datetime.now().date() else "scaduta"
    except Exception:
        return ""

def promo_hash(row):
    raw = "|".join([row.get(k,"") for k in ["Brand","Modello","Titolo Promo","Rata","Intero","Scadenza","Offer URL"]])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def row_from_detail(model_name, model_value, offer_id, note, status, run_id):
    tan, taeg = extract_tan_taeg(note)
    scad = extract_scadenza(note)

    is_noleggio = "ESEMPIO DI NOLEGGIO" in note or "NOLEGGIO" in note[:700].upper()
    is_prezzo_secco = "ESEMPIO DI FINANZIAMENTO" not in note and not is_noleggio

    tech = [f"source=modal_detail", f"offer_id={offer_id}"]
    if is_noleggio:
        tech.append("noleggio")
        tech.append("tan_taeg_not_applicable")
    elif is_prezzo_secco:
        tech.append("prezzo_secco_incentivi")
        tech.append("tan_taeg_not_applicable")
    else:
        tech.append("finanziamento_intelligent_buy")

    row = {
        "Brand": BRAND,
        "Modello": model_name,
        "Titolo Promo": title_from_note(model_name, note),
        "Motorizzazione": motore_from_note(model_name, note),
        "Claim Promo": claim_from_note(note),
        "Rata": extract_rata(note),
        "Intero": extract_intero(note),
        "Anticipo": extract_anticipo(note),
        "Rata Finale / VFG": extract_vfg(note),
        "Importo Totale Credito": extract_credito(note),
        "Importo Totale Dovuto": extract_dovuto(note),
        "TAN (%)": tan,
        "TAEG (%)": taeg,
        "Scadenza": scad,
        "Note Legali": note,
        "Fonte URL": BASE,
        "Offer URL": BASE + "&model=" + model_value + "&offerId=" + offer_id,
        "Data Aggiornamento": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Data Scansione": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Last Seen": datetime.now().strftime("%Y-%m-%d"),
        "Stato": active(scad),
        "Alert Type": "",
        "Promo Hash": "",
        "Extraction Confidence": "high" if status == "modal_found" else "medium",
        "Run ID": run_id,
        "Legal Source Status": "extended_legal_found",
        "Note Tecniche": "; ".join(tech),
    }
    row["Promo Hash"] = promo_hash(row)
    return row

def build_rows():
    run_id = "nissan_v2_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []
    bad = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])

        items = []
        for name, value in MODELS.items():
            declared, ids = get_offer_ids(browser, name, value)
            print(name, "| offerte dichiarate:", declared, "| detail ids:", ids)
            for oid in ids:
                items.append((name, value, oid))

        print("TOTALE NISSAN DETAIL:", len(items))

        for i, (name, value, oid) in enumerate(items, start=1):
            note, status = read_modal(browser, name, value, oid)
            row = row_from_detail(name, value, oid, note, status, run_id)

            flags = []
            if name not in note:
                flags.append("model_not_in_note")
            if not row["Scadenza"]:
                flags.append("missing_scadenza")
            if not row["Note Legali"] or len(row["Note Legali"]) < 1200:
                flags.append("note_short")
            if not row["Rata"] and not row["Intero"]:
                flags.append("missing_rata_intero")
            if "finanziamento_intelligent_buy" in row["Note Tecniche"]:
                for col in ["Anticipo", "Rata Finale / VFG", "Importo Totale Credito", "Importo Totale Dovuto", "TAN (%)", "TAEG (%)"]:
                    if not row.get(col):
                        flags.append("missing_" + col)

            print(
                f"{i}/{len(items)} | {row['Modello']} | {row['Motorizzazione']} | {row['Titolo Promo']} | "
                f"{row['Claim Promo']} | {row['Rata']} | {row['Intero']} | {row['Anticipo']} | "
                f"{row['Rata Finale / VFG']} | {row['Importo Totale Credito']} | {row['Importo Totale Dovuto']} | "
                f"{row['TAN (%)']} | {row['TAEG (%)']} | {row['Scadenza']} | {row['Note Tecniche']} | FLAGS: {flags}"
            )

            # Regola progetto: escludiamo i noleggi, manteniamo solo offerte acquisto/finanziamento.
            if "noleggio" in row["Note Tecniche"]:
                print("SKIP NOLEGGIO:", row["Modello"], "|", row["Titolo Promo"], "|", row["Offer URL"])
                continue

            # Regola progetto: escludiamo i noleggi, manteniamo solo offerte acquisto/finanziamento.
            if "noleggio" in row["Note Tecniche"]:
                print("SKIP NOLEGGIO:", row["Modello"], "|", row["Titolo Promo"], "|", row["Offer URL"])
                continue

            if flags:
                bad.append((row["Titolo Promo"], flags))
            rows.append(row)

        browser.close()

    print("RIGHE NISSAN:", len(rows))
    print("BAD:", bad)
    print("DEBUG ONLY: nessun push su Google Sheet")
    return rows

if __name__ == "__main__":
    build_rows()
