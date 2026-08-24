from playwright.sync_api import sync_playwright
import re

HUB = "https://www.citroen.it/acquista/offerte-privati.html"

def clean(t):
    return re.sub(r"\s+", " ", t or "").strip()

def euro(n):
    if n is None:
        return ""
    return "€ " + f"{int(round(n)):,}".replace(",", ".")

def parse_num(s):
    if not s:
        return None
    s = s.replace("€", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(s)
    except:
        return None

def perc(s):
    if not s:
        return ""
    return s.replace(".", ",") + "%"

def motore(title, body):
    t = (title + " " + body[:800]).lower()
    if "elettric" in t or "100% elettrica" in t or " ë-" in t or "e-" in t:
        return "elettrica"
    if "plug-in" in t or "plug in" in t:
        return "plug-in"
    if "hybrid" in t:
        return "hybrid"
    if "diesel" in t or "bluehdi" in t:
        return "diesel"
    if "benzina" in t or "turbo" in t:
        return "benzina"
    return ""

def modello(title):
    t = title.lower()
    if "ami" in t:
        return "NUOVA AMI"
    if "berlingo" in t:
        return "Nuovo Berlingo"
    if "spacetourer" in t:
        return "Spacetourer"
    if "c5 aircross" in t:
        return "Nuovo Suv C5 Aircross"
    if "c3 aircross" in t:
        return "C3 Aircross"
    if "c5 x" in t or "c5x" in t:
        return "C5 X"
    if "c4 x" in t or "c4x" in t:
        return "C4 X"
    if "c4" in t:
        return "C4"
    if "c3" in t:
        return "C3"
    return title

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
    for s in stops:
        idx = sub.find(s)
        if idx != -1:
            end = min(end, idx)

    return sub[:end].strip()

def parse_detail(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3500)

    body = page.locator("body").inner_text(timeout=30000)
    lines = [x.strip() for x in body.splitlines() if x.strip()]

    legal = extract_legal(body)
    source = legal if legal else body

    # titolo: prima riga utile dopo skip/header
    title = ""
    for l in lines[:80]:
        if any(x in l.lower() for x in ["citroën", "citroen", "c3", "c4", "c5", "ami", "berlingo", "spacetourer"]):
            if len(l) < 80 and "skip" not in l.lower() and "contatti" not in l.lower():
                title = l
                break

    if not title:
        # fallback da url
        slug = url.rstrip("/").split("/")[-1].replace(".html", "")
        title = slug.replace("-", " ").title()

    rata = None
    for pat in [
        r"(?:rate|canoni)\s+(?:mensili\s+)?da\s*([\d\.,]+)\s*€",
        r"(\d{1,3})\s*€\s*al mese",
        r"CANONI MENSILI DA\s*([\d\.,]+)\s*€",
    ]:
        m = re.search(pat, source, re.I)
        if m:
            rata = parse_num(m.group(1))
            break

    intero = None
    for pat in [
        r"Prezzo Promo\s*([\d\.,]+)\s*€",
        r"Prezzo promo da\s*([\d\.,]+)\s*€",
        r"Listino\s*([\d\.,]+)\s*€",
    ]:
        m = re.search(pat, source, re.I)
        if m:
            intero = parse_num(m.group(1))
            break

    tan = ""
    taeg = ""
    m = re.search(r"TAN\s*(?:\(fisso\))?\s*([\d\.,]+)\s*%", source, re.I)
    if m:
        tan = perc(m.group(1))
    m = re.search(r"TAEG\s*([\d\.,]+)\s*%", source, re.I)
    if m:
        taeg = perc(m.group(1))

    scadenza = ""
    m = re.search(r"(?:fino al|entro il|immatricolazioni fino al|valid[ao] fino al)\s*(\d{2}/\d{2}/\d{4})", source, re.I)
    if m:
        scadenza = m.group(1)
    else:
        mesi = {"gennaio":"01","febbraio":"02","marzo":"03","aprile":"04","maggio":"05","giugno":"06","luglio":"07","agosto":"08","settembre":"09","ottobre":"10","novembre":"11","dicembre":"12"}
        m = re.search(r"(?:fino al|entro il|immatricolazioni fino al|contratti stipulati.*?fino al)\s*(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})", source, re.I)
        if m:
            scadenza = f"{m.group(1).zfill(2)}/{mesi.get(m.group(2).lower(),'')}/{m.group(3)}"

    return {
        "titolo": clean(title),
        "modello": modello(title),
        "motore": motore(title, body),
        "rata": euro(rata),
        "intero": euro(intero),
        "tan": tan,
        "taeg": taeg,
        "scadenza": scadenza,
        "legal_start": clean(legal[:120]),
        "url": url
    }

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width":1366,"height":1800})

    page.goto(HUB, wait_until="networkidle", timeout=90000)

    urls = page.locator("a").evaluate_all("""
        els => [...new Set(els.map(a => a.href).filter(h =>
            h.includes('/acquista/offerte-privati/') && h.endsWith('.html')
        ))]
    """)

    print("URL:", len(urls))

    detail = browser.new_page(viewport={"width":1366,"height":1800})

    for u in urls[:35]:
        r = parse_detail(detail, u)
        print(r["modello"], "|", r["titolo"], "|", r["motore"], "|", r["rata"], "|", r["intero"], "|", r["tan"], "|", r["taeg"], "|", r["scadenza"])
        print("NOTE:", r["legal_start"])
        print("URL:", r["url"])
        print("-"*120)

    browser.close()
