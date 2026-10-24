"""Ręczna kontrola dwóch mutantów serwera, bez edycji plików źródłowych.

Uruchom: python3 scripts/check_remote_mutations.py
Każdy mutant jest ładowany wyłącznie do pamięci osobnego procesu pytest.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MUTATIONS = (
    (
        "bind-wszystkie-interfejsy",
        'super().__init__(("127.0.0.1", port), _ClientHandler)',
        'super().__init__(("0.0.0.0", port), _ClientHandler)',
        "tests/test_remote_server.py::test_socket_bind_is_loopback_and_other_local_address_cannot_connect",
    ),
    (
        "wykonanie-w-watku-klienta",
        "self._call_after(invoke)",
        "return function(*args)",
        "tests/test_remote_server.py::test_real_socket_commands_run_on_main_thread",
    ),
)


def main() -> int:
    failed = False
    for name, old, new, test in MUTATIONS:
        program = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(ROOT / 'src')!r})
import sara.remote.server as module
path = Path(module.__file__)
source = path.read_text(encoding='utf-8')
assert source.count({old!r}) == 1
exec(compile(source.replace({old!r}, {new!r}), str(path), 'exec'), module.__dict__)
import pytest
raise SystemExit(pytest.main(['-q', {test!r}]))
"""
        result = subprocess.run([sys.executable, "-c", program], cwd=ROOT, capture_output=True, text=True, timeout=30)
        killed = result.returncode == 1 and "1 failed" in result.stdout and "AssertionError" in result.stdout
        print(f"{name}: {'ZABITY' if killed else 'BŁĄD WERYFIKACJI'} (exit={result.returncode})")
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        failed |= not killed
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
