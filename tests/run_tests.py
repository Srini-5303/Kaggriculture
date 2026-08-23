"""Run the test suite without pytest (which is not installed here).

The test files are still plain pytest-style, so `pytest tests/` works too if you
install it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import test_market

    failures = []
    names = [n for n in dir(test_market) if n.startswith("test_")]
    for name in names:
        try:
            getattr(test_market, name)()
            print(f"  PASS  {name}")
        except Exception as exc:  # noqa: BLE001
            failures.append(name)
            print(f"  FAIL  {name}: {exc}")
    print(f"\n{len(names) - len(failures)}/{len(names)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
