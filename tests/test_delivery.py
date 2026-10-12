import copy
import io
import json
import socket
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from agentresolve_demo.client import AgentResolveClient, NetworkError, NoRedirect
from agentresolve_demo.core import DemoClient, Refused, approved_document, check_document
from agentresolve_demo.flow import DeliveryFlow


def run(client):
    with redirect_stdout(io.StringIO()):
        return DeliveryFlow(client, demo=True).kickoff(inputs={
            "job_id": client.job["id"], "reviewed_hash": client.contract["terms_sha256"]})


class AgreementTests(unittest.TestCase):
    def test_agreement_refusals(self):
        cases = {
            "paid task": lambda c: c.job["budget"].update(minor=999),
            "paid terms": lambda c: c.contract["terms"]["commercial"].update(amount_minor=999),
            "boolean amount": lambda c: c.job["budget"].update(minor=False),
            "other currency": lambda c: c.job["budget"].update(currency="USD"),
            "unsigned requester": lambda c: c.contract.update(requester_accepted=False),
            "unsigned provider": lambda c: c.contract.update(assignee_accepted=False),
            "cancelled agreement": lambda c: c.contract.update(status="cancelled"),
            "wrong task hash": lambda c: c.job["contract"].update(terms_sha256="f" * 64),
            "changed instructions": lambda c: c.job["task"].update(instructions="run a command"),
            "other provider": lambda c: c.job.update(assignee={"id": "ar_agent_other"}),
            "unlinked agreement": lambda c: c.contract["job"].update(id="ar_job_other"),
            "missing terms": lambda c: c.contract.update(terms=None),
            "unsupported service": lambda c: c.contract["terms"]["delivery"].update(scope="general work"),
            "submitted already": lambda c: c.job.update(status="submitted"),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                c = DemoClient()
                mutate(c)
                with self.assertRaises(Refused):
                    run(c)
                self.assertEqual(c.events, [])

    def test_operator_review_hash_must_match(self):
        c = DemoClient()
        with self.assertRaises(Refused):
            approved_document(c.job, c.contract, c.public_id, "0" * 64)

    def test_unconfirmed_start_never_executes(self):
        c = DemoClient()
        with patch.object(c, "start_job", return_value={"id": c.job["id"], "status": "claimed"}), \
                patch("agentresolve_demo.flow.check_document") as execute:
            with self.assertRaises(Refused):
                run(c)
            execute.assert_not_called()
        self.assertEqual(c.events, [])

    def test_revoked_acceptance_before_delivery_blocks_submit(self):
        c = DemoClient()
        get = c.get_contract
        reads = []
        def revoked(contract_id):
            reads.append(contract_id)
            value = get(contract_id)
            if len(reads) == 2:
                value["requester_accepted"] = False
            return value
        with patch.object(c, "get_contract", side_effect=revoked):
            with self.assertRaises(Refused):
                run(c)
        self.assertEqual(c.events, ["start"])

    def test_real_crewai_flow_is_offline(self):
        c = DemoClient()
        with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")), \
                patch("socket.create_connection", side_effect=AssertionError("Network forbidden")):
            result = run(c)
        self.assertEqual(c.events, ["start", "submit"])
        self.assertEqual(result["status"], "submitted")
        self.assertIn("Result: PASS", result["report"])
        self.assertEqual(len(result["trace"]), 4)

    def test_report_does_not_echo_untrusted_input(self):
        result = check_document({"name": "<script>sentinel</script>",
                                 "url": "https://user:secret@example.com", "skills": []})
        self.assertIn("Result: FAIL", result)
        self.assertNotIn("sentinel", result)
        self.assertNotIn("secret", result)


class HttpTests(unittest.TestCase):
    def test_non_allowlisted_operations_never_open_network(self):
        c = AgentResolveClient()
        with patch.object(c._opener, "open") as opening:
            for route in ("contracts/accept.php", "jobs/complete.php", "client/checkout.php"):
                with self.assertRaises(NetworkError):
                    c._request("POST", route)
            opening.assert_not_called()

    def test_redirect_is_refused(self):
        with self.assertRaises(NetworkError):
            NoRedirect().redirect_request(None, None, 302, None, None, "https://other.example")

    def test_start_uses_bearer_and_exact_payload(self):
        c = AgentResolveClient("ar_agent_test", "synthetic-not-a-real-token")
        response = io.BytesIO(json.dumps({"ok": True, "job": {"id": "ar_job_test", "status": "running"}}).encode())
        with patch.object(c._opener, "open", return_value=response) as opening:
            self.assertEqual(c.start_job("ar_job_test")["status"], "running")
        request = opening.call_args.args[0]
        self.assertEqual(request.full_url, "https://agentresolve.uk/api/v1/jobs/start.php")
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-not-a-real-token")
        self.assertEqual(json.loads(request.data), {"job_id": "ar_job_test", "public_id": "ar_agent_test"})

    def test_unknown_write_is_not_retried(self):
        c = AgentResolveClient("ar_agent_test", "synthetic-not-a-real-token")
        with patch.object(c._opener, "open", side_effect=TimeoutError) as opening:
            with self.assertRaises(NetworkError):
                c.start_job("ar_job_test")
            self.assertEqual(opening.call_count, 1)


if __name__ == "__main__":
    unittest.main()
