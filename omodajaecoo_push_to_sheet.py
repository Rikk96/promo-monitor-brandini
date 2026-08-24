import gspread
from google.oauth2.service_account import Credentials

from promo_common import HEADERS
from omodajaecoo_to_sheet_v2 import build_rows, MIN_EXPECTED_ROWS

SPREADSHEET_ID = "1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
KEY_PATH = "/tmp/key.json"

BRANDS = ["Omoda", "Jaecoo", "Omoda & Jaecoo"]

def safe_cell_value(v):
    v = "" if v is None else str(v)
    if len(v) > 49000:
        return v[:49000] + " ... [TRONCATO PER LIMITE GOOGLE SHEETS]"
    return v

rows = build_rows()
errors = []

print()
print("RIGHE OMODA/JAECOO:", len(rows))

if len(rows) < MIN_EXPECTED_ROWS:
    raise SystemExit(f"STOP: attese almeno {MIN_EXPECTED_ROWS} righe Omoda/Jaecoo, trovate {len(rows)}. Nessun push eseguito.")

if len(rows) > MIN_EXPECTED_ROWS:
    print(f"ATTENZIONE: nuove offerte Omoda/Jaecoo trovate: {len(rows)} invece di baseline {MIN_EXPECTED_ROWS}. Push consentito.")

brand_counts = {}
for r in rows:
    brand_counts[r.get("Brand", "")] = brand_counts.get(r.get("Brand", ""), 0) + 1

print("CONTEGGIO BRAND:", brand_counts)

if brand_counts.get("Omoda", 0) < 5:
    errors.append(f"Omoda sotto baseline: {brand_counts.get('Omoda', 0)}")
if brand_counts.get("Jaecoo", 0) < 6:
    errors.append(f"Jaecoo sotto baseline: {brand_counts.get('Jaecoo', 0)}")

for i, r in enumerate(rows, start=1):
    required = [
        "Brand","Modello","Motorizzazione","Titolo Promo","Claim Promo",
        "Rata","Intero","Anticipo","Rata Finale / VFG",
        "Importo Totale Credito","Importo Totale Dovuto",
        "TAN (%)","TAEG (%)","Scadenza","Note Legali",
        "Fonte URL","Offer URL","Legal Source Status","Note Tecniche"
    ]

    for col in required:
        if not str(r.get(col, "")).strip():
            errors.append(f"{i} missing {col}: {r.get('Brand')} | {r.get('Titolo Promo')}")

    low_note = str(r.get("Note Legali","")).lower()
    low_tech = str(r.get("Note Tecniche","")).lower()

    forbidden = [
        "richiedi maggiori informazioni",
        "richiedi informazioni",
        "informativa sulla privacy",
        "datalayer",
        "window.",
        "leasing operativo",
        "noleggio",
    ]

    for x in forbidden:
        if x in low_note or x in low_tech:
            errors.append(f"{i} forbidden {x}: {r.get('Brand')} | {r.get('Titolo Promo')}")

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
kept = [r for r in existing if str(r.get("Brand", "")).strip() not in BRANDS]
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

print("PUSH COMPLETATO: righe Omoda/Jaecoo scritte:", len(rows))
