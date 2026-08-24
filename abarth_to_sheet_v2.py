from playwright.sync_api import sync_playwright
import re
from datetime import datetime

from promo_common import clean, build_row

BRAND = "Abarth"
HUB = "https://www.abarth.it/offerte"

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
    page.goto(HUB, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(6000)

    links = page.locator("a").evaluate_all("""
        els => [...new Set(els.map(a => a.href).filter(h =>
            h.includes('/offerte/')
            && h !== 'https://www.abarth.it/offerte'
            && !h.includes('privacy')
            && !h.includes('cookie')
        ))]
    """)

    urls = []
    seen = set()
    for u in links:
        if not u:
            continue
        u = u.split("#")[0].strip()
        if "/offerte/" not in u:
            continue
        if u.rstrip("/") == HUB:
            continue
        if u not in seen:
            seen.add(u)
            urls.append(u)

    return urls

def slug_from_url(url):
    return url.rstrip("/").split("/")[-1].lower()

def model_from_url_title(url, title):
    s = (url + " " + title).lower()
    if "600" in s:
        return "600e"
    if "500" in s:
        return "500e"
    return ""

def motore_from_title_url(title, url, legal):
    s = (title + " " + url + " " + legal[:1000]).lower()
    if "elettrica" in s or "500e" in s or "600e" in s or "electric" in s:
        return "elettrica"
    return ""

def title_from_legal_or_url(legal, url):
    txt = clean(legal)
    txt = re.sub(r"\s+", " ", txt).strip()

    patterns = [
        r"(Abarth\s+500e\s+.*?)(?:\s+Listino|\s+Prezzo|\s+promo)",
        r"(Abarth\s+600e\s+.*?)(?:\s+Listino|\s+Prezzo|\s+promo)",
        r"(Abarth\s+500e)(?:\s+Hatchback|\s+Listino|\s+promo)",
        r"(Abarth\s+600e)(?:\s+Turismo|\s+Listino|\s+promo)",
    ]

    for pat in patterns:
        m = re.search(pat, txt, re.I)
        if m:
            t = clean(m.group(1))
            t = re.sub(r"\s+", " ", t).strip(" .,:;")
            if len(t) > 4:
                return t

    slug = slug_from_url(url).replace("-", " ").title()
    if "500" in slug:
        return "Abarth 500E"
    if "600" in slug:
        return "Abarth 600E"
    return slug

def claim_from_legal(legal):
    claims = []
    low = legal.lower()
    if "sconto abarth" in low:
        claims.append("sconto Abarth")
    if "non cumulabile" in low:
        claims.append("non cumulabile")
    if "con finanziamento" in low or "finanziamento stellantis" in low:
        claims.append("finanziamento")
    return "; ".join(dict.fromkeys(claims))

def extract_legal_from_html(html):
    text = html_to_text(html)
    low = text.lower()

    starts = []
    for needle in ["dettaglio promozione", "iniziativa valida"]:
        idx = low.find(needle)
        if idx != -1:
            starts.append(idx)

    if not starts:
        return ""

    legal = text[min(starts):].strip()

    legal = re.sub(r"<!--\s*", " ", legal)
    legal = re.sub(r"-+>\s*", " ", legal)

    # Residui navigazione/accordion del sito.
    legal = re.sub(r"\bBack\b", " ", legal, flags=re.I)
    legal = re.sub(r"\s+Back\s+", " ", legal, flags=re.I)
    legal = re.sub(r"\bIndietro\b", " ", legal, flags=re.I)

    legal = re.sub(r"\s+", " ", legal).strip()

    stop_patterns = [
        r"\bDESIDERO\s+RICHIEDERE\b",
        r"\bRichiedi\s+Informazioni\b",
        r"\bI\s+tuoi\s+dati\b",
        r"\bConcessionaria\b",
        r"\bScegli\s+il\s+modello\b",
        r"\bCompila\s+con\s+i\s+tuoi\s+dati\b",
        r"\bCONSENSO\b",
        r"\bRequired\s+Field\b",
        r"\bRequired\s+field\b",
        r"#AnagraficRECText#",
        r"#label_mittente#",
        r"#label_destinatario#",
        r"#bro#",
        r"#pbr#",
    ]

    stops = []
    for pat in stop_patterns:
        m = re.search(pat, legal, flags=re.I)
        if m and m.start() > 500:
            stops.append(m.start())

    if stops:
        legal = legal[:min(stops)].strip()

    legal = legal.replace("�", "")
    legal = re.sub(r"\s+€", " €", legal)
    legal = re.sub(r"(?<=\d)€", "€", legal)
    legal = re.sub(r"\s+([,.;:])", r"\1", legal)
    legal = re.sub(r"\s+", " ", legal).strip()

    if legal.rstrip().lower().endswith("documentazione precontrattuale bancaria/assicurativa in"):
        legal = re.sub(
            r"Documentazione\s+precontrattuale\s+bancaria/assicurativa\s+in\s*$",
            "Documentazione precontrattuale bancaria/assicurativa in concessionaria e sul sito www.stellantis-financial-services.it (Sez. Trasparenza).",
            legal,
            flags=re.I
        )

    # Ultimo passaggio anti-residui.
    legal = re.sub(r"\bBack\b", " ", legal, flags=re.I)
    legal = re.sub(r"\bIndietro\b", " ", legal, flags=re.I)
    legal = re.sub(r"\s+", " ", legal).strip()

    return clean(legal)

def abarth_money(v):
    if not v:
        return ""
    v = str(v).strip().split(",")[0]
    return "€ " + v

def abarth_intero_from_legal(legal):
    patterns = [
        r"promo\s*€\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})",
        r"promo\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})\s*€",
        r"prezzo\s+promo:\s*€\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})",
        r"prezzo\s+promo\s*€\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})",
    ]
    for pat in patterns:
        m = re.search(pat, legal, re.I)
        if m:
            return abarth_money(m.group(1))
    return ""

def parse_detail(page, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(5000)

    html = page.evaluate("() => document.body.innerHTML")
    legal = extract_legal_from_html(html)

    if not legal:
        return None

    title = title_from_legal_or_url(legal, url)
    modello = model_from_url_title(url, title)
    motore = motore_from_title_url(title, url, legal)
    claim = claim_from_legal(legal)

    row = build_row(
        brand=BRAND,
        modello=modello,
        titolo_promo=title,
        claim_promo=claim,
        motorizzazione=motore,
        legal=legal,
        fonte_url=HUB,
        offer_url=url,
        run_id=run_id,
        note_tecniche_extra=["source=detail_legal", "debug_only_no_push"],
        allow_missing_intero=True
    )

    intero = abarth_intero_from_legal(legal)
    if intero:
        row["Intero"] = intero

    return row

def build_rows():
    run_id = "abarth_v2_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []
    skipped = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])

        hub = browser.new_page(viewport={"width":1366,"height":8000})
        urls = get_urls(hub)

        print("URL ABARTH TROVATI:", len(urls))
        for u in urls:
            print("URL:", u)

        detail = browser.new_page(viewport={"width":1366,"height":10000})

        for i, url in enumerate(urls, start=1):
            try:
                r = parse_detail(detail, url, run_id)
                if not r:
                    skipped.append(f"{i} NO_ROW {url}")
                    print(f"{i}/{len(urls)} | NO_ROW | {url}")
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
                skipped.append(f"{i} ERR {url} | {e}")
                print(f"{i}/{len(urls)} | ERR | {url} | {e}")

        browser.close()

    print("RIGHE VALIDE:", len(rows))
    print("SKIPPED:", len(skipped))
    for s in skipped:
        print("SKIP:", s)

    return rows

if __name__ == "__main__":
    rows = build_rows()
    print("DEBUG ONLY: nessun push su Google Sheet")
