from datetime import datetime
import re
import hashlib

import omodajaecoo_to_sheet
from promo_common import HEADERS, clean

BRAND_MAIN = "Omoda & Jaecoo"
HUB = "https://www.omodajaecooitalia.com/promozioni"
MIN_EXPECTED_ROWS = 11

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
    return "€ " + x

def extract_money(note, patterns):
    text = str(note or "")
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return euro_from_raw(m.group(1))
    return ""

def extract_intero(old_row, note):
    old = str(old_row.get("Intero", "") or "").strip()
    if old:
        return old

    return extract_money(note, [
        r"Valore\s+fornitura\s+([\d\.,]+)\s*€",
        r"Valore\s+fornitura\s+€\s*([\d\.,]+)",
        r"Prezzo\s+Promo\s+([\d\.,]+)\s*€",
        r"Prezzo\s+Promo\s*:?\s*€?\s*([\d\.,]+)",
    ])

def infer_motorizzazione(row, note):
    mot = str(row.get("Motorizzazione", "") or "").strip()
    if mot:
        return mot

    title = str(row.get("Titolo Promo", "") or "").lower()
    model = str(row.get("Modello", "") or "").lower()
    low = (title + " " + model + " " + str(note or "").lower())

    if "ev" in low or "elettrica" in low:
        return "elettrica"
    if "shs-p" in low or "plug-in" in low or "phev" in low:
        return "plug-in"
    if "shs-h" in low or "hybrid" in low or "hev" in low:
        return "hybrid"
    return "benzina"

def extract_rate_count(note):
    m = re.search(r"(\d+)\s+(?:rate|canoni)\s+mensili", str(note or ""), re.I)
    return f"{m.group(1)} rate" if m else ""

def claim_from_note(row, note):
    low = str(note or "").lower()
    mot = infer_motorizzazione(row, note)
    claims = []

    if "finanziamento" in low or "ca auto bank" in low:
        claims.append("finanziamento")
    if "canoni mensili" in low or "valore riscatto" in low:
        claims.append("leasing finanziario")
    if "prezzo promo" in low:
        claims.append("prezzo promo")
    if "permuta" in low:
        claims.append("permuta")
    if "rottamazione" in low:
        claims.append("rottamazione")
    if "dealer aderenti" in low:
        claims.append("dealer aderenti")
    if "ca auto bank" in low:
        claims.append("CA Auto Bank")
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
    note = normalize_legal(old_row.get("Note Legali", ""))

    anticipo = extract_money(note, [
        r"Anticipo\s*([\d\.,]+)\s*€",
        r"Anticipo\s*€\s*([\d\.,]+)",
    ])

    vfg = extract_money(note, [
        r"Rata\s+Finale\s+Residua(?:\s*\([^)]*\))?\s*([0-9\.]+)",
        r"Maxi\s+Rata\s*([0-9\.]+)",
        r"Valore\s+Riscatto\s*([0-9\.]+)",
    ])

    credito = extract_money(note, [
        r"Importo\s+Totale\s+del\s+Credito\s+([\d\.,]+)\s*€",
        r"Importo\s+Totale\s+del\s+Credito\s*€\s*([\d\.,]+)",
    ])

    dovuto = extract_money(note, [
        r"Importo\s+Totale\s+Dovuto\s*\(escluso\s+anticipo\)\s*([\d\.,]+)\s*€",
        r"Importo\s+Totale\s+Dovuto\s+([\d\.,]+)\s*€",
        r"Importo\s+Totale\s+Dovuto\s*€\s*([\d\.,]+)",
        r"Importo\s+Totale\s+Dovuto[^\\d]{0,80}([\d\.,]+)\s*€",
    ])

    mot = infer_motorizzazione(old_row, note)

    tech = ["source=detail_legal"]
    if "canoni mensili" in note.lower() or "valore riscatto" in note.lower():
        tech.append("leasing_finanziario_ca_bank")
    else:
        tech.append("finanziamento_ca_bank")

    rc = extract_rate_count(note)
    if rc:
        tech.append(rc)

    row = {
        "Brand": old_row.get("Brand",""),
        "Modello": old_row.get("Modello",""),
        "Motorizzazione": mot,
        "Titolo Promo": old_row.get("Titolo Promo",""),
        "Claim Promo": claim_from_note(old_row, note),
        "Rata": old_row.get("Rata",""),
        "Intero": extract_intero(old_row, note),
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
    run_id = "omodajaecoo_v2_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    old_rows = omodajaecoo_to_sheet.build_rows()
    rows = []
    bad = []

    print("RIGHE OMODA/JAECOO OLD:", len(old_rows))

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
            "richiedi maggiori informazioni",
            "richiedi informazioni",
            "informativa sulla privacy",
            "datalayer",
            "window.",
            "leasing operativo",
            "noleggio",
        ]

        for x in hard_bad:
            if x in low_note:
                flags.append("dirty_" + x)

        # "canone" qui è leasing finanziario CA Auto Bank, non noleggio operativo.
        # "rent" è falso positivo dentro parole come precontrattuale/Trasparenza.
        if len(r["Note Legali"]) < 700:
            flags.append("note_short")

        print(
            f"{i}/{len(old_rows)} | {r['Brand']} | {r['Modello']} | {r['Motorizzazione']} | {r['Titolo Promo']} | "
            f"{r['Claim Promo']} | {r['Rata']} | {r['Intero']} | {r['Anticipo']} | "
            f"{r['Rata Finale / VFG']} | {r['Importo Totale Credito']} | {r['Importo Totale Dovuto']} | "
            f"{r['TAN (%)']} | {r['TAEG (%)']} | {r['Scadenza']} | {r['Note Tecniche']} | FLAGS: {flags}"
        )

        if flags:
            bad.append((r["Brand"], r["Titolo Promo"], flags))

        rows.append(r)

    print("RIGHE OMODA/JAECOO:", len(rows))
    print("BAD:", bad)

    from collections import Counter
    print("CONTEGGIO BRAND:", Counter([r.get("Brand") for r in rows]))

    print("DEBUG ONLY: nessun push su Google Sheet")
    return rows

if __name__ == "__main__":
    build_rows()
