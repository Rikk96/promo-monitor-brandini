from playwright.sync_api import sync_playwright
import re
from datetime import datetime

from promo_common import clean, build_row

BRAND = "Leapmotor"
HUB = "https://www.leapmotor.net/it"

MODEL_URLS = {
    "T03": "https://www.leapmotor.net/it/t03",
    "B10": "https://www.leapmotor.net/it/b10-reev-hybrid",
    "C10": "https://www.leapmotor.net/it/c10-reev-hybrid",
    "B05": "https://www.leapmotor.net/it/b05",
}

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
    # Discovery dinamica: parte dai modelli noti, ma prova anche link promo/prodotto dalla home.
    page.goto(HUB, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(7000)

    urls = []
    seen = set()

    for u in MODEL_URLS.values():
        if u not in seen:
            seen.add(u)
            urls.append(u)

    links = page.locator("a").evaluate_all("""
        els => [...new Set(els.map(a => a.href).filter(h =>
            h.includes('leapmotor.net/it/')
        ))]
    """)

    for u in links:
        if not u:
            continue
        u = u.split("#")[0].split("?")[0].rstrip("/")
        slug = u.rstrip("/").split("/")[-1].lower()
        if slug in ["t03", "b05", "b10-reev-hybrid", "c10-reev-hybrid"]:
            if u not in seen:
                seen.add(u)
                urls.append(u)

    return urls

def modello_from_url(url):
    s = url.lower()
    if "t03" in s:
        return "T03"
    if "b10" in s:
        return "B10"
    if "c10" in s:
        return "C10"
    if "b05" in s:
        return "B05"
    return ""

def motore_from_legal_title(title, legal):
    s = (title + " " + legal[:1500]).lower()

    if "reev" in s or "hybrid" in s:
        return "hybrid"

    if (
        "consumo di energia elettrica" in s
        or "emissioni co2 (g/km): 0" in s
        or "emissioni co₂ (g/km): 0" in s
        or "t03" in s
        or "b05" in s
    ):
        return "elettrica"

    return ""

def title_from_legal(legal, modello):
    txt = clean(legal)
    txt = re.sub(r"\s+", " ", txt).strip()

    patterns = [
        r"DETTAGLIO\s+PROMOZIONE:?\s*(Leapmotor\s+B05\s+Life)",
        r"DETTAGLIO\s+PROMOZIONE:?\s*(B10\s+REEV\s+HYBRID\s+Life)",
        r"DETTAGLIO\s+PROMOZIONE:?\s*(C10\s+REEV\s+HYBRID\s+Life)",
        r"DETTAGLIO\s+PROMOZIONE:?\s*(T03)",
        r"(Leapmotor\s+B05\s+Life)",
        r"(B10\s+REEV\s+HYBRID\s+Life)",
        r"(C10\s+REEV\s+HYBRID\s+Life)",
    ]

    for pat in patterns:
        m = re.search(pat, txt, re.I)
        if m:
            t = clean(m.group(1))
            t = re.sub(r"^Leapmotor\s+", "", t, flags=re.I).strip()
            return t

    # fallback sicuro per i 4 modelli noti
    fallbacks = {
        "T03": "T03",
        "B10": "B10 REEV HYBRID Life",
        "C10": "C10 REEV HYBRID Life",
        "B05": "B05 Life",
    }
    return fallbacks.get(modello, modello)

def claim_from_legal(legal):
    claims = []
    low = legal.lower()
    if "permuta" in low:
        claims.append("permuta")
    if "rottamazione" in low:
        claims.append("rottamazione")
    if "non cumulabile" in low:
        claims.append("non cumulabile")
    if "clientela privata" in low:
        claims.append("clientela privata")
    return "; ".join(dict.fromkeys(claims))

def extract_legal_from_html(html):
    text = html_to_text(html)
    low = text.lower()

    starts = []
    for needle in ["dettaglio promozione", "prezzo promo"]:
        idx = low.find(needle)
        if idx != -1:
            starts.append(idx)

    if not starts:
        return ""

    legal = text[min(starts):].strip()

    # taglia eventuali blocchi non legali/form
    stop_patterns = [
        r"\bDESIDERO\s+RICHIEDERE\b",
        r"\bRichiedi\s+Informazioni\b",
        r"\bI\s+tuoi\s+dati\b",
        r"\bCONSENSO\b",
        r"\bRequired\s+Field\b",
        r"#AnagraficRECText#",
        r"\bScopri\s+di\s+più\b",
        r"\bPrenota\s+un\s+test\s+drive\b",
    ]

    stops = []
    for pat in stop_patterns:
        m = re.search(pat, legal, flags=re.I)
        if m and m.start() > 700:
            stops.append(m.start())
    if stops:
        legal = legal[:min(stops)].strip()

    legal = legal.replace("�", "")
    legal = re.sub(r"<!--\s*", " ", legal)
    legal = re.sub(r"-+>\s*", " ", legal)
    legal = re.sub(r"\bBack\b", " ", legal, flags=re.I)

    # Taglia footer/link generici del sito dopo la parte legale e consumi.
    footer_markers = [
        "Segui Leapmotor",
        "Data Act",
        "Informazioni Legali",
        "Politica dei cookie",
        "Tutela dei dati personali",
    ]
    cut_points = []
    for marker in footer_markers:
        idx = legal.lower().find(marker.lower())
        if idx != -1 and idx > 900:
            cut_points.append(idx)
    if cut_points:
        legal = legal[:min(cut_points)].strip()

    legal = re.sub(r"\s+€", " €", legal)
    legal = re.sub(r"\s+([,.;:])", r"\1", legal)
    legal = re.sub(r"\s+", " ", legal).strip()

    return clean(legal)

def leap_money(v):
    if not v:
        return ""
    v = str(v).strip().split(",")[0]
    return "€ " + v

def intero_from_legal(legal):
    patterns = [
        r"Prezzo\s+Promo\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})\s*€",
        r"Prezzo\s+Promo\s*€\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})",
    ]
    for pat in patterns:
        m = re.search(pat, legal, re.I)
        if m:
            return leap_money(m.group(1))
    return ""

def parse_detail(page, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(5000)

    html = page.evaluate("() => document.body.innerHTML")
    legal = extract_legal_from_html(html)

    if not legal:
        return None

    modello = modello_from_url(url)
    title = title_from_legal(legal, modello)
    motore = motore_from_legal_title(title, legal)
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

    intero = intero_from_legal(legal)
    if intero:
        row["Intero"] = intero

    return row

def build_rows():
    run_id = "leapmotor_v2_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []
    skipped = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])

        hub = browser.new_page(viewport={"width":1366,"height":8000})
        urls = get_urls(hub)

        print("URL LEAPMOTOR TROVATI:", len(urls))
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
