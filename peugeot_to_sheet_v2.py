from playwright.sync_api import sync_playwright
import re
from datetime import datetime

from promo_common import clean, build_row

BRAND = "Peugeot"
HUB = "https://www.peugeot.it/acquista/offerte-privati.html"

def html_to_text(html):
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"</p>|</div>|</li>|</h[1-6]>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&euro;", "€")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()

def get_urls(page):
    page.goto(HUB, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(6000)

    urls = page.locator("a").evaluate_all("""
        els => [...new Set(els.map(a => a.href).filter(h =>
            h.includes('/acquista/offerte-privati/')
            && h.endsWith('.html')
            && !h.toLowerCase().includes('business')
        ))]
    """)

    # Mantiene solo URL dettaglio offerte, esclude hub stesso.
    urls = [u for u in urls if u.rstrip("/") != HUB.rstrip("/")]
    return urls

def slug_from_url(url):
    return url.rstrip("/").split("/")[-1].replace(".html","").lower()

def model_from_slug(url):
    s = slug_from_url(url)
    if "e-208" in s or s == "208-elettrica":
        return "E-208"
    if "208" in s:
        return "208"
    if "e-2008" in s or "2008-elettrica" in s:
        return "E-2008"
    if "2008" in s:
        return "2008"
    if "e-308-sw" in s:
        return "E-308 SW"
    if "e-308" in s:
        return "E-308"
    if "308-sw" in s:
        return "308 SW"
    if "308" in s:
        return "308"
    if "408" in s:
        return "408"
    if "3008" in s:
        return "3008"
    if "5008" in s:
        return "5008"
    if "508" in s:
        return "508"
    if "rifter" in s:
        return "Rifter"
    return s.replace("-", " ").title()

def motore_from_url_and_legal(url, legal):
    title = title_from_legal_or_url(legal, url).lower()
    slug = slug_from_url(url)

    # Priorità assoluta al titolo della promo, non ai consumi/emissioni nella nota.
    if "bluehdi" in title or "blue hdi" in title or "diesel" in title:
        return "diesel"
    if "plug-in hybrid" in title or "hybrid plug-in" in title or "plug in" in title:
        return "plug-in"
    if "hybrid" in title or "e-dcs" in title or "e-dsc" in title:
        return "hybrid"
    if "motore elettrico" in title or "elettric" in title or "electric" in title or slug.startswith("e-"):
        return "elettrica"
    if "benzina" in title or "turbo benzina" in title:
        return "benzina"

    low = (url + " " + legal).lower()
    if "bluehdi" in low or "blue hdi" in low or "diesel" in low:
        return "diesel"
    if "plug-in" in low or "plug in" in low:
        return "plug-in"
    if "hybrid" in low:
        return "hybrid"
    if "elettric" in low or "electric" in low or slug.startswith("e-"):
        return "elettrica"
    if "benzina" in low or "turbo" in low:
        return "benzina"
    return ""

def extract_legal(body):
    m = re.search(r"DETTAGLIO PROMOZIONE", body, re.I)
    if not m:
        return ""

    sub = body[m.start():]
    cut_positions = []

    # Taglia eventuali seconde note / componenti successivi.
    for pattern in [
        r"Nota\s+legale\s+e\s+consumi\s+DETTAGLIO\s+PROMOZIONE",
        r"DETTAGLIO\s+PROMOZIONE",
    ]:
        matches = list(re.finditer(pattern, sub, re.I))
        if len(matches) > 1:
            cut_positions.append(matches[1].start())

    markers = [
        "SELEZIONA IL MODELLO",
        "Seleziona il modello",
        "INSERISCI I TUOI DATI",
        "Inserisci i tuoi dati",
        "LA TUA PRIVACY",
        "La tua privacy",
        "Configura",
        "Contatta il Concessionario",
        "Pronta consegna",
        "Gamma",
        "© Peugeot",
        "Copyright",
        "Preferenze sui cookie",
    ]
    for marker in markers:
        idx = sub.find(marker)
        if idx != -1 and idx > 300:
            cut_positions.append(idx)

    if cut_positions:
        sub = sub[:min(cut_positions)]

    return clean(sub)

def title_from_legal_or_url(legal, url):
    m = re.search(r"\bsu\s+([^:]{8,180}):", legal, re.I)
    if m:
        t = clean(m.group(1))
        t = re.sub(r"\bPeugeot\s+", "Peugeot ", t, flags=re.I)
        return t
    return model_from_slug(url)

def claim_from_legal(legal):
    low = legal.lower()
    claims = []
    if "permuta" in low and "rottamazione" in low:
        claims.append("permuta/rottamazione")
    elif "rottamazione" in low:
        claims.append("rottamazione")
    elif "permuta" in low:
        claims.append("permuta")
    if "peugeot care" in low or "garanzia peugeot care" in low or "8 anni di garanzia" in low:
        claims.append("Peugeot Care / garanzia")
    if "wallbox" in low:
        claims.append("wallbox inclusa")
    if "pronta consegna" in low or "stock" in low:
        claims.append("stock/pronta consegna")
    if "non cumulabile" in low:
        claims.append("non cumulabile")
    return "; ".join(dict.fromkeys(claims))

def peugeot_money(value):
    n = re.search(r"\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?", value or "")
    if not n:
        return ""
    raw = n.group(0).replace(".", "").replace(",", ".")
    try:
        return "€ " + f"{int(round(float(raw))):,}".replace(",", ".")
    except Exception:
        return ""

def peugeot_intero_from_legal(legal):
    m = re.search(r"oppure\s*([\d\.,]+)\s*€\s*oltre\s+oneri\s+finanziari", legal, re.I)
    if m:
        return peugeot_money(m.group(1))
    m = re.search(r"Prezzo\s+promo\s+oltre\s+oneri\s+finanziari:?\s*([\d\.,]+)\s*€", legal, re.I)
    if m:
        return peugeot_money(m.group(1))
    return ""

def peugeot_dovuto_from_legal(legal):
    # Peugeot in alcune note spezza "Importo" come "I mporto".
    patterns = [
        r"I\s*mporto\s+Totale\s+Dovuto\s*([\d\.,]+)\s*€",
        r"Importo\s+Totale\s+Dovuto\s*([\d\.,]+)\s*€",
        r"I\s*mporto\s+Totale\s+Dovuto[^0-9]{0,40}([\d\.,]+)\s*€",
        r"Importo\s+Totale\s+Dovuto[^0-9]{0,40}([\d\.,]+)\s*€",
    ]
    for pat in patterns:
        m = re.search(pat, legal, re.I)
        if m:
            return peugeot_money(m.group(1))
    return ""

def parse_detail(page, url, run_id):
    page.goto(url, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(5000)

    html = page.evaluate("() => document.body.innerHTML")
    body = html_to_text(html)
    legal = extract_legal(body)

    if not legal:
        print("DEBUG NO LEGAL:", url, "| final_url:", page.url, "| dettaglio_html:", "DETTAGLIO PROMOZIONE" in html)
        return None

    row = build_row(
        brand=BRAND,
        modello=model_from_slug(url),
        titolo_promo=title_from_legal_or_url(legal, url),
        claim_promo=claim_from_legal(legal),
        motorizzazione=motore_from_url_and_legal(url, legal),
        legal=legal,
        fonte_url=HUB,
        offer_url=url,
        run_id=run_id,
        note_tecniche_extra=["source=detail_legal", "debug_only_no_push"],
        allow_missing_intero=True,
    )

    intero = peugeot_intero_from_legal(legal)
    if intero:
        row["Intero"] = intero

    dovuto = peugeot_dovuto_from_legal(legal)
    if dovuto:
        row["Importo Totale Dovuto"] = dovuto

    return row

if __name__ == "__main__":
    run_id = "peugeot_debug_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []
    skipped = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        hub = browser.new_page(viewport={"width":1366,"height":7000})
        urls = get_urls(hub)
        print("URL PEUGEOT TROVATI:", len(urls))
        for u in urls:
            print("URL:", u)

        page = browser.new_page(viewport={"width":1366,"height":10000})
        for i,u in enumerate(urls, start=1):
            r = parse_detail(page, u, run_id)
            if not r:
                skipped.append(u)
                print(f"SKIP NO LEGAL | {i}/{len(urls)} | {u}")
                continue

            rows.append(r)
            print(
                f"{i}/{len(urls)} | {r['Modello']} | {r['Motorizzazione']} | {r['Titolo Promo']} | "
                f"{r['Claim Promo']} | {r['Rata']} | {r['Intero']} | {r['Anticipo']} | "
                f"{r['Rata Finale / VFG']} | {r['Importo Totale Credito']} | {r['Importo Totale Dovuto']} | "
                f"{r['TAN (%)']} | {r['TAEG (%)']} | {r['Scadenza']} | {r['Legal Source Status']} | {r['Note Tecniche']}"
            )

        browser.close()

    print("RIGHE VALIDE:", len(rows))
    print("SKIPPED:", len(skipped))
    for s in skipped:
        print("SKIPPED_URL:", s)
    print("DEBUG ONLY: nessun push su Google Sheet")
