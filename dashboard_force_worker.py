import ast
import fcntl
import json
import os
import re
import subprocess
import time
from datetime import datetime, time as clock_time, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
COMMAND_PATH = BASE_DIR / "dashboard" / "command.json"
STATUS_PATH = BASE_DIR / "dashboard" / "status.json"
LOCK_PATH = BASE_DIR / ".dashboard_publish.lock"
LOG_DIR = BASE_DIR / "logs"
TIMEOUT_SECONDS = 10 * 60

SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|token|authorization|password|secret)"
    r"(\s*[:=]\s*)(\S+)"
)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(command, check=True, timeout=180):
    result = subprocess.run(
        command,
        cwd=BASE_DIR,
        text=True,
        capture_output=True,
        timeout=timeout,
    )

    if check and result.returncode != 0:
        raise RuntimeError(
            f"Comando fallito ({result.returncode}): {' '.join(command)}\n"
            f"{result.stderr}"
        )

    return result


def configured_scripts():
    tree = ast.parse(
        (BASE_DIR / "run_all_promos.py").read_text(encoding="utf-8")
    )

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue

        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "SCRIPTS":
                scripts = ast.literal_eval(node.value)
                return {
                    script.replace("_push_to_sheet.py", ""): script
                    for script in scripts
                }

    raise RuntimeError("SCRIPTS non trovato")


def scheduled_monitor_active():
    result = run(
        ["systemctl", "is-active", "--quiet", "promo-monitor.service"],
        check=False,
    )
    return result.returncode == 0


def protected_night_window():
    current = datetime.now(timezone.utc).time()
    return clock_time(4, 15) <= current <= clock_time(5, 45)


def ensure_service_account_key():
    key_path = Path("/tmp/key.json")

    if key_path.exists() and key_path.stat().st_size > 500:
        return

    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        name = (
            "projects/brandini-promo-monitor/secrets/"
            "promo-monitor-sa-key/versions/latest"
        )
        payload = client.access_secret_version(
            request={"name": name}
        ).payload.data

        key_path.write_bytes(payload)
        key_path.chmod(0o600)
        return

    except Exception:
        result = run([
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            "--secret",
            "promo-monitor-sa-key",
            "--project",
            "brandini-promo-monitor",
        ])

        key_path.write_text(result.stdout, encoding="utf-8")
        key_path.chmod(0o600)

    if not key_path.exists() or key_path.stat().st_size < 500:
        raise RuntimeError("Service account key non valida")


def redact(text, limit=10000):
    clean = SECRET_PATTERN.sub(r"\1\2[REDACTED]", text)
    return clean[-limit:].strip()


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def publish(paths, message):
    run(["git", "add", *paths])

    diff = run(["git", "diff", "--cached", "--quiet"], check=False)
    if diff.returncode == 0:
        return

    run(["git", "commit", "-m", message])
    run(["git", "push", "origin", "main"])


def update_manual_status(script, result):
    status_data = load_json(STATUS_PATH)

    for item in status_data.get("items", []):
        if item.get("script") == script:
            item["last_manual_run"] = result
            break

    status_data["generated_at"] = now_iso()
    save_json(STATUS_PATH, status_data)


def main():
    LOG_DIR.mkdir(exist_ok=True)

    with LOCK_PATH.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)

        run(["git", "pull", "--rebase", "origin", "main"])

        command = load_json(COMMAND_PATH)
        if command.get("status") != "PENDING":
            return

        if scheduled_monitor_active() or protected_night_window():
            print("Comando lasciato in coda: ciclo notturno attivo o imminente")
            return

        scripts = configured_scripts()
        brand_key = command.get("brand")

        if brand_key not in scripts:
            command.update({
                "status": "REJECTED",
                "finished_at": now_iso(),
                "message": "Brand non autorizzato",
            })
            save_json(COMMAND_PATH, command)
            publish(
                ["dashboard/command.json"],
                "Dashboard: rifiuta comando non valido",
            )
            return

        script = scripts[brand_key]
        command.update({
            "status": "RUNNING",
            "script": script,
            "started_at": now_iso(),
            "message": f"Esecuzione manuale di {script}",
        })
        save_json(COMMAND_PATH, command)
        publish(
            ["dashboard/command.json"],
            f"Dashboard: avvia {brand_key}",
        )

        started = time.monotonic()
        execution_status = "FAIL"
        return_code = None
        output = ""

        try:
            ensure_service_account_key()

            environment = os.environ.copy()
            environment["GOOGLE_APPLICATION_CREDENTIALS"] = "/tmp/key.json"

            result = subprocess.run(
                [str(BASE_DIR / ".venv" / "bin" / "python"), script],
                cwd=BASE_DIR,
                text=True,
                capture_output=True,
                timeout=TIMEOUT_SECONDS,
                env=environment,
            )

            return_code = result.returncode
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            execution_status = "OK" if result.returncode == 0 else "FAIL"

        except subprocess.TimeoutExpired as error:
            execution_status = "TIMEOUT"
            output = (error.stdout or "") + "\n" + (error.stderr or "")

        except Exception as error:
            execution_status = "FAIL"
            output = f"{type(error).__name__}: {error}"

        elapsed = round(time.monotonic() - started, 1)
        finished_at = now_iso()
        excerpt = redact(output)

        log_name = (
            f"manual_{command.get('id', 'unknown')}_"
            f"{script.replace('.py', '')}.log"
        )
        (LOG_DIR / log_name).write_text(output, encoding="utf-8")

        manual_result = {
            "command_id": command.get("id"),
            "status": execution_status,
            "started_at": command["started_at"],
            "finished_at": finished_at,
            "elapsed_seconds": elapsed,
            "return_code": return_code,
            "log_excerpt": excerpt,
        }

        command.update({
            "status": "COMPLETED" if execution_status == "OK" else "FAILED",
            "finished_at": finished_at,
            "elapsed_seconds": elapsed,
            "result": execution_status,
            "return_code": return_code,
            "log_excerpt": excerpt,
            "message": (
                "Esecuzione completata"
                if execution_status == "OK"
                else "Esecuzione terminata con errore"
            ),
        })

        save_json(COMMAND_PATH, command)
        update_manual_status(script, manual_result)

        publish(
            ["dashboard/command.json", "dashboard/status.json"],
            f"Dashboard: risultato manuale {brand_key} {execution_status}",
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"FORCE WORKER ERROR: {error}")
