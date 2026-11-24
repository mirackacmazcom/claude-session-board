"""Apply mark ops from stdin (a JSON op or list of ops) and print the marks.

Usage: python3 -I marks.py <data dir> < ops.json
"""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store

data_dir = sys.argv[1]
raw = sys.stdin.read().strip()
ops = json.loads(raw) if raw else []
d = store.apply(data_dir, ops, int(time.time() * 1000)) if ops else store.load(data_dir)
json.dump({"marks": d["marks"], "rev": d["rev"], "projects": d.get("projects", []), "migrated": d.get("migrated", False)}, sys.stdout, ensure_ascii=False)
