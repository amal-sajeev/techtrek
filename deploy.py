"""
TechTrek – Deployment Runner
============================
Run this file once to install everything and start the server:

    python deploy.py

The script will:
  1. Check your Python version (3.11+ required)
  2. Install all Python dependencies from requirements.txt
  3. Validate that the required environment variables are set in .env
  4. Apply any pending database migrations (alembic upgrade head)
  5. Start the production web server (uvicorn)

To stop the server press Ctrl+C.

CONFIGURATION
-------------
Copy .env.example to .env and fill in the values before running:

    copy .env.example .env   (Windows)
    cp   .env.example .env   (Linux / Mac)

Required .env keys
  SECRET_KEY           – random hex string, ≥ 32 chars
  DATABASE_URL         – PostgreSQL connection string
  FIELD_ENCRYPTION_KEY – Fernet key for PII encryption

Generate the two secret keys with:

    python -c "import secrets; print(secrets.token_hex(32))"
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Optional .env keys (server tuning)
  HOST     – bind address  (default: 0.0.0.0)
  PORT     – TCP port      (default: 8000)
  WORKERS  – uvicorn worker processes (default: 4)
"""

from __future__ import annotations

import os
import subprocess
import sys


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def _ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET}  {msg}")


def _warn(msg: str) -> None:
    print(f"  {YELLOW}!{RESET}  {msg}")


def _err(msg: str) -> None:
    print(f"\n  {RED}✗  ERROR:{RESET} {msg}\n")


def _header(msg: str) -> None:
    print(f"\n{BOLD}{msg}{RESET}")


def _run(cmd: str, *, capture: bool = False) -> subprocess.CompletedProcess:
    """Run *cmd* in the current shell and return the result."""
    return subprocess.run(
        cmd,
        shell=True,
        capture_output=capture,
    )


def _die(msg: str) -> None:
    _err(msg)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Step 1 – Python version
# ---------------------------------------------------------------------------

def check_python() -> None:
    _header("Step 1 – Python version")
    if sys.version_info < (3, 11):
        _die(f"Python 3.11 or newer is required. You are running {sys.version.split()[0]}.")
    _ok(f"Python {sys.version.split()[0]}")


# ---------------------------------------------------------------------------
# Step 2 – Install dependencies
# ---------------------------------------------------------------------------

def install_deps() -> None:
    _header("Step 2 – Installing dependencies")
    if not os.path.exists("requirements.txt"):
        _die("requirements.txt not found. Make sure you are in the project root directory.")
    result = _run(f'"{sys.executable}" -m pip install -r requirements.txt -q --disable-pip-version-check')
    if result.returncode != 0:
        _die("pip install failed. See the output above for details.")
    _ok("All dependencies installed")


# ---------------------------------------------------------------------------
# Step 3 – Validate environment
# ---------------------------------------------------------------------------

def _patch_env_file(updates: dict[str, str]) -> None:
    """
    Write *updates* (var → value) into .env, replacing existing lines or
    appending them if not present.  Only touches the specified keys; every
    other line is left exactly as-is.
    """
    with open(".env", "r", encoding="utf-8") as fh:
        lines = fh.readlines()

    remaining = dict(updates)  # keys still to be written
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        var = stripped.split("=", 1)[0].strip()
        if var in remaining:
            new_lines.append(f"{var}={remaining.pop(var)}\n")
        else:
            new_lines.append(line)

    # Append any keys that were not already present in the file
    for var, val in remaining.items():
        new_lines.append(f"{var}={val}\n")

    with open(".env", "w", encoding="utf-8") as fh:
        fh.writelines(new_lines)


def check_env() -> None:
    _header("Step 3 – Environment configuration")

    # .env must exist before we can do anything
    if not os.path.exists(".env"):
        _die(
            ".env file not found.\n\n"
            "  Copy .env.example to .env and fill in the required values:\n"
            "    copy .env.example .env   (Windows)\n"
            "    cp   .env.example .env   (Linux/Mac)"
        )

    # dotenv is now installed (step 2 ran pip install).
    from dotenv import load_dotenv  # noqa: PLC0415
    load_dotenv(override=True)      # load from file so we can inspect each value

    _ok(".env loaded")

    import secrets as _secrets
    from cryptography.fernet import Fernet as _Fernet  # noqa: PLC0415

    _PLACEHOLDERS = ("replace_", "your_", "xxxx", "changeme", "<", ">")

    def _is_bad(val: str) -> bool:
        """True if val is empty or looks like placeholder text."""
        if not val.strip():
            return True
        vl = val.lower()
        return any(p in vl for p in _PLACEHOLDERS)

    auto_patches: dict[str, str] = {}   # keys we can generate automatically
    manual_needed: list[str] = []       # keys that need human input

    # ── SECRET_KEY ────────────────────────────────────────────────────────────
    sk = os.environ.get("SECRET_KEY", "")
    if _is_bad(sk) or len(sk) < 32:
        new_sk = _secrets.token_hex(32)
        auto_patches["SECRET_KEY"] = new_sk
        _warn("SECRET_KEY was missing/invalid – a new one has been generated.")

    # ── FIELD_ENCRYPTION_KEY ─────────────────────────────────────────────────
    fek = os.environ.get("FIELD_ENCRYPTION_KEY", "")
    fek_ok = False
    if not _is_bad(fek):
        try:
            _Fernet(fek.encode())
            fek_ok = True
        except Exception:
            pass
    if not fek_ok:
        new_fek = _Fernet.generate_key().decode()
        auto_patches["FIELD_ENCRYPTION_KEY"] = new_fek
        _warn("FIELD_ENCRYPTION_KEY was missing/invalid – a new one has been generated.")

    # ── DATABASE_URL ─────────────────────────────────────────────────────────
    db_url = os.environ.get("DATABASE_URL", "")
    if _is_bad(db_url):
        manual_needed.append(
            "DATABASE_URL  →  e.g. postgresql+psycopg2://user:password@host:5432/techtrek"
        )

    # ── Auto-patch .env for generated keys ───────────────────────────────────
    if auto_patches:
        _patch_env_file(auto_patches)
        print()
        print(f"  {GREEN}✓{RESET}  The following keys were written to .env automatically:")
        for var, val in auto_patches.items():
            print(f"      {YELLOW}{var}{RESET}={val}")
        print()
        print(f"  {BOLD}IMPORTANT – keep these values safe and backed up.{RESET}")
        print(f"  Losing FIELD_ENCRYPTION_KEY makes all encrypted user data unreadable.")
        print()
        # Reload so the rest of this run picks up the new values
        load_dotenv(override=True)

    # ── Still need human input? ───────────────────────────────────────────────
    if manual_needed:
        print()
        print(f"  {RED}The following values still need to be set manually in .env:{RESET}")
        for item in manual_needed:
            print(f"    • {item}")
        print()
        _die("Edit .env with the values above, then run deploy.py again.")

    _ok("All required environment variables are valid")


# ---------------------------------------------------------------------------
# Step 4 – Database migrations
# ---------------------------------------------------------------------------

def run_migrations() -> None:
    _header("Step 4 – Database migrations")
    result = _run("alembic upgrade head")
    if result.returncode != 0:
        _die(
            "alembic upgrade head failed.\n"
            "  Check that DATABASE_URL is correct and the database server is reachable."
        )
    _ok("Database schema is up to date")


# ---------------------------------------------------------------------------
# Step 5 – Start the server
# ---------------------------------------------------------------------------

def start_server() -> None:
    host    = os.environ.get("HOST",    "0.0.0.0")
    port    = os.environ.get("PORT",    "8000")
    workers = os.environ.get("WORKERS", "4")

    _header("Step 5 – Starting TechTrek server")
    print(f"  Listening on  http://{host}:{port}")
    print(f"  Workers       {workers}")
    print(f"  Press Ctrl+C  to stop\n")

    cmd = (
        f'"{sys.executable}" -m uvicorn app.main:app '
        f'--host {host} --port {port} --workers {workers}'
    )
    result = _run(cmd)
    sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"\n{BOLD}{'=' * 50}")
    print("  TechTrek Deployment Runner")
    print(f"{'=' * 50}{RESET}")

    check_python()
    install_deps()
    check_env()
    run_migrations()
    start_server()
