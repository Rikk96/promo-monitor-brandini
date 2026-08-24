from datetime import datetime
import re
import hashlib

import honda_to_sheet
from promo_common import HEADERS, clean

BRAND = "Honda"
HUB = "https://www.honda.it/cars/offers.html"
MIN_EXPECTED_ROWS = 7

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
    return "€ " + x

def extract_money(note, patterns):
    text = str(note or "")
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            raw = m.group(1).strip()
            raw = raw.split(",")[0] if "," in raw else raw
            return euro_from_raw(raw)
    return ""

def extract_oldtech_money(old_row, key):
    text = str(old_row.get("Note Tecniche", "") or "")
    patterns = {
        "anticipo": r"anticipo\s*€\s*([\d\.,]+)",
        "vfg": r"rata_finale\s*€\s*([\d\.,]+)",
        "credito": r"importo_totale_credito\s*€\s*([\d\.,]+)",
        "dovuto": r"totale_dovuto\s*€\s*([\d\.,]+)",
    }
    pat = patterns.get(key)
    if not pat:
        return ""
    m = re.search(pat, text, re.I)
    if not m:
        return ""
    raw = m.group(1).strip()
    raw = raw.split(",")[0] if "," in raw else raw
    return euro_from_raw(raw)

def extract_anticipo(note):
    return extract_money(note, [
        r"anticipo\s+di\s+([\d\.,]+)\s*€",
        r"anticipo\s*€\s*([\d\.,]+)",
    ])

def extract_vfg(note):
    return extract_money(note, [
        r"Valore\s+Futuro\s+Garantito.*?([\d\.,]+)\s*€",
        r"rata\s+finale\s+di\s+([\d\.,]+)\s*€",
        r"Rata\s+Finale.*?([\d\.,]+)\s*€",
    ])

def extract_credito(note):
    return extract_money(note, [
        r"Importo\s+totale\s+del\s+credito\s+([\d\.,]+)\s*€",
        r"importo\s+totale\s+credito\s+([\d\.,]+)\s*€",
    ])

def extract_dovuto(note):
    return extract_money(note, [
        r"Importo\s+totale\s+dovuto(?:[^€]{0,250})?€\s*([\d\.,]+)",
        r"totale\s+dovuto(?:[^€]{0,250})?€\s*([\d\.,]+)",
        r"Importo\s+totale\s+dovuto\s+([\d\.,]+)\s*€",
        r"totale\s+dovuto\s+([\d\.,]+)\s*€",
    ])

def extract_rate_count(note):
    m = re.search(r"(\d+)\s+rate", note, re.I)
    if m:
        return f"{m.group(1)} rate"
    return ""

def claim_from_row_note(old_row, note):
    low = str(note or "").lower()
    title = str(old_row.get("Titolo Promo","")).lower()
    claims = []

    if "ecobonus" in low or "bonus" in low:
        claims.append("bonus")
    if "honda finanzia" in low or "honda financial services" in low:
        claims.append("finanziamento Honda")
    if old_row.get("Rata"):
        claims.append("finanziamento")
    else:
        claims.append("prezzo promo")
    if "full hybrid" in title or "e:hev" in low:
        claims.append("full hybrid")
    if "plug-in" in title:
        claims.append("plug-in hybrid")
    if "stock" in low:
        claims.append("stock")
    if "concessionarie honda" in low:
        claims.append("concessionari aderenti")

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
    note = normalize_legal(old_row.get("Note Legali", ""))

    is_fin = bool(str(old_row.get("Rata","")).strip())
    is_prezzo = not is_fin

    tech = ["source=detail_legal"]
    if is_fin:
        tech.append("finanziamento_honda")
        rc = extract_rate_count(note)
        if rc:
            tech.append(rc)
    else:
        tech.append("prezzo_promo")
        tech.append("tan_taeg_not_applicable")

    row = {
        "Brand": BRAND,
        "Modello": old_row.get("Modello",""),
        "Motorizzazione": old_row.get("Motorizzazione",""),
        "Titolo Promo": old_row.get("Titolo Promo",""),
        "Claim Promo": claim_from_row_note(old_row, note),
        "Rata": old_row.get("Rata",""),
        "Intero": old_row.get("Intero",""),
        "Anticipo": extract_oldtech_money(old_row, "anticipo") or extract_anticipo(note),
        "Rata Finale / VFG": extract_oldtech_money(old_row, "vfg") or extract_vfg(note),
        "Importo Totale Credito": extract_oldtech_money(old_row, "credito") or extract_credito(note),
        "Importo Totale Dovuto": extract_oldtech_money(old_row, "dovuto") or extract_dovuto(note),
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
    run_id = "honda_v2_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    old_rows = honda_to_sheet.build_rows()
    rows = []
    bad = []

    print("RIGHE HONDA OLD:", len(old_rows))

    for i, old in enumerate(old_rows, start=1):
        r = convert_row(old, run_id)
        flags = []

        required = ["Brand","Modello","Motorizzazione","Titolo Promo","Claim Promo","Intero","Scadenza","Note Legali","Offer URL"]

        for col in required:
            if not str(r.get(col,"")).strip():
                flags.append("missing_" + col)

        if "finanziamento_honda" in r["Note Tecniche"]:
            for col in ["Rata","Anticipo","Rata Finale / VFG","Importo Totale Credito","Importo Totale Dovuto","TAN (%)","TAEG (%)"]:
                if not str(r.get(col,"")).strip():
                    flags.append("missing_" + col)

        if "noleggio" in r["Note Legali"].lower() or "canone" in r["Note Legali"].lower():
            flags.append("possible_noleggio")

        print(
            f"{i}/{len(old_rows)} | {r['Modello']} | {r['Motorizzazione']} | {r['Titolo Promo']} | "
            f"{r['Claim Promo']} | {r['Rata']} | {r['Intero']} | {r['Anticipo']} | "
            f"{r['Rata Finale / VFG']} | {r['Importo Totale Credito']} | {r['Importo Totale Dovuto']} | "
            f"{r['TAN (%)']} | {r['TAEG (%)']} | {r['Scadenza']} | {r['Note Tecniche']} | FLAGS: {flags}"
        )

        if flags:
            bad.append((r["Titolo Promo"], flags))

        rows.append(r)

    print("RIGHE HONDA:", len(rows))
    print("BAD:", bad)
    print("DEBUG ONLY: nessun push su Google Sheet")
    return rows

if __name__ == "__main__":
    build_rows()
