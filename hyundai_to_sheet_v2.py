from datetime import datetime
import re

import hyundai_to_sheet_legacy_dependency as hyundai_to_sheet
from promo_common import HEADERS, clean

BRAND = "Hyundai"
HUB = "https://www.hyundai.com/it/it/promozioni-offerte/Promozioni/offerte-hyundai-plus.html"
MIN_EXPECTED_ROWS = 14

def euro_from_number(x):
    x = str(x or "").strip()
    if not x:
        return ""
    x = x.replace("€", "").strip()
    return "€ " + x

def normalize_legal(note):
    note = clean(note or "")
    note = note.replace("�", "")
    note = re.sub(r"\n\s*\n+", "\n\n", note)
    note = re.sub(r"[ \t]+", " ", note)
    note = re.sub(r"\s+([,.;:])", r"\1", note)
    note = re.sub(r"\s+", " ", note).strip()
    return note


def extract_credito_from_note(note):
    text = str(note or "")
    m = re.search(r"importo\s+totale\s+del\s+credito\s*€\s*([\d\.,]+)", text, re.I)
    if m:
        raw = m.group(1).strip()
        raw = raw.split(",")[0] if "," in raw else raw
        return "€ " + raw
    return ""

def active(scadenza):
    try:
        d = datetime.strptime(scadenza, "%d/%m/%Y").date()
        return "attiva" if d >= datetime.now().date() else "scaduta"
    except Exception:
        return ""

def modello_clean(old_row):
    title = str(old_row.get("Titolo Promo","") or "")
    model = str(old_row.get("Modello","") or "").strip()

    if "IONIQ 9" in title.upper():
        return "IONIQ 9"
    if model.upper().startswith("I ") or "56.497" in model:
        return "IONIQ 9"

    return model

def extract_value_after_label(note, label_patterns, max_chars=260):
    text = str(note or "")
    for label in label_patterns:
        m = re.search(label + r"\s*€?\s*([\d\.,]+)", text, re.I)
        if m:
            return euro_from_number(m.group(1))

        m = re.search(label + r"[\s\S]{0," + str(max_chars) + r"}?€\s*([\d\.,]+)", text, re.I)
        if m:
            return euro_from_number(m.group(1))

    return ""

def extract_anticipo(note):
    # Deve prendere la label Anticipo, non la rata.
    m = re.search(r"\bAnticipo\b\s*€\s*([\d\.,]+)", note, re.I)
    if m:
        return euro_from_number(m.group(1))

    m = re.search(r"\bAnticipo\b\s+([\d\.,]+)", note, re.I)
    if m:
        return euro_from_number(m.group(1))

    # fallback su blocco "Anticipo ... € X" molto vicino
    m = re.search(r"\bAnticipo\b[\s\S]{0,80}?€\s*([\d\.,]+)", note, re.I)
    if m:
        return euro_from_number(m.group(1))

    return ""

def extract_vfg(note):
    return extract_value_after_label(note, [
        r"Valore\s+Futuro\s+Garantito\s+pari\s+alla\s+Rata\s+finale",
        r"Rata\s+finale",
        r"Valore\s+Futuro\s+Garantito",
    ], max_chars=260)

def extract_importo_dovuto(note):
    return extract_value_after_label(note, [
        r"Importo\s+totale\s+dovuto\s+dal\s+consumatore\s+per\s+il\s+finanziamento",
        r"Importo\s+totale\s+dovuto",
    ], max_chars=180)

def extract_rate_count(note):
    m = re.search(r"(\d+)\s+rate\s+da\s*€\s*([\d\.,]+)", note, re.I)
    if m:
        return f"{m.group(1)} rate"
    m = re.search(r"(\d+)\s+rate", note, re.I)
    if m:
        return f"{m.group(1)} rate"
    return ""

def claim_from_note(note):
    low = str(note or "").lower()
    claims = []

    if "hyundai plus" in low:
        claims.append("finanziamento Hyundai Plus")
    if "anticipo 0" in low:
        claims.append("anticipo zero")
    if "interessi 0" in low:
        claims.append("interessi zero")
    if "hyundai boost" in low:
        claims.append("Hyundai Boost")
    if "bonus rottamazione" in low or "rottamazione" in low:
        claims.append("rottamazione")
    if "dark line" in low:
        claims.append("Dark Line")
    if "per tutti" in low:
        claims.append("per tutti")

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
    import hashlib
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def convert_row(old_row, run_id):
    note = normalize_legal(old_row.get("Note Legali",""))

    row = {
        "Brand": BRAND,
        "Modello": modello_clean(old_row),
        "Motorizzazione": old_row.get("Motorizzazione",""),
        "Titolo Promo": old_row.get("Titolo Promo",""),
        "Claim Promo": claim_from_note(note),
        "Rata": old_row.get("Rata",""),
        "Intero": old_row.get("Intero",""),
        "TAN (%)": old_row.get("TAN (%)",""),
        "TAEG (%)": old_row.get("TAEG (%)",""),
        "Scadenza": old_row.get("Scadenza",""),
        "Note Legali": note,
        "Anticipo": extract_anticipo(note),
        "Rata Finale / VFG": extract_vfg(note),
        "Importo Totale Credito": extract_credito_from_note(note),
        "Importo Totale Dovuto": extract_importo_dovuto(note),
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
        "Note Tecniche": "source=detail_legal; finanziamento_hyundai_plus; " + extract_rate_count(note),
    }
    row["Promo Hash"] = promo_hash(row)
    return row

def build_rows():
    run_id = "hyundai_v2_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    old_rows = hyundai_to_sheet.build_rows()
    rows = []

    print("RIGHE HYUNDAI OLD:", len(old_rows))

    for i, old in enumerate(old_rows, start=1):
        r = convert_row(old, run_id)
        rows.append(r)

        print(
            f"{i}/{len(old_rows)} | {r['Modello']} | {r['Motorizzazione']} | {r['Titolo Promo']} | "
            f"{r['Claim Promo']} | {r['Rata']} | {r['Intero']} | {r['Anticipo']} | "
            f"{r['Rata Finale / VFG']} | {r['Importo Totale Dovuto']} | "
            f"{r['TAN (%)']} | {r['TAEG (%)']} | {r['Scadenza']} | {r['Legal Source Status']} | {r['Note Tecniche']}"
        )

    print("RIGHE VALIDE:", len(rows))
    print("DEBUG ONLY: nessun push su Google Sheet")
    return rows

if __name__ == "__main__":
    build_rows()
