import gspread
from google.oauth2.service_account import Credentials

from promo_common import HEADERS
from nissan_to_sheet_v2 import build_rows, BRAND, MIN_EXPECTED_ROWS

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"

def safe_cell_value(v):
    v = "" if v is None else str(v)
    if len(v) > 49000:
        return v[:49000] + " ... [TRONCATO PER LIMITE GOOGLE SHEETS]"
    return v

rows = build_rows()
errors = []

print()
print("RIGHE NISSAN:", len(rows))

if len(rows) < MIN_EXPECTED_ROWS:
    raise SystemExit(f"STOP: attese almeno {MIN_EXPECTED_ROWS} righe Nissan, trovate {len(rows)}. Nessun push eseguito.")

if len(rows) > MIN_EXPECTED_ROWS:
    print(f"ATTENZIONE: nuove offerte Nissan trovate: {len(rows)} invece di baseline {MIN_EXPECTED_ROWS}. Push consentito.")

for i, r in enumerate(rows, start=1):
    required_base = [
        "Brand", "Modello", "Titolo Promo", "Claim Promo", "Scadenza",
        "Note Legali", "Fonte URL", "Offer URL", "Legal Source Status", "Note Tecniche"
    ]

    for col in required_base:
        if not str(r.get(col, "")).strip():
            errors.append(f"{i} missing {col}: {r.get('Titolo Promo')}")

    tech = str(r.get("Note Tecniche", ""))

    if "finanziamento_intelligent_buy" in tech:
        for col in [
            "Rata", "Intero", "Anticipo", "Rata Finale / VFG",
            "Importo Totale Credito", "Importo Totale Dovuto",
            "TAN (%)", "TAEG (%)"
        ]:
            if not str(r.get(col, "")).strip():
                errors.append(f"{i} missing {col} finanziamento: {r.get('Titolo Promo')}")

    elif "prezzo_secco_incentivi" in tech:
        if not str(r.get("Intero", "")).strip():
            errors.append(f"{i} missing Intero prezzo secco: {r.get('Titolo Promo')}")

    elif "noleggio" in tech:
        errors.append(f"{i} noleggio non ammesso: {r.get('Titolo Promo')}")

if errors:
    print("ERRORI:", len(errors))
    for e in errors:
        print("ERRORE:", e)
    raise SystemExit("STOP: errori presenti, nessun push eseguito.")

creds = Credentials.from_service_account_file(KEY_PATH, scopes=[
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
])

gc = gspread.authorize(creds)
ws = gc.open_by_key(SPREADSHEET_ID).worksheet("Promo_Output")

existing = ws.get_all_records()
kept = [r for r in existing if str(r.get("Brand", "")).strip().lower() != BRAND.lower()]
final_rows = kept + rows

values = [HEADERS] + [[safe_cell_value(r.get(h, "")) for h in HEADERS] for r in final_rows]

too_long = []
for ri, row in enumerate(values, start=1):
    for ci, cell in enumerate(row, start=1):
        if len(str(cell)) > 50000:
            too_long.append((ri, ci, len(str(cell))))

if too_long:
    raise SystemExit(f"STOP: celle oltre 50k prima del clear: {too_long[:10]}")

ws.clear()
ws.update("A1", values)
ws.format("A:AA", {"wrapStrategy": "WRAP"})

print("PUSH COMPLETATO: righe Nissan scritte:", len(rows))
