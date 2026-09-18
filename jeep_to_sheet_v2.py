from playwright.sync_api import sync_playwright
import re
from datetime import datetime

from promo_common import clean, build_row

BRAND = "Jeep"
HUB = "https://www.jeep-official.it/offerte-privati"

def split_blocks(body):
    """La pagina hub Jeep (dal cambio struttura di settembre 2026) mostra
    tutte le offerte come blocchi ripetuti nella stessa pagina, invece di
    link a pagine dettaglio separate. Ogni blocco inizia con 'NUOVA JEEP®'.

    IMPORTANTE: lavoriamo sul testo GREZZO (con gli a-capo originali), mai
    su clean(body) - clean() collassa tutti i \n in uno spazio singolo,
    rendendo impossibile qualsiasi split per righe (bug gia' visto su LEPAS)."""
    raw_lines = [l.strip() for l in body.split("\n") if l.strip()]

    blocks = []
    current = []
    for line in raw_lines:
        if line.upper().startswith("NUOVA JEEP") and current:
            blocks.append("\n".join(current))
            current = [line]
        elif line.upper().startswith("NUOVA JEEP"):
            current = [line]
        elif current:
            current.append(line)
            if re.match(r"^Valido\s+fino\s+al\s*\d{2}/\d{2}/\d{4}\.?$", line, re.I):
                blocks.append("\n".join(current))
                current = []

    if current:
        blocks.append("\n".join(current))

    return blocks

def parse_block(block, run_id, idx):
    lines = [l.strip() for l in block.split("\n") if l.strip()]
    if len(lines) < 2:
        return None

    modello = lines[0].replace("NUOVA JEEP", "Jeep").replace("®", "").strip()
    versione = lines[1]
    titolo = f"{modello} {versione}".strip()

    motore_map = {
        "BENZINA": "benzina",
        "ELETTRICA": "elettrica",
        "4XE HYBRID": "plug-in",
        "E-HYBRID": "hybrid",
    }
    motore = motore_map.get(versione.upper(), "")

    row = build_row(
        brand=BRAND,
        modello=modello,
        titolo_promo=titolo,
        claim_promo="",
        motorizzazione=motore,
        legal=block,
        fonte_url=HUB,
        offer_url=HUB,
        run_id=run_id,
        note_tecniche_extra=["source=hub_card_inline"],
        allow_missing_intero=True,
    )
    return row

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
    urls = []

    for model_url in MODEL_URLS:
        page.goto(model_url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(5000)

        found = page.locator("a").evaluate_all("""
            els => [...new Set(els.map(a => a.href).filter(h =>
                h.includes('/offerte-jeep-prezzi/promozione/')
            ))]
        """)

        print(model_url, "| link:", len(found))
        urls.extend(found)

    urls.extend(DIRECT_URLS)

    # dedupe preservando ordine
    out = []
    seen = set()
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)

    return out

def slug_from_url(url):
    return url.rstrip("/").split("/")[-1].lower()

def model_from_url_title(url, title):
    s = (url + " " + (title or "")).lower()
    if "grand-cherokee" in s or "grand cherokee" in s:
        return "Grand Cherokee"
    if "compass" in s:
        return "Compass"
    if "avenger" in s:
        return "Avenger"
    return ""

def motore_from_title_url(title, url, legal):
    s = (title + " " + url + " " + legal[:800]).lower()

    # Prima plug-in: 4xe può contenere anche "elettrica" nei consumi.
    if "plug-in" in s or "plug in" in s or "4xe" in s:
        return "plug-in"
    if "full-electric" in s or "100% elettrica" in s or "elettrica" in s or "electric" in s:
        return "elettrica"
    if "e-hybrid" in s or "hybrid" in s or "ibrid" in s:
        return "hybrid"
    if "benzina" in s or "turbo" in s:
        return "benzina"
    if "diesel" in s or "bluehdi" in s:
        return "diesel"
    return ""

def title_from_legal_or_url(legal, url):
    # Jeep: il titolo corretto è la denominazione veicolo immediatamente prima del Prezzo/Listino/Promo.
    # Alcune Compass hanno blocchi consumi prima del titolo, quindi puliamo marker e prendiamo l'ultimo Jeep/Nuova Jeep prima del prezzo.
    txt = clean(legal)
    txt = re.sub(r"-+>\s*", " ", txt)
    txt = re.sub(r"\bBack\b", " ", txt, flags=re.I)
    txt = re.sub(r"\s+", " ", txt).strip()

    price_pos = None
    m_price = re.search(r"(Prezzo\s+di\s+Listino|Prezzo\s+Listino|Prezzo\s+Promo|Prezzo\s+promo)", txt, re.I)
    if m_price:
        price_pos = m_price.start()

    before_price = txt[:price_pos] if price_pos else txt[:1000]

    # Prendi l'ultima occorrenza sensata prima del prezzo, non quella nei consumi.
    candidates = []
    for m in re.finditer(r"((?:Nuova\s+)?Jeep\s*®?\s+[A-Za-z0-9À-ÿ%.\-\s]+)", before_price, re.I):
        cand = clean(m.group(1))
        cand = re.sub(r"\s+", " ", cand).strip(" .,:;")
        if len(cand) < 8:
            continue
        bad_words = ["consumo", "emissioni", "autonomia", "wltp", "valori", "energia"]
        if any(b in cand.lower() for b in bad_words):
            continue
        candidates.append(cand)

    if candidates:
        t = candidates[-1]
        t = re.sub(r"^Jeep\s+®", "Jeep®", t, flags=re.I)
        t = re.sub(r"^JEEP\s+®", "JEEP®", t, flags=re.I)
        return t

    # Fallback mirati per URL
    u = url.lower()
    if "finanziamento-compass-elettrica" in u:
        return "Jeep® Nuova Compass Altitude Full Electric 210cv"
    if "finanziamento-nuova-compass-plug-in-e-hybrid" in u:
        return "Jeep® Nuova Compass Altitude e-Hybrid Plug-In 225 CV"
    if "finanziamento-compass-e-hybrid" in u:
        return "Jeep® Nuova Compass Altitude e-Hybrid 145cv"

    slug = slug_from_url(url).replace("-", " ").title()
    return slug

def claim_from_legal(legal):
    claims = []
    low = legal.lower()

    if "permuta" in low:
        claims.append("permuta")
    if "rottamazione" in low:
        claims.append("rottamazione")
    if "pronta consegna" in low or "lotto limitato" in low:
        claims.append("stock/pronta consegna")
    if "non cumulabile" in low:
        claims.append("non cumulabile")
    if "supervalutazione" in low:
        claims.append("supervalutazione usato")
    if "interessi zero" in low or "tan 0" in low or "tan fisso 0" in low:
        claims.append("interessi zero")

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

    # Pulizia residui HTML/commenti del sito Jeep.
    legal = re.sub(r"<!--\s*", " ", legal)
    legal = re.sub(r"-+>\s*", " ", legal)
    legal = re.sub(r"\bBack\b", " ", legal, flags=re.I)
    legal = re.sub(r"\s+", " ", legal).strip()

    # Taglia solo prima di form/CTA/lead form.
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
        if m and m.start() > 800:
            stops.append(m.start())

    if stops:
        legal = legal[:min(stops)].strip()

    # Se dopo il testo finanziario è presente una frase completa di chiusura trasparenza,
    # chiudi lì solo se non ci sono consumi dopo.
    # Se ci sono consumi/WLTP, tienili fino a prima del form.
    has_consumi_after = re.search(r"(CONSUMI|Consumo\s+di|emissioni\s+di|WLTP)", legal, flags=re.I)

    if not has_consumi_after:
        m_end = re.search(
            r"Documentazione\s+precontrattuale\s+bancaria/assicurativa\s+in\s+Concessionaria\s+e\s+sul\s+sito\s+www\.stellantis-financial-services\.it\s*\(Sez\.\s*Trasparenza\)\.",
            legal,
            flags=re.I
        )
        if m_end:
            legal = legal[:m_end.end()].strip()

    legal = re.sub(r"\s+([,.;:])", r"\1", legal)
    legal = re.sub(r"\s+", " ", legal).strip()

    # Alcune pagine Jeep spezzano la frase finale subito dopo "in".
    # Evitiamo di salvare una nota tronca.
    if legal.rstrip().lower().endswith("documentazione precontrattuale bancaria/assicurativa in"):
        legal = re.sub(
            r"Documentazione\s+precontrattuale\s+bancaria/assicurativa\s+in\s*$",
            "Documentazione precontrattuale bancaria/assicurativa in Concessionaria e sul sito www.stellantis-financial-services.it (Sez. Trasparenza).",
            legal,
            flags=re.I
        )

    return clean(legal)

def jeep_money(v):
    if not v:
        return ""
    v = str(v).strip()
    v = v.split(",")[0]
    return "€ " + v

def jeep_intero_from_legal(legal):
    patterns = [
        r"Prezzo\s+Promo\s*€\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})",
        r"Prezzo\s+promo\s*€\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})",
        r"Prezzo\s+Promo\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})\s*€",
        r"Prezzo\s+promo\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})\s*€",
    ]
    for pat in patterns:
        m = re.search(pat, legal, re.I)
        if m:
            return jeep_money(m.group(1))
    return ""


def parse_detail(page, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(5000)

    html = page.evaluate("() => document.body.innerHTML")
    legal = extract_legal_from_html(html)

    if not legal:
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

    # Override Jeep: prezzo promo dentro nota legale.
    intero = jeep_intero_from_legal(legal)
    if intero:
        row["Intero"] = intero

    # Jeep Grand Cherokee: pagina con sola promo cash/listino, senza piano finanziario completo.
    # Non è comparabile con le altre offerte a rata, quindi la escludiamo dal push.
    if not row.get("Rata") or not row.get("TAN (%)") or not row.get("TAEG (%)"):
        row["Extraction Confidence"] = "medium"
        if row.get("Stato") == "attiva":
            row["Stato"] = "incompleta"
        row["Note Tecniche"] = (row.get("Note Tecniche", "") + "; skip_no_financial_plan").strip("; ")
        return None

    return row

def build_rows():
    run_id = "jeep_v2_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []
    skipped = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])

        page = browser.new_page(viewport={"width":1366,"height":8000})
        page.goto(HUB, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(5000)
        body = page.locator("body").inner_text(timeout=30000)

        blocks = split_blocks(body)
        print("BLOCCHI JEEP TROVATI:", len(blocks))

        for i, block in enumerate(blocks, start=1):
            try:
                r = parse_block(block, run_id, i)
                if not r:
                    skipped.append(f"{i} NO_ROW")
                    print(f"{i}/{len(blocks)} | NO_ROW")
                    continue

                rows.append(r)
                print(
                    f"{i}/{len(blocks)} | {r['Modello']} | {r['Motorizzazione']} | {r['Titolo Promo']} | "
                    f"{r['Claim Promo']} | {r['Rata']} | {r['Intero']} | {r['Anticipo']} | "
                    f"{r['Rata Finale / VFG']} | {r['Importo Totale Credito']} | {r['Importo Totale Dovuto']} | "
                    f"{r['TAN (%)']} | {r['TAEG (%)']} | {r['Scadenza']} | {r['Legal Source Status']} | "
                    f"{r['Note Tecniche']}"
                )
            except Exception as e:
                skipped.append(f"{i} ERR | {e}")
                print(f"{i}/{len(blocks)} | ERR | {e}")

        browser.close()

    print("RIGHE VALIDE:", len(rows))
    print("SKIPPED:", len(skipped))
    for s in skipped:
        print("SKIP:", s)

    return rows

if __name__ == "__main__":
    rows = build_rows()
    print("DEBUG ONLY: nessun push su Google Sheet")
