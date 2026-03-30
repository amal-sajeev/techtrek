"""Quick dev server — just run: python run.py"""

import secrets, os, sys, pathlib

os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ.setdefault("DEBUG", "1")

if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError:
        sys.exit("uvicorn not installed. Run:  pip install -r requirements.txt")

    kwargs: dict = dict(host="0.0.0.0", port=8000, reload=True, timeout_graceful_shutdown=3)

    use_http = os.environ.get("USE_HTTP", "").strip().lower() in ("1", "true", "yes")
    default_cert = pathlib.Path(__file__).parent / "certs" / "cert.pem"
    default_key = pathlib.Path(__file__).parent / "certs" / "key.pem"
    cert_file = pathlib.Path(os.environ.get("SSL_CERTFILE", "") or default_cert)
    key_file = pathlib.Path(os.environ.get("SSL_KEYFILE", "") or default_key)

    if use_http:
        print(f"  [HTTP] USE_HTTP=1 — plain HTTP only. From other devices use:  http://<this-PC-IP>:8000  (not https://)")
    elif cert_file.exists() and key_file.exists():
        kwargs["ssl_certfile"] = str(cert_file)
        kwargs["ssl_keyfile"] = str(key_file)
        print(f"  [HTTPS] enabled — https://localhost:8000")
        print(f"           From other devices: https://<this-PC-IP>:8000 (run: python scripts/gen_cert.py to include LAN IP in cert)")
    else:
        print(f"  [HTTP] No certs at {default_cert.parent} — running plain HTTP")

    uvicorn.run("app.main:app", **kwargs)
