from datetime import datetime
import re
import hashlib

import mg_to_sheet
from promo_common import HEADERS, clean

BRAND = "MG"
HUB = "https://www.mgmotor.it/campaign"
MIN_EXPECTED_ROWS = 9

def normalize_legal(note):
    note = clean(note or "")
    note = note.replace("�", "")

    cut_patterns = [
        r"\bRichiedi maggiori informazioni\b",
        r"\bRichiedi Informazioni\b",
        r"\bNome \*\b",
        r"\bCognome \*\b",
        r"\bIndirizzo e-mail \*\b",
        r"\bLe informazioni sul nostro trattamento dei dati personali\b",
        r"\bInvia\s*\* Campo obbligatorio\b",
    ]

    for pat in cut_patterns:
        m = re.search(pat, note, re.I)
        if m:
            note = note[:m.start()].strip()

    note = re.sub(r"\n\s*\n+", "\n\n", note)
    note = re.sub(r"[ \t]+", " ", note)
    note = re.sub(r"\s+([,.;:])", r"\1", note)
    note = re.sub(r'""+', '"', note)
    note = re.sub(r"\s+", " ", note).strip()

    # Caso MG3 benzina: il sito può duplicare la nota finanziaria dopo "CONSUMI ED EMISSIONI".
    # Se dopo CONSUMI riparte una nota finanziaria invece di valori WLTP, tagliamo da lì.
    if "MG MG3 1.5 Standard Prezzo di listino" in note and "CONSUMI ED EMISSIONI" in note:
        note = note.split("CONSUMI ED EMISSIONI")[0].strip()

    # Normalizza doppi apici/apostrofi residui.
    note = note.replace("L''assicurazione", "L'assicurazione")
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

def extract_rate_count(note):
    m = re.search(r"(\d+)\s+rate", str(note or ""), re.I)
    return f"{m.group(1)} rate" if m else ""

def claim_from_note(row, note):
    low = str(note or "").lower()
    title = str(row.get("Titolo Promo", "")).lower()
    mot = str(row.get("Motorizzazione", "")).lower()
    claims = []

    if "finanziamento" in low or row.get("Rata"):
        claims.append("finanziamento")
    if "prezzo promo" in low or "prezzo promozionale" in low:
        claims.append("prezzo promo")
    if "permuta" in low:
        claims.append("permuta")
    if "rottamazione" in low:
        claims.append("rottamazione")
    if "dealers aderenti" in low:
        claims.append("dealers aderenti")
    if "santander" in low:
        claims.append("Santander")
    if "hybrid" in title or "hybrid" in mot:
        claims.append("hybrid")
    if "plug-in" in mot or "phev" in title:
        claims.append("plug-in")
    if "elettrica" in mot or "ev" in title:
        claims.append("elettrica")

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
        r"anticipo\s*€\s*([\d\.,]+)",
        r"Anticipo:\s*€\s*([\d\.,]+)",
    ])

    credito = extract_money(note, [
        r"importo\s+totale\s+del\s+credito\s*€\s*([\d\.,]+)",
    ])

    vfg = extract_money(note, [
        r"VFG\s+pari\s+alla\s+maxi\s+rata\s+finale\s+di\s*€\s*([\d\.,]+)",
        r"maxi\s+rata\s+finale\s+di\s*€\s*([\d\.,]+)",
        r"rata_finale\s*€\s*([\d\.,]+)",
    ])

    dovuto = extract_money(note, [
        r"importo\s+totale\s+dovuto\s+dal\s+consumatore\s*€\s*(\d{1,3}(?:\.\d{3})*(?:,\d+)?)",
        r"importo_totale_dovuto\s*€\s*([\d\.,]+)",
    ])

    tech = ["source=detail_legal", "finanziamento_mg"]
    rc = extract_rate_count(note)
    if rc:
        tech.append(rc)

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
    run_id = "mg_v2_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    old_rows = mg_to_sheet.build_rows()
    rows = []
    bad = []

    print("RIGHE MG OLD:", len(old_rows))

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
            "informativa sulla privacy",
            "dataLayer",
            "window.",
            "leasing operativo",
            "canone",
            "noleggio",
        ]

        for x in hard_bad:
            if x.lower() in low_note:
                flags.append("dirty_" + x)

        # Santander contiene "rent": non è noleggio, quindi non è dirty.
        if len(r["Note Legali"]) < 900:
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

    print("RIGHE MG:", len(rows))
    print("BAD:", bad)
    print("DEBUG ONLY: nessun push su Google Sheet")
    return rows

if __name__ == "__main__":
    build_rows()
