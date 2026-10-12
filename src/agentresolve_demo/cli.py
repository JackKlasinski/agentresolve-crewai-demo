import argparse
import html
import json
import os
from pathlib import Path
import re
from .client import AgentResolveClient, NetworkError
from .core import DemoClient, Refused


def write_preview(result, destination):
    rows = "".join(f'<li><b>{html.escape(x["step"])}</b><p>{html.escape(x["detail"])}</p></li>' for x in result["trace"])
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentResolve × CrewAI — executable demo</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f5ef;color:#193d35;font:17px/1.6 system-ui,sans-serif}main{max-width:1000px;margin:auto;padding:56px 24px}.tag{font-size:13px;text-transform:uppercase;letter-spacing:.13em;color:#527263}h1{font-size:clamp(34px,6vw,62px);line-height:1.08;letter-spacing:-.045em;max-width:780px}.intro{font-size:20px;max-width:730px;color:#53675e}.badge{display:inline-block;background:#dfeccf;padding:8px 15px;border-radius:8px;font-weight:700}section{display:grid;grid-template-columns:1fr 1fr;gap:28px;margin-top:30px}ol{padding:0;list-style:none;counter-reset:n}li{counter-increment:n;padding:20px 20px 20px 60px;position:relative;background:white;margin:0 0 14px;border:1px solid #dde4d9;border-radius:12px}li:before{content:counter(n,decimal-leading-zero);position:absolute;left:18px;top:20px;color:#6f8a5b;font-weight:700}p{margin:.5em 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#173c34;color:#f1f7ea;padding:24px;border-radius:12px;font:14px/1.7 monospace}aside{font-size:14px;color:#53675e}a{color:#245d46}@media(max-width:700px){section{grid-template-columns:1fr}main{padding-top:30px}}
</style><main><p class="tag">AgentResolve × CrewAI · Runnable example</p><h1>Agree the work.<br>Then let the flow run.</h1><p class="intro">A real CrewAI Flow checks a reviewed agreement, validates a synthetic agent document and submits a result for review.</p>'''
    page += f'<p class="badge">{html.escape(result["mode"])} · GBP 0 · {html.escape(result["status"])}</p><section><ol>{rows}</ol><div><h2>The delivered result</h2><pre>{html.escape(result["report"])}</pre><aside>This page is the output of a local simulation, not evidence of a live customer job or payment. The network adapter uses the documented AgentResolve API when explicitly selected.</aside></div></section><p>Run: <code>agentresolve-demo --demo</code></p><p><a href="https://agentresolve.uk/developers/quickstart.php">Provider integration guide</a> · <a href="https://agentresolve.uk/join/">Join AgentResolve</a></p></main></html>'
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (destination / "demo.html").write_text(page, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="CrewAI Flow for a reviewed, GBP 0 AgentResolve task")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--demo", action="store_true", help="Offline fixture; no network, account or model key")
    mode.add_argument("--inspect", action="store_true", help="Read public status only; no credentials or writes")
    mode.add_argument("--network", action="store_true", help="Execute one already-approved GBP 0 network task")
    parser.add_argument("--job-id")
    parser.add_argument("--contract-hash", help="SHA-256 copied from the agreement you reviewed and accepted")
    parser.add_argument("--output", type=Path, default=Path("output"), help="Offline demo output directory")
    args = parser.parse_args()
    try:
        if args.inspect:
            client = AgentResolveClient()
            print(json.dumps({"network_ok": client.status()["ok"], "market": client.market(), "writes": 0}, indent=2))
            return
        from .flow import DeliveryFlow
        if args.demo:
            client = DemoClient()
            job_id, digest = client.job["id"], client.contract["terms_sha256"]
            print("OFFLINE SIMULATION — fixture agreements and task states; no real network writes.")
        else:
            if not re.fullmatch(r"ar_job_[a-z0-9]+", args.job_id or "") or not re.fullmatch(r"[a-f0-9]{64}", args.contract_hash or ""):
                parser.error("--network requires --job-id and the reviewed --contract-hash")
            client = AgentResolveClient(os.getenv("AR_AGENT_ID", ""), os.getenv("AR_MANAGEMENT_TOKEN", ""))
            job_id, digest = args.job_id, args.contract_hash
            print("NETWORK MODE — start and submit for one already-approved GBP 0 task.")
        result = DeliveryFlow(client, demo=args.demo).kickoff(inputs={"job_id": job_id, "reviewed_hash": digest})
        print(json.dumps(result, indent=2))
        if args.demo:
            write_preview(result, args.output)
            print("Open", args.output / "demo.html")
    except (NetworkError, Refused) as exc:
        parser.exit(1, "Stopped: " + str(exc) + "\n")
    except Exception:
        parser.exit(1, "Stopped: unexpected response or runtime error. Inspect the task before retrying; no automatic write retry was made.\n")


if __name__ == "__main__":
    main()
