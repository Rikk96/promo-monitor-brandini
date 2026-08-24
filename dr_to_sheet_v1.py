from datetime import datetime
import re
import hashlib
from playwright.sync_api import sync_playwright

from promo_common import HEADERS, clean

BRAND = "DR"
HUB = "https://drautomobiles.com/promo/"
MIN_EXPECTED_ROWS = 6

def norm(t):
    return clean(str(t or "").replace("�", ""))

def euro(x):
    x = str(x or "").replace("€", "").strip()
    if not x:
        return ""
    x = x.split(",")[0]
    x = x.rstrip(".")
    return "€ " + x

def parse_scadenza(text):
    mesi = {
        "gennaio": "01", "febbraio": "02", "marzo": "03", "aprile": "04",
        "maggio": "05", "giugno": "06", "luglio": "07", "agosto": "08",
        "settembre": "09", "ottobre": "10", "novembre": "11", "dicembre": "12",
    }
    m = re.search(r"Fino\s+al\s+(\d{1,2})\s+([a-zà]+)\s+(\d{4})", text, re.I)
    if m:
        gg = m.group(1).zfill(2)
        mm = mesi.get(m.group(2).lower(), "")
        aa = m.group(3)
        if mm:
            return f"{gg}/{mm}/{aa}"
    return ""

def active(scadenza):
    try:
        d = datetime.strptime(scadenza, "%d/%m/%Y").date()
        return "attiva" if d >= datetime.now().date() else "scaduta"
    except Exception:
        return ""

def mot_from_version(versione):
    v = versione.lower()
    if "phev" in v or "superhybrid" in v:
        return "plug-in"
    if "hev" in v or "full hybrid" in v:
        return "hybrid"
    if "gpl" in v:
        return "benzina/gpl"
    if "bz" in v or "benzina" in v:
        return "benzina"
    return ""

def title_from_model_version(model, versione):
    return f"{model} {versione}".strip()

def note_from_block(block):
    return norm(block)

def claim_from_block(model, versione, bonus, mot, also_gpl):
    claims = ["Bonus DR"]
    if bonus:
        claims.append(f"bonus {euro(bonus)}")
    if versione:
        claims.append(versione)
    if mot:
        claims.append(mot)
    if also_gpl:
        claims.append("disponibile anche GPL")
    return "; ".join(dict.fromkeys(claims))

def promo_hash(row):
    raw = "|".join([row.get(k, "") for k in ["Brand","Modello","Titolo Promo","Intero","Scadenza","Offer URL"]])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def split_blocks(body):
    text = norm(body)

    # Blocchi DR reali attuali (verificati 24/08/2026):
    # DR 5 Collection Versione 1.5 MT BZ [+ eventuale "Disponibile anche GPL"]
    # DR 5 Full Hybrid Collection 1.5 HEV
    # DR 5 Stilnovo Versione Benzina [+ eventuale "Disponibile anche GPL"]
    # DR 6 Collection Versione TGDI BZ [+ eventuale "Disponibile anche GPL"]
    # DR 6 Stilnovo Versione Benzina [+ eventuale "Disponibile anche GPL"]
    # DR 6 Superhybrid Collection Superhybrid PHEV

    model_pat = r"(DR\s+\d(?:\s+(?:Full\s+Hybrid|Superhybrid))?\s+(?:Collection|Stilnovo))"
    version_pat = r"(.+?)"

    pattern = re.compile(
        model_pat +
        r"\s+" + version_pat +
        r"\s+Tua\s+con\s+Bonus\s+DR\s+"
        r"Prezzo\s+di\s+listino\s+([\d\.,]+)\s*€\*\s+"
        r"Prezzo\s+promo\s+([\d\.,]+)\s*€\s+con\s+bonus\s+DR\s+da\s+([\d\.,]+)\s*€\s*"
        r"(Disponibile\s+anche\s+GPL)?\s*"
        r"(Fino\s+al\s+\d{1,2}\s+[a-zà]+\s+\d{4})"
        r"\s+\*\(([^)]+)\)",
        re.I
    )

    out = []
    for m in pattern.finditer(text):
        model = norm(m.group(1))
        versione = norm(m.group(2)).replace("Versione ", "").strip()
        versione = re.sub(r"\s+", " ", versione).strip()

        out.append({
            "model": model,
            "versione": versione,
            "listino": m.group(3),
            "promo": m.group(4),
            "bonus": m.group(5),
            "also_gpl": bool(m.group(6)),
            "scad_text": m.group(7),
            "nota": "*(" + norm(m.group(8)) + ")",
        })

    return out

def safe_body_text(page):
    last_err = None
    for attempt in range(1, 4):
        try:
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
            return norm(page.evaluate("() => document.body ? document.body.innerText : ''"))
        except Exception as e:
            last_err = e
            print(f"DR safe_body_text retry {attempt}/3:", e)
            page.wait_for_timeout(2500)
    raise last_err

def discover_urls(page):
    """Legge dinamicamente i link alle pagine promozione dalla hub DR."""
    page.goto(HUB, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    links = page.eval_on_selector_all(
        "a[href*='drautomobiles.com/promozione']",
        "els => els.map(e => e.href)"
    )
    return sorted(set(links))

def parse_page(page, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    body = safe_body_text(page)
    blocks = split_blocks(body)

    rows = []
    for b in blocks:
        model = b["model"]
        versione = b["versione"]
        mot = mot_from_version(versione + " " + model)
        scad = parse_scadenza(b["scad_text"])
        gpl_suffix = " Disponibile anche GPL." if b["also_gpl"] else ""

        note = norm(
            f"{model} {versione}. Tua con Bonus DR. "
            f"Prezzo di listino {euro(b['listino'])}. "
            f"Prezzo promo {euro(b['promo'])} con bonus DR da {euro(b['bonus'])}."
            f"{gpl_suffix} "
            f"{b['scad_text']}. {b['nota']}"
        )

        row = {
            "Brand": BRAND,
            "Modello": model,
            "Motorizzazione": mot,
            "Titolo Promo": title_from_model_version(model, versione),
            "Claim Promo": claim_from_block(model, versione, b["bonus"], mot, b["also_gpl"]),
            "Rata": "",
            "Intero": euro(b["promo"]),
            "Anticipo": "",
            "Rata Finale / VFG": "",
            "Importo Totale Credito": "",
            "Importo Totale Dovuto": "",
            "TAN (%)": "",
            "TAEG (%)": "",
            "Scadenza": scad,
            "Note Legali": note,
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
            "Note Tecniche": "source=detail_card; no_financial_legal_found; bonus_dr" + ("; also_gpl" if b["also_gpl"] else ""),
        }
        row["Promo Hash"] = promo_hash(row)
        rows.append(row)

    return rows

def build_rows():
    run_id = "dr_v1_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 9000})

        urls = discover_urls(page)
        print(f"URL scoperti dinamicamente dalla hub: {len(urls)}")
        for u in urls:
            print("  -", u)

        for url in urls:
            page_rows = parse_page(page, url, run_id)
            rows.extend(page_rows)

        browser.close()

    seen = set()
    deduped = []
    for r in rows:
        key = (r["Modello"], r["Titolo Promo"], r["Intero"], r["Offer URL"])
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    rows = deduped

    bad = []
    for i, r in enumerate(rows, start=1):
        flags = []

        for col in ["Brand","Modello","Titolo Promo","Claim Promo","Intero","Scadenza","Note Legali","Offer URL"]:
            if not str(r.get(col, "")).strip():
                flags.append("missing_" + col)

        if not str(r.get("Motorizzazione", "")).strip():
            flags.append("missing_Motorizzazione")

        for col in ["Rata","Anticipo","Rata Finale / VFG","Importo Totale Credito","Importo Totale Dovuto","TAN (%)","TAEG (%)"]:
            if str(r.get(col, "")).strip():
                flags.append("unexpected_financial_" + col)

        if r.get("Legal Source Status") != "card_only_no_legal":
            flags.append("bad_legal_status")

        print(
            f"{i}/{len(rows)} | {r['Modello']} | {r['Motorizzazione']} | {r['Titolo Promo']} | "
            f"{r['Claim Promo']} | Intero {r['Intero']} | Scad {r['Scadenza']} | "
            f"{r['Legal Source Status']} | {r['Note Tecniche']} | FLAGS: {flags}"
        )

        if flags:
            bad.append((r["Titolo Promo"], flags))

    print("RIGHE DR:", len(rows))
    print("BAD:", bad)
    print("DEBUG ONLY: nessun push su Google Sheet")
    return rows

if __name__ == "__main__":
    build_rows()
