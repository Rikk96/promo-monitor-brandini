import subprocess
import time
from datetime import datetime

SCRIPTS = [
    "ds_to_sheet.py",
    "abarth_to_sheet.py",
    "leapmotor_to_sheet.py",
    "mg_to_sheet.py",
    "omodajaecoo_to_sheet.py",
    "hyundai_to_sheet.py",
    "honda_to_sheet.py",
    "mazda_to_sheet_v2.py",
    "bmw_to_sheet.py",
]

print("START:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

for script in SCRIPTS:
    print("\n" + "="*100)
    print("RUN:", script)
    t0 = time.time()

    try:
        res = subprocess.run(
            ["python3", script],
            text=True,
            capture_output=True,
            timeout=900
        )
        print(res.stdout)
        if res.stderr:
            print("STDERR:")
            print(res.stderr)
        print("EXIT CODE:", res.returncode)
    except subprocess.TimeoutExpired:
        print("TIMEOUT:", script)

    print("DURATA:", round(time.time() - t0, 1), "sec")

print("\nEND:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
