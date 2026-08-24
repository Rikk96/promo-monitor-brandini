from playwright.sync_api import sync_playwright
import re
from datetime import datetime

from promo_common import clean, build_row

BRAND = "Opel"
HUB = "https://www.opel.it/offerte/privati.html"

def slug_from_url(url):
    return url.rstrip("/").split("/")[-1].replace(".html", "").lower()

def model_from_slug(url):
    s = slug_from_url(url)
    if "corsa" in s:
        return "Corsa"
    if "mokka" in s:
        return "Mokka"
    if "frontera" in s:
        return "Frontera"
    if "astra-sports-tourer" in s:
        return "Astra Sports Tourer"
    if "astra" in s:
        return "Astra"
    if "grandland" in s:
        return "Grandland"
    if "zafira" in s:
        return "Zafira"
    if "combo" in s:
        return "Combo"
    return s.replace("-", " ").title()

def motore_from_url_and_legal(url, legal):
    slug = slug_from_url(url).lower()
    t = (slug + " " + legal[:1200]).lower()

    if "plug-in" in slug or "plug-in" in t or "plug in" in t:
        return "plug-in"
    if "elettrico" in slug or "elettrica" in slug or "electric" in slug or "leasing" in slug:
        return "elettrica"
    if "hybrid" in slug or "ibrido" in slug or "hybrid" in t or "ibrid" in t:
        return "hybrid"
    if "diesel" in slug or "diesel" in t or "bluehdi" in t:
        return "diesel"
    if "benzina" in slug or "benzina" in t or "turbo" in t:
        return "benzina"
    return ""

def get_urls(page):
    page.goto(HUB, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(5000)

    urls = page.locator("a").evaluate_all("""
        els => [...new Set(els.map(a => a.href).filter(h =>
            h.includes('/offerte/privati/')
            && h.endsWith('.html')
            && !h.toLowerCase().includes('noleggio')
            && (
                h.toLowerCase().includes('finanziamento')
                || h.toLowerCase().includes('leasing')
            )
        ))]
    """)

    # Esclude pagina non standard: redirect a store.opel.it/configurable senza DETTAGLIO PROMOZIONE.
    urls = [u for u in urls if "zafira-diesel-finanziamento.html" not in u.lower()]

    return urls

def click_legal(page):
    # Opel: click JS sul primo q-expander-header-elem visibile/con testo "Nota legale e consumi".
    try:
        page.evaluate("""
            () => {
                const elems = [...document.querySelectorAll('.q-expander-header-elem')];
                const target = elems.find(e => (e.innerText || e.textContent || '').trim().toLowerCase().includes('nota legale e consumi'));
                if (target) {
                    target.scrollIntoView({block:'center'});
                    target.click();
                    if (target.parentElement) target.parentElement.click();
                }
            }
        """)
        page.wait_for_timeout(2500)

        body = page.evaluate("() => document.body.innerText")
        if "DETTAGLIO PROMOZIONE" in body:
            return True
    except Exception:
        pass

    # fallback: click su text locator senza filtri
    try:
        loc = page.locator("text=Nota legale e consumi")
        for i in range(min(loc.count(), 5)):
            try:
                loc.nth(i).click(timeout=4000, force=True)
                page.wait_for_timeout(2000)
                body = page.evaluate("() => document.body.innerText")
                if "DETTAGLIO PROMOZIONE" in body:
                    return True
            except Exception:
                pass
    except Exception:
        pass

    return False

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

def extract_legal(body):
    # Opel: nella pagina dettaglio l'HTML può contenere più note nascoste,
    # anche vecchie MY25. Prendiamo SOLO il primo DETTAGLIO PROMOZIONE
    # della pagina vettura specifica.
    m = re.search(r"DETTAGLIO PROMOZIONE", body, re.I)
    if not m:
        return ""

    sub = body[m.start():]

    cut_positions = []

    # Secondo blocco nota: da tagliare sempre.
    for pattern in [
        r"Nota\s+legale\s+e\s+consumi\s+DETTAGLIO\s+PROMOZIONE",
        r"DETTAGLIO\s+PROMOZIONE",
    ]:
        matches = list(re.finditer(pattern, sub, re.I))
        if len(matches) > 1:
            cut_positions.append(matches[1].start())
        elif len(matches) == 1 and pattern.lower().startswith("nota"):
            cut_positions.append(matches[0].start())

    # Marker di uscita pagina/form/configuratore.
    markers = [
        "1. Scegli il tuo modello preferito",
        "SELEZIONA IL MODELLO",
        "Seleziona il modello",
        "INSERISCI I TUOI DATI",
        "Inserisci i tuoi dati",
        "LA TUA PRIVACY",
        "La tua privacy",
        "Lead Type Code",
        "Configura",
        "Contatta il Concessionario",
        "Pronta consegna",
        "Vetture",
        "Gamma elettrica",
        "Mondo Opel",
        "© Opel",
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

def title_from_legal_or_body(body, legal, url):
    # Fonte primaria: nota legale estesa.
    # Esempi:
    # "su Corsa MY26A Edition 1.2 Benzina 100 cv, cambio manuale:"
    # "su Mokka Edition MY26A 54 kWh 156 cv, cambio automatico:"
    m = re.search(r"\bsu\s+([^:]{8,160}):", legal, re.I)
    if m:
        t = clean(m.group(1))
        t = re.sub(r"\bOpel\s+", "", t, flags=re.I)
        return t

    # fallback da slug
    return slug_from_url(url).replace("finanziamento", "").replace("leasing", "").replace("-", " ").strip().title()

def claim_from_legal(legal):
    claims = []
    low = legal.lower()

    if re.search(r"anticipo\s*(?:0|zero)\s*€?", low):
        claims.append("anticipo zero")
    if re.search(r"permuta\s*/\s*rottamazione|permuta\s+e\s+rottamazione|permuta\s+o\s+rottamazione|in\s+caso\s+di\s+permuta.*rottamazione", low):
        claims.append("permuta/rottamazione")
    elif "rottamazione" in low:
        claims.append("rottamazione")
    elif "permuta" in low:
        claims.append("permuta")
    if "non cumulabile" in low:
        claims.append("non cumulabile")
    if "fino a esaurimento" in low or "stock disponibile" in low or "pronta consegna" in low:
        claims.append("stock/pronta consegna")
    if "garanzia speciale" in low or "opel care" in low:
        claims.append("garanzia/care")
    if "wallbox" in low:
        claims.append("wallbox inclusa")

    return "; ".join(dict.fromkeys(claims))

def opel_money(value):
    n = re.search(r"\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?", value or "")
    if not n:
        return ""
    raw = n.group(0).replace(".", "").replace(",", ".")
    try:
        return "€ " + f"{int(round(float(raw))):,}".replace(",", ".")
    except Exception:
        return ""

def opel_rata_from_legal(legal):
    matches = re.findall(r"n[°º]?\s*\d+\s+rate\s+da\s*([\d\.,]+)\s*€", legal, flags=re.I)
    if matches:
        vals = []
        for m in matches:
            try:
                v = float(m.replace(".", "").replace(",", "."))
                if v > 0:
                    vals.append(m)
            except Exception:
                pass
        if vals:
            return opel_money(vals[-1])
        return opel_money(matches[-1])

    m = re.search(r"\d+\s+canoni\s+mensili\s+da\s*([\d\.,]+)\s*€", legal, re.I)
    if m:
        return opel_money(m.group(1))

    m = re.search(r"canoni\s+mensili\s+da\s*([\d\.,]+)\s*€", legal, re.I)
    if m:
        return opel_money(m.group(1))

    return ""

def opel_intero_from_legal(legal):
    # preferisce prezzo specifico "oltre oneri finanziari"
    m = re.search(r"oppure\s*([\d\.,]+)\s*€\s*oltre\s+oneri\s+finanziari", legal, re.I)
    if m:
        return opel_money(m.group(1))

    m = re.search(r"Prezzo\s+promo\s+oltre\s+oneri\s+finanziari:?\s*([\d\.,]+)\s*€", legal, re.I)
    if m:
        return opel_money(m.group(1))

    m = re.search(r"Prezzo\s+Promo\s*([\d\.,]+)\s*€", legal, re.I)
    if m:
        return opel_money(m.group(1))

    return ""

def parse_detail(page, url, run_id):
    page.goto(url, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(3500)

    html = page.evaluate("() => document.body.innerHTML")
    body = html_to_text(html)
    legal = extract_legal(body)

    if not legal:
        print("DEBUG NO LEGAL:", url, "| dettaglio_html:", "DETTAGLIO PROMOZIONE" in html, "| dettaglio_text:", "DETTAGLIO PROMOZIONE" in body)
        return None

    row = build_row(
        brand=BRAND,
        modello=model_from_slug(url),
        titolo_promo=title_from_legal_or_body(body, legal, url),
        claim_promo=claim_from_legal(legal),
        motorizzazione=motore_from_url_and_legal(url, legal),
        legal=legal,
        fonte_url=HUB,
        offer_url=url,
        run_id=run_id,
        note_tecniche_extra=["source=detail_legal", "debug_only_no_push"],
        allow_missing_intero=True,
    )

    # Override specifici Opel da nota legale estesa.
    rata = opel_rata_from_legal(legal)
    intero = opel_intero_from_legal(legal)
    if rata:
        row["Rata"] = rata
    if intero:
        row["Intero"] = intero

    return row

def main():
    run_id = "opel_v2_debug_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])

        hub = browser.new_page(viewport={"width":1366,"height":6000})
        urls = get_urls(hub)

        print("URL OPEL TROVATI:", len(urls))
        for u in urls:
            print("URL:", u)

        detail = browser.new_page(viewport={"width":1366,"height":8000})

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
                    f"{i}/{len(urls)} | {r['Modello']} | {r['Motorizzazione']} | {r['Titolo Promo']} | "
                    f"{r['Claim Promo']} | {r['Rata']} | {r['Intero']} | {r['Anticipo']} | "
                    f"{r['Rata Finale / VFG']} | {r['Importo Totale Credito']} | {r['Importo Totale Dovuto']} | "
                    f"{r['TAN (%)']} | {r['TAEG (%)']} | {r['Scadenza']} | {r['Legal Source Status']} | "
                    f"{r['Note Tecniche']}"
                )
            except Exception as e:
                skipped += 1
                print(f"ERRORE | {i}/{len(urls)} | {url} | {e}")

        browser.close()

    print("RIGHE VALIDE:", len(rows))
    print("SKIPPED:", skipped)
    print("DEBUG ONLY: nessun push su Google Sheet")

if __name__ == "__main__":
    main()
