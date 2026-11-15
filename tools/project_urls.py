"""Read the website default URL from the one public web config (not a duplicate constant)."""
from pathlib import Path
import re

def public_base():
    js = (Path(__file__).resolve().parents[1] / "web/config.js").read_text()
    match = re.search(r'window\.LUNEX_PUBLIC_BASE\s*=\s*window\.LUNEX_PUBLIC_BASE\s*\|\|\s*"([^"\n]+)"', js)
    if not match:
        raise ValueError("Missing public base URL in web/config.js")
    from manifest_security import validate_https_file_url
    base = match.group(1).rstrip("/")
    if not validate_https_file_url(base + "/update.json", base):
        raise ValueError("Public base URL is not an allowed HTTPS prefix")
    return base
