from playwright.sync_api import sync_playwright
import re

URL = "https://www.opel.it/offerte/privati.html"

def parse_number(value):
    if not value:
        return None
    value = value.strip().replace(".", "").replace(",", ".")
    try:
        return float(value)
    except:
        return None

def parse_percent(value):
    if not value:
        return None
    return float(value.strip().replace(",", "."))

def motore(title):
    t = title.lower()
    if "electric" in t or "elettrica" in t:
        return "elettrica"
    if "plug" in t:
        return "plug-in"
    if "hybrid" in t:
        return "hybrid"
    if "diesel" in t:
        return "diesel"
    if "benzina" in t:
        return "benzina"
    return ""

def extract_blocks(text):
    # blocchi tra "Scopri l'offerta"
    chunks = re.split(r"Scopri l'offerta", text, flags=re.I)
    rows = []

    for chunk in chunks:
        if "TAN" not in chunk or "TAEG" not in chunk:
            continue

        lines = [x.strip() for x in chunk.splitlines() if x.strip()]

        title = ""
        for line in lines[:8]:
            if any(x in line.lower() for x in ["corsa", "mokka", "frontera", "astra", "grandland", "zafira", "combo"]):
                title = line
                break

        if not title and lines:
            title = lines[0]

        rata = None
        m = re.search(r"(?:rate da|Da)\s*([\d\.,]+)\s*€|([\d\.,]+)\s*€\s*al mese", chunk, re.I)
        if m:
            rata = parse_number(m.group(1) or m.group(2))

        intero = None
        m = re.search(r"Prezzo promo oltre oneri finanziari:\s*([\d\.,]+)\s*€", chunk, re.I)
        if m:
            intero = parse_number(m.group(1))

        tan = None
        m = re.search(r"TAN\s*\(Fisso\)\s*([\d\.,]+)\s*%", chunk, re.I)
        if m:
            tan = parse_percent(m.group(1))

        taeg = None
        m = re.search(r"TAEG\s*([\d\.,]+)\s*%", chunk, re.I)
        if m:
            taeg = parse_percent(m.group(1))

        scadenza = ""
        m = re.search(r"Fino al\s*(\d{2}/\d{2}/\d{4})", chunk, re.I)
        if m:
            scadenza = m.group(1)

        rows.append({
            "title": title,
            "motorizzazione": motore(title + " " + chunk[:200]),
            "rata": rata,
            "intero": intero,
            "tan": tan,
            "taeg": taeg,
            "scadenza": scadenza
        })

    return rows

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True,args=["--no-sandbox"])
    page = browser.new_page()
    page.goto(URL, wait_until="networkidle", timeout=90000)
    text = page.locator("body").inner_text(timeout=30000)

    rows = extract_blocks(text)

    print("RIGHE:", len(rows))
    for r in rows[:20]:
        print(r)

    browser.close()
