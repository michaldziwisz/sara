E2E on Windows with pywinauto relies on finding the SARA window via UIA. If tests hang on startup, run with -s to see the list of visible windows and their PIDs.
Typical run:
  set RUN_SARA_E2E=1
  set PYTHONPATH=src
  python -m pytest -m e2e tests/e2e -s
Ensure no stale SARA instance is open before running.
