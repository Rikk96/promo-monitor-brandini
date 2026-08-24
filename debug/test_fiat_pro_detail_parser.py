from playwright.sync_api import sync_playwright
import re

HUB="https://www.fiat.it/professional/offerte"

def clean(t):
    return re.sub(r"\s+", " ", t or "").strip()

def parse_num(s):
    if not s:
        return None
    s=s.replace("€","").replace(".","").replace(",",".").strip()
    try:
        return float(s)
    except:
        return None

def euro(n):
    if n is None:
        return ""
    return "€ " + f"{int(round(n)):,}".replace(",", ".")

def slug(url):
    return url.rstrip("/").split("/")[-1].lower()

def modello(url):
    s=slug(url)
    if "doblo" in s:
        return "Doblò"
    if "ducato" in s:
        return "Ducato"
    if "scudo" in s:
        return "Scudo"
    return s.replace("-", " ").title()

def motore(url, body):
    s=(slug(url)+" "+body[:1200]).lower()
    if "elettric" in s or "e-scudo" in s or "e-ducato" in s or "e-doblo" in s or "bev" in s:
        return "elettrica"
    if "diesel" in s or "multijet" in s or "bluehdi" in s:
        return "diesel"
    if "benzina" in s:
        return "benzina"
    return ""

def extract_offer_note(body):
    lines=[x.strip() for x in body.splitlines() if x.strip()]
    text="\n".join(lines)

    starts=[
        "Offerta valida per",
        "L'offerta include",
        "Offerta valida fino",
    ]

    start=-1
    for s in starts:
        idx=text.find(s)
        if idx!=-1:
            start=idx
            break

    if start==-1:
        return ""

    stops=[
        "\nRichiedi preventivo",
        "\nConfigura e ordina",
        "\nTrova concessionario",
        "\nFIAT SERVIZIO CLIENTI",
        "\nFACEBOOK",
    ]

    sub=text[start:]
    end=len(sub)
    for s in stops:
        idx=sub.find(s)
        if idx!=-1:
            end=min(end,idx)

    return sub[:end].strip()

def extract_consumi(body):
    idx=body.lower().find("consumo")
    if idx==-1:
        return ""
    sub=body[idx:]
    stops=[
        "Richiedi preventivo",
        "Configura e ordina",
        "Trova concessionario",
        "FIAT SERVIZIO CLIENTI",
    ]
    end=len(sub)
    for s in stops:
        i=sub.find(s)
        if i!=-1:
            end=min(end,i)
    return sub[:end].strip()

def extract_title(body, url):
    lines=[x.strip() for x in body.splitlines() if x.strip()]
    for l in lines[:40]:
        ll=l.lower()
        if any(x in ll for x in ["dobl", "ducato", "scudo"]):
            if len(l)<100 and "modelli" not in ll:
                return clean(l)
    return slug(url).replace("-", " ").title()

def parse_detail(page,url):
    page.goto(url,wait_until="domcontentloaded",timeout=45000)
    page.wait_for_timeout(3000)

    body=page.locator("body").inner_text(timeout=30000)

    title=extract_title(body,url)
    note=extract_offer_note(body)
    consumi=extract_consumi(body)

    full_note=""
    if note:
        full_note="DETTAGLIO PROMOZIONE\n\n"+note
    if consumi:
        full_note=(full_note+"\n\nCONSUMI ED EMISSIONI\n\n"+consumi).strip()

    source=note+"\n"+body[:1500]

    rata=None
    for pat in [
        r"([\d\.,]+)\s*€\s*al mese",
        r"(?:rate|canoni)\s+(?:mensili\s+)?da\s*([\d\.,]+)\s*€",
        r"n°\s*\d+\s*(?:rate|canoni)\s*da\s*([\d\.,]+)\s*€",
    ]:
        m=re.search(pat, source, re.I)
        if m:
            rata=parse_num(m.group(1))
            break

    anticipo=None
    m=re.search(r"Anticipo\s*([\d\.,]+)\s*€", source, re.I)
    if m:
        anticipo=parse_num(m.group(1))

    scad=""
    m=re.search(r"Fino al\s*(\d{2}/\d{2}/\d{4})", source, re.I)
    if m:
        scad=m.group(1)
    else:
        m=re.search(r"Offerta valida fino al\s*(\d{2}/\d{2}/\d{4})", source, re.I)
        if m:
            scad=m.group(1)
        else:
            mesi={"gennaio":"01","febbraio":"02","marzo":"03","aprile":"04","maggio":"05","giugno":"06","luglio":"07","agosto":"08","settembre":"09","ottobre":"10","novembre":"11","dicembre":"12"}
            m=re.search(r"(?:fino al|valida fino al)\s*(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})", source, re.I)
            if m and m.group(2).lower() in mesi:
                scad=f"{m.group(1).zfill(2)}/{mesi[m.group(2).lower()]}/{m.group(3)}"

    return {
        "modello": modello(url),
        "title": title,
        "motore": motore(url,body),
        "rata": euro(rata),
        "anticipo": euro(anticipo),
        "scadenza": scad,
        "note_start": clean(full_note[:160]),
        "url": url
    }

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
    page=browser.new_page(viewport={"width":1366,"height":1800})

    page.goto(HUB,wait_until="domcontentloaded",timeout=60000)
    page.wait_for_timeout(5000)

    urls=page.locator("a").evaluate_all("""
        els => [...new Set(
            els.map(a => String(a.href || '')).filter(h =>
                h.includes('/professional/offerte/')
                && !h.endsWith('/offerte')
                && !h.endsWith('/offerte#')
            )
        )]
    """)

    print("URL:",len(urls))

    detail=browser.new_page(viewport={"width":1366,"height":1800})
    for u in urls:
        r=parse_detail(detail,u)
        print(r["modello"],"|",r["title"],"|",r["motore"],"|",r["rata"],"| anticipo",r["anticipo"],"|",r["scadenza"])
        print("NOTE:",r["note_start"])
        print("URL:",r["url"])
        print("-"*100)

    browser.close()
