#!/usr/bin/env python3
"""
Full patent harvest for humanoid-robot patents (ti="humanoid robot") published in
KR and CN: bibliographic + INPADOC family + citations (patent + NPL) from EPO OPS.

Phase 1 (search, ~5/min): paginate search/biblio -> seed list with core biblio.
Phase 2 (retrieval ~50/min + inpadoc ~30/min): per patent, fetch full biblio
        (references-cited = patent + NPL) and INPADOC family. Resumable.

Usage:
  python collect_patents_full.py seed [KR|CN|ALL]     # phase 1
  python collect_patents_full.py enrich [--limit N]   # phase 2
  python collect_patents_full.py test                 # 3-patent KR dry run
"""
import urllib.request, urllib.parse, base64, json, time, os, re, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.abspath(os.path.join(HERE, "..", "data", "patents"))
SEED = os.path.join(D, "kr_cn_seed.jsonl")
FULL = os.path.join(D, "kr_cn_full.jsonl")
CKPT = os.path.join(D, "kr_cn_full.ckpt")
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

def api(path, headers=None, tries=40):
    url = "https://ops.epo.org/3.2/rest-services/" + path
    for t in range(tries):
        h = {"Authorization": "Bearer " + token(), "Accept": "application/json"}
        if headers: h.update(headers)
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60).read())
        except urllib.error.HTTPError as e:
            if e.code == 404: return None                      # not found / no results
            if e.code == 401: token(force=True); continue
            if e.code == 429 or 500 <= e.code < 600:            # throttle / overload / gateway (502/503/504)
                time.sleep(min(240, 15 * (t + 1)) + random.uniform(0, 6)); continue
            raise
        except Exception:
            time.sleep(min(120, 12 * (t + 1)))
    return None

def L(x):
    return [] if x is None else (x if isinstance(x, list) else [x])
def sval(x):
    if isinstance(x, dict): return x.get("$")
    return x

def parse_core(ex):
    ed = ex.get("exchange-document", {})
    bib = ed.get("bibliographic-data", {})
    country = ed.get("@country"); num = ed.get("@doc-number"); kind = ed.get("@kind")
    pid = f"{country}{num}{kind}"
    epodoc = f"{country}{num}"
    apps = L(bib.get("parties", {}).get("applicants", {}).get("applicant"))
    en, orig, acountries = [], [], set()
    for pa in apps:
        nm = sval(pa.get("applicant-name", {}).get("name", {}))
        if not nm: continue
        m = re.search(r"\[([A-Z]{2})\]\s*$", nm)          # epodoc names carry [CC] country suffix
        if m: acountries.add(m.group(1))
        (en if (re.search(r"[A-Za-z]", nm) and not re.search(r"[一-鿿가-힣]", nm)) else orig).append(nm.strip())
    inv = L(bib.get("parties", {}).get("inventors", {}).get("inventor"))
    n_inv = len(set(sval(i.get("inventor-name", {}).get("name", {})) for i in inv if sval(i.get("inventor-name", {}).get("name", {}))))
    cpc = []
    for c in L(bib.get("patent-classifications", {}).get("patent-classification")):
        sec = sval(c.get("section")); cl = sval(c.get("class")); sc = sval(c.get("subclass"))
        if sec and cl and sc: cpc.append(f"{sec}{cl}{sc}")
    ipc = [sval(x).split()[0] if sval(x) else None for x in L(bib.get("classifications-ipcr", {}).get("classification-ipcr"))]
    ipc = [x for x in ipc if x]
    titles = L(bib.get("invention-title"))
    title = next((sval(x) for x in titles if x.get("@lang") == "en"), sval(titles[0]) if titles else None)
    def dref(ref):
        for x in L(bib.get(ref, {}).get("document-id")):
            if x.get("@document-id-type") == "epodoc":
                return sval(x.get("date"))
        return None
    return {"id": pid, "epodoc": epodoc, "country": country,
            "applicant_countries": sorted(acountries),
            "applicants_en": sorted(set(en)), "applicants_orig": sorted(set(orig)), "n_inventors": n_inv,
            "cpc": sorted(set(cpc)), "ipc": sorted(set(ipc)), "title": title,
            "app_date": dref("application-reference"), "pub_date": dref("publication-reference"),
            "prio_date": (lambda ps: min([sval(p.get("date")) for p in L(ps.get("priority-claim")) for _ in [1] if sval(p.get("date"))], default=None))(bib.get("priority-claims", {}))}

# ---------------- Phase 1: seed ----------------
def phase_seed(which):
    countries = ["KR", "CN"] if which in ("ALL", None) else [which]
    seen = set()
    if os.path.exists(SEED):
        for l in open(SEED): seen.add(json.loads(l)["id"])
    fout = open(SEED, "a")
    for c in countries:
        cql = f'ti="humanoid robot" and pn={c}'
        start = 1; total = None
        while True:
            d = api("published-data/search/biblio?" + urllib.parse.urlencode({"q": cql}),
                    headers={"X-OPS-Range": f"{start}-{start+99}"})
            if not d: break
            root = d["ops:world-patent-data"]["ops:biblio-search"]
            total = int(root["@total-result-count"])
            for ex in L(root.get("ops:search-result", {}).get("exchange-documents")):
                rec = parse_core(ex)
                if rec["id"] not in seen:
                    seen.add(rec["id"]); fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fout.flush()
            print(f"[seed {c}] {start}-{start+99} / {total}", flush=True)
            start += 100
            if start > min(total, 2000): break
            time.sleep(13 + random.uniform(0, 2))
    fout.close(); print("SEED DONE", flush=True)

# ---------------- Phase 1b: seed by year (bypass 2000-result cap) ----------------
def phase_seed_year(country, y0=2000, y1=2026):
    seen = set()
    if os.path.exists(SEED):
        for l in open(SEED): seen.add(json.loads(l)["id"])
    before = len(seen)
    fout = open(SEED, "a")
    for y in range(y0, y1 + 1):
        cql = f'ti="humanoid robot" and pn={country} and pd within "{y}"'
        start = 1; total = None; added = 0
        while True:
            d = api("published-data/search/biblio?" + urllib.parse.urlencode({"q": cql}),
                    headers={"X-OPS-Range": f"{start}-{start+99}"})
            if not d: break
            root = d["ops:world-patent-data"]["ops:biblio-search"]
            total = int(root["@total-result-count"])
            if total == 0: break
            for ex in L(root.get("ops:search-result", {}).get("exchange-documents")):
                rec = parse_core(ex)
                if rec["id"] not in seen:
                    seen.add(rec["id"]); fout.write(json.dumps(rec, ensure_ascii=False) + "\n"); added += 1
            fout.flush()
            start += 100
            if start > min(total, 2000): break
            time.sleep(13 + random.uniform(0, 2))
        print(f"[seedyear {country} {y}] total={total} new={added} (seed now {len(seen)})", flush=True)
    fout.close()
    print(f"SEEDYEAR DONE {country}: +{len(seen)-before} new (total {len(seen)})", flush=True)

# ---------------- Phase 2: enrich ----------------
def parse_citations(ed):
    bib = ed.get("bibliographic-data", {})
    patcit, npl = [], []
    for c in L(bib.get("references-cited", {}).get("citation")):
        if "patcit" in c:
            dids = L(c.get("patcit", {}).get("document-id"))
            epo = next((f"{sval(x.get('country'))}{sval(x.get('doc-number'))}" for x in dids
                        if x.get("@document-id-type") == "docdb"), None)
            patcit.append(epo)
        if "nplcit" in c:
            npl.append(sval(c.get("nplcit", {}).get("text")))
    return [p for p in patcit if p], [n for n in npl if n]

def parse_family(d):
    if not d: return None, [], []
    fam = d.get("ops:world-patent-data", {}).get("ops:patent-family", {})
    fid = fam.get("@family-id")
    members, countries = [], set()
    for m in L(fam.get("ops:family-member")):
        for x in L(m.get("publication-reference", {}).get("document-id")):
            if x.get("@document-id-type") == "docdb":
                cc = sval(x.get("country")); members.append(f"{cc}{sval(x.get('doc-number'))}{sval(x.get('kind')) or ''}")
                if cc: countries.add(cc)
                break
    return fid, sorted(set(members)), sorted(countries)

def phase_enrich(limit=None):
    done = set(open(CKPT).read().split()) if os.path.exists(CKPT) else set()
    seeds = [json.loads(l) for l in open(SEED)]
    todo = [s for s in seeds if s["id"] not in done]
    if limit: todo = todo[:limit]
    fout = open(FULL, "a"); fck = open(CKPT, "a")
    for i, s in enumerate(todo, 1):
        epo = s["epodoc"]
        # full biblio -> citations
        bd = api(f"published-data/publication/epodoc/{epo}/biblio")
        patcit, npl = [], []
        if bd:
            ed = bd.get("ops:world-patent-data", {}).get("exchange-documents", {}).get("exchange-document", {})
            ed = ed[0] if isinstance(ed, list) else ed
            patcit, npl = parse_citations(ed)
        time.sleep(2.2 + random.uniform(0, 1.2))
        # family
        fd = api(f"family/publication/docdb/{s['country']}.{s['id'][len(s['country']):-1]}.{s['id'][-1]}/biblio")
        fid, members, fcountries = parse_family(fd)
        rec = {**s, "cit_patent": patcit, "cit_npl": npl, "n_patcit": len(patcit), "n_npl": len(npl),
               "family_id": fid, "family_members": members, "family_size": len(members), "family_countries": fcountries}
        fout.write(json.dumps(rec, ensure_ascii=False) + "\n"); fout.flush()
        fck.write(s["id"] + "\n"); fck.flush()
        if i % 25 == 0 or i <= 5:
            print(f"[enrich {i}/{len(todo)}] {s['id']} npl={len(npl)} patcit={len(patcit)} fam={len(members)}", flush=True)
        time.sleep(2.2 + random.uniform(0, 1.2))
    fout.close(); fck.close(); print("ENRICH DONE", flush=True)

# ---------------- test ----------------
def test():
    d = api("published-data/search/biblio?" + urllib.parse.urlencode({"q": 'ti="humanoid robot" and pn=KR'}),
            headers={"X-OPS-Range": "1-3"})
    root = d["ops:world-patent-data"]["ops:biblio-search"]
    recs = [parse_core(ex) for ex in L(root["ops:search-result"]["exchange-documents"])]
    for s in recs:
        bd = api(f"published-data/publication/epodoc/{s['epodoc']}/biblio")
        patcit, npl = [], []
        if bd:
            ed = bd.get("ops:world-patent-data", {}).get("exchange-documents", {}).get("exchange-document", {})
            ed = ed[0] if isinstance(ed, list) else ed
            patcit, npl = parse_citations(ed)
        time.sleep(2)
        fd = api(f"family/publication/docdb/{s['country']}.{s['id'][len(s['country']):-1]}.{s['id'][-1]}/biblio")
        fid, members, fcountries = parse_family(fd)
        print(f"{s['id']} | {s['title'][:40] if s['title'] else ''!r}")
        print(f"   출원인:{s['applicants_en'] or s['applicants_orig']} | CPC:{s['cpc'][:3]} | 출원일:{s['app_date']}")
        print(f"   인용: 특허{len(patcit)} NPL{len(npl)} | 패밀리:{len(members)}개국={fcountries} fid={fid}")
        time.sleep(2)

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    if cmd == "seed": phase_seed(sys.argv[2] if len(sys.argv) > 2 else "ALL")
    elif cmd == "seedyear": phase_seed_year(sys.argv[2] if len(sys.argv) > 2 else "CN")
    elif cmd == "enrich":
        lim = int(sys.argv[sys.argv.index("--limit")+1]) if "--limit" in sys.argv else None
        phase_enrich(lim)
    else: test()
