from playwright.sync_api import sync_playwright
from google.oauth2.service_account import Credentials
import gspread
import re
from datetime import datetime

from promo_common import HEADERS, clean, build_row

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"
BRAND = "Citroen"
HUB = "https://www.citroen.it/acquista/offerte-privati.html"

def slug_from_url(url):
    return url.rstrip("/").split("/")[-1].replace(".html", "").lower()

def model_from_url(url):
    s = slug_from_url(url)
    if "jumpy" in s:
        return "Jumpy Combi"
    if "berlingo" in s:
        return "Nuovo Berlingo"
    if "spacetourer" in s:
        return "Spacetourer"
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
    return slug_from_url(url).replace("-", " ").title()

def motore_from_url_and_legal(url, legal):
    slug = slug_from_url(url).lower()
    t = (slug + " " + legal[:1800]).lower()

    if "ami" in slug:
        return "elettrica"
    if "plug-in" in t or "plug in" in t or "phev" in t:
        return "plug-in"
    if any(x in t for x in ["elettric", "100% elettrica", "bev", "e-c3", "ë-c", "ë-spacetourer", "e berlingo", "wallbox", "emissioni co2: 0"]):
        return "elettrica"
    if "hybrid" in t or "ibrid" in t:
        return "hybrid"
    if "diesel" in t or "bluehdi" in t:
        return "diesel"
    if "benzina" in t or "turbo" in t or "puretech" in t:
        return "benzina"
    return ""

def get_urls(page):
    page.goto(HUB, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)

    urls = page.locator("a").evaluate_all("""
        els => [...new Set(els.map(a => a.href).filter(h =>
            h.includes('/acquista/offerte-privati/')
            && h.endsWith('.html')
            && h.toLowerCase().includes('finanziamento')
            && !h.toLowerCase().includes('acquisto')
        ))]
    """)
    return urls

def click_legal(page):
    # Click robusto su dettaglio promozione / nota legale.
    labels = ["Dettaglio Promozione", "Dettaglio promozione", "Nota legale", "Condizioni"]
    for label in labels:
        try:
            loc = page.get_by_text(label, exact=False)
            if loc.count() > 0:
                for i in range(min(loc.count(), 3)):
                    try:
                        loc.nth(i).click(timeout=4000, force=True)
                        page.wait_for_timeout(1200)
                    except Exception:
                        pass
        except Exception:
            pass

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
    for stop in stops:
        idx = sub.find(stop)
        if idx != -1 and idx > 300:
            end = min(end, idx)

    return clean(sub[:end])

def title_from_legal_or_body(body, legal, url):
    lines = [x.strip() for x in body.splitlines() if x.strip()]

    trims = ["YOU", "PLUS", "MAX", "BUSINESS", "FEEL", "SHINE", "LIVE", "PACK", "ë-Series", "E-SERIES"]
    for i, line in enumerate(lines[:160]):
        if line.upper() in [x.upper() for x in trims]:
            parts = [line]
            for j in range(i + 1, min(i + 5, len(lines))):
                nxt = lines[j].strip()
                low = nxt.lower()
                if any(stop in low for stop in ["dettaglio", "n°", "tan", "taeg", "anticipo", "rata", "prezzo", "scopri"]):
                    break
                if len(nxt) <= 90:
                    parts.append(nxt)
            if len(parts) >= 2:
                return clean(" ".join(parts))

    # fallback dalla nota: testo tra "su C3..." e ":"
    m = re.search(r"su\s+(?:NUOVA\s+)?(?:CITROEN\s+|CITROËN\s+)?(?:C3|C4|C5|AMI|BERLINGO|SPACETOURER|JUMPY|C3 AIRCROSS|C5 AIRCROSS|Ë-C4|E-C3)?\s*([^:]{8,100}):", legal, re.I)
    if m:
        return clean(m.group(1))

    return slug_from_url(url).replace("finanziamento", "").replace("-", " ").title()

def normalize_title(title):
    t = title.strip()
    replacements = {
        "YOU HYBRID 100 Automatico YOU": "YOU Hybrid 110 Automatico",
        "X HYBRID 136 eDCS6 YOU": "YOU Hybrid 136 eDCS6",
        "PLUS HYBRID 145 Automatico": "PLUS Hybrid 145 Automatico",
    }
    return replacements.get(t, t)

def claim_from_legal(legal):
    claims = []
    low = legal.lower()
    if "anticipo 0" in low or "anticipo zero" in low:
        claims.append("anticipo zero")
    if "permuta/rottamazione" in low or "permuta e rottamazione" in low:
        claims.append("permuta/rottamazione")
    if "non cumulabile" in low:
        claims.append("non cumulabile")
    if "garanzia speciale" in low:
        claims.append("garanzia speciale")
    if "wallbox" in low:
        claims.append("wallbox inclusa")
    return "; ".join(claims)

def parse_detail(page, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3500)

    click_legal(page)

    body = page.locator("body").inner_text(timeout=30000)
    legal = extract_legal(body)

    if not legal:
        return None

    modello = model_from_url(url)
    titolo = normalize_title(title_from_legal_or_body(body, legal, url))
    mot = motore_from_url_and_legal(url, legal)
    claim = claim_from_legal(legal)

    return build_row(
        brand=BRAND,
        modello=modello,
        titolo_promo=titolo,
        claim_promo=claim,
        motorizzazione=mot,
        legal=legal,
        fonte_url=HUB,
        offer_url=url,
        run_id=run_id,
        note_tecniche_extra=["source=detail_legal"],
        allow_missing_intero=True,
    )

def write_to_sheet(rows):
    raise RuntimeError("DISABLED: citroen_to_sheet_v2.py è parser-only. Usa citroen_push_to_sheet.py per scrivere su Google Sheet.")

def safe_cell_value(v):
    v = "" if v is None else str(v)
    if len(v) > 49000:
        return v[:49000] + " ... [TRONCATO PER LIMITE GOOGLE SHEETS]"
    return v

MIN_EXPECTED_ROWS = 1

def build_rows():
    run_id = "citroen_v2_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        hub = browser.new_page(viewport={"width": 1366, "height": 5000})
        urls = get_urls(hub)
        print("URL FINANZIAMENTO TROVATI:", len(urls))

        detail = browser.new_page(viewport={"width": 1366, "height": 7000})

        skipped = 0
        for i, url in enumerate(urls, start=1):
            try:
                r = parse_detail(detail, url, run_id)
                if not r:
                    skipped += 1
                    print(f"SKIP NO LEGAL | {i}/{len(urls)} | {url}")
                    continue
                rows.append(r)
                print(
                    f"{i}/{len(urls)} | {r['Modello']} | {r['Titolo Promo']} | "
                    f"{r['Rata']} | {r['Intero']} | {r['Anticipo']} | {r['Rata Finale / VFG']} | "
                    f"{r['TAN (%)']} | {r['TAEG (%)']} | {r['Scadenza']} | {r['Legal Source Status']}"
                )
            except Exception as e:
                skipped += 1
                print(f"ERRORE | {i}/{len(urls)} | {url} | {e}")

        browser.close()

    print("RIGHE VALIDE:", len(rows))
    print("SKIPPED:", skipped)
    print("DEBUG ONLY: nessun push su Google Sheet")
    return rows

def main():
    print("Parser only: usa citroen_push_to_sheet.py per scrivere su Google Sheet.")
    rows = build_rows()
    print("RIGHE CITROEN DEBUG:", len(rows))

if __name__ == "__main__":
    main()
