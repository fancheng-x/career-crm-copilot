#!/usr/bin/env python3
"""Method B — offline extraction benchmark against a hand-labelled gold set.

Runs `llm.extract()` over each note in `gold_extractions.json` and reports, against
your labels:

  * Entity recall / precision  — did we find the right people & companies?
  * Field accuracy             — on matched contacts, how many fields are right?
  * Hallucination rate         — extracted entities that aren't in the gold set.

This is the cold-start counterpart to the online correction-rate instrumentation on
the Add Note page: the gold set gives a stable benchmark without waiting for usage.

Usage (needs ANTHROPIC_API_KEY):
    .venv/bin/python scripts/eval_extraction.py

Extend it by adding your own real notes + expected entities to gold_extractions.json.
Only the fields you fill into "expected" are scored, so partial labels are fine.
"""
import json
import pathlib
import sys

# Make `src` importable when run from anywhere.
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import llm                                    # noqa: E402
from src.eval_extraction import _norm, _norm_set       # noqa: E402

GOLD = pathlib.Path(__file__).parent / "gold_extractions.json"
# `background` is free text, so it's scored by token overlap (text_field) rather
# than exact/containment match — keep it out of the scalar list to avoid double-counting.
SCORED_CONTACT_FIELDS = ["title", "company"]
SCORED_COMPANY_FIELDS = ["stage", "industry", "product_area"]


def _match(gold_v, pred_v):
    """Lenient scalar match: equal, or one contains the other (phrasing varies)."""
    g, p = _norm(gold_v), _norm(pred_v)
    if not g:
        return None                      # nothing labelled → don't score this field
    if not p:
        return False
    return g == p or g in p or p in g


def _overlap(gold_v, pred_v, thresh=0.3):
    """Token-Jaccard match for free-text fields like `background`."""
    g, p = _norm_set(gold_v.split()) if isinstance(gold_v, str) else set(), \
        _norm_set(pred_v.split()) if isinstance(pred_v, str) else set()
    if not g:
        return None
    if not p:
        return False
    return (len(g & p) / len(g | p)) >= thresh


def _find_by_name(items, name):
    for it in items:
        if _norm(it.get("name")) == _norm(name):
            return it
    return None


def _score_entities(gold, pred, scored_fields, text_field=None):
    """Return (name_tp, name_fn, name_fp, field_hits, field_total)."""
    gold_names = [_norm(g.get("name")) for g in gold if _norm(g.get("name"))]
    pred_names = [_norm(p.get("name")) for p in pred if _norm(p.get("name"))]
    tp = sum(1 for n in gold_names if n in pred_names)
    fn = len(gold_names) - tp
    fp = sum(1 for n in pred_names if n not in gold_names)

    hits = total = 0
    for g in gold:
        p = _find_by_name(pred, g.get("name"))
        if not p:
            continue
        for fld in scored_fields:
            res = _match(g.get(fld), p.get(fld))
            if res is not None:
                total += 1
                hits += 1 if res else 0
        if text_field:
            res = _overlap(g.get(text_field), p.get(text_field))
            if res is not None:
                total += 1
                hits += 1 if res else 0
    return tp, fn, fp, hits, total


def main():
    if not GOLD.exists():
        print(f"No gold set at {GOLD}")
        return 1
    cases = json.loads(GOLD.read_text())
    print(f"Benchmarking extraction over {len(cases)} gold note(s)…\n")

    C = {"tp": 0, "fn": 0, "fp": 0, "hits": 0, "total": 0}   # contacts
    K = {"tp": 0, "fn": 0, "fp": 0, "hits": 0, "total": 0}   # companies

    for i, case in enumerate(cases, 1):
        try:
            pred = llm.extract(case["raw_text"])
        except Exception as e:
            print(f"[{i}] extraction failed: {e}")
            continue
        exp = case.get("expected", {})
        ctp, cfn, cfp, chits, ctot = _score_entities(
            exp.get("contacts", []), pred.get("contacts", []),
            SCORED_CONTACT_FIELDS, text_field="background")
        ktp, kfn, kfp, khits, ktot = _score_entities(
            exp.get("companies", []), pred.get("companies", []),
            SCORED_COMPANY_FIELDS)
        for agg, vals in ((C, (ctp, cfn, cfp, chits, ctot)),
                          (K, (ktp, kfn, kfp, khits, ktot))):
            agg["tp"] += vals[0]; agg["fn"] += vals[1]; agg["fp"] += vals[2]
            agg["hits"] += vals[3]; agg["total"] += vals[4]
        names = [c.get("name") for c in pred.get("contacts", [])]
        acc = f"{chits}/{ctot}" if ctot else "n/a"
        print(f"[{i}] contacts found: {names or '—'}  |  field acc: {acc}")

    print("\n=== Summary ===")
    _report("Contacts", C)
    _report("Companies", K)
    return 0


def _rate(n, d):
    return f"{n / d * 100:.0f}%" if d else "n/a"


def _report(label, a):
    recall = _rate(a["tp"], a["tp"] + a["fn"])
    precision = _rate(a["tp"], a["tp"] + a["fp"])
    field_acc = _rate(a["hits"], a["total"])
    hallu = _rate(a["fp"], a["tp"] + a["fp"])
    print(f"{label:10}  recall {recall:>4}  precision {precision:>4}  "
          f"field-accuracy {field_acc:>4}  hallucination {hallu:>4}")


if __name__ == "__main__":
    raise SystemExit(main())
