"""A real CrewAI Flow, with no LLM dependency or model API charges."""
import os
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_TELEMETRY_ENABLED"] = "false"
os.environ["CREWAI_TRACING_ENABLED"] = "false"

from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel, Field
from .core import approved_document, check_document, require


class DeliveryState(BaseModel):
    job_id: str = ""
    reviewed_hash: str = ""
    status: str = "not_started"
    report: str = ""
    trace: list[dict[str, str]] = Field(default_factory=list)


class DeliveryFlow(Flow[DeliveryState]):
    def __init__(self, client, *, demo=False):
        super().__init__(tracing=False)
        self.client = client
        self.demo = demo
        self._document = None

    def record(self, step, detail):
        self.state.trace.append({"step": step, "detail": detail})

    @start()
    def review_agreement(self):
        job = self.client.get_job(self.state.job_id)
        require(job.get("id") == self.state.job_id, "Unexpected task returned.")
        contract_id = (job.get("contract") or {}).get("id")
        require(bool(contract_id), "Task has no linked agreement.")
        contract = self.client.get_contract(contract_id)
        self._document = approved_document(job, contract, self.client.public_id, self.state.reviewed_hash)
        self.record("Agreement checked", "Assigned operator, accepted hash, frozen instructions and GBP 0 scope match.")
        if job["status"] == "claimed":
            started = self.client.start_job(self.state.job_id)
            require(started.get("id") == self.state.job_id and started.get("status") == "running", "Start was not confirmed; execution stopped.")
        self.state.status = "running"
        self.record("Start confirmed", "Synthetic API fixture." if self.demo else "AgentResolve accepted the start; its Gate remains authoritative.")

    @listen(review_agreement)
    def execute_bounded_task(self):
        self.state.report = check_document(self._document)
        self.record("Task executed", "Local JSON field rules; no LLM call, URL fetch, shell command or payment.")

    @listen(execute_bounded_task)
    def submit_for_review(self):
        # Reconcile the frozen agreement again before delivery; never accept new terms automatically.
        job = self.client.get_job(self.state.job_id)
        contract = self.client.get_contract(job["contract"]["id"])
        approved_document(job, contract, self.client.public_id, self.state.reviewed_hash)
        require(job["status"] == "running", "Task is no longer running.")
        submitted = self.client.submit_job(self.state.job_id, self.state.report)
        require(submitted.get("id") == self.state.job_id and submitted.get("status") == "submitted", "Submission outcome unconfirmed; inspect before retrying.")
        self.state.status = "submitted"
        self.record("Submitted for review", "The requester still needs to review the result. No completion or payment is triggered by this example.")
        return {"mode": "offline simulation" if self.demo else "AgentResolve GBP 0 task",
                "job_id": self.state.job_id, "status": self.state.status,
                "report": self.state.report, "trace": self.state.trace}
