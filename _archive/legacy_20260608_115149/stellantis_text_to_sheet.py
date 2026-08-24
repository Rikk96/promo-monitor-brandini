



def format_euro_output(value):
    if value == "" or value is None:
        return ""

    s = str(value).strip().replace("€", "").strip()
    if not s:
        return ""

    # Se arriva già rovinato dal vecchio formatter: € 1.990,00 => 199
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{2}", s):
        n = round(float(s.replace(".", "").replace(",", ".")) / 10)

    # Python float corretto: 199.0, 19950.0
    elif re.fullmatch(r"\d+\.0", s):
        n = int(float(s))

    # Python float generico
    elif re.fullmatch(r"\d+\.\d+", s):
        n = round(float(s))

    # Italiano con virgola
    elif "," in s:
        n = round(float(s.replace(".", "").replace(",", ".")))

    # Intero puro
    else:
        cleaned = re.sub(r"[^\d]", "", s)
        if not cleaned:
            return ""
        n = int(cleaned)

        # Correzione se arriva già moltiplicato x10
        if 800 < n < 10000:
            n = round(n / 10)
        elif n > 70000:
            n = round(n / 10)

    return "€ " + f"{n:,}".replace(",", ".")


def euro_to_float(value):
    if value == "" or value is None:
        return None

    s = str(value).strip().replace("€", "").strip()
    if not s:
        return None

    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{2}", s):
        n = float(s.replace(".", "").replace(",", ".")) / 10
    elif re.fullmatch(r"\d+\.0", s):
        n = float(s)
    elif re.fullmatch(r"\d+\.\d+", s):
        n = float(s)
    elif "," in s:
        n = float(s.replace(".", "").replace(",", "."))
    else:
        cleaned = re.sub(r"[^\d]", "", s)
        if not cleaned:
            return None
        n = float(cleaned)
        if 800 < n < 10000:
            n = n / 10
        elif n > 70000:
            n = n / 10

    return n


def percent_to_float(value):
    if value == "" or value is None:
        return None

    s = str(value).strip().replace("%", "").replace(",", ".")
    try:
        n = float(s)
    except:
        return None

    if n >= 100:
        n = n / 100

    return n

def normalize_percent_output(value):
    if value == "" or value is None:
        return ""

    s = str(value).strip()
    if not s:
        return ""

    if s.endswith("%"):
        return s

    s = s.replace(",", ".")
    try:
        n = float(s)
    except:
        return s

    # Caso Google Sheet/gspread: 599 significa 5,99
    if n >= 100:
        n = n / 100

    out = f"{n:.2f}".replace(".", ",")
    out = out.rstrip("0").rstrip(",")
    return out + "%"

from playwright.sync_api import sync_playwright
from google.oauth2.service_account import Credentials
import gspread
import re
import hashlib
from datetime import datetime, date, date

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"

HEADERS = [
    "Brand","Modello","Titolo Promo","Motorizzazione","Rata","Intero",
    "TAN (%)","TAEG (%)","Scadenza","Note Legali","Fonte URL","Offer URL",
    "Data Aggiornamento","Data Scansione","Last Seen","Stato","Alert Type",
    "Promo Hash","Extraction Confidence","Run ID","Note Tecniche"
]

CONFIGS = [
    {
        "brand": "Opel",
        "url": "https://www.opel.it/offerte/privati.html",
        "title_terms": ["corsa", "mokka", "frontera", "astra", "grandland", "zafira", "combo"],
        "splitter": r"Scopri l'offerta",
    },
    {
        "brand": "Peugeot",
        "url": "https://www.peugeot.it/acquista/offerte-privati.html",
        "title_terms": ["peugeot", "208", "2008", "308", "408", "3008", "5008", "rifter"],
        "splitter": r"SCOPRI L'OFFERTA",
    },
    {
        "brand": "Citroen",
        "url": "https://www.citroen.it/acquista/offerte-privati.html",
        "splitter": r"(?=NUOVA AMI|C3|NUOVO SUV C3 AIRCROSS|C4|C4 X|NUOVO SUV C5 AIRCROSS|C5 X|SPACETOURER|NUOVO BERLINGO|NUOVO JUMPY)",
        "model_terms": ["ami", "c3", "c4", "c5", "aircross", "spacetourer", "berlingo", "jumpy"],
        "title_terms": ["ami", "c3", "c4", "c5", "aircross", "spacetourer", "berlingo", "jumpy"],
        "detail_path": "/acquista/offerte-privati/",
    },

]

def parse_number(value):
    if not value:
        return ""
    value = value.strip().replace(".", "").replace(",", ".")
    try:
        return float(value)
    except:
        return ""

def parse_percent(value):
    if not value:
        return ""
    try:
        return float(value.strip().replace(",", "."))
    except:
        return ""


def format_percent_value(value):
    return normalize_percent_output(value)

def parse_percent_from_legal(note, label):
    import re
    if not note:
        return ""
    pattern = label + r"\s*(?:\(fisso\))?\s*([\d\.,]+)\s*%"
    m = re.search(pattern, note, re.I)
    if m:
        return m.group(1).replace(".", ",") + "%"
    return ""

def parse_scadenza_from_legal(note):
    import re
    if not note:
        return ""

    mesi = {
        "gennaio": "01", "febbraio": "02", "marzo": "03", "aprile": "04",
        "maggio": "05", "giugno": "06", "luglio": "07", "agosto": "08",
        "settembre": "09", "ottobre": "10", "novembre": "11", "dicembre": "12",
    }

    # formato numerico
    matches = re.findall(r"(?:entro il|fino al|stipulati fino al|immatricolazione entro il|targatura entro il)\s*(\d{2}/\d{2}/\d{4})", note, re.I)
    if matches:
        return matches[-1]

    # formato 31 Maggio 2026
    matches = re.findall(r"(?:entro il|fino al|stipulati fino al|contratti stipulati fino al|immatricolazione entro il|targatura entro il)\s*(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})", note, re.I)
    if matches:
        g, mese_txt, anno = matches[-1]
        mese = mesi.get(mese_txt.lower(), "")
        if mese:
            return f"{g.zfill(2)}/{mese}/{anno}"

    return ""

def clean_legal_footer(note):
    if not note:
        return note

    stops = [
        "\n TROVA UN PUNTO VENDITA",
        "\nTROVA UN PUNTO VENDITA",
        "\n MY PEUGEOT",
        "\nMY PEUGEOT",
        "\n VALUTA IL TUO USATO",
        "\nVALUTA IL TUO USATO",
        "\n CONTATTI",
        "\nCONTATTI",
        "\nLA NOSTRA GAMMA",
        "\n LA NOSTRA GAMMA",
        "\nConfigura",
        "\nDomande e risposte",
        "\nPrivacy Policy",
        "\nNote Legali",
        "\nCondizioni Generali",
    ]

    end = len(note)
    for s in stops:
        idx = note.find(s)
        if idx != -1:
            end = min(end, idx)

    return note[:end].strip()


def parse_scadenza(chunk):
    m = re.search(r"(?:Fino al|Valida fino al)\s*(\d{2}/\d{2}/\d{4})", chunk, re.I)
    if m:
        return m.group(1)

    mesi = {
        "gennaio": "01", "febbraio": "02", "marzo": "03", "aprile": "04",
        "maggio": "05", "giugno": "06", "luglio": "07", "agosto": "08",
        "settembre": "09", "ottobre": "10", "novembre": "11", "dicembre": "12",
    }

    m = re.search(r"(?:Fino al|Valida fino al)\s*(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})", chunk, re.I)
    if m:
        giorno = m.group(1).zfill(2)
        mese = mesi.get(m.group(2).lower(), "")
        anno = m.group(3)
        if mese:
            return f"{giorno}/{mese}/{anno}"

    return ""


def scadenza_is_active(scadenza):
    if not scadenza:
        return False

    try:
        dt = datetime.strptime(scadenza, "%d/%m/%Y").date()
        return dt >= date.today()
    except:
        return False

def motore(title, chunk):
    t = (title + " " + chunk[:700]).lower()
    clean_title = title.lower().replace("peugeot", "").strip()

    if "plug-in" in t or "plug in" in t or "plug-in hybrid" in t:
        return "plug-in"
    if clean_title.startswith("e-") or " electric" in t or "elettrica" in t or "motore elettrico" in t:
        return "elettrica"
    if "hybrid" in t or "ibrida" in t:
        return "hybrid"
    if "diesel" in t or "bluehdi" in t or "blue hdi" in t:
        return "diesel"
    if "benzina" in t or "turbo benzina" in t or "qubo" in t:
        return "benzina"
    return ""

def modello_from_title(brand, title):
    t = title.lower()
    clean = title.replace("PEUGEOT", "").replace("Peugeot", "").strip()

    if brand == "Peugeot":
        for m in ["5008", "3008", "408", "308 SW", "308", "2008", "208", "RIFTER", "Rifter"]:
            if m.lower() in t:
                return m.upper() if m.lower() != "rifter" else "Rifter"
        return clean

    if brand == "Opel":
        if "astra st" in t or "sports tourer" in t:
            return "Astra Sports Tourer"
        for m in ["Corsa", "Mokka", "Frontera", "Astra", "Grandland", "Zafira", "Combo"]:
            if m.lower() in t:
                return m
        return title

    return title

def clean_note_legali(chunk, title):
    lines = [x.strip() for x in chunk.splitlines() if x.strip()]

    # Rimuovo header/menu prima dell'offerta reale
    start_idx = 0
    for i, line in enumerate(lines):
        low = line.lower()

        # Se trova una riga motore/allestimento più specifica, parte da lì
        if any(k in low for k in [
            "benzina",
            "hybrid",
            "electric",
            "diesel",
            "plug-in",
            "elettrico",
            "elettrica"
        ]) and not any(bad in low for bad in [
            "seleziona",
            "gamma",
            "offerte",
            "veicoli",
            "scopri"
        ]):
            start_idx = max(0, i - 1)
            break

        if title and title.lower() in low and "seleziona" not in low:
            start_idx = i
            break

        if any(k in low for k in [
            "prezzo promo",
            "rate da",
            "canoni da",
            "tan",
            "taeg",
            "anticipo",
            "rata finale",
            "primo canone"
        ]):
            start_idx = max(0, i - 4)
            break

    cleaned = lines[start_idx:]

    # Taglio footer o roba non utile
    stop_words = [
        "configura",
        "contatta il concessionario",
        "trova un punto vendita",
        "my peugeot",
        "valuta il tuo usato",
        "la nostra gamma",
        "post vendita",
        "privacy",
        "cookie",
        "continua senza accettare",
        "la tua privacy",
        "chatta con noi",
    ]

    final = []
    for line in cleaned:
        if any(sw in line.lower() for sw in stop_words):
            break
        final.append(line)

    note = "\n".join(final).strip()

    if not note:
        note = chunk.strip()

    return note

def extract_rows_from_text(config, text, run_id):
    chunks = re.split(config["splitter"], text, flags=re.I)
    rows = []

    for chunk in chunks:
        if "TAN" not in chunk or "TAEG" not in chunk:
            continue

        lines = [x.strip() for x in chunk.splitlines() if x.strip()]

        title = ""
        for line in lines[:10]:
            low = line.lower()
            if any(term in low for term in config["title_terms"]):
                if "skipto" not in low and "seleziona" not in low:
                    title = line
                    break

        if config["brand"] == "Opel":
            for line in lines[:8]:
                low = line.lower()
                if any(x in low for x in ["hybrid", "electric", "diesel", "benzina", "plug-in"]):
                    if not any(x in low for x in ["edition", "cv", "cambio", "prezzo", "rate"]):
                        title = line
                        break

        if not title and config["brand"] == "Peugeot" and "Peugeot 208 Turbo Benzina" in chunk:
            title = "PEUGEOT 208"

        if not title and lines:
            title = lines[0]

        rata = ""
        m = re.search(r"(?:rate da|canoni da|Da)\s*([\d\.,]+)\s*€|([\d\.,]+)\s*€\s*(?:al mese|/Mese)", chunk, re.I)
        if m:
            rata = parse_number(m.group(1) or m.group(2))

        intero = ""
        m = re.search(r"Prezzo promo(?: oltre oneri finanziari)?:\s*([\d\.,]+)\s*€|Prezzo promo da\s*([\d\.,]+)\s*€", chunk, re.I)
        if m:
            intero = parse_number(m.group(1) or m.group(2))

        tan = ""
        m = re.search(r"TAN\s*\(Fisso\)\s*([\d\.,]+)\s*%|TAN\s*\(fisso\)\s*([\d\.,]+)\s*%", chunk, re.I)
        if m:
            tan = parse_percent(m.group(1) or m.group(2))

        taeg = ""
        m = re.search(r"TAEG\s*([\d\.,]+)\s*%", chunk, re.I)
        if m:
            taeg = parse_percent(m.group(1))

        scadenza = parse_scadenza(chunk)
        motorizzazione = motore(title, chunk)
        modello = modello_from_title(config["brand"], title)

        missing = []
        if not title: missing.append("titolo")
        if not modello: missing.append("modello")
        if not motorizzazione: missing.append("motorizzazione")
        if not rata and not intero: missing.append("rata/intero")
        if not tan and tan != 0: missing.append("tan")
        if not taeg: missing.append("taeg")
        if not scadenza: missing.append("scadenza")

        if missing:
            stato = "incompleta"
        elif scadenza and not scadenza_is_active(scadenza):
            stato = "scaduta"
            missing.append("offerta_scaduta")
        else:
            stato = "attiva"

        confidence = max(0, 100 - len(missing) * 15)

        hash_base = f"{config['brand']}|{modello}|{title}|{motorizzazione}|{rata}|{intero}|{tan}|{taeg}|{scadenza}|{config['url']}"
        promo_hash = hashlib.sha256(hash_base.encode("utf-8")).hexdigest()

        now = datetime.now()

        note_legali = clean_note_legali(chunk, title)

        rows.append({
            "Brand": config["brand"],
            "Modello": modello,
            "Titolo Promo": title,
            "Motorizzazione": motorizzazione,
            "Rata": format_euro_output(rata),
            "Intero": format_euro_output(intero),
            "TAN (%)": normalize_percent_output(tan),
            "TAEG (%)": normalize_percent_output(taeg),
            "Scadenza": scadenza,
            "Note Legali": note_legali,
            "Fonte URL": config["url"],
            "Offer URL": config["url"],
            "Data Aggiornamento": now.strftime("%d/%m/%Y"),
            "Data Scansione": now.strftime("%Y-%m-%d %H:%M:%S"),
            "Last Seen": now.strftime("%d/%m/%Y"),
            "Stato": stato,
            "Alert Type": "",
            "Promo Hash": promo_hash,
            "Extraction Confidence": confidence,
            "Run ID": run_id,
            "Note Tecniche": "; ".join(missing)
        })

    return rows

def extract_offer_links(page, brand):
    links = page.locator("a").evaluate_all("""
        els => els.map(a => ({
            text:(a.innerText||'').trim().replace(/\\s+/g,' '),
            href:a.href
        }))
    """)

    out = []
    for l in links:
        txt = (l.get("text") or "").lower()
        href = l.get("href") or ""

        if brand == "Opel":
            if "scopri l'offerta" in txt and "/offerte/privati/" in href and href.endswith(".html"):
                out.append(href)

        if brand in ["Peugeot", "Citroen"]:
            if "scopri l'offerta" in txt and "/acquista/offerte-privati/" in href and href.endswith(".html"):
                out.append(href)

    # dedup mantenendo ordine
    seen = set()
    clean = []
    for u in out:
        if u not in seen:
            seen.add(u)
            clean.append(u)
    return clean


def clean_detail_page_text(text):
    lines = [x.strip() for x in text.splitlines() if x.strip()]

    # parte dal primo blocco offerta reale, saltando menu/header
    start = 0
    for i, line in enumerate(lines):
        low = line.lower()
        if any(k in low for k in [
            "prezzo promo",
            "rate da",
            "canoni da",
            "da 239 €",
            "da 249 €",
            "tan",
            "taeg"
        ]):
            start = max(0, i - 6)
            break

    # taglia cookie/chat footer pesante, ma lascia eventuale nota consumi se è prima
    stop_words = [
        "continua senza accettare",
        "la tua privacy è importante",
        "gestisci le mie impostazioni",
        "accetta tutto",
        "chatta con noi",
    ]

    final = []
    for line in lines[start:]:
        if any(sw in line.lower() for sw in stop_words):
            break
        final.append(line)

    return "\n".join(final).strip()


def get_detail_note(browser, url):
    try:
        page = browser.new_page(viewport={"width": 1366, "height": 1600})
        page.goto(url, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(1500)

        # prova apertura accordion "Nota legale e consumi"
        try:
            header = page.locator(".q-expander-header-elem").filter(has_text="Nota legale e consumi").first

            if header.count() > 0 and header.is_visible():
                header.evaluate("""
                    el => {
                        let p = el;
                        for (let i = 0; i < 8; i++) {
                            if (!p) break;

                            const cls = String(p.className || '').toLowerCase();
                            const aria = p.getAttribute('aria-expanded');
                            const role = p.getAttribute('role');

                            if (
                                role === 'button' ||
                                aria !== null ||
                                cls.includes('q-expander-header') ||
                                cls.includes('expander-header') ||
                                cls.includes('q-expander')
                            ) {
                                p.click();
                                return;
                            }

                            p = p.parentElement;
                        }

                        el.click();
                    }
                """)
                page.wait_for_timeout(3000)

        except Exception:
            pass

        body = page.locator("body").inner_text(timeout=30000)

        # Se la pagina espone la nota integrale, prendo quella
        start = body.lower().find("dettaglio promozione")
        if start != -1:
            sub = body[start:]

            stops = [
                "Configura",
                "Contatta il Concessionario",
                "Pronta consegna",
                "Vetture",
                "Gamma elettrica",
                "CONTINUA SENZA ACCETTARE",
                "LA TUA PRIVACY",
                "Chatta con noi",
                "TROVA UN PUNTO VENDITA",
                "MY PEUGEOT",
                "VALUTA IL TUO USATO",
                "LA NOSTRA GAMMA",
                "Domande e risposte",
                "Privacy Policy"
            ]

            end = len(sub)
            for s in stops:
                idx = sub.find(s)
                if idx != -1:
                    end = min(end, idx)

            legal = clean_legal_footer(sub[:end].strip())
            page.close()
            return legal

        page.close()
        return ""
    except Exception as e:
        return f"ERRORE_NOTE_DETTAGLIO: {e}"


def scrape_all():
    run_id = "manual_text_parser_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    all_rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])

        for config in CONFIGS:
            print("Scraping:", config["brand"])
            page = browser.new_page()
            page.goto(config["url"], wait_until="networkidle", timeout=90000)
            text = page.locator("body").inner_text(timeout=30000)

            offer_links = extract_offer_links(page, config["brand"])
            rows = extract_rows_from_text(config, text, run_id)

            # Associa i link dettaglio in ordine: i siti Opel/Peugeot espongono i link nello stesso ordine delle card
            for idx, r in enumerate(rows):
                if idx < len(offer_links):
                    detail_url = offer_links[idx]
                    r["Offer URL"] = detail_url

                    # Per Opel vogliamo testo esteso pagina dettaglio
                    # Per Peugeot lo lasciamo opzionale: se è pagina scaduta, comunque prende il massimo disponibile
                    detail_note = get_detail_note(browser, detail_url)
                    if detail_note and not detail_note.startswith("ERRORE_NOTE_DETTAGLIO"):
                        r["Note Legali"] = detail_note

                        tan_legal = parse_percent_from_legal(detail_note, "TAN")
                        taeg_legal = parse_percent_from_legal(detail_note, "TAEG")
                        scad_legal = parse_scadenza_from_legal(detail_note)

                        if tan_legal:
                            r["TAN (%)"] = tan_legal
                        if taeg_legal:
                            r["TAEG (%)"] = taeg_legal
                        if scad_legal:
                            r["Scadenza"] = scad_legal
                            if scadenza_is_active(scad_legal):
                                r["Stato"] = "attiva"
                            else:
                                r["Stato"] = "scaduta"
                                nt = r.get("Note Tecniche", "")
                                if "offerta_scaduta" not in nt:
                                    r["Note Tecniche"] = (nt + "; offerta_scaduta").strip("; ")

                        r["Note Tecniche"] = (r.get("Note Tecniche", "") + "; note_da_pagina_dettaglio").strip("; ")
                    else:
                        r["Note Tecniche"] = (r.get("Note Tecniche", "") + "; note_dettaglio_non_trovate").strip("; ")

            print(config["brand"], "righe:", len(rows), "| link dettaglio:", len(offer_links))
            all_rows.extend(rows)
            page.close()

        browser.close()

    return all_rows

def write_to_sheet(rows):
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    creds = Credentials.from_service_account_file(KEY_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet("Promo_Output")

    existing = ws.get_all_values()

    brands_to_replace = set(r["Brand"].lower() for r in rows)

    kept_rows = []
    if existing:
        for row in existing[1:]:
            if row and row[0].strip().lower() not in brands_to_replace:
                kept_rows.append(row)

    new_rows = [[r.get(h, "") for h in HEADERS] for r in rows]
    final_values = [HEADERS] + kept_rows + new_rows

    ws.clear()
    ws.update("A1", final_values)

    print("RIGHE SCRITTE:", len(new_rows))
    print("SHEET AGGIORNATO")

if __name__ == "__main__":
    rows = scrape_all()
    write_to_sheet(rows)
