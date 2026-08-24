from playwright.sync_api import sync_playwright
import re
from datetime import datetime

from promo_common import clean, build_row

BRAND = "DS"
HUB = "https://www.dsautomobiles.it/acquisto-noleggio/offerte-privati.html"

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
    page.wait_for_timeout(7000)

    urls = page.locator("a").evaluate_all("""
        els => [...new Set(els.map(a => a.href).filter(h =>
            h.includes('/acquisto-noleggio/offerte-privati/')
            && h.endsWith('.html')
            && !h.includes('offerte-privati.html')
        ))]
    """)

    # Solo URL vere offerta DS, evitiamo tutorial o altro.
    good = []
    for u in urls:
        low = u.lower()
        if any(x in low for x in [
            "ds3-acquisto",
            "ds3-e-tense",
            "ds7-diesel",
            "ds7-plug-in-hybrid",
            "n4-hybrid",
            "n4-diesel",
            "n4-plug-in-hybrid",
            "n8-e-tense",
        ]):
            good.append(u)

    return list(dict.fromkeys(good))

def slug_from_url(url):
    return url.rstrip("/").split("/")[-1].replace(".html", "").lower()

def model_from_url(url):
    s = slug_from_url(url)
    if "ds3" in s:
        return "DS 3"
    if "ds7" in s:
        return "DS 7"
    if "n4" in s:
        return "N°4"
    if "n8" in s:
        return "N°8"
    return ""

def motore_from_url_and_legal(url, legal):
    title = title_from_legal_or_url(legal, url).lower()
    slug = slug_from_url(url)

    if "bluehdi" in title or "diesel" in title or "diesel" in slug:
        return "diesel"
    if "plug-in hybrid" in title or "plug in" in title or "plug-in" in slug:
        return "plug-in"
    if "e-tense" in title or "100% elettric" in title or "elettric" in title or "e-tense" in slug:
        return "elettrica"
    if "hybrid" in title or "hybrid" in slug:
        return "hybrid"
    return ""

def extract_legal_from_html(html):
    text = html_to_text(html)

    low = text.lower()
    start = low.find("dettaglio promozione")
    if start == -1:
        return ""

    sub = text[start:]

    # Taglio prima di blocchi form/footer se presenti.
    cut_markers = [
        "Lascia i tuoi dati",
        "Lascia i tuoi dati Richiedi un preventivo",
        "Richiedi un preventivo",
        "Contatta il concessionario",
        "Contatta il Concessionario",
        "Configurazione del veicolo",
        "Configura e ordina",
        "Prenota appuntamento",
        "FAQ",
        "Domande frequenti",
        "Scopri il brand",
        "Note consumi Note consumi",
        "SELEZIONA IL MODELLO",
        "INSERISCI I TUOI DATI",
        "LA TUA PRIVACY",
    ]

    end = len(sub)
    for marker in cut_markers:
        idx = sub.lower().find(marker.lower())
        if idx != -1 and idx > 400:
            end = min(end, idx)

    legal = sub[:end]

    # Se per qualche motivo prende due note duplicate, tieni solo la prima fino al secondo DETTAGLIO.
    second = legal.lower().find("dettaglio promozione", 30)
    if second != -1:
        legal = legal[:second]

    legal = legal.replace("Nota legale e consumi Nota legale e consumi", "")
    legal = legal.replace("Nota legale e consumi", "")
    return clean(legal)

def title_from_legal_or_url(legal, url):
    # Esempi:
    # "su DS3 HYBRID Pallas:"
    # "su DS 7 BlueHDi 130 Automatico Pallas:"
    # "su DS N° 4 HYBRID PERFORMANCE LINE:"
    m = re.search(r"\bsu\s+([^:]{6,180}):", legal, re.I)
    if m:
        return clean(m.group(1))
    return slug_from_url(url).replace("-", " ").title()

def claim_from_legal(legal):
    low = legal.lower()
    tags = []

    if "permuta" in low:
        tags.append("permuta")
    if "rottamazione" in low:
        tags.append("rottamazione")
    if "stock" in low or "pronta consegna" in low:
        tags.append("stock/pronta consegna")
    if "non cumulabile" in low:
        tags.append("non cumulabile")
    if "wallbox" in low:
        tags.append("wallbox inclusa")

    return "; ".join(dict.fromkeys(tags))

def parse_detail(page, url, run_id):
    page.goto(url, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(6000)

    html = page.evaluate("() => document.body.innerHTML")
    legal = extract_legal_from_html(html)

    if not legal:
        print("DEBUG NO LEGAL:", url)
        return None

    row = build_row(
        brand=BRAND,
        modello=model_from_url(url),
        titolo_promo=title_from_legal_or_url(legal, url),
        motorizzazione=motore_from_url_and_legal(url, legal),
        legal=legal,
        fonte_url=HUB,
        offer_url=url,
        run_id=run_id,
        note_tecniche_extra=["source=detail_legal", "debug_only_no_push"],
        claim_promo=claim_from_legal(legal),
        allow_missing_intero=False,
    )

    # Leasing: build_row può mettere il valore di riscatto nel campo Rata Finale / VFG se trova "Valore di riscatto".
    # Se mancasse, recupero esplicito DS leasing.
    if not row.get("Rata Finale / VFG"):
        m = re.search(r"Valore\s+di\s+riscatto\s*([\d\.,]+)\s*€", legal, re.I)
        if m:
            raw = m.group(1)
            row["Rata Finale / VFG"] = "€ " + raw.split(",")[0]

    return row

def main():
    run_id = "ds_debug_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []
    skipped = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])

        hub = browser.new_page(viewport={"width":1366,"height":7000})
        urls = get_urls(hub)

        print("URL DS TROVATI:", len(urls))
        for u in urls:
            print("URL:", u)

        detail = browser.new_page(viewport={"width":1366,"height":10000})

        for i, url in enumerate(urls, start=1):
            try:
                r = parse_detail(detail, url, run_id)
                if not r:
                    skipped.append(url)
                    print(f"{i}/{len(urls)} | NO_ROW | {url}")
                    continue

                rows.append(r)
                print(
                    f"{i}/{len(urls)} | {r['Modello']} | {r['Motorizzazione']} | {r['Titolo Promo']} | "
                    f"{r['Claim Promo']} | {r['Rata']} | {r['Intero']} | {r['Anticipo']} | "
                    f"{r['Rata Finale / VFG']} | {r['Importo Totale Credito']} | {r['Importo Totale Dovuto']} | "
                    f"{r['TAN (%)']} | {r['TAEG (%)']} | {r['Scadenza']} | {r['Legal Source Status']} | {r['Note Tecniche']}"
                )
            except Exception as e:
                skipped.append(url)
                print(f"{i}/{len(urls)} | ERR | {url} | {e}")

        browser.close()

    print("RIGHE VALIDE:", len(rows))
    print("SKIPPED:", len(skipped))
    print("DEBUG ONLY: nessun push su Google Sheet")

if __name__ == "__main__":
    main()
