import re
import gspread
from google.oauth2.service_account import Credentials
from collections import defaultdict, Counter

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
creds = Credentials.from_service_account_file("/tmp/key.json", scopes=[
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
])
gc = gspread.authorize(creds)
sh = gc.open_by_key(SPREADSHEET_ID)

output_records = sh.worksheet("Promo_Output").get_all_records()
config_records = sh.worksheet("Brand_Config").get_all_records()

config_by_brand = {r.get("Brand", "").strip(): r for r in config_records if r.get("Brand", "").strip()}

by_brand = defaultdict(list)
for r in output_records:
    b = str(r.get("Brand", "")).strip()
    if b:
        by_brand[b].append(r)

# Accetta sia "4,99%" che "0%" / "7%" (interi legittimi senza decimali)
PERCENT_OK = re.compile(r"^\d{1,3}(?:,\d{1,3})?%$")
CURRENCY_OK = re.compile(r"^€ [\d\.]+$")
DATE_OK = re.compile(r"^\d{2}/\d{2}/\d{4}$")

FINANCIAL_COLS = ["Rata", "Anticipo", "Rata Finale / VFG", "Importo Totale Credito", "Importo Totale Dovuto"]
PERCENT_COLS = ["TAN (%)", "TAEG (%)"]

CARD_ONLY_STATUSES = {"card_only_no_legal"}
EXTENDED_STATUSES = {"extended_legal_found"}

REQUIRED_ALWAYS = ["Brand", "Modello", "Titolo Promo", "Scadenza", "Note Legali", "Offer URL", "Legal Source Status"]

# Note Tecniche contenenti questi marker = noleggio operativo, TAN/TAEG/Intero legittimamente assenti
NOLEGGIO_MARKERS = ["noleggio_leasys", "tan_taeg_not_applicable"]

total_issues = 0
total_notes = 0
brand_summary = []

print("=" * 110)
print("AUDIT COMPLETO Promo_Output (v2 - falsi positivi corretti)")
print("=" * 110)

for brand in sorted(by_brand.keys()):
    rows = by_brand[brand]
    cfg = config_by_brand.get(brand, {})
    expected_min = cfg.get("Validated Rows", "")

    issues = []
    notes = []

    # Conteggio righe vs baseline storica -> solo NOTA, non issue
    try:
        expected_min_int = int(expected_min)
        if len(rows) < expected_min_int:
            notes.append(f"Nota: righe attuali ({len(rows)}) sotto baseline storica Brand_Config ({expected_min_int}) - normale se il sito ha ridotto le promo, verificare solo se sospetto")
    except (ValueError, TypeError):
        pass

    hashes = [r.get("Promo Hash", "") for r in rows if r.get("Promo Hash", "")]
    dup = [h for h, c in Counter(hashes).items() if c > 1]
    if dup:
        issues.append(f"PROMO HASH DUPLICATI: {len(dup)} hash ripetuti")

    for i, r in enumerate(rows, start=1):
        row_label = f"riga {i} ({r.get('Titolo Promo', '')[:40]})"
        note_tecniche = str(r.get("Note Tecniche", "")).lower()
        is_noleggio = any(m in note_tecniche for m in NOLEGGIO_MARKERS)

        for col in REQUIRED_ALWAYS:
            if not str(r.get(col, "")).strip():
                issues.append(f"{row_label}: campo obbligatorio vuoto: {col}")

        # Intero vuoto: issue normale, ma solo NOTA se e' un noleggio (atteso)
        if not str(r.get("Intero", "")).strip():
            if is_noleggio:
                notes.append(f"{row_label}: Intero vuoto ma e' un noleggio operativo (Note Tecniche lo conferma) - probabilmente atteso, verificare sul sito se serve comunque un valore")
            else:
                issues.append(f"{row_label}: campo obbligatorio vuoto: Intero")

        legal_status = str(r.get("Legal Source Status", "")).strip()

        for col in PERCENT_COLS:
            val = str(r.get(col, "")).strip()
            if val and not PERCENT_OK.match(val):
                issues.append(f"{row_label}: formato {col} sospetto: {val!r} (atteso tipo '4,99%' o '0%')")

        for col in FINANCIAL_COLS + ["Intero"]:
            val = str(r.get(col, "")).strip()
            if val:
                if val.endswith(".") or val.endswith(","):
                    issues.append(f"{row_label}: {col} ha punteggiatura finale residua: {val!r}")
                elif not CURRENCY_OK.match(val):
                    issues.append(f"{row_label}: formato {col} inatteso: {val!r}")

        if legal_status in CARD_ONLY_STATUSES:
            for col in FINANCIAL_COLS + PERCENT_COLS:
                if str(r.get(col, "")).strip():
                    issues.append(f"{row_label}: {col} valorizzato ma Legal Source Status={legal_status} (dovrebbe essere vuoto)")

        # extended_legal_found con TAN/TAEG vuoti: issue solo se NON e' un noleggio noto
        if legal_status in EXTENDED_STATUSES and r.get("Stato") == "attiva" and not is_noleggio:
            for col in PERCENT_COLS:
                if not str(r.get(col, "")).strip():
                    issues.append(f"{row_label}: {col} vuoto nonostante Legal Source Status={legal_status}")

        scad = str(r.get("Scadenza", "")).strip()
        if scad and not DATE_OK.match(scad):
            issues.append(f"{row_label}: formato Scadenza non valido: {scad!r}")

    status_icon = "OK" if not issues else f"{len(issues)} PROBLEMI"
    if notes and not issues:
        status_icon += f" ({len(notes)} note informative)"
    brand_summary.append((brand, len(rows), status_icon))

    if issues or notes:
        total_issues += len(issues)
        total_notes += len(notes)
        print(f"\n--- {brand} ({len(rows)} righe) : {len(issues)} PROBLEMI, {len(notes)} note ---")
        for iss in issues:
            print("  [PROBLEMA]", iss)
        for n in notes:
            print("  [nota]    ", n)

print("\n" + "=" * 110)
print("RIEPILOGO PER BRAND")
print("=" * 110)
for brand, count, status in brand_summary:
    print(f"  {brand:20} | {count:3} righe | {status}")

print("\n" + "=" * 110)
print(f"TOTALE PROBLEMI REALI: {total_issues}")
print(f"TOTALE NOTE INFORMATIVE (non bloccanti): {total_notes}")
print(f"TOTALE BRAND: {len(brand_summary)}")
print(f"TOTALE RIGHE: {sum(c for _, c, _ in brand_summary)}")
print("=" * 110)
