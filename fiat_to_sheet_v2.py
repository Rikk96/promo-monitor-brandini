from playwright.sync_api import sync_playwright
import re
from datetime import datetime

from promo_common import clean, build_row

BRAND = "Fiat"
HUB = "https://www.fiat.it/offerte-privati"



def clean_fiat_legal_note(text):
    if not text:
        return ""

    text = str(text).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()

    # Parti sempre dalla nota vera
    m = re.search(r"DETTAGLIO\s+PROMOZIONE", text, flags=re.I)
    if m:
        text = text[m.start():].strip()

    # Taglia JS/configurazioni pagina dopo la parte legale/consumi
    stop_patterns = [
        r"\bvar\s+_defaultCTA\b",
        r"\bvar\s+_CTASelection\b",
        r"\bvar\s+_offer\b",
        r"\bvar\s+_campaign\b",
        r"\bvar\s+formManager\b",
        r"\bClickToCall\b",
        r"\bDisclaimerID\b",
        r"\bmodelPage\b",
        r"\badobeModelDescription\b",
        r"\bcontent/dam\b",
        r"\bwindow\.",
        r"\bdataLayer\b",
    ]

    stops = []
    for pattern in stop_patterns:
        sm = re.search(pattern, text, flags=re.I)
        if sm:
            stops.append(sm.start())

    if stops:
        text = text[:min(stops)].strip()

    # Chiudi dopo la frase finale utile dei consumi, quando presente
    final_phrases = [
        "possono variare a seconda delle condizioni di utilizzo e di vari fattori.",
        "i valori possono variare a seconda delle condizioni di utilizzo e di vari fattori.",
        "caratteristiche/colori possono differire.",
        "caratteristiche/colori possono differire da quanto rappresentato.",
        "Messaggio pubblicitario, con finalità promozionale.",
    ]

    low = text.lower()
    best_end = None

    for phrase in final_phrases:
        idx = low.find(phrase.lower())
        if idx != -1:
            end = idx + len(phrase)
            if best_end is None or end > best_end:
                best_end = end

    if best_end:
        text = text[:best_end].strip()

    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text).strip()

    return text

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
    # URL validate da hub + detail page: hanno DETTAGLIO PROMOZIONE + credito/dovuto.
    urls = [
        "https://www.fiat.it/offerte-privati/nuova-fiat-pandina",
        "https://www.fiat.it/offerte-privati/fiat-500-ibrida-pop",
        "https://www.fiat.it/offerte-privati/finanziamento-fiat-500-hybrid-dolcevita",
        "https://www.fiat.it/offerte-privati/500-elettrica-red",
        "https://www.fiat.it/offerte-privati/grande-panda-benzina",
        "https://www.fiat.it/offerte-privati/grande-panda-hybrid",
        "https://www.fiat.it/offerte-privati/grande-panda-electric",
        "https://www.fiat.it/offerte-privati/offerta-fiat-600-benzina",
        "https://www.fiat.it/offerte-privati/600-hybrid",
        "https://www.fiat.it/offerte-privati/fiat-e-600",
        "https://www.fiat.it/offerte-privati/qubo-l",
        "https://www.fiat.it/offerte-privati/fiat-topolino",
    ]
    return urls

def slug_from_url(url):
    return url.rstrip("/").split("/")[-1].lower()

def model_from_url(url):
    s = slug_from_url(url)
    if "pandina" in s:
        return "Pandina"
    if "grande-panda" in s:
        return "Grande Panda"
    if "e-600" in s or "600-hybrid" in s or "600-benzina" in s:
        return "600"
    if "qubo" in s:
        return "Qubo"
    if "topolino" in s:
        return "Topolino"
    if "500" in s:
        return "500"
    return ""

def title_from_legal_or_url(legal, url):
    patterns = [
        r"(Nuova\s+Fiat\s+Pandina|Pandina[^.]{0,80}?)\s+Listino",
        r"(Fiat\s+500\s+Ibrida\s+Pop|Nuova\s+500\s+Hybrid[^.]{0,120}?)\s+Listino",
        r"(Fiat\s+500\s+Hybrid\s+Dolcevita|500\s+Hybrid\s+Dolcevita[^.]{0,120}?)\s+Listino",
        r"(500e[^.]{0,120}?)\s+Listino",
        r"(Grande\s+Panda\s+Benzina[^.]{0,140}?)\s+Listino",
        r"(Grande\s+Panda\s+Hybrid[^.]{0,140}?)\s+Listino",
        r"(Grande\s+Panda\s+Elettrica[^.]{0,140}?)\s+Listino",
        r"(Nuova\s+600\s+Benzina[^.]{0,140}?)\s+Listino",
        r"(600\s+Hybrid[^.]{0,120}?)\s+Listino",
        r"(600e[^.]{0,120}?)\s+Listino",
        r"(Qubo\s+L[^.]{0,120}?)\s+Listino",
        r"(Fiat\s+Topolino[^.]{0,120}?)\s+Listino",
    ]
    for pat in patterns:
        m = re.search(pat, legal, re.I)
        if m:
            return clean(m.group(1))

    s = slug_from_url(url)
    return s.replace("finanziamento-", "").replace("offerta-fiat-", "fiat-").replace("-", " ").title()

def motore_from_url_and_legal(url, legal):
    s = slug_from_url(url)
    title = title_from_legal_or_url(legal, url).lower()
    low = legal.lower()

    if "electric" in s or "elettrica" in s or "e-600" in s or "500e" in title or "600e" in title or "topolino" in s or "energia elettrica" in low:
        return "elettrica"
    if "hybrid" in s or "ibrida" in s or "hybrid" in title or "pandina" in s:
        return "hybrid"
    if "benzina" in s or "benzina" in title or "qubo" in s:
        return "benzina"
    return ""

def extract_legal_from_html(html):
    text = html_to_text(html)
    low = text.lower()

    start = low.find("dettaglio promozione")
    if start == -1:
        return ""

    sub = text[start:]

    # Evita duplicati: spesso la nota è presente più volte nell'HTML.
    second = sub.lower().find("dettaglio promozione", 30)
    if second != -1:
        sub = sub[:second]

    cut_markers = [
        "MODELLI",
        "VEICOLI FIAT PROFESSIONAL",
        "CONFIGURA E ORDINA",
        "CONTATTI",
        "Privacy",
        "Cookie",
        "FAQ",
    ]

    end = len(sub)
    for marker in cut_markers:
        idx = sub.lower().find(marker.lower())
        if idx != -1 and idx > 600:
            end = min(end, idx)

    return clean(sub[:end])

def claim_from_legal(legal):
    low = legal.lower()
    tags = []

    if "rottamazione" in low:
        tags.append("rottamazione")
    if "pronta consegna" in low:
        tags.append("stock/pronta consegna")
    if "non cumulabile" in low:
        tags.append("non cumulabile")
    if "finanziamento" in low:
        tags.append("finanziamento")

    return "; ".join(dict.fromkeys(tags))

def fiat_intero_from_legal(legal):
    patterns = [
        r"oppure\s*€\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]{4,}(?:,[0-9]+)?)\s*solo\s+con\s+finanziamento",
        r"oppure\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]{4,}(?:,[0-9]+)?)\s*solo\s+con\s+finanziamento",
        r"oppure\s*€?\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]{4,}(?:,[0-9]+)?)\s*con\s+finanziamento",
        r"Da\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]{4,}(?:,[0-9]+)?)\s*€\s*oltre\s+oneri\s+finanziari",
        r"promo\s*€\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]{4,}(?:,[0-9]+)?)",
    ]
    for pat in patterns:
        m = re.search(pat, legal, re.I)
        if m:
            return "€ " + m.group(1).split(",")[0]
    return ""

def fiat_vfg_from_legal(legal):
    patterns = [
        r"Rata\s+Finale\s+Residua[^0-9]{0,80}([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]{4,}(?:,[0-9]+)?)",
        r"Rata\s+Finale[^0-9]{0,40}([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]{4,}(?:,[0-9]+)?)\s*€",
    ]
    for pat in patterns:
        m = re.search(pat, legal, re.I)
        if m:
            return "€ " + m.group(1).split(",")[0]
    return ""

def parse_detail(page, url, run_id):
    page.goto(url, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(6500)

    final_url = page.url.rstrip("/")
    if final_url == HUB.rstrip("/"):
        print("DEBUG REDIRECT HUB:", url)
        return None

    html = page.evaluate("() => document.body.innerHTML")
    legal = extract_legal_from_html(html)
    legal = clean_fiat_legal_note(legal)

    if not legal:
        print("DEBUG NO LEGAL:", url)
        return None

    row = build_row(
        brand=BRAND,
        modello=model_from_url(url),
        titolo_promo=title_from_legal_or_url(legal, url),
        claim_promo=claim_from_legal(legal),
        motorizzazione=motore_from_url_and_legal(url, legal),
        legal=legal,
        fonte_url=HUB,
        offer_url=url,
        run_id=run_id,
        note_tecniche_extra=["source=detail_legal", "debug_only_no_push"],
        allow_missing_intero=False,
    )

    # Override Fiat: prezzo finanziamento e VFG da nota legale.
    intero = fiat_intero_from_legal(legal)
    if intero:
        row["Intero"] = intero

    if not row.get("Rata Finale / VFG"):
        vfg = fiat_vfg_from_legal(legal)
        if vfg:
            row["Rata Finale / VFG"] = vfg

    # Fallback robusto rata: alcune pagine Fiat leggono il simbolo € come carattere corrotto.
    # Esempio: "35 rate da 99€" oppure "n° 35 rate da 99 ��".
    if not row.get("Rata"):
        source_rate = str(legal or "")
        m = re.search(
            r"(?:n\s*[°º]\s*)?\d+\s+rate\s+da\s+([0-9]{1,4}(?:[\.,][0-9]{1,2})?)",
            source_rate,
            re.I
        )
        if m:
            row["Rata"] = "€ " + str(m.group(1)).replace(".", "").split(",")[0]
            row["Note Tecniche"] = (row.get("Note Tecniche", "") + "; rata_from_rate_da").strip("; ")

    # Ricalcolo note tecniche dopo override.
    row["Note Tecniche"] = row["Note Tecniche"].replace("missing_intero", "").replace("missing_rata", "").replace(";;", ";").strip("; ").strip()
    row["Promo Hash"] = row.get("Promo Hash", "")

    return row

def main():
    run_id = "fiat_debug_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []
    skipped = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])

        page = browser.new_page(viewport={"width":1366,"height":10000})
        urls = get_urls(page)

        print("URL FIAT TROVATI:", len(urls))
        for u in urls:
            print("URL:", u)

        for i, url in enumerate(urls, start=1):
            try:
                r = parse_detail(page, url, run_id)
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
