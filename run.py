"""Quick dev server — just run: python run.py"""

import secrets, os, sys, pathlib

os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ.setdefault("DEBUG", "1")

if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError:
        sys.exit("uvicorn not installed. Run:  pip install -r requirements.txt")

    kwargs: dict = dict(host="0.0.0.0", port=8000, reload=True)

    cert_dir = pathlib.Path(__file__).parent / "certs"
    cert_file = cert_dir / "cert.pem"
    key_file = cert_dir / "key.pem"
    if cert_file.exists() and key_file.exists():
        kwargs["ssl_certfile"] = str(cert_file)
        kwargs["ssl_keyfile"] = str(key_file)
        print(f"  [HTTPS] enabled -- https://0.0.0.0:8000")
    else:
        print(f"  ⚠  No certs found at {cert_dir} — running plain HTTP")

    uvicorn.run("app.main:app", **kwargs)
