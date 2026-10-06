#!/usr/bin/env python3
"""Generate docs/zippyy.postman_collection.json from docs/openapi.yaml.  Usage: python3 scripts/openapi_to_postman.py"""
import json, yaml, pathlib
root = pathlib.Path(__file__).resolve().parent.parent
spec = yaml.safe_load((root / "docs/openapi.yaml").read_text())
items = {}
for path, ops in spec["paths"].items():
    for method, op in ops.items():
        if method not in ("get", "post", "put", "delete"):
            continue
        body = None
        rb = op.get("requestBody", {}).get("content", {}).get("application/json", {})
        ex = rb.get("example")
        if ex is None and rb.get("examples"):
            ex = next(iter(rb["examples"].values())).get("value")
        if ex is not None:
            body = {"mode": "raw", "raw": json.dumps(ex, indent=2), "options": {"raw": {"language": "json"}}}
        url = "{{baseUrl}}" + path.replace("{", ":").replace("}", "")
        params = [p for p in op.get("parameters", []) if p.get("in") == "path"]
        req = {"method": method.upper(), "header": [{"key": "Content-Type", "value": "application/json"}, {"key": "X-Zippy-Role", "value": "{{role}}", "disabled": True}],
               "url": {"raw": url, "host": ["{{baseUrl}}"], "path": [s.replace("{", ":").replace("}", "") for s in path.strip("/").split("/")],
                       "variable": [{"key": p["name"], "value": str(p.get("example", ""))} for p in params]}}
        if body: req["body"] = body
        items.setdefault(op.get("tags", ["Other"])[0], []).append({"name": f"{method.upper()} {path} — {op.get('summary','')}", "request": req})
col = {"info": {"name": "Zippyy API", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
       "variable": [{"key": "baseUrl", "value": "http://localhost:8080"}, {"key": "role", "value": "SELLER"}],
       "item": [{"name": t, "item": v} for t, v in items.items()]}
(root / "docs/zippyy.postman_collection.json").write_text(json.dumps(col, indent=2))
print("wrote docs/zippyy.postman_collection.json")
