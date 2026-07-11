#!/usr/bin/env python3
"""
Collect humanoid-robot patent COUNTS from EPO OPS (Open Patent Services).

EPO OPS search is throttled to ~5 requests/minute (X-Throttling-Control: search=green:5)
and can return 403 "overloaded" under system load, so we space requests >=13s apart and
back off hard on 403/overloaded. We only read the `@total-result-count` attribute per
(definition x country x year) cell. Output: resumable CSV grid.

Country filter: CQL `pn=CC` matches the publication-number country prefix (CN, US, ...).
Date filter:    CQL `pd within "YYYY"` = publication year.
World cell:     omit the `pn=` clause.
"""
import urllib.request, urllib.parse, base64, json, time, csv, os, random

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(HERE, "..", "data", "patents", "epo_patent_counts.csv")
OUT_CSV = os.path.abspath(OUT_CSV)
SECRETS = os.path.join(HERE, "..", ".epo_ops_secrets.env")

def load_secrets():
    kv = {}
    with open(SECRETS) as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                kv[k] = v
    return kv["EPO_OPS_KEY"], kv["EPO_OPS_SECRET"]

KEY, SECRET = load_secrets()
_token = {"val": None, "ts": 0}

def get_token(force=False):
    # tokens last ~20 min; refresh every 15 min or on demand
    if not force and _token["val"] and (time.time() - _token["ts"] < 900):
        return _token["val"]
    cred = base64.b64encode(f"{KEY}:{SECRET}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        "https://ops.epo.org/3.2/auth/accesstoken", data=data,
        headers={"Authorization": "Basic " + cred,
                 "Content-Type": "application/x-www-form-urlencoded"})
    tok = json.loads(urllib.request.urlopen(req, timeout=30).read())["access_token"]
    _token["val"], _token["ts"] = tok, time.time()
    return tok

def search_count(cql, tries=40):
    # 403 here = EPO system "overloaded" (transient), so we retry patiently for a
    # long time rather than giving up to None. Backoff grows then caps at 240s.
    url = "https://ops.epo.org/3.2/rest-services/published-data/search?" + \
          urllib.parse.urlencode({"q": cql})
    for t in range(tries):
        tok = get_token()
        req = urllib.request.Request(
            url, headers={"Authorization": "Bearer " + tok, "Accept": "application/json"})
        try:
            resp = urllib.request.urlopen(req, timeout=45)
            d = json.loads(resp.read())
            n = int(d["ops:world-patent-data"]["ops:biblio-search"]["@total-result-count"])
            return n
        except urllib.error.HTTPError as e:
            if e.code == 404:            # EPO returns 404 when a query has ZERO results
                return 0
            if e.code == 401:            # token expired
                get_token(force=True); continue
            if e.code in (403, 503, 500, 429):   # overloaded / throttled
                wait = min(240, 20 * (t + 1)) + random.uniform(0, 8)
                print(f"    [{e.code}] backoff {wait:.0f}s (try {t+1}/{tries})", flush=True)
                time.sleep(wait); continue
            raise
        except Exception as e:
            time.sleep(min(120, 15 * (t + 1)))
    return None

# --- query grid -------------------------------------------------------------
DEFINITIONS = {
    "humanoid": 'ti="humanoid robot"',                       # humanoid-specific, title (clean)
    "humanoid_txt": 'txt="humanoid robot"',                  # title+abstract (broader recall)
    "legged": 'ti="biped robot" or ti="bipedal robot" or ti="legged robot"',
}
COUNTRIES = ["CN", "US", "JP", "KR", "EP", "WO", None]       # None = WORLD
YEARS = list(range(2010, 2026))
SPACING = 13.0   # seconds between search calls (<=5/min limit)

def load_done():
    # positional parse so it works with or without a header row
    done = set()
    if os.path.exists(OUT_CSV):
        with open(OUT_CSV) as f:
            for row in csv.reader(f):
                if len(row) >= 3 and row[0] != "definition":
                    done.add((row[0], row[1], row[2]))
    return done

def main():
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    done = load_done()
    empty = (not os.path.exists(OUT_CSV)) or os.path.getsize(OUT_CSV) == 0
    f = open(OUT_CSV, "a", newline="")
    w = csv.writer(f)
    if empty:
        w.writerow(["definition", "country", "year", "count"])
    cells = [(dn, c, y) for dn in DEFINITIONS for c in COUNTRIES for y in YEARS]
    total = len(cells)
    for i, (dn, c, y) in enumerate(cells, 1):
        cval = c if c else "WORLD"
        if (dn, cval, str(y)) in done:
            continue
        cql = DEFINITIONS[dn] + f' and pd within "{y}"'
        if c:
            cql += f' and pn={c}'
        n = search_count(cql)
        w.writerow([dn, cval, y, n]); f.flush()
        print(f"[{i}/{total}] {dn:12} {cval:6} {y} -> {n}", flush=True)
        time.sleep(SPACING + random.uniform(0, 2))
    f.close()
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
