from datetime import datetime
import re
import hashlib
from playwright.sync_api import sync_playwright

from promo_common import HEADERS, clean

BRAND = "MINI"
HUB = "https://www.mini.it/it_IT/home/financial-service/leasing.html"
MIN_EXPECTED_ROWS = 7

URL_META = [
    ("MINI Cooper", "MINI Cooper ONE", "benzina", "https://www.mini.it/it_IT/home/range/mini-cooper-3-door/offers.html"),
    ("MINI Cooper Cabrio", "MINI Cooper Cabrio", "benzina", "https://www.mini.it/it_IT/home/range/mini-cooper-convertible/offers.html"),
    ("MINI Aceman", "All-Electric MINI Aceman", "elettrica", "https://www.mini.it/it_IT/home/range/all-electric-mini-aceman/offers.html"),
    ("MINI Cooper Elettrica", "All-Electric MINI Cooper", "elettrica", "https://www.mini.it/it_IT/home/range/all-electric-mini-cooper/offers.html"),
    ("MINI Cooper 5 Porte", "MINI Cooper 5 Porte ONE", "benzina", "https://www.mini.it/it_IT/home/range/mini-cooper-5-door/offers.html"),
    ("MINI Countryman", "MINI Countryman ONE", "benzina", "https://www.mini.it/it_IT/home/range/mini-countryman/offers.html"),
    ("MINI Countryman Elettrica", "All-Electric MINI Countryman", "elettrica", "https://www.mini.it/it_IT/home/range/all-electric-mini-countryman/offers.html"),
]

def norm(t):
    return clean(str(t or "").replace("�", ""))

def normalize_legal(note):
    note = norm(note)
    for pat in [
        r"\bLE NOSTRE OFFERTE ATTUALI\b",
        r"\bLE NOSTRE OFFERTE\.\b",
        r"\bFAI IL PASSO SUCCESSIVO\b",
        r"\bMINI FINANCIAL SERVICES\b",
        r"\bPRENOTA TEST DRIVE\b",
        r"\bDICHIARAZIONI DI NON RESPONSABILITÀ\b",
        r"\bAiuto & Contatti\b",
        r"\bCookie\b",
        r"\bPrivacy\b",
    ]:
        m = re.search(pat, note, re.I)
        if m:
            note = note[:m.start()].strip()
    note = re.sub(r"\s+([,.;:])", r"\1", note)
    note = re.sub(r"\s+", " ", note).strip()
    return note

def euro(x):
    x = str(x or "").replace("€", "").strip()
    if not x:
        return ""
    x = x.split(",")[0]
    x = x.rstrip(".")
    return "€ " + x

def pct(x):
    x = str(x or "").strip().replace(".", ",")
    if not x:
        return ""
    return x if x.endswith("%") else x + "%"

def find1(text, patterns):
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1).strip()
    return ""

def money(text, patterns):
    return euro(find1(text, patterns))

def perc(text, patterns):
    return pct(find1(text, patterns))

def extract_note(body):
    m = re.search(r"Note\s+legali\s+(\*Un\s+esempio\s+rappresentativo.+)", body, re.I)
    if m:
        return normalize_legal(m.group(1))
    m = re.search(r"(\*Un\s+esempio\s+rappresentativo.+)", body, re.I)
    if m:
        return normalize_legal(m.group(1))
    return normalize_legal(body)

def has_extended_offer(body):
    return "Un esempio rappresentativo" in body

def extract_card_only(body, modello):
    # Formato semplificato oggi presente su alcuni modelli (es. elettrici):
    # "Tua a 32.100€ con vantaggio cliente di 3.000€ incluso."
    m = re.search(
        r"Tua\s+a\s*([\d\.,]+)\s*€\s+con\s+vantaggio\s+cliente\s+di\s*([\d\.,]+)\s*€",
        body, re.I
    )
    if not m:
        return None
    prezzo, vantaggio = m.group(1), m.group(2)

    # Frase completa per Note Legali (dalla riga "Design..." fino al punto finale)
    m_frase = re.search(r"([A-ZÀ-Ý][^.]*?Tua\s+a\s*[\d\.,]+\s*€\s+con\s+vantaggio\s+cliente\s+di\s*[\d\.,]+\s*€\s+incluso\.)", body, re.I)
    nota = normalize_legal(m_frase.group(1)) if m_frase else normalize_legal(f"{modello}. Tua a {prezzo}€ con vantaggio cliente di {vantaggio}€ incluso.")

    return {
        "intero": euro(prezzo),
        "vantaggio": euro(vantaggio),
        "nota": nota,
    }

def scadenza(text):
    m = re.search(r"Offerta\s+valida\s+fino\s+al\s+(\d{2})/(\d{2})/(\d{4})", text, re.I)
    if not m:
        m = re.search(r"fino\s+al\s+(\d{2})/(\d{2})/(\d{4})", text, re.I)
    if m:
        return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return ""

def active(s):
    try:
        d = datetime.strptime(s, "%d/%m/%Y").date()
        return "attiva" if d >= datetime.now().date() else "scaduta"
    except:
        return ""

def claim(mot, note):
    low = note.lower()
    out = ["leasing finanziario", "MINI WHY-BUY"]
    if "bmw bank" in low:
        out.append("BMW Bank")
    if mot:
        out.append(mot)
    return "; ".join(dict.fromkeys(out))

def promo_hash(row):
    raw = "|".join([row.get(k, "") for k in ["Brand","Modello","Titolo Promo","Rata","Intero","Scadenza","Offer URL"]])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def parse_page(page, modello, titolo, mot, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)

    body = norm(page.evaluate("() => document.body.innerText"))

    if not has_extended_offer(body):
        # Formato semplificato (oggi presente sui modelli elettrici): solo prezzo + vantaggio cliente,
        # nessun dettaglio di leasing/TAN/TAEG disponibile sul sito.
        card = extract_card_only(body, modello)
        if card:
            scad = scadenza(body)  # quasi certamente vuota su questo formato, non si inventa
            row = {
                "Brand": BRAND,
                "Modello": modello,
                "Motorizzazione": mot,
                "Titolo Promo": titolo,
                "Claim Promo": f"vantaggio cliente {card['vantaggio']}; {mot}" if mot else f"vantaggio cliente {card['vantaggio']}",
                "Rata": "",
                "Intero": card["intero"],
                "Anticipo": "",
                "Rata Finale / VFG": "",
                "Importo Totale Credito": "",
                "Importo Totale Dovuto": "",
                "TAN (%)": "",
                "TAEG (%)": "",
                "Scadenza": scad,
                "Note Legali": card["nota"],
                "Fonte URL": HUB,
                "Offer URL": url,
                "Data Aggiornamento": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Data Scansione": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Last Seen": datetime.now().strftime("%Y-%m-%d"),
                "Stato": active(scad) if scad else "incompleta",
                "Alert Type": "",
                "Promo Hash": "",
                "Extraction Confidence": "medium",
                "Run ID": run_id,
                "Legal Source Status": "card_only_no_legal",
                "Note Tecniche": "source=detail_card; no_financial_legal_found; vantaggio_cliente" + ("" if scad else "; missing_scadenza_on_site"),
            }
            row["Promo Hash"] = promo_hash(row)
            return row
        # Se nemmeno il formato card-only matcha, procede col percorso esteso sotto (che restituira' flag)

    note = extract_note(body)

    rata = money(body, [
        r"A\s+partire\s+da\s+([\d\.,]+)\s*€\s+al\s+mese",
    ])

    intero = money(note, [
        r"Prezzo\s+vettura\s*€\s*([\d\.,]+)",
    ])

    anticipo = money(note, [
        r"Anticipo\s+o\s+eventuale\s+permuta\s*€\s*([\d\.,]+)",
    ])

    vfg = money(note, [
        r"Opzione\s+di\s+acquisto\s+finale[^€]{0,140}€\s*([\d\.,]+)",
    ])

    credito = money(note, [
        r"Importo\s+totale\s+del\s+credito\s*€\s*([\d\.,]+)",
    ])

    dovuto = money(note, [
        r"Importo\s+totale\s+dovuto\s+dal\s+Cliente\s*€\s*([\d\.,]+)",
    ])

    tan = perc(note, [
        r"Tasso\s+Leasing\s*([\d\.,]+)\s*%",
    ])

    taeg = perc(note, [
        r"TAEG\s*([\d\.,]+)\s*%",
    ])

    scad = scadenza(note) or scadenza(body)

    mesi = find1(note, [r"Durata\s+di\s+(\d+)\s+mesi"]) or find1(body, [r"Durata:\s*(\d+)\s+mesi"])
    canoni = find1(note, [r"con\s+(\d+)\s+canoni"])

    tech = ["source=detail_legal", "leasing_finanziario_mini_why_buy", "bmw_bank"]
    if mesi:
        tech.append(f"{mesi} mesi")
    if canoni:
        tech.append(f"{canoni} canoni")

    row = {
        "Brand": BRAND,
        "Modello": modello,
        "Motorizzazione": mot,
        "Titolo Promo": titolo,
        "Claim Promo": claim(mot, note),
        "Rata": rata,
        "Intero": intero,
        "Anticipo": anticipo,
        "Rata Finale / VFG": vfg,
        "Importo Totale Credito": credito,
        "Importo Totale Dovuto": dovuto,
        "TAN (%)": tan,
        "TAEG (%)": taeg,
        "Scadenza": scad,
        "Note Legali": note,
        "Fonte URL": HUB,
        "Offer URL": url,
        "Data Aggiornamento": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Data Scansione": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Last Seen": datetime.now().strftime("%Y-%m-%d"),
        "Stato": active(scad),
        "Alert Type": "",
        "Promo Hash": "",
        "Extraction Confidence": "high",
        "Run ID": run_id,
        "Legal Source Status": "extended_legal_found",
        "Note Tecniche": "; ".join(tech),
    }
    row["Promo Hash"] = promo_hash(row)
    return row

def build_rows():
    run_id = "mini_v1_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []
    bad = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 10000})

        for i, (modello, titolo, mot, url) in enumerate(URL_META, start=1):
            r = parse_page(page, modello, titolo, mot, url, run_id)
            flags = []

            is_card_only = r.get("Legal Source Status") == "card_only_no_legal"
            base_required = ["Brand","Modello","Motorizzazione","Titolo Promo","Claim Promo","Intero","Note Legali","Offer URL"]
            financial_fields = ["Rata","Anticipo","Rata Finale / VFG","Importo Totale Credito","Importo Totale Dovuto","TAN (%)","TAEG (%)"]

            for col in base_required:
                if not str(r.get(col, "")).strip():
                    flags.append("missing_" + col)

            if is_card_only:
                for col in financial_fields:
                    if str(r.get(col, "")).strip():
                        flags.append("unexpected_financial_" + col)
                if not str(r.get("Scadenza", "")).strip():
                    flags.append("info_missing_scadenza_on_site")  # non bloccante, il sito non la mostra
            else:
                for col in financial_fields + ["Scadenza"]:
                    if not str(r.get(col, "")).strip():
                        flags.append("missing_" + col)

            low = r["Note Legali"].lower()
            for x in ["noleggio a lungo termine", "leasing operativo", "datalayer", "window.", "cookiebanner"]:
                if x in low:
                    flags.append("dirty_" + x)

            print(
                f"{i}/7 | {r['Modello']} | {r['Motorizzazione']} | {r['Titolo Promo']} | "
                f"{r['Rata']} | {r['Intero']} | {r['Anticipo']} | {r['Rata Finale / VFG']} | "
                f"{r['Importo Totale Credito']} | {r['Importo Totale Dovuto']} | "
                f"{r['TAN (%)']} | {r['TAEG (%)']} | {r['Scadenza']} | {r['Note Tecniche']} | FLAGS: {flags}"
            )

            if flags:
                bad.append((r["Titolo Promo"], flags))
            rows.append(r)

        browser.close()

    print("RIGHE MINI:", len(rows))
    print("BAD:", bad)
    print("DEBUG ONLY: nessun push su Google Sheet")
    return rows

if __name__ == "__main__":
    build_rows()
