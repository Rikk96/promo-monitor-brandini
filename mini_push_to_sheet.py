import gspread
from google.oauth2.service_account import Credentials

from promo_common import HEADERS
from mini_to_sheet_v1 import build_rows, BRAND, MIN_EXPECTED_ROWS

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
print("RIGHE MINI:", len(rows))

if len(rows) < MIN_EXPECTED_ROWS:
    raise SystemExit(f"STOP: attese almeno {MIN_EXPECTED_ROWS} righe MINI, trovate {len(rows)}. Nessun push eseguito.")

if len(rows) > MIN_EXPECTED_ROWS:
    print(f"ATTENZIONE: nuove offerte MINI trovate: {len(rows)} invece di baseline {MIN_EXPECTED_ROWS}. Push consentito.")

FINANCIAL_FIELDS = ["Rata","Anticipo","Rata Finale / VFG","Importo Totale Credito","Importo Totale Dovuto","TAN (%)","TAEG (%)"]

for i, r in enumerate(rows, start=1):
    is_card_only = r.get("Legal Source Status") == "card_only_no_legal"

    base_required = [
        "Brand","Modello","Motorizzazione","Titolo Promo","Claim Promo",
        "Intero","Note Legali",
        "Fonte URL","Offer URL","Legal Source Status","Note Tecniche"
    ]

    for col in base_required:
        if not str(r.get(col, "")).strip():
            errors.append(f"{i} missing {col}: {r.get('Titolo Promo')}")

    if is_card_only:
        for col in FINANCIAL_FIELDS:
            if str(r.get(col, "")).strip():
                errors.append(f"{i} unexpected {col} on card_only_no_legal row: {r.get('Titolo Promo')}")
    else:
        for col in FINANCIAL_FIELDS + ["Scadenza"]:
            if not str(r.get(col, "")).strip():
                errors.append(f"{i} missing {col}: {r.get('Titolo Promo')}")

    low_note = str(r.get("Note Legali","")).lower()
    low_tech = str(r.get("Note Tecniche","")).lower()

    forbidden = [
        "noleggio a lungo termine",
        "leasing operativo",
        "datalayer",
        "window.",
        "cookiebanner",
    ]

    for x in forbidden:
        if x in low_note or x in low_tech:
            errors.append(f"{i} forbidden {x}: {r.get('Titolo Promo')}")

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

print("PUSH COMPLETATO: righe MINI scritte:", len(rows))
