"""Run unittest with a concise GitHub summary and name-only failure annotations."""

import os
import sys
import unittest
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if os.getenv('GITHUB_ACTIONS') == 'true':
        for test, _ in result.failures + result.errors:
            # Only identifiers: never forward exception values into annotations.
            identifier = test.id().replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
            print(f'::error title=Autonomous test failed::{identifier}', flush=True)
    if summary := os.getenv('GITHUB_STEP_SUMMARY'):
        with open(summary, 'a', encoding='utf-8') as stream:
            stream.write(f'## Autonomous tests\n\n'
                         f'- Discovered: {result.testsRun}\n'
                         f'- Skipped: {len(result.skipped)}\n'
                         f'- Failures: {len(result.failures)}\n'
                         f'- Errors: {len(result.errors)}\n')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
