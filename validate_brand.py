import re
import sys
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID="1okKJrFrLMRXHaZsGUpiJICroVpxLm3wsF22X2o1WXfo"
BRAND=sys.argv[1] if len(sys.argv)>1 else "Citroen"

def euro_to_int(v):
    if not v:
        return None
    m=re.search(r"\d[\d\.]*", str(v))
    if not m:
        return None
    try:
        return int(m.group(0).replace(".",""))
    except:
        return None

creds=Credentials.from_service_account_file("/tmp/key.json", scopes=[
"https://www.googleapis.com/auth/spreadsheets",
"https://www.googleapis.com/auth/drive"
])

gc=gspread.authorize(creds)
rows=gc.open_by_key(SPREADSHEET_ID).worksheet("Promo_Output").get_all_records()

brand_rows=[r for r in rows if str(r.get("Brand","")).strip().lower()==BRAND.lower()]
errors=[]

if not brand_rows:
    errors.append("Nessuna riga trovata")

for i,r in enumerate(brand_rows, start=1):
    label=f"{i} | {r.get('Modello','')} | {r.get('Titolo Promo','')}"
    note=str(r.get("Note Legali",""))
    tecn=str(r.get("Note Tecniche",""))
    offer=str(r.get("Offer URL",""))

    required = ["Modello","Motorizzazione","Titolo Promo","Rata","Intero","TAN (%)","TAEG (%)","Scadenza","Note Legali","Anticipo"]
    for col in required:
        if not str(r.get(col,"")).strip():
            errors.append(f"{label} | missing {col}")

    if "DETTAGLIO PROMOZIONE" not in note.upper():
        errors.append(f"{label} | nota legale non estesa")

    if "source=detail_legal" not in tecn:
        errors.append(f"{label} | source non detail_legal")

    if BRAND.lower()=="citroen":
        if "finanziamento" not in offer.lower():
            errors.append(f"{label} | Offer URL non finanziamento")

    vfg=euro_to_int(r.get("Rata Finale / VFG",""))
    if vfg is not None and vfg < 100:
        errors.append(f"{label} | VFG sospetto: {r.get('Rata Finale / VFG')}")

    if "Consumo" not in note and "CONSUMO" not in note:
        errors.append(f"{label} | consumi non trovati in nota")

    if "\\1" in note:
        errors.append(f"{label} | nota contiene \\1 letterale")

    if ("Consumo" in note or "CONSUMO" in note) and ("\\n\\nConsumo" not in repr(note) and "\\n\\nCONSUMO" not in repr(note)):
        errors.append(f"{label} | consumi presenti ma non separati con riga vuota")

print("BRAND:", BRAND)
print("RIGHE:", len(brand_rows))
print("ERRORI:", len(errors))

if errors:
    print("\n".join(errors[:100]))
    raise SystemExit(1)

print("VALIDAZIONE OK")
