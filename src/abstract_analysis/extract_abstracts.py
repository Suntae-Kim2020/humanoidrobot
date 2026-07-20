#!/usr/bin/env python3
"""Structured extraction of humanoid-robot paper abstracts via the Anthropic
Message Batches API (50% cheaper, async). Reads the corpus JSONL produced by
build_pilot_corpus.py, extracts the schema.json fields per paper, writes
extracted.jsonl keyed by work id.

Usage:
    export ANTHROPIC_API_KEY=...            # or `ant auth login`
    python extract_abstracts.py corpus.jsonl extracted.jsonl [--limit N] [--model M]

Cost lever: default model is claude-opus-4-8 (highest quality). For a large run
you may pass --model claude-haiku-4-5 or claude-sonnet-5 to trade some accuracy
for cost — validate the choice against a gold set first (see gold_set.md).
"""
import sys, os, json, time, argparse
import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = json.load(open(os.path.join(HERE, "schema.json")))
SYSTEM_PROMPT = open(os.path.join(HERE, "extract_prompt.md")).read()

def build_request(rec, model):
    user = f"TITLE: {rec['title']}\nABSTRACT: {rec['abstract']}"
    return Request(
        custom_id=rec["id"].split("/")[-1][:64],   # OpenAlex Wxxxx id
        params=MessageCreateParamsNonStreaming(
            model=model,
            max_tokens=1024,
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": user}],
        ),
    )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus"); ap.add_argument("out")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--model", default="claude-opus-4-8")
    ap.add_argument("--batch-size", type=int, default=2000)
    a = ap.parse_args()

    recs = [json.loads(l) for l in open(a.corpus)]
    if a.limit: recs = recs[:a.limit]
    by_id = {r["id"].split("/")[-1][:64]: r for r in recs}
    client = anthropic.Anthropic()
    print(f"submitting {len(recs)} papers on {a.model} in batches of {a.batch_size}")

    with open(a.out, "w") as fout:
        for i in range(0, len(recs), a.batch_size):
            chunk = recs[i:i + a.batch_size]
            batch = client.messages.batches.create(
                requests=[build_request(r, a.model) for r in chunk])
            print(f"  batch {batch.id}: {len(chunk)} reqs, status={batch.processing_status}")
            while True:
                b = client.messages.batches.retrieve(batch.id)
                if b.processing_status == "ended": break
                print(f"    processing={b.request_counts.processing} "
                      f"succeeded={b.request_counts.succeeded}")
                time.sleep(30)
            for res in client.messages.batches.results(batch.id):
                if res.result.type != "succeeded":
                    print(f"    [{res.custom_id}] {res.result.type}"); continue
                txt = next((bl.text for bl in res.result.message.content
                            if bl.type == "text"), "")
                try:
                    fields = json.loads(txt)
                except Exception as e:
                    print(f"    [{res.custom_id}] parse error: {e}"); continue
                src = by_id.get(res.custom_id, {})
                out = {"id": src.get("id"), "title": src.get("title"),
                       "year": src.get("year"), "cn": src.get("cn"),
                       "kr": src.get("kr"), "us": src.get("us"),
                       "fwci": src.get("fwci"), "venue": src.get("venue"),
                       "extract": fields}
                fout.write(json.dumps(out, ensure_ascii=False) + "\n")
            fout.flush()
    print(f"done -> {a.out}")

if __name__ == "__main__":
    main()
