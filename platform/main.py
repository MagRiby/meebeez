import os
import sys
import socket
import re

from dotenv import load_dotenv

load_dotenv()

# ── Force IPv4 for all connections ────────────────────────────────
# Many networks advertise IPv6 but don't route it properly, causing
# database connections to hang.  We fix this at two levels:
#
# 1. Monkey-patch socket.getaddrinfo so Python-level libraries
#    (psycopg 3, requests, etc.) prefer IPv4.
# 2. Rewrite DATABASE_URL and TENANT_DB_BASE_URI to include an
#    explicit IPv4 address via the "hostaddr" libpq parameter so
#    that psycopg2/libpq (C-level DNS) also uses IPv4.

_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_first_getaddrinfo(*args, **kwargs):
    results = _orig_getaddrinfo(*args, **kwargs)
    return sorted(results, key=lambda x: x[0] != socket.AF_INET)


socket.getaddrinfo = _ipv4_first_getaddrinfo


def _inject_hostaddr(uri):
    """Add hostaddr=<IPv4> to a PostgreSQL URI so libpq uses IPv4."""
    if not uri or "hostaddr" in uri:
        return uri
    m = re.search(r"@([^/:?]+)", uri)
    if not m:
        return uri
    hostname = m.group(1)
    try:
        ipv4 = _orig_getaddrinfo(hostname, 5432, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        sep = "&" if "?" in uri else "?"
        return uri + sep + "hostaddr=" + ipv4
    except Exception:
        return uri


for _env_key in ("DATABASE_URL", "TENANT_DB_BASE_URI"):
    _val = os.environ.get(_env_key)
    if _val:
        os.environ[_env_key] = _inject_hostaddr(_val)

# Ensure the platform directory is on the Python path
sys.path.insert(0, os.path.dirname(__file__))

from core import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
