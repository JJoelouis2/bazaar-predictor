import argparse
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
STEPS = [
    ("calendar", "seed_calendar.py"),
    ("collect", "collect.py"),
    ("train", "train.py"),
    ("predict", "predict.py"),
    ("build", "build.py"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip", nargs="*", default=[], choices=[s[0] for s in STEPS])
    parser.add_argument("--continue-on-error", action="store_true", help="keep going if a step fails")
    args = parser.parse_args()

    failures = []
    for name, script in STEPS:
        if name in args.skip:
            print(f"=== {name}: skipped ===", flush=True)
            continue
        print(f"=== {name}: {script} ===", flush=True)
        rc = subprocess.call([sys.executable, str(SRC / script)])
        if rc:
            failures.append((name, rc))
            print(f"=== {name}: FAILED rc={rc} ===", flush=True)
            if not args.continue_on_error:
                return rc
    if failures:
        print(f"pipeline finished with failures: {failures}", file=sys.stderr)
        return 1
    print("pipeline complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
