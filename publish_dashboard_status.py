import fcntl
import json
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOCK_PATH = BASE_DIR / ".dashboard_publish.lock"
STATUS_PATH = BASE_DIR / "dashboard" / "status.json"


def run(command, check=True):
    result = subprocess.run(
        command,
        cwd=BASE_DIR,
        text=True,
        capture_output=True,
        timeout=180,
    )

    if result.stdout:
        print(result.stdout.strip())

    if result.stderr:
        print(result.stderr.strip())

    if check and result.returncode != 0:
        raise RuntimeError(
            f"Comando fallito ({result.returncode}): {' '.join(command)}"
        )

    return result


def main():
    with LOCK_PATH.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)

        run(["git", "pull", "--rebase", "origin", "main"])
        run(["python3", "build_dashboard_status.py"])
        run(["git", "add", "dashboard/status.json"])

        diff = run(
            ["git", "diff", "--cached", "--quiet"],
            check=False,
        )

        if diff.returncode == 0:
            print("Dashboard invariata: nessun commit")
            return

        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        run([
            "git",
            "commit",
            "-m",
            f"Dashboard: aggiorna run {data['run_id']}",
        ])
        run(["git", "push", "origin", "main"])

        print("Dashboard pubblicata correttamente")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Non altera l'esito del monitor originale.
        print(f"DASHBOARD PUBLISH ERROR: {error}")
