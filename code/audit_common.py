"""
audit_common.py -- shared helpers for the biobank preanalytical-metadata audit.

Every HTTP call made by the pull scripts goes through AuditClient, which:
  * rate-limits requests (default 1 request / 0.5 s),
  * retries transient failures with backoff,
  * archives each raw response body to raw/<source>/<sha256>.json (provenance),
  * appends one line per call to out/api_call_log.jsonl
    (timestamp, source, method, url, params, status, bytes, sha256, seconds).

That log + the archived responses are what you cite for the
"Transparency and Methodological Description" requirement.
"""
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
RAW = ROOT / "raw"
CALL_LOG = OUT / "api_call_log.jsonl"

# Generic client name on purpose: no personal e-mail in request headers.
USER_AGENT = "biobank-preanalytical-audit/0.1 (academic metadata audit; python-requests)"

MISSING_STRINGS = {
    "", "na", "n/a", "nan", "none", "null", "unknown", "not reported",
    "not available", "not applicable", "unspecified", "[not available]",
    "[not reported]", "[unknown]", "[not applicable]", "not allowed to collect",
}


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_missing(value):
    """True if a metadata value should count as 'not populated'."""
    if value is None:
        return True
    if isinstance(value, float) and value != value:  # NaN
        return True
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return str(value).strip().lower() in MISSING_STRINGS


def require_terms_ack(args, source, terms_url):
    """Refuse to harvest until the user confirms they read the terms of use."""
    if getattr(args, "ack_terms", False):
        return
    sys.exit(
        f"\n[{source}] Please read the terms of use first: {terms_url}\n"
        f"Then re-run with --ack-terms to confirm that systematic metadata "
        f"retrieval is permitted. (This is logged in the run manifest.)\n"
    )


class AuditClient:
    def __init__(self, source, delay=0.5, timeout=60, retries=4):
        self.source = source
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self._last = 0.0
        OUT.mkdir(exist_ok=True)
        (RAW / source).mkdir(parents=True, exist_ok=True)

    def _wait(self):
        gap = time.time() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.time()

    def request(self, method, url, params=None, json_body=None, save=True):
        last_err = None
        for attempt in range(1, self.retries + 1):
            self._wait()
            t0 = time.time()
            try:
                if method == "GET":
                    r = self.session.get(url, params=params, timeout=self.timeout)
                else:
                    r = self.session.post(url, params=params, json=json_body, timeout=self.timeout)
                dt = round(time.time() - t0, 3)
                body = r.content
                digest = hashlib.sha256(body).hexdigest()
                if save and r.status_code == 200:
                    (RAW / self.source / f"{digest}.json").write_bytes(body)
                with CALL_LOG.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({
                        "timestamp_utc": utcnow(), "source": self.source, "method": method,
                        "url": r.url, "params": params, "json_body": json_body,
                        "status": r.status_code, "bytes": len(body),
                        "sha256": digest, "seconds": dt, "attempt": attempt,
                        **({"error_body": r.text[:1500]} if r.status_code != 200 else {}),
                    }, default=str) + "\n")
                if r.status_code == 200:
                    return r
                if r.status_code in (429, 500, 502, 503, 504):
                    last_err = f"HTTP {r.status_code}"
                    time.sleep(2 ** attempt)
                    continue
                last_err = f"HTTP {r.status_code}: {r.text[:800]}"
                if r.status_code in (400, 401, 403, 404, 405, 422):
                    break  # client errors will not succeed on retry
                r.raise_for_status()
            except requests.RequestException as e:
                last_err = repr(e)
                time.sleep(2 ** attempt)
        raise RuntimeError(f"[{self.source}] failed (last attempt {attempt}): {url} :: {last_err}")

    def get_json(self, url, params=None):
        return self.request("GET", url, params=params).json()

    def post_json(self, url, body, params=None):
        return self.request("POST", url, params=params, json_body=body).json()


def write_manifest(source, info):
    """Write out/<source>_run_manifest.json describing the run (for the Methods text)."""
    info = dict(info)
    info.update({"source": source, "run_finished_utc": utcnow(), "python": sys.version.split()[0],
                 "requests": requests.__version__})
    (OUT / f"{source}_run_manifest.json").write_text(json.dumps(info, indent=2, default=str))


COMPLETENESS_COLUMNS = [
    "source", "stratum", "field", "schema_defined", "n_records", "n_populated",
    "pct_populated", "notes",
]


def completeness_row(source, stratum, field, schema_defined, n_records, n_populated, notes=""):
    pct = round(100.0 * n_populated / n_records, 2) if n_records else None
    return {"source": source, "stratum": stratum, "field": field,
            "schema_defined": schema_defined, "n_records": n_records,
            "n_populated": n_populated, "pct_populated": pct, "notes": notes}
