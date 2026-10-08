"""Fail before paid worker deployment unless an operating record is approved."""
import os


def validate(record):
    fields = ("START", "END", "BUDGET", "BILLING_OWNER", "BILLING_ACCOUNT",
              "SHUTDOWN_OWNER", "SHUTDOWN_PROCEDURE")
    if record.get("APPROVED") != "true" or any(not record.get(k, "").strip() for k in fields):
        raise ValueError("Paid worker deployment requires approval and a complete operating record")


if __name__ == "__main__":
    validate({k.removeprefix("TEAM_OPERATION_"): v for k, v in os.environ.items()
              if k.startswith("TEAM_OPERATION_")})
