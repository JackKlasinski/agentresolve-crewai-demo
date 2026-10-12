"""Pure validation and a clearly labelled, offline API fixture."""
import copy
import hashlib
import json
import re
from urllib.parse import urlsplit

SERVICE = "agentresolve-json-check-v1"


class Refused(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Refused(message)


def approved_document(job, contract, agent_id, reviewed_hash):
    """Pin the operator-reviewed hash; the server enforces canonical integrity at start."""
    require(isinstance(job, dict) and isinstance(contract, dict), "Invalid agreement response.")
    for record, keys in [(job, ("assignee", "requester", "contract", "budget", "task")),
                         (contract, ("assignee", "requester", "job", "terms"))]:
        require(all(isinstance(record.get(key), dict) for key in keys), "Incomplete agreement response.")
    require(bool(re.fullmatch(r"[a-f0-9]{64}", reviewed_hash)), "Supply the reviewed contract hash.")
    require(job.get("assignee", {}).get("id") == agent_id
            and contract.get("assignee", {}).get("id") == agent_id, "Assignee mismatch.")
    require(job.get("requester", {}).get("id") == contract.get("requester", {}).get("id")
            and bool(contract.get("requester", {}).get("id")), "Requester mismatch.")
    require(job.get("contract", {}).get("id") == contract.get("id")
            and contract.get("job", {}).get("id") == job.get("id"), "Contract linkage mismatch.")
    require(job.get("contract", {}).get("terms_sha256") == reviewed_hash
            and contract.get("terms_sha256") == reviewed_hash, "Contract changed since review.")
    require(contract.get("status") == "active"
            and contract.get("requester_accepted") is True
            and contract.get("assignee_accepted") is True, "Both parties must accept the active agreement.")
    require(job.get("status") in {"claimed", "running"}, "Task must be claimed or running.")
    terms = contract.get("terms", {})
    require(all(isinstance(terms.get(key), dict) for key in ("commercial", "job", "parties", "delivery")),
            "Incomplete frozen agreement.")
    require(isinstance(terms["job"].get("task"), dict)
            and all(isinstance(terms["parties"].get(key), dict) for key in ("requester", "assignee")),
            "Incomplete frozen task or parties.")
    for commercial, amount_key in [(job.get("budget", {}), "minor"), (terms.get("commercial", {}), "amount_minor")]:
        require(type(commercial.get(amount_key)) is int and commercial[amount_key] == 0
                and commercial.get("currency") == "GBP", "This example only handles GBP 0 tasks.")
    require(terms.get("job", {}).get("id") == job.get("id"), "Frozen task identity mismatch.")
    require(terms.get("parties", {}).get("assignee", {}).get("id") == agent_id
            and terms.get("parties", {}).get("requester", {}).get("id") == job["requester"]["id"], "Frozen parties mismatch.")
    require(terms.get("job", {}).get("task") == job.get("task"), "Task instructions changed after agreement.")
    scope = terms["delivery"].get("scope")
    require(isinstance(scope, str) and SERVICE in scope.split(), "Scope must name the exact sample service.")
    instructions = terms["job"]["task"].get("instructions", "")
    require(isinstance(instructions, str) and len(instructions.encode()) <= 16000, "Invalid or oversized instructions.")
    try:
        task = json.loads(instructions)
    except ValueError:
        raise Refused("Instructions must contain the documented JSON envelope.") from None
    require(isinstance(task, dict) and set(task) == {"service", "document"}
            and task["service"] == SERVICE, "Unsupported task envelope.")
    return task["document"]


def check_document(document):
    errors = []
    def short_text(value):
        return isinstance(value, str) and bool(value.strip()) and len(value.encode()) <= 120
    if not isinstance(document, dict):
        errors.append("document must be a JSON object")
    else:
        if not short_text(document.get("name")):
            errors.append("name must be non-empty text up to 120 UTF-8 bytes")
        try:
            url = document.get("url", "")
            parsed = urlsplit(url)
            valid_url = (isinstance(url, str) and parsed.scheme == "https" and parsed.hostname
                         and not parsed.username and not parsed.password and not any(c.isspace() for c in url))
        except (TypeError, ValueError, AttributeError):
            valid_url = False
        if not valid_url:
            errors.append("url must be HTTPS without credentials or whitespace")
        skills = document.get("skills")
        if not isinstance(skills, list) or not 1 <= len(skills) <= 20 or not all(short_text(x) for x in skills):
            errors.append("skills must contain 1–20 non-empty strings, each up to 120 UTF-8 bytes")
    return "\n".join(["AgentResolve JSON check v1", "Result: " + ("FAIL" if errors else "PASS"),
                     *(errors or ["Required name, url and skills passed the local field rules."]),
                     "Scope: local field validation only. No URL fetched or identity/protocol certified."])


class DemoClient:
    """Synthetic in-memory states, not a real registration, agreement or network job."""
    public_id = "ar_agent_demoexecutor"

    def __init__(self):
        self.events = []
        self.job = {
            "id": "ar_job_demo", "status": "claimed", "budget": {"minor": 0, "currency": "GBP"},
            "requester": {"id": "ar_agent_demorequester"}, "assignee": {"id": self.public_id},
            "task": {"instructions": json.dumps({"service": SERVICE, "document": {
                "name": "Synthetic catalogue checker", "url": "https://example.com/agent",
                "skills": ["JSON validation", "Catalogue checks"]}})},
        }
        terms = {"job": {"id": self.job["id"], "task": copy.deepcopy(self.job["task"])},
                 "parties": {"requester": self.job["requester"], "assignee": self.job["assignee"]},
                 "commercial": {"amount_minor": 0, "currency": "GBP"},
                 "delivery": {"scope": SERVICE + " using synthetic data only"}}
        digest = hashlib.sha256(json.dumps(terms, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.contract = {"id": "ar_contract_demo", "job": {"id": self.job["id"]},
                         "requester": self.job["requester"], "assignee": self.job["assignee"],
                         "terms": terms, "terms_sha256": digest, "status": "active",
                         "requester_accepted": True, "assignee_accepted": True}
        self.job["contract"] = {"id": self.contract["id"], "terms_sha256": digest}

    def get_job(self, job_id):
        require(job_id == self.job["id"], "Unknown demo task.")
        return copy.deepcopy(self.job)

    def get_contract(self, contract_id):
        require(contract_id == self.contract["id"], "Unknown demo agreement.")
        return copy.deepcopy(self.contract)

    def start_job(self, job_id):
        require(job_id == self.job["id"] and self.job["status"] == "claimed", "Demo start refused.")
        self.events.append("start")
        self.job["status"] = "running"
        return copy.deepcopy(self.job)

    def submit_job(self, job_id, report):
        require(job_id == self.job["id"] and self.job["status"] == "running", "Demo submit refused.")
        self.events.append("submit")
        self.job["status"] = "submitted"
        self.job["result_summary"] = report
        return copy.deepcopy(self.job)
