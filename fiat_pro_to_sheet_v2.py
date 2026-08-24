from datetime import datetime
import re

import fiat_pro_to_sheet
from promo_common import HEADERS, clean

BRAND = "Fiat Professional"
HUB = "https://www.fiat.it/professional/offerte"

MIN_EXPECTED_ROWS = 8

def normalize_legal(note):
    note = clean(note or "")
    note = note.replace("�", "")
    note = re.sub(r"\n\s*\n+", "\n\n", note)
    note = re.sub(r"[ \t]+", " ", note)
    note = re.sub(r"\s+([,.;:])", r"\1", note)
    note = re.sub(r"\n\s+\.", "\n.", note)
    note = re.sub(r"\n+\.\s*$", ".", note.strip())
    note = re.sub(r"\s+", " ", note).strip()
    return note

def is_leasys(row):
    note = (row.get("Note Legali") or "").lower()
    title = (row.get("Titolo Promo") or "").lower()
    url = (row.get("Offer URL") or "").lower()

    return (
        "leasys" in note
        or "noleggio" in note
        or "leasys-pro" in url
        or "easy-pro" in url
        or title.startswith("doblo van")
        or title.startswith("scudo van")
        or title.startswith("ducato 30")
    )

def is_evolease(row):
    note = (row.get("Note Legali") or "").lower()
    return "evolease" in note or "leasing finanziario" in note

def active(scadenza):
    try:
        d = datetime.strptime(scadenza, "%d/%m/%Y").date()
        return "attiva" if d >= datetime.now().date() else "scaduta"
    except Exception:
        return ""

def claim_from_note(row, note, leasys=False, evolease=False):
    claims = []
    low = (str(note or "") + " " + str(row.get("Offer URL","")) + " " + str(row.get("Titolo Promo",""))).lower()

    if leasys:
        claims.extend(["noleggio", "Leasys", "partita IVA"])

    if evolease or "evolease" in low or "leasing finanziario" in low:
        claims.append("leasing finanziario")

    if "permuta" in low:
        claims.append("permuta")
    if "rottamazione" in low:
        claims.append("rottamazione")
    if "partita iva" in low or "titolari di partita iva" in low:
        claims.append("partita IVA")
    if "pronta consegna" in low:
        claims.append("pronta consegna")

    return "; ".join(dict.fromkeys(claims))

def clean_duplicate_consumi_fiatpro(note):
    text = str(note or "")

    # Fiat Pro elettriche: a volte il sito mette un blocco consumi inline
    # e poi ripete "CONSUMI ED EMISSIONI". Non dobbiamo tagliare la parte finanziaria.
    # Teniamo la nota completa e, se ci sono due blocchi CONSUMI ED EMISSIONI, teniamo solo il primo.
    first = text.find("CONSUMI ED EMISSIONI")
    if first != -1:
        second = text.find("CONSUMI ED EMISSIONI", first + len("CONSUMI ED EMISSIONI"))
        if second != -1:
            text = text[:second].strip()

    text = re.sub(r"\.\.", ".", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def extract_anticipo_from_old(old_row):
    url = str(old_row.get("Offer URL", "") or "").lower()
    title = str(old_row.get("Titolo Promo", "") or "").lower()

    fixed_leasys = {
        "doblo-ice-leasys-pro": "€ 4.699",
        "fiat-scudo-easy-pro": "€ 5.199",
        "fiat-ducato-easy-pro": "€ 5.499",
    }

    for key, value in fixed_leasys.items():
        if key in url:
            return value

    if title.startswith("doblo van"):
        return "€ 4.699"
    if title.startswith("scudo van m 1.5"):
        return "€ 5.199"
    if title.startswith("ducato 30 l2h1"):
        return "€ 5.499"

    for source in [
        old_row.get("Anticipo", ""),
        old_row.get("Note Tecniche", ""),
        old_row.get("Note Legali", ""),
    ]:
        text = str(source or "")
        m = re.search(r"anticipo\s*€\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})", text, re.I)
        if m:
            return "€ " + m.group(1)

        m = re.search(r"Primo\s+canone\s+anticipato\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})\s*€", text, re.I)
        if m:
            return "€ " + m.group(1)

    return old_row.get("Anticipo", "")

def extract_money_from_note(note, patterns):
    text = str(note or "")
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            value = m.group(1).strip().split(",")[0]
            return "€ " + value
    return ""

def convert_row(old_row, run_id):
    raw_note = normalize_legal(old_row.get("Note Legali", ""))

    # I dati economici vanno estratti dalla nota completa prima di eventuali pulizie sui consumi.
    note_for_values = raw_note

    # La nota finale su Sheet viene pulita da duplicati di consumi/footer.
    note = clean_duplicate_consumi_fiatpro(raw_note)

    leasys = is_leasys(old_row)
    evolease = is_evolease(old_row)

    note_tecniche = ["source=detail_legal"]
    if leasys:
        note_tecniche.append("noleggio_leasys")
        note_tecniche.append("tan_taeg_not_applicable")
    if evolease:
        note_tecniche.append("leasing_finanziario")

    # Mantieni eventuali note tecniche old utili, senza sporcare.
    old_notes = clean(old_row.get("Note Tecniche", ""))
    if old_notes:
        note_tecniche.append(old_notes)

    scad = old_row.get("Scadenza", "")

    rata_finale_vfg = old_row.get("Rata Finale / VFG", "") or extract_money_from_note(note_for_values, [
        r"Valore\s+di\s+riscatto\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})(?:,[0-9]+)?\s*€",
        r"Valore\s+di\s+Riscatto\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})(?:,[0-9]+)?\s*€",
    ])

    importo_credito = old_row.get("Importo Totale Credito", "") or extract_money_from_note(note_for_values, [
        r"Importo\s+Totale\s+del\s+Credito\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})(?:,[0-9]+)?\s*€",
    ])

    importo_dovuto = old_row.get("Importo Totale Dovuto", "") or extract_money_from_note(note_for_values, [
        r"Importo\s+Totale\s+Dovuto\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]{4,})(?:,[0-9]+)?\s*€",
    ])

    return {
        "Brand": BRAND,
        "Modello": old_row.get("Modello", ""),
        "Motorizzazione": old_row.get("Motorizzazione", ""),
        "Titolo Promo": old_row.get("Titolo Promo", ""),
        "Claim Promo": claim_from_note(old_row, note, leasys=leasys, evolease=evolease),
        "Rata": old_row.get("Rata", ""),
        "Intero": old_row.get("Intero", ""),
        "TAN (%)": old_row.get("TAN (%)", ""),
        "TAEG (%)": old_row.get("TAEG (%)", ""),
        "Scadenza": scad,
        "Note Legali": note,
        "Anticipo": extract_anticipo_from_old(old_row),
        "Rata Finale / VFG": rata_finale_vfg,
        "Importo Totale Credito": importo_credito,
        "Importo Totale Dovuto": importo_dovuto,
        "Fonte URL": HUB,
        "Offer URL": old_row.get("Offer URL", ""),
        "Data Aggiornamento": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Data Scansione": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Last Seen": datetime.now().strftime("%Y-%m-%d"),
        "Stato": active(scad),
        "Alert Type": "",
        "Promo Hash": old_row.get("Promo Hash", ""),
        "Extraction Confidence": "high",
        "Run ID": run_id,
        "Legal Source Status": "extended_legal_found",
        "Note Tecniche": "; ".join(dict.fromkeys([x for x in note_tecniche if x])),
    }

def build_rows():
    run_id = "fiat_pro_v2_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    old_rows = fiat_pro_to_sheet.build_rows()
    rows = []

    print("RIGHE FIAT PRO OLD:", len(old_rows))

    for i, old in enumerate(old_rows, start=1):
        r = convert_row(old, run_id)
        rows.append(r)

        print(
            f"{i}/{len(old_rows)} | {r['Modello']} | {r['Motorizzazione']} | {r['Titolo Promo']} | "
            f"{r['Rata']} | {r['Intero']} | {r['Anticipo']} | {r['Rata Finale / VFG']} | "
            f"{r['Importo Totale Credito']} | {r['Importo Totale Dovuto']} | "
            f"{r['TAN (%)']} | {r['TAEG (%)']} | {r['Scadenza']} | "
            f"{r['Legal Source Status']} | {r['Note Tecniche']}"
        )

    print("RIGHE VALIDE:", len(rows))
    print("DEBUG ONLY: nessun push su Google Sheet")
    return rows

if __name__ == "__main__":
    build_rows()
