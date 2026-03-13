"""Quick dev server — just run: python run.py"""

import secrets, os, sys

os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
os.environ.setdefault("DEBUG", "1")

if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError:
        sys.exit("uvicorn not installed. Run:  pip install -r requirements.txt")

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
