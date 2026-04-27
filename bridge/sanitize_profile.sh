#!/usr/bin/env bash
set -euo pipefail

FILE="${1:-}"

if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
    exit 0
fi

python3 - "$FILE" <<'PYEOF'
import sys, re, os, tempfile

path = sys.argv[1]
pattern = re.compile(
    r'^\s*#class\s+\{[^}]+\}\s+\{?(open|close)\}?\s*$',
    re.IGNORECASE
)

with open(path, 'r', newline='') as f:
    lines = f.readlines()

filtered = [line for line in lines if not pattern.match(line.rstrip('\r\n'))]

if filtered == lines:
    sys.exit(0)

dir_ = os.path.dirname(os.path.abspath(path))
fd, tmp = tempfile.mkstemp(dir=dir_)
try:
    with os.fdopen(fd, 'w', newline='') as out:
        out.writelines(filtered)
    os.replace(tmp, path)
except Exception:
    os.unlink(tmp)
    raise
PYEOF
