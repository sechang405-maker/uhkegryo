"""Send a synthetic worker span and verify receipt via Langfuse v4 Observations API."""
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
values = dict(os.environ)
if len(sys.argv) > 1:
    for line in Path(sys.argv[1]).read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("LANGFUSE_") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"').strip("'")
host = values.get("LANGFUSE_APP_URL") or values.get("LANGFUSE_BASE_URL") or values.get("LANGFUSE_HOST") or "http://localhost:3000"
for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
    os.environ[key] = values[key]
os.environ["LANGFUSE_BASE_URL"] = os.environ["LANGFUSE_HOST"] = host
from backend.services.job_trace import JobTracer

tracer = JobTracer.from_settings()
assert tracer.client and tracer.client.auth_check(), "Langfuse authentication failed"
job_id = str(uuid.uuid4())
with tracer.attempt({"job_id": job_id, "session_id": "deployment-verification", "attempt": 1,
                     "max_attempts": 1, "request_text": "Connectivity verification; no user data"}) as trace:
    with trace.stage("deployment-verification"):
        pass
tracer.shutdown()
trace_id = tracer.client.create_trace_id(seed=job_id)
auth = base64.b64encode(f'{values["LANGFUSE_PUBLIC_KEY"]}:{values["LANGFUSE_SECRET_KEY"]}'.encode()).decode()
now = datetime.now(timezone.utc)
query = urlencode({"traceId": trace_id, "fromStartTime": (now-timedelta(hours=1)).isoformat(),
                   "toStartTime": (now+timedelta(minutes=5)).isoformat()})
request = Request(f"{host}/api/public/v2/observations?{query}", headers={"Authorization": f"Basic {auth}"})
for attempt in range(30):
    try:
        with urlopen(request, timeout=10) as response:
            rows = json.load(response)["data"]
        assert any(row["traceId"] == trace_id for row in rows), "Observation not indexed"
        print(json.dumps({"host": host, "trace_id": trace_id, "received": True}))
        break
    except (HTTPError, URLError, AssertionError):
        if attempt == 29:
            raise RuntimeError("Trace receipt not verified") from None
        time.sleep(2)
