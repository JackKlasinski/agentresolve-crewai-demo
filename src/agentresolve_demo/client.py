"""Small HTTPS client. No registration, contract acceptance or payment methods."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

ORIGIN = "https://agentresolve.uk"
LIMIT = 524288
ROUTES = {
    ("GET", "network/status.php"), ("GET", "client/market.php"),
    ("GET", "jobs/get.php"), ("GET", "contracts/get.php"),
    ("POST", "jobs/start.php"), ("POST", "jobs/submit.php"),
}


class NetworkError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise NetworkError("Redirect refused; credentials stay on AgentResolve.")


class AgentResolveClient:
    def __init__(self, public_id="", token=""):
        self.public_id = public_id
        self._token = token
        self._opener = urllib.request.build_opener(NoRedirect)

    def _request(self, method, route, payload=None, auth=False):
        if (method, route) not in ROUTES:
            raise NetworkError("Unsupported API operation.")
        if auth and (not re.fullmatch(r"ar_agent_[a-z0-9]+", self.public_id)
                     or not self._token or len(self._token) > 512
                     or any(c.isspace() for c in self._token)):
            raise NetworkError("Set a valid AR_AGENT_ID and AR_MANAGEMENT_TOKEN privately.")
        data = dict(payload or {})
        headers = {"Accept": "application/json", "User-Agent": "AgentResolve-CrewAI-Demo/0.1"}
        if auth:
            data["public_id"] = self.public_id
            headers["Authorization"] = "Bearer " + self._token
        url = ORIGIN + "/api/v1/" + route
        body = None
        if method == "GET" and data:
            url += "?" + urllib.parse.urlencode(data)
        elif method == "POST":
            body = json.dumps(data, allow_nan=False).encode()
            headers["Content-Type"] = "application/json"
        try:
            with self._opener.open(urllib.request.Request(url, body, headers, method=method), timeout=15) as response:
                raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise NetworkError("Response exceeded the size limit.")
            result = json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise NetworkError(f"AgentResolve refused the request (HTTP {exc.code}).") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise NetworkError("Network outcome uncertain. Inspect the task before retrying a write.") from None
        except (ValueError, UnicodeError):
            raise NetworkError("Invalid API response.") from None
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise NetworkError("API did not confirm success. Inspect the task before retrying.")
        return result

    def status(self):
        return self._request("GET", "network/status.php")

    def market(self):
        return self._request("GET", "client/market.php")

    def get_job(self, job_id):
        return self._request("GET", "jobs/get.php", {"id": job_id}, True)["job"]

    def get_contract(self, contract_id):
        return self._request("GET", "contracts/get.php", {"id": contract_id}, True)["contract"]

    def start_job(self, job_id):
        return self._request("POST", "jobs/start.php", {"job_id": job_id}, True)["job"]

    def submit_job(self, job_id, report):
        if not isinstance(report, str) or len(report.encode()) > 4000:
            raise NetworkError("Report exceeds the sample limit.")
        return self._request("POST", "jobs/submit.php", {"job_id": job_id, "result_summary": report}, True)["job"]
