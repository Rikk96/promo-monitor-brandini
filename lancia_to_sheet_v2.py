from playwright.sync_api import sync_playwright
import re
from datetime import datetime

from promo_common import clean, build_row

BRAND = "Lancia"
HUB = "https://www.lancia.it/offerte-ypsilon"

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

    urls = page.locator("a").evaluate_all("""
        els => [...new Set(els.map(a => a.href).filter(h =>
            h.includes('/offerte-ypsilon/')
            && !h.endsWith('/offerte-ypsilon')
            && !h.includes('#')
        ))]
    """)

    # tieni solo pagine offerta reali
    out = []
    seen = set()
    for u in urls:
        if not u:
            continue
        if any(x in u.lower() for x in ["privacy", "cookie", "contatti", "brochure"]):
            continue
        if u not in seen:
            seen.add(u)
            out.append(u)

    return out

def slug_from_url(url):
    return url.rstrip("/").split("/")[-1].lower()

def model_from_url_title(url, title):
    return "Ypsilon"

def motore_from_title_url(title, url, legal):
    s = (title + " " + url + " " + legal[:1000]).lower()

    if "elettrica" in s or "electric" in s or "280cv" in s:
        return "elettrica"
    if "ibrida" in s or "hybrid" in s or "1.2 110" in s:
        return "hybrid"
    if "benzina" in s or "turbo" in s:
        return "benzina"
    return ""

def title_from_legal_or_url(legal, url):
    txt = clean(legal)
    txt = re.sub(r"\s+", " ", txt).strip()

    # Titolo tra iniziativa e listino/prezzo
    patterns = [
        r"Iniziativa\s+valida\s+fino\s+al\s+30\s+Giugno\s+2026\.\s*(.*?)(?:\s+Listino|\s+Prezzo\s+di\s+Listino|:\s+Prezzo\s+di\s+Listino)",
        r"Iniziativa\s+valida\s+fino\s+al\s+30\.06\.2026\.\s*(.*?)(?:\s+Listino|\s+Prezzo\s+di\s+Listino|:\s+Prezzo\s+di\s+Listino)",
        r"(Lancia\s+Ypsilon\s+.*?)(?:\s*:\s*Prezzo\s+di\s+Listino|\s+Prezzo\s+di\s+Listino)",
        r"(Ypsilon\s+.*?)(?:\s+Listino|\s+Prezzo\s+di\s+Listino)",
    ]

    for pat in patterns:
        m = re.search(pat, txt, re.I)
        if m:
            t = clean(m.group(1))
            t = re.sub(r"^Lancia\s+", "", t, flags=re.I).strip()
            t = re.sub(r"\s+", " ", t).strip(" .,:;")
            if len(t) > 4:
                return t

    slug = slug_from_url(url).replace("-", " ").title()
    return slug

def claim_from_legal(legal):
    claims = []
    low = legal.lower()

    if "permuta" in low:
        claims.append("permuta")
    if "rottamazione" in low:
        claims.append("rottamazione")
    if "pronta consegna" in low or "selezione di vetture" in low:
        claims.append("stock/pronta consegna")
    if "non cumulabile" in low:
        claims.append("non cumulabile")
    if "sconto lancia" in low:
        claims.append("sconto Lancia")
    if "solo con finanziamento" in low or "con finanziamento" in low:
        claims.append("finanziamento")

    return "; ".join(dict.fromkeys(claims))

def is_lead_gen_form(text):
    """Riconosce le pagine 'Richiedi Informazioni' (modulo lead a 3 step:
    Modello / I tuoi dati / Concessionaria) che compaiono tra i link della hub
    ma non sono pagine offerta vere - non hanno mai avuto una nota legale."""
    low = text.lower()
    return (
        "i tuoi dati" in low
        and "concessionaria" in low
        and "compila con i tuoi dati" in low
        and "prezzo" not in low
        and "dettaglio promozione" not in low
        and "iniziativa valida" not in low
    )

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

    # pulizia HTML/commenti
    legal = re.sub(r"<!--\s*", " ", legal)
    legal = re.sub(r"-+>\s*", " ", legal)
    legal = re.sub(r"\bBack\b", " ", legal, flags=re.I)
    legal = re.sub(r"\s+", " ", legal).strip()

    # stop form/CTA
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
        if m and m.start() > 700:
            stops.append(m.start())

    if stops:
        legal = legal[:min(stops)].strip()

    # Pulizia caratteri corrotti da encoding vicino a euro/spazi.
    legal = legal.replace("�", "")
    legal = re.sub(r"\s+€", " €", legal)
    legal = re.sub(r"([0-9]),\s*€", r"\1 €", legal)

    legal = re.sub(r"\s+([,.;:])", r"\1", legal)
    legal = re.sub(r"\s+", " ", legal).strip()

    # completa eventuale frase spezzata
    if legal.rstrip().lower().endswith("documentazione precontrattuale bancaria/assicurativa in"):
        legal = re.sub(
            r"Documentazione\s+precontrattuale\s+bancaria/assicurativa\s+in\s*$",
            "Documentazione precontrattuale bancaria/assicurativa in concessionaria e sul sito www.stellantis-financial-services.it (Sez. Trasparenza).",
            legal,
            flags=re.I
        )

    return clean(legal)

def lancia_money(v):
    if not v:
        return ""
    v = str(v).strip().split(",")[0]
    return "€ " + v

def lancia_intero_from_legal(legal):
    patterns = [
        r"prezzo\s+promo\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})\s*€",
        r"Prezzo\s+Promo\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})\s*€",
        r"promo\s*€\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})",
        r"Prezzo\s+Promo\s*€\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})",
    ]
    for pat in patterns:
        m = re.search(pat, legal, re.I)
        if m:
            return lancia_money(m.group(1))
    return ""

def parse_detail(page, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(5000)

    html = page.evaluate("() => document.body.innerHTML")
    legal = extract_legal_from_html(html)

    if not legal:
        text = html_to_text(html)
        if is_lead_gen_form(text):
            print("SKIP (modulo Richiedi Informazioni, non e una pagina offerta):", url)
            return "NOT_OFFER"
        print("DEBUG NO LEGAL:", url)
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

    intero = lancia_intero_from_legal(legal)
    if intero:
        row["Intero"] = intero

    return row

def build_rows():
    run_id = "lancia_v2_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []
    skipped = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])

        hub = browser.new_page(viewport={"width":1366,"height":8000})
        urls = get_urls(hub)

        print("URL LANCIA TROVATI:", len(urls))
        for u in urls:
            print("URL:", u)

        detail = browser.new_page(viewport={"width":1366,"height":10000})

        for i, url in enumerate(urls, start=1):
            try:
                r = parse_detail(detail, url, run_id)
                if r == "NOT_OFFER":
                    print(f"{i}/{len(urls)} | SKIP (modulo richiesta info, non offerta) | {url}")
                    continue
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
