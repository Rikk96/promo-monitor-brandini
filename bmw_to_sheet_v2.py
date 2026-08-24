from datetime import datetime
import re
import hashlib

import bmw_to_sheet
from promo_common import HEADERS, clean

BRAND = "BMW"
HUB = "https://www.bmw.it/it/topics/offerte-bmw/panoramica.html"
MIN_EXPECTED_ROWS = 8

def normalize_legal(note):
    note = clean(note or "")
    note = note.replace("�", "")
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
    x = x.rstrip(".")
    return "€ " + x

def extract_money(text, patterns):
    text = str(text or "")
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return euro_from_raw(m.group(1))
    return ""

def extract_from_oldtech(old_row, key):
    text = str(old_row.get("Note Tecniche","") or "")
    patterns = {
        "anticipo": r"anticipo\s*€\s*([\d\.,]+)",
        "vfg": r"rata_finale\s*€\s*([\d\.,]+)",
        "credito": r"importo_totale_credito\s*€\s*([\d\.,]+)",
        "dovuto": r"importo_totale_dovuto\s*€\s*([\d\.,]+)",
    }
    pat = patterns.get(key)
    if not pat:
        return ""
    return extract_money(text, [pat])

def extract_duration(note, old_row):
    text = str(old_row.get("Note Tecniche","") or "") + " " + str(note or "")
    mesi = ""
    canoni = ""

    m = re.search(r"(\d+)\s+mesi", text, re.I)
    if m:
        mesi = f"{m.group(1)} mesi"

    c = re.search(r"(\d+)\s+canoni", text, re.I)
    if c:
        canoni = f"{c.group(1)} canoni"

    return mesi, canoni

def claim_from_note(row, note):
    low = str(note or "").lower()
    mot = str(row.get("Motorizzazione","") or "").strip()
    claims = []

    if "leasing finanziario" in low:
        claims.append("leasing finanziario")
    if "bmw bank" in low:
        claims.append("BMW Bank")
    if "service inclusive" in low or "programma di manutenzione" in low:
        claims.append("manutenzione inclusa")
    if "concessionarie aderenti" in low:
        claims.append("concessionarie aderenti")
    if mot:
        claims.append(mot)

    return "; ".join(dict.fromkeys(claims))

def active(scadenza):
    try:
        d = datetime.strptime(scadenza, "%d/%m/%Y").date()
        return "attiva" if d >= datetime.now().date() else "scaduta"
    except Exception:
        return ""

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

def convert_row(old_row, run_id):
    note = normalize_legal(old_row.get("Note Legali",""))

    anticipo = extract_from_oldtech(old_row, "anticipo") or extract_money(note, [
        r"Anticipo\s+o\s+eventuale\s+permuta\s*€\s*([\d\.,]+)",
    ])

    vfg = extract_from_oldtech(old_row, "vfg") or extract_money(note, [
        r"valore\s+futuro\s+garantito[^€]{0,80}€\s*([\d\.,]+)",
        r"Opzione\s+di\s+acquisto[^€]{0,120}€\s*([\d\.,]+)",
    ])

    credito = extract_from_oldtech(old_row, "credito") or extract_money(note, [
        r"Importo\s+totale\s+del\s+credito\s*€\s*([\d\.,]+)",
    ])

    dovuto = extract_from_oldtech(old_row, "dovuto") or extract_money(note, [
        r"Importo\s+totale\s+dovuto\s+dal\s+Cliente\s*€\s*([\d\.,]+)",
    ])

    mesi, canoni = extract_duration(note, old_row)

    tech = ["source=detail_legal", "leasing_finanziario_bmw_bank"]
    if mesi:
        tech.append(mesi)
    if canoni:
        tech.append(canoni)

    row = {
        "Brand": BRAND,
        "Modello": old_row.get("Modello",""),
        "Motorizzazione": old_row.get("Motorizzazione",""),
        "Titolo Promo": old_row.get("Titolo Promo",""),
        "Claim Promo": claim_from_note(old_row, note),
        "Rata": old_row.get("Rata",""),
        "Intero": old_row.get("Intero",""),
        "Anticipo": anticipo,
        "Rata Finale / VFG": vfg,
        "Importo Totale Credito": credito,
        "Importo Totale Dovuto": dovuto,
        "TAN (%)": old_row.get("TAN (%)",""),
        "TAEG (%)": old_row.get("TAEG (%)",""),
        "Scadenza": old_row.get("Scadenza",""),
        "Note Legali": note,
        "Fonte URL": HUB,
        "Offer URL": old_row.get("Offer URL",""),
        "Data Aggiornamento": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Data Scansione": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Last Seen": datetime.now().strftime("%Y-%m-%d"),
        "Stato": active(old_row.get("Scadenza","")),
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
    run_id = "bmw_v2_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    old_rows = bmw_to_sheet.build_rows()
    rows = []
    bad = []

    print("RIGHE BMW OLD:", len(old_rows))

    for i, old in enumerate(old_rows, start=1):
        r = convert_row(old, run_id)
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
        hard_bad = [
            "noleggio a lungo termine",
            "leasing operativo",
            "richiedi informazioni",
            "datalayer",
            "window.",
            "cookiebanner",
        ]

        for x in hard_bad:
            if x in low_note:
                flags.append("dirty_" + x)

        if len(r["Note Legali"]) < 700:
            flags.append("note_short")

        print(
            f"{i}/{len(old_rows)} | {r['Modello']} | {r['Motorizzazione']} | {r['Titolo Promo']} | "
            f"{r['Claim Promo']} | {r['Rata']} | {r['Intero']} | {r['Anticipo']} | "
            f"{r['Rata Finale / VFG']} | {r['Importo Totale Credito']} | {r['Importo Totale Dovuto']} | "
            f"{r['TAN (%)']} | {r['TAEG (%)']} | {r['Scadenza']} | {r['Note Tecniche']} | FLAGS: {flags}"
        )

        if flags:
            bad.append((r["Titolo Promo"], flags))

        rows.append(r)

    print("RIGHE BMW:", len(rows))
    print("BAD:", bad)
    print("DEBUG ONLY: nessun push su Google Sheet")
    return rows

if __name__ == "__main__":
    build_rows()
