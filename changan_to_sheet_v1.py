from datetime import datetime
import re
import hashlib
from playwright.sync_api import sync_playwright

from promo_common import HEADERS, clean

BRAND = "Changan"
HUB = "https://www.changaneurope.com/it/"
MIN_EXPECTED_ROWS = 3

URLS = [
    "https://www.changaneurope.com/it/promozioni/changan-deepal-s05-ultra-hybrid-finanziamento",
    "https://www.changaneurope.com/it/promozioni/changan-deepal-s05",
    "https://www.changaneurope.com/it/promozioni/changan-deepal-s07",
]

def normalize_legal(note):
    note = clean(note or "")
    note = note.replace("�", "")

    cut_patterns = [
        r"\bRichiedi informazioni\b",
        r"\bRICHIEDI INFORMAZIONI\b",
        r"\bSosteniamo la nostra qualità\b",
        r"\bLe immagini hanno solo scopo illustrativo\b",
        r"\bInformativa sulla privacy\b",
        r"\bCookie\b",
    ]

    for pat in cut_patterns:
        m = re.search(pat, note, re.I)
        if m:
            note = note[:m.start()].strip()

    note = re.sub(r"\n\s*\n+", "\n\n", note)
    note = re.sub(r"[ \t]+", " ", note)
    note = re.sub(r"\s+([,.;:])", r"\1", note)
    note = re.sub(r"\s+", " ", note).strip()
    return note

def euro_from_raw(x):
    x = str(x or "").strip()
    if not x:
        return ""
    x = x.replace("€", "").strip()
    x = x.split(",")[0] if "," in x else x
    return "€ " + x

def pct_from_raw(x):
    x = str(x or "").strip().replace(".", ",")
    if not x:
        return ""
    return x + "%"

def extract_money(text, patterns):
    text = str(text or "")
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return euro_from_raw(m.group(1))
    return ""

def extract_pct(text, patterns):
    text = str(text or "")
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return pct_from_raw(m.group(1))
    return ""

def extract_scadenza(text):
    m = re.search(r"valida\s+fino\s+al\s+(\d{2})[./](\d{2})[./](\d{4})", text, re.I)
    if not m:
        m = re.search(r"fino\s+al\s+(\d{2})[./](\d{2})[./](\d{4})", text, re.I)
    if m:
        return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return ""

def title_model_mot(url, body):
    # Usa solo URL: il body contiene anche i link del menu verso altri modelli.
    low_url = str(url or "").lower()

    if "ultra-hybrid" in low_url:
        return "Deepal S05", "Changan Deepal S05 Pro ULTRA-HYBRID", "plug-in"
    if "s07" in low_url:
        return "Deepal S07", "Changan Deepal S07 BEV", "elettrica"
    return "Deepal S05", "Changan Deepal S05 BEV Pro", "elettrica"

def extract_note(body):
    start_patterns = [
        r"Offerta di finanziamento\s+[\"“]STAY IN THE GAME",
        r"\*\s*Messaggio pubblicitario con finalità promozionale",
        r"Messaggio pubblicitario con finalità promozionale",
    ]

    starts = []
    for pat in start_patterns:
        m = re.search(pat, body, re.I)
        if m:
            starts.append(m.start())

    start = min(starts) if starts else 0

    note = body[start:]
    return normalize_legal(note)

def active(scadenza):
    try:
        d = datetime.strptime(scadenza, "%d/%m/%Y").date()
        return "attiva" if d >= datetime.now().date() else "scaduta"
    except Exception:
        return ""

def claim_from_note(mot, note):
    low = note.lower()
    claims = ["finanziamento", "Findomestic"]
    if "stay in the game" in low:
        claims.append("STAY IN THE GAME")
    if "prima rata dopo 3 mesi" in low:
        claims.append("prima rata dopo 3 mesi")
    if mot:
        claims.append(mot)
    return "; ".join(dict.fromkeys(claims))

def promo_hash(row):
    raw = "|".join([
        row.get("Brand",""),
        row.get("Modello",""),
        row.get("Titolo Promo",""),
        row.get("Rata",""),
        row.get("Intero",""),
        row.get("Scadenza",""),
        row.get("Offer URL",""),
    ])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def parse_detail(page, url, run_id):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)

    body = clean(page.locator("body").inner_text(timeout=10000))
    note = extract_note(body)

    modello, titolo, mot = title_model_mot(url, body)

    rata = extract_money(body, [
        r"Tua\s+a\s+([\d\.,]+)\s*€\s+al\s+mese",
        r"in\s+60\s+rate\s+da\s*€\s*([\d\.,]+)",
    ])

    intero = extract_money(body, [
        r"Prezzo\s+Promo\s+con\s+Finanziamento\s+a\s+partire\s+da\s*€\s*([\d\.,]+)",
        r"Prezzo\s+Promo\s+con\s+Finanziamento[^€]{0,80}€\s*([\d\.,]+)",
        r"Prezzo\s+di\s+listino[^€]{0,80}€\s*([\d\.,]+)",
    ])

    anticipo = extract_money(body, [
        r"Anticipo\s+([\d\.,]+)\s*€",
        r"anticipo\s*€\s*([\d\.,]+)",
    ])

    vfg = extract_money(body, [
        r"Maxirata\s+([\d\.,]+)\s*€",
        r"importo\s+residuo\s*€\s*([\d\.,]+)",
    ])

    credito = extract_money(body, [
        r"Importo\s+totale\s+del\s+credito:\s*€\s*([\d\.,]+)",
    ])

    dovuto = extract_money(body, [
        r"Importo\s+totale\s+dovuto\s+dal\s+Cliente:\s*€\s*([\d\.,]+)",
    ])

    tan = extract_pct(body, [
        r"Prima\s+fase\s+TAN\s+fisso\s*([\d\.,]+)\s*%",
        r"TAN\s+fisso\s*([\d\.,]+)\s*%",
    ])

    taeg = extract_pct(body, [
        r"Prima\s+fase\s+TAN\s+fisso\s*[\d\.,]+\s*%,\s*TAEG\s*([\d\.,]+)\s*%",
        r"TAEG\s*([\d\.,]+)\s*%",
    ])

    scadenza = extract_scadenza(body)

    tech = ["source=detail_legal", "finanziamento_findomestic", "60 rate prima fase", "seconda fase con maxirata residua"]

    row = {
        "Brand": BRAND,
        "Modello": modello,
        "Motorizzazione": mot,
        "Titolo Promo": titolo,
        "Claim Promo": claim_from_note(mot, note),
        "Rata": rata,
        "Intero": intero,
        "Anticipo": anticipo,
        "Rata Finale / VFG": vfg,
        "Importo Totale Credito": credito,
        "Importo Totale Dovuto": dovuto,
        "TAN (%)": tan,
        "TAEG (%)": taeg,
        "Scadenza": scadenza,
        "Note Legali": note,
        "Fonte URL": HUB,
        "Offer URL": url,
        "Data Aggiornamento": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Data Scansione": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Last Seen": datetime.now().strftime("%Y-%m-%d"),
        "Stato": active(scadenza),
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
    run_id = "changan_v1_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = []
    bad = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 5000})

        for i, url in enumerate(URLS, start=1):
            r = parse_detail(page, url, run_id)
            flags = []

            required = [
                "Brand","Modello","Motorizzazione","Titolo Promo","Claim Promo",
                "Rata","Intero","Anticipo","Rata Finale / VFG",
                "Importo Totale Credito","Importo Totale Dovuto",
                "TAN (%)","TAEG (%)","Scadenza","Note Legali","Offer URL"
            ]

            for col in required:
                if not str(r.get(col,"")).strip():
                    flags.append("missing_" + col)

            low_note = r["Note Legali"].lower()
            forbidden = [
                "richiedi informazioni",
                "informativa sulla privacy",
                "cookiescript",
                "datalayer",
                "window.",
                "noleggio",
                "leasing per privati",
            ]

            for x in forbidden:
                if x in low_note:
                    flags.append("dirty_" + x)

            if len(r["Note Legali"]) < 900:
                flags.append("note_short")

            print(
                f"{i}/{len(URLS)} | {r['Modello']} | {r['Motorizzazione']} | {r['Titolo Promo']} | "
                f"{r['Claim Promo']} | {r['Rata']} | {r['Intero']} | {r['Anticipo']} | "
                f"{r['Rata Finale / VFG']} | {r['Importo Totale Credito']} | {r['Importo Totale Dovuto']} | "
                f"{r['TAN (%)']} | {r['TAEG (%)']} | {r['Scadenza']} | {r['Note Tecniche']} | FLAGS: {flags}"
            )

            print("NOTE END:", r["Note Legali"][-500:])

            if flags:
                bad.append((r["Titolo Promo"], flags))

            rows.append(r)

        browser.close()

    print("RIGHE CHANGAN:", len(rows))
    print("BAD:", bad)
    print("DEBUG ONLY: nessun push su Google Sheet")
    return rows

if __name__ == "__main__":
    build_rows()
