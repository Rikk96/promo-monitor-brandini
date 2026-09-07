import re
import hashlib
import time
import random
from datetime import datetime
from gspread.exceptions import APIError

HEADERS = [
    "Brand",
    "Modello",
    "Motorizzazione",
    "Titolo Promo",
    "Claim Promo",
    "Rata",
    "Intero",
    "TAN (%)",
    "TAEG (%)",
    "Scadenza",
    "Note Legali",
    "Anticipo",
    "Rata Finale / VFG",
    "Importo Totale Credito",
    "Importo Totale Dovuto",
    "Fonte URL",
    "Offer URL",
    "Data Aggiornamento",
    "Data Scansione",
    "Last Seen",
    "Stato",
    "Alert Type",
    "Promo Hash",
    "Extraction Confidence",
    "Run ID",
    "Legal Source Status",
    "Note Tecniche",
]

MONTHS_IT = {
    "gennaio": "01",
    "febbraio": "02",
    "marzo": "03",
    "aprile": "04",
    "maggio": "05",
    "giugno": "06",
    "luglio": "07",
    "agosto": "08",
    "settembre": "09",
    "ottobre": "10",
    "novembre": "11",
    "dicembre": "12",
}

def clean(text):
    text = re.sub(r"\s+", " ", text or "").strip()

    # Residui finali accordion/form dei siti Stellantis.
    text = re.sub(r"\s+Nota\s+legale\s+e\s+consumi\s*$", "", text, flags=re.I)
    text = re.sub(r"\s+Scegli\s+il\s+tuo\s+modello\s+preferito\s*$", "", text, flags=re.I)

    # Format fisso note legali: separa il blocco consumi/emissioni dal blocco finanziario.
    text = re.sub(r"\s+(CONSUMO:)", "\n\nCONSUMO:", text, flags=re.I)
    text = re.sub(r"\s+(Consumo\s+di\s+carburante)", "\n\nConsumo di carburante", text, flags=re.I)
    text = re.sub(r"\s+(Consumo\s+elettrico)", "\n\nConsumo elettrico", text, flags=re.I)
    text = re.sub(r"\s+(Consumo\s+di\s+energia\s+elettrica)", "\n\nConsumo di energia elettrica", text, flags=re.I)
    text = re.sub(r"\s+(Consumo\s+di\s+energia)", "\n\nConsumo di energia", text, flags=re.I)
    text = re.sub(r"\s+(Emissioni\s+CO2)", "\n\nEmissioni CO2", text, flags=re.I)

    text = text.replace(". Consumo elettrico", ".\n\nConsumo elettrico")
    text = text.replace(". Consumo di energia elettrica", ".\n\nConsumo di energia elettrica")
    text = text.replace(". Consumo di energia", ".\n\nConsumo di energia")
    text = text.replace(". Consumo di carburante", ".\n\nConsumo di carburante")

    return text.strip()

def parse_num(value):
    if value is None:
        return None
    value = str(value).replace("€", "").strip()

    # Prende numeri italiani robusti:
    # 5.650
    # 8.253,30
    # 8253,3
    # 15475,7
    # 0
    matches = re.findall(r"\d+(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?", value)
    if not matches:
        return None

    # usa il match più lungo, così evita di prendere solo "825" da "8253,3"
    raw = max(matches, key=len)
    raw = raw.replace(".", "").replace(",", ".")

    try:
        return float(raw)
    except Exception:
        return None

def euro(value):
    n = parse_num(value)
    if n is None:
        return ""
    return "€ " + f"{int(round(n)):,}".replace(",", ".")

def perc(value):
    if value is None or value == "":
        return ""
    return str(value).replace(".", ",").replace("%", "").strip() + "%"

def find1(patterns, text):
    for pat in patterns:
        m = re.search(pat, text or "", re.I | re.S)
        if m:
            return m.group(1)
    return ""

def extract_rata(legal):
    return find1([
        r"n[°º]?\s*\d+\s+rate\s+da\s*([\d\.,]+)\s*€",
        r"n[°º]?\s*\d+\s+canoni\s+mensili\s+da\s*([\d\.,]+)\s*€",
        r"n[°º]?\s*\d+\s+canoni\s+da\s*([\d\.,]+)\s*€",
        r"\d+\s+rate\s+mensili\s+da\s*([\d\.,]+)\s*€",
        r"\d+\s+canoni\s+mensili\s+da\s*([\d\.,]+)\s*€",
        r"rate\s+da\s*([\d\.,]+)\s*€",
        r"canoni\s+mensili\s+da\s*([\d\.,]+)\s*€",
        r"([\d\.,]+)\s*€\s*al\s+mese",
    ], legal)

def extract_intero_promo(legal):
    # Sempre prezzo promo, non prezzo listino.
    return find1([
        r"Prezzo\s+Promo\s*([\d\.,]+)\s*€",
        r"Prezzo\s+promo\s*([\d\.,]+)\s*€",
        r"Prezzo\s+promozionale\s*([\d\.,]+)\s*€",
        r"Tua\s+da\s*([\d\.,]+)\s*€",
        r"Subito\s+tua\s+da\s*([\d\.,]+)\s*€",
    ], legal)

def extract_anticipo(legal):
    return find1([
        r"Anticipo\s*([\d\.,]+)\s*€",
        r"Primo\s+canone\s+anticipato\s*([\d\.,]+)\s*€",
        r"Primo\s+Canone\s+Anticipato\s*([\d\.,]+)\s*€",
        r"P\s*rimo\s+[Cc]anone\s+[Aa]nticipato\s*([\d\.,]+)\s*€",
    ], legal)

def extract_finale(legal):
    patterns = [
        r"Rata\s+Finale\s+Residua\s*\(pari\s+al\s+Valore\s+Garantito\s+Futuro\)\s*([\d\.,]+)\s*€",
        r"Rata\s+Finale\s+Residua[^\d]{0,80}([\d\.]{1,3}(?:\.\d{3})*(?:,\d+)?|\d{4,}(?:,\d+)?)\s*€",
        r"Valore\s+Garantito\s+Futuro[^\d]{0,80}([\d\.]{1,3}(?:\.\d{3})*(?:,\d+)?|\d{4,}(?:,\d+)?)\s*€",
        r"Valore\s+Futuro\s+Garantito[^\d]{0,80}([\d\.]{1,3}(?:\.\d{3})*(?:,\d+)?|\d{4,}(?:,\d+)?)\s*€",
        r"Valore\s+di\s+riscatto\s*([\d\.]{1,3}(?:\.\d{3})*(?:,\d+)?|\d{4,}(?:,\d+)?)\s*€",
        r"Valore\s+di\s+Riscatto\s*([\d\.]{1,3}(?:\.\d{3})*(?:,\d+)?|\d{4,}(?:,\d+)?)\s*€",
    ]
    return find1(patterns, legal)

def extract_importo_credito(legal):
    return find1([
        r"Importo\s+Totale\s+del\s+Credito\s*([\d\.,]+)\s*€",
        r"Importo\s+totale\s+del\s+credito\s*([\d\.,]+)\s*€",
    ], legal)

def extract_importo_dovuto(legal):
    return find1([
        r"Importo\s+Totale\s+Dovuto\s*([\d\.,]+)\s*€",
        r"Importo\s+totale\s+dovuto[^€]{0,80}€\s*([\d\.,]+)",
        r"Importo\s+totale\s+dovuto\s*([\d\.,]+)\s*€",
    ], legal)

def extract_tan_taeg(legal):
    tan = find1([
        r"TAN\s*\(fisso\)\s*([\d\.,]+)\s*%",
        r"TAN\s*\(Fisso\)\s*([\d\.,]+)\s*%",
        r"TAN\s*([\d\.,]+)\s*%",
        r"T\s*AN\s*\([Ff]isso\)\s*([\d\.,]+)\s*%",
        r"T\s*AN\s*([\d\.,]+)\s*%",
    ], legal)
    taeg = find1([
        r"TAEG\s*([\d\.,]+)\s*%",
    ], legal)
    return perc(tan), perc(taeg)

def extract_scadenza(legal):
    m = re.search(
        r"(?:fino al|entro il|immatricolazioni fino al|valid[ao] fino al|termini di validità|contratti stipulati.*?fino al)\s*(\d{2}/\d{2}/\d{4})",
        legal or "",
        re.I | re.S
    )
    if m:
        return m.group(1)

    m = re.search(
        r"(?:fino al|entro il|immatricolazioni fino al|valid[ao] fino al|termini di validità|contratti stipulati.*?fino al)\s*(\d{1,2})\s+([A-Za-zÀ-ÿ]+?)\s*(\d{4})",
        legal or "",
        re.I | re.S
    )
    if m:
        month = MONTHS_IT.get(m.group(2).lower(), "")
        if month:
            return f"{m.group(1).zfill(2)}/{month}/{m.group(3)}"

    return ""

def is_active(scad):
    if not scad:
        return False
    try:
        return datetime.strptime(scad, "%d/%m/%Y").date() >= datetime.now().date()
    except Exception:
        return False

def promo_hash(row):
    raw = "|".join([
        row.get("Brand", ""),
        row.get("Modello", ""),
        row.get("Titolo Promo", ""),
        row.get("Claim Promo", ""),
        row.get("Rata", ""),
        row.get("Intero", ""),
        row.get("Anticipo", ""),
        row.get("Rata Finale / VFG", ""),
        row.get("TAN (%)", ""),
        row.get("TAEG (%)", ""),
        row.get("Scadenza", ""),
        row.get("Offer URL", ""),
    ])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def legal_status(legal, extended_markers=None):
    if not legal:
        return "missing_legal"
    markers = extended_markers or [
        "DETTAGLIO PROMOZIONE",
        "Importo Totale",
        "Messaggio Pubblicitario",
        "Annuncio pubblicitario",
        "Documentazione precontrattuale",
    ]
    if any(m.lower() in legal.lower() for m in markers):
        return "extended_legal_found"
    return "legal_block_found_not_extended"

def build_row(
    brand,
    modello,
    titolo_promo,
    claim_promo,
    motorizzazione,
    legal,
    fonte_url,
    offer_url,
    run_id,
    note_tecniche_extra=None,
    allow_missing_intero=True,
):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rata_raw = extract_rata(legal)
    intero_raw = extract_intero_promo(legal)
    anticipo_raw = extract_anticipo(legal)
    finale_raw = extract_finale(legal)
    credito_raw = extract_importo_credito(legal)
    dovuto_raw = extract_importo_dovuto(legal)
    tan, taeg = extract_tan_taeg(legal)
    scad = extract_scadenza(legal)

    row = {
        "Brand": brand,
        "Modello": modello,
        "Titolo Promo": titolo_promo,
        "Claim Promo": claim_promo,
        "Motorizzazione": motorizzazione,
        "Rata": euro(rata_raw),
        "Intero": euro(intero_raw),
        "Anticipo": euro(anticipo_raw),
        "Rata Finale / VFG": euro(finale_raw),
        "Importo Totale Credito": euro(credito_raw),
        "Importo Totale Dovuto": euro(dovuto_raw),
        "TAN (%)": tan,
        "TAEG (%)": taeg,
        "Scadenza": scad,
        "Note Legali": clean(legal),
        "Fonte URL": fonte_url,
        "Offer URL": offer_url,
        "Data Aggiornamento": now,
        "Data Scansione": now,
        "Last Seen": now,
        "Stato": "attiva" if is_active(scad) else "scaduta",
        "Alert Type": "",
        "Promo Hash": "",
        "Extraction Confidence": "high",
        "Run ID": run_id,
        "Legal Source Status": legal_status(legal),
        "Note Tecniche": "",
    }

    missing = []
    if not legal:
        missing.append("missing_note_legali")
    if not row["Rata"]:
        missing.append("missing_rata")
    if not row["Intero"] and not allow_missing_intero:
        missing.append("missing_intero")
    if not row["Anticipo"]:
        missing.append("missing_anticipo")
    if not row["TAN (%)"]:
        missing.append("missing_tan")
    if not row["TAEG (%)"]:
        missing.append("missing_taeg")
    if not row["Scadenza"]:
        missing.append("missing_scadenza")

    extras = note_tecniche_extra or []
    row["Note Tecniche"] = "; ".join(extras + missing)

    if missing:
        row["Extraction Confidence"] = "medium"
        if row["Stato"] == "attiva" and any(m in missing for m in ["missing_note_legali", "missing_rata", "missing_tan", "missing_taeg", "missing_scadenza"]):
            row["Stato"] = "incompleta"

    row["Promo Hash"] = promo_hash(row)
    return row

# --- OVERRIDE STANDARD 2026-06-05 ---
# Rata: se la nota contiene rate iniziali a 0€ e poi rate ricorrenti, usare la rata ricorrente non-zero.
def extract_rata(legal):
    matches = re.findall(r"n[°º]?\s*\d+\s+rate\s+da\s*([\d\.,]+)\s*€", legal, flags=re.I)
    if matches:
        non_zero = [m for m in matches if parse_num(m) and parse_num(m) > 0]
        if non_zero:
            return non_zero[-1]
        return matches[-1]

    return find1([
        r"\d+\s+canoni\s+mensili\s+da\s*([\d\.,]+)\s*€",
        r"canoni\s+mensili\s+da\s*([\d\.,]+)\s*€",
        r"rate\s+da\s*([\d\.,]+)\s*€",
        r"da\s*([\d\.,]+)\s*€\s+al\s+mese",
    ], legal)

# Intero: per offerte finanziarie Opel/Scelta Opel, se c'è prezzo "oltre oneri finanziari",
# preferire quello perché è il prezzo promo specifico con finanziamento.
def extract_intero(legal):
    special = find1([
        r"oppure\s*([\d\.,]+)\s*€\s*oltre\s+oneri\s+finanziari",
        r"([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]{4,}(?:,[0-9]+)?)\s*€\s*oltre\s+oneri\s+finanziari",
        r"Prezzo\s+promo\s+oltre\s+oneri\s+finanziari:?\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]{4,}(?:,[0-9]+)?)\s*€",
    ], legal)
    if special:
        return special

    return find1([
        r"promo\s*€\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]{4,}(?:,[0-9]+)?)\s*oppure\s*€\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]{4,}(?:,[0-9]+)?)\s*solo\s+con\s+finanziamento",
        r"promo\s*€\s*[0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?\s*oppure\s*€\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]{4,}(?:,[0-9]+)?)\s*solo\s+con\s+finanziamento",
        r"oppure\s*€\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]{4,}(?:,[0-9]+)?)\s*solo\s+con\s+finanziamento",
        r"Prezzo\s+Promo\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]{4,}(?:,[0-9]+)?)\s*€",
        r"Prezzo\s+promozionale[^\d]{0,80}([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]{4,}(?:,[0-9]+)?)\s*€",
        r"Tua\s+da\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]+)?|[0-9]{4,}(?:,[0-9]+)?)\s*€",
    ], legal)


def with_retry(fn, retries=4, base_delay=3, label="operazione Google Sheets"):
    """Esegue fn() ritentando con backoff esponenziale su errori transitori
    dell'API Google Sheets (503, 500, 502, 504, 429 - rate limit).
    Rilancia subito l'errore se non e' transitorio o se i tentativi finiscono."""
    TRANSIENT_STATUS = {429, 500, 502, 503, 504}
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            return fn()
        except APIError as e:
            status = None
            try:
                status = e.response.status_code
            except Exception:
                pass

            last_error = e

            if status not in TRANSIENT_STATUS or attempt == retries:
                raise

            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1)
            print(f"AVVISO: {label} fallita (tentativo {attempt}/{retries}, status {status}). Retry tra {delay:.1f}s...")
            time.sleep(delay)

    raise last_error
