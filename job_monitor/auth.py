"""Configure the private Tailscale + passkey gateway using environment variables."""
import os
import sys
from . import register
from .passkey_gate import PasskeyGate, cli
GATE = PasskeyGate(
    "Job Hub", data_dir=os.path.join(register.DATA_DIR, "passkey"),
    host=os.environ.get("JOB_HUB_PUBLIC_HOST", "jobhub.example.invalid"),
    https_port=int(os.environ.get("JOB_HUB_HTTPS_PORT", "8446")),
    allowed_logins=[v.strip() for v in os.environ.get("JOB_HUB_ALLOWED_LOGINS", "").split(",") if v.strip()],
    cookie="jobhub_session", open_paths={"/health"},
)
if __name__ == "__main__":
    sys.exit(cli(GATE, sys.argv[1:]))
