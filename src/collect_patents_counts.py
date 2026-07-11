#!/usr/bin/env python3
"""
Collect humanoid-robot patent COUNTS from Google Patents' public query endpoint.

We only use aggregate `total_num_results` per query cell (country x year x definition)
so the footprint is one lightweight request per cell. Output: a tidy CSV/parquet grid
that feeds trend / share charts.

Endpoint (unofficial, keyless):
  https://patents.google.com/xhr/query?url=<url-encoded inner query>&exp=
Inner query params: q, country, type, after=priority:YYYYMMDD, before=priority:YYYYMMDD
"""
import urllib.parse, urllib.request, json, gzip, time, csv, os, random, sys

OUT_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "patents", "patent_counts.csv")
OUT_CSV = os.path.abspath(OUT_CSV)

UAS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]

def gp(inner, tries=8, base_sleep=1.5):
    url = "https://patents.google.com/xhr/query?url=" + urllib.parse.quote(inner) + "&exp="
    last = None
    for t in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": random.choice(UAS)})
            raw = urllib.request.urlopen(req, timeout=40).read()
            try: raw = gzip.decompress(raw)
            except Exception: pass
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 503, 500, 502):
                time.sleep(base_sleep * (2 ** t) + random.uniform(0, 1.5))
                continue
            raise
        except Exception as e:
            last = e
            time.sleep(base_sleep * (2 ** t))
    raise RuntimeError(f"failed after {tries}: {last}")

def total(q, country=None, year=None):
    parts = ["q=" + urllib.parse.quote_plus(q), "type=PATENT"]
    if country:
        parts.append("country=" + country)
    if year:
        parts.append(f"after=priority:{year}0101")
        parts.append(f"before=priority:{year+1}0101")
    d = gp("&".join(parts))
    return d.get("results", {}).get("total_num_results")

DEFINITIONS = {
    # humanoid-specific exact phrase (cleanest)
    "humanoid": '"humanoid robot"',
    # bipedal / legged locomotion (humanoid-adjacent)
    "legged": '("bipedal robot" OR "legged robot" OR "biped robot")',
    # general robotics baseline (CPC B25J manipulators/robots) for share context
    "robotics_all": '(B25J)',
}
# WORLD is represented by country=None
COUNTRIES = ["CN", "US", "JP", "KR", "DE", "WO", None]
YEARS = list(range(2010, 2026))

def load_done():
    done = set()
    if os.path.exists(OUT_CSV):
        with open(OUT_CSV) as f:
            for row in csv.DictReader(f):
                done.add((row["definition"], row["country"], row["year"]))
    return done

def main():
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    done = load_done()
    new_file = not os.path.exists(OUT_CSV)
    f = open(OUT_CSV, "a", newline="")
    w = csv.writer(f)
    if new_file:
        w.writerow(["definition", "country", "year", "count"])
    total_cells = len(DEFINITIONS) * len(COUNTRIES) * len(YEARS)
    i = 0
    for defname, q in DEFINITIONS.items():
        for c in COUNTRIES:
            cval = c if c else "WORLD"
            for y in YEARS:
                i += 1
                key = (defname, cval, str(y))
                if key in done:
                    continue
                try:
                    n = total(q, country=c, year=y)
                except Exception as e:
                    print(f"[{i}/{total_cells}] ERR {defname}/{cval}/{y}: {e}", flush=True)
                    n = None
                w.writerow([defname, cval, y, n]); f.flush()
                print(f"[{i}/{total_cells}] {defname:12} {cval:6} {y} -> {n}", flush=True)
                time.sleep(random.uniform(1.2, 2.6))
    f.close()
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
