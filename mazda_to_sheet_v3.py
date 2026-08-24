from datetime import datetime
import re
import hashlib

import mazda_to_sheet_v2
from promo_common import HEADERS, clean

BRAND = "Mazda"
HUB = "https://www.mazda.it/offerte/offerte-privati/"
MIN_EXPECTED_ROWS = 9

def normalize_legal(note):
    note = clean(note or "")
    note = note.replace("�", "")

    # Taglia blocchi non pertinenti a noleggio/rent/Arval o footnote commerciali extra.
    cut_patterns = [
        r"\bMAZDA RENT OFFERTA PRIVATI\b",
        r"\bARVAL SERVICE LEASE ITALIA\b",
        r"\bCanone Totale\b",
        r"\bRimpatrio veicolo\b",
        r"\bAssicurazione RCA\b",
        r"\bInfortunio conducente\b",
        r"\bAddebito premio Infortunio conducente\b",
        r"\*Gli importi indicati si intendono IVA inclusa",
        r"\*\*\*\s*salvo condizioni e limitazioni",
        r"\bSalvo condizioni e limitazioni indicate da contratto; chilometraggio annuale",
        r"\bTutti i prezzi riportati sono in",
        r"\n\s*\d+\s+Salvo condizioni e limitazioni indicate da contratto",
    ]

    for pat in cut_patterns:
        m = re.search(pat, note, re.I)
        if m:
            note = note[:m.start()].strip()

    # Se la nota ha un blocco WLTP/consumi lo lasciamo, ma rimuoviamo sporcizia finale e spazi.
    note = re.sub(r"\n\s*\n+", "\n\n", note)
    note = re.sub(r"[ \t]+", " ", note)
    note = re.sub(r"\s+([,.;:])", r"\1", note)
    note = re.sub(r",\s*,", ",", note)
    note = re.sub(r"\s+", " ", note).strip()
    # Rimuove footnote numeriche residue a fine nota: " ... Bank. 1"
    note = re.sub(r"\s+\d+\s*$", "", note).strip()
    return note

def euro_from_raw(x):
    x = str(x or "").strip()
    if not x:
        return ""
    x = x.replace("€", "").strip()
    x = x.split(",")[0] if "," in x else x
    return "€ " + x

def extract_oldtech_money(old_row, key):
    text = str(old_row.get("Note Tecniche", "") or "")
    patterns = {
        "anticipo": r"anticipo\s*€\s*([\d\.,]+)",
        "vfg": r"rata_finale\s*€\s*([\d\.,]+)",
        "credito": r"importo_totale_credito\s*€\s*([\d\.,]+)",
        "dovuto": r"importo_totale_dovuto\s*€\s*([\d\.,]+)",
    }
    pat = patterns.get(key)
    if not pat:
        return ""
    m = re.search(pat, text, re.I)
    if not m:
        return ""
    return euro_from_raw(m.group(1))

def extract_rate_count(old_row, note):
    text = str(old_row.get("Note Tecniche", "") or "") + " " + str(note or "")
    m = re.search(r"(\d+)\s+rate", text, re.I)
    return f"{m.group(1)} rate" if m else ""

def claim_from_row_note(old_row, note):
    low = str(note or "").lower()
    title = str(old_row.get("Titolo Promo","")).lower()
    claims = []

    if "mazda advantage" in low:
        claims.append("Mazda Advantage")
    if "cash plan" in low:
        claims.append("Cash Plan")
    if "finanziamento" in low or old_row.get("Rata"):
        claims.append("finanziamento")
    if "prezzo promo" in low or "prezzo promozionale" in low:
        claims.append("prezzo promo")
    if "qualsiasi usato" in low:
        claims.append("qualsiasi usato")
    if "permuta" in low:
        claims.append("permuta")
    if "rottamazione" in low:
        claims.append("rottamazione")
    if "stock" in low:
        claims.append("stock")
    if "hybrid" in title or "mhev" in low or "m-hybrid" in low:
        claims.append("hybrid")
    if "elettrica" in str(old_row.get("Motorizzazione","")).lower():
        claims.append("elettrica")
    if "plug-in" in str(old_row.get("Motorizzazione","")).lower():
        claims.append("plug-in")
    if "dealers aderenti" in low:
        claims.append("dealers aderenti")

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

    tech = ["source=detail_legal", "finanziamento_mazda"]
    rc = extract_rate_count(old_row, note)
    if rc:
        tech.append(rc)

    row = {
        "Brand": BRAND,
        "Modello": old_row.get("Modello",""),
        "Motorizzazione": old_row.get("Motorizzazione",""),
        "Titolo Promo": old_row.get("Titolo Promo",""),
        "Claim Promo": claim_from_row_note(old_row, note),
        "Rata": old_row.get("Rata",""),
        "Intero": old_row.get("Intero",""),
        "Anticipo": extract_oldtech_money(old_row, "anticipo"),
        "Rata Finale / VFG": extract_oldtech_money(old_row, "vfg"),
        "Importo Totale Credito": extract_oldtech_money(old_row, "credito"),
        "Importo Totale Dovuto": extract_oldtech_money(old_row, "dovuto"),
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
    run_id = "mazda_v3_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    old_rows = mazda_to_sheet_v2.build_rows()
    rows = []
    bad = []

    print("RIGHE MAZDA OLD:", len(old_rows))

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
        hard_bad = ["arval service lease", "canone totale", "rimpatrio veicolo", "richiedi informazioni", "dataLayer", "window."]
        for x in hard_bad:
            if x.lower() in low_note:
                flags.append("dirty_" + x)

        # La parola Santander contiene "rent": non è noleggio. Quindi NON flaggare rent.
        if "noleggio" in low_note:
            flags.append("possible_noleggio")

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

    rows = [
        r for r in rows
        if not (
            str(r.get("Titolo Promo", "")).strip().upper() in ["MAZDA CX-60", "MAZDA CX-80", "MAZDA3 SEDAN"]
            and not str(r.get("Rata", "")).strip()
            and not str(r.get("Intero", "")).strip()
            and not str(r.get("TAN (%)", "")).strip()
            and not str(r.get("TAEG (%)", "")).strip()
        )
    ]

    print("RIGHE MAZDA:", len(rows))
    print("BAD:", bad)
    print("DEBUG ONLY: nessun push su Google Sheet")
    return rows

if __name__ == "__main__":
    build_rows()
