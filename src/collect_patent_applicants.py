#!/usr/bin/env python3
"""
Harvest humanoid-robot patent RECORDS (applicants + CPC) from EPO OPS biblio search,
for CN and US, years 2020-2025 (each country-year < 2000 OPS retrieval cap).
Output: JSONL of {id, country, year, applicants_en, applicants_orig, cpc, title}.
Throttled ~13s/request, resumable via a per-(country,year,page) checkpoint set.
"""
import urllib.request, urllib.parse, base64, json, time, os, re, random

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "data", "patents", "applicants.jsonl"))
CKPT = OUT + ".ckpt"
SECRETS = os.path.join(HERE, "..", ".epo_ops_secrets.env")

s = open(SECRETS).read()
KEY = re.search(r"EPO_OPS_KEY=(\S+)", s).group(1)
SECRET = re.search(r"EPO_OPS_SECRET=(\S+)", s).group(1)
_tok = {"v": None, "t": 0}

def token(force=False):
    if not force and _tok["v"] and time.time() - _tok["t"] < 900:
        return _tok["v"]
    cred = base64.b64encode(f"{KEY}:{SECRET}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    r = urllib.request.Request("https://ops.epo.org/3.2/auth/accesstoken", data=data,
        headers={"Authorization": "Basic " + cred, "Content-Type": "application/x-www-form-urlencoded"})
    _tok["v"] = json.loads(urllib.request.urlopen(r, timeout=30).read())["access_token"]
    _tok["t"] = time.time()
    return _tok["v"]

def as_list(x):
    if x is None: return []
    return x if isinstance(x, list) else [x]

def fetch_page(cql, start, tries=40):
    url = "https://ops.epo.org/3.2/rest-services/published-data/search/biblio?" + \
          urllib.parse.urlencode({"q": cql})
    for t in range(tries):
        req = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + token(), "Accept": "application/json",
            "X-OPS-Range": f"{start}-{start+99}"})
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=60).read())
            root = d["ops:world-patent-data"]["ops:biblio-search"]
            total = int(root["@total-result-count"])
            docs = []
            sr = root.get("ops:search-result", {})
            if sr:
                docs = as_list(sr.get("exchange-documents"))
            return total, docs
        except urllib.error.HTTPError as e:
            if e.code == 404: return 0, []
            if e.code == 401: token(force=True); continue
            if e.code in (403, 503, 500, 429):
                time.sleep(min(240, 20 * (t + 1)) + random.uniform(0, 8)); continue
            raise
        except Exception:
            time.sleep(min(120, 15 * (t + 1)))
    return None, []

def parse_doc(ex, country, year):
    ed = ex.get("exchange-document", {})
    bib = ed.get("bibliographic-data", {})
    pid = f"{ed.get('@country','')}{ed.get('@doc-number','')}{ed.get('@kind','')}"
    apps = as_list(bib.get("parties", {}).get("applicants", {}).get("applicant"))
    en, orig = [], []
    for pa in apps:
        fmt = pa.get("@data-format")
        nm = pa.get("applicant-name", {}).get("name", {})
        nm = nm.get("$") if isinstance(nm, dict) else nm
        if not nm: continue
        # epodoc format is usually the normalized/English-ish; original has CJK
        if re.search(r"[A-Za-z]", nm) and not re.search(r"[一-鿿]", nm):
            en.append(nm.strip())
        else:
            orig.append(nm.strip())
    en = sorted(set(en)); orig = sorted(set(orig))
    cpc = []
    for c in as_list(bib.get("patent-classifications", {}).get("patent-classification")):
        sec = c.get("section", {}); sec = sec.get("$") if isinstance(sec, dict) else sec
        cls = c.get("class", {}); cls = cls.get("$") if isinstance(cls, dict) else cls
        scls = c.get("subclass", {}); scls = scls.get("$") if isinstance(scls, dict) else scls
        if sec and cls and scls:
            cpc.append(f"{sec}{cls}{scls}")
    titles = as_list(bib.get("invention-title"))
    t = next((x.get("$") for x in titles if isinstance(x, dict) and x.get("@lang") == "en"),
             (titles[0].get("$") if titles and isinstance(titles[0], dict) else ""))
    return {"id": pid, "country": country, "year": year,
            "applicants_en": en, "applicants_orig": orig,
            "cpc": sorted(set(cpc)), "title": t}

def load_ckpt():
    return set(open(CKPT).read().split()) if os.path.exists(CKPT) else set()

def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    done = load_ckpt()
    fout = open(OUT, "a")
    fck = open(CKPT, "a")
    jobs = [(c, y) for c in ["CN", "US"] for y in range(2020, 2026)]
    for c, y in jobs:
        cql = f'ti="humanoid robot" and pn={c} and pd within "{y}"'
        start = 1
        total = None
        while True:
            key = f"{c}:{y}:{start}"
            if key in done:
                start += 100
                if total is not None and start > total: break
                if total is None and start > 2000: break
                continue
            total, docs = fetch_page(cql, start)
            if total is None:
                print(f"[{c} {y} @{start}] FAILED page", flush=True)
                break
            for ex in docs:
                rec = parse_doc(ex, c, y)
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fout.flush()
            fck.write(key + "\n"); fck.flush(); done.add(key)
            print(f"[{c} {y} @{start}] total={total} got={len(docs)}", flush=True)
            start += 100
            if start > min(total, 2000): break
            time.sleep(13 + random.uniform(0, 2))
    fout.close(); fck.close()
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
