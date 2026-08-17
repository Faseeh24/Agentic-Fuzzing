# Allow running the triage package as a module:  python -m triage
from triage.run import run_triage
import sys

if __name__ == "__main__":
    result = run_triage()
    confirmed = result.get("confirmed", 0)
    sys.exit(0 if confirmed > 0 else 1)
