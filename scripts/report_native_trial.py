"""Summarize a marked native exchange without copying dialogue or private protocol data."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3


def report(root, prompt, expected):
    uri = (root/"diary"/"memory.sqlite3").resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        rows = db.execute("""SELECT provider,status,reason,response FROM conversations
            LEFT JOIN exchange_end USING(id) WHERE trim(prompt)=?""", (prompt.strip(),)).fetchall()
    counts = Counter()
    for line in (root/"recorder.log").read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("outcome"):
            counts[(event.get("host") or "unmatched",event["outcome"])] += 1
    return {"commit":(root/"commit.txt").read_text(encoding="utf-8-sig").strip(),
            "rows":[{"provider":p,"status":s,"reason":r,"exact_reply":v==expected} for p,s,r,v in rows],
            "whole_trial_events":[{"host":h,"outcome":o,"count":n} for (h,o),n in sorted(counts.items())]}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("trial", type=Path)
    cli.add_argument("prompt")
    cli.add_argument("expected")
    args = cli.parse_args()
    print(json.dumps(report(args.trial, args.prompt, args.expected), indent=2))
