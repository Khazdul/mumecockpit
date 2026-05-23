#!/usr/bin/env bash
set -euo pipefail

FILE="${1:-}"

if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
    exit 0
fi

python3 - "$FILE" <<'PYEOF'
import sys, re, os, tempfile

path = sys.argv[1]
class_pat = re.compile(
    rb'^\s*#class\s+\{[^}]+\}\s+\{?(open|close)\}?\s*$',
    re.IGNORECASE
)
profile_loaded_pat = re.compile(
    rb'^\s*#var(?:iable)?\s+\{_profile_loaded\}\s+\{[^}]*\}\s*$',
    re.IGNORECASE
)

with open(path, 'rb') as f:
    raw = f.read()

data = raw

# 1. Strip UTF-8 BOM
if data.startswith(b'\xef\xbb\xbf'):
    data = data[3:]

# 2. Normalize CRLF → LF, bare \r → nothing
data = data.replace(b'\r\n', b'\n').replace(b'\r', b'')

# Work on lines without endings (split on \n; rejoin preserves them)
lines = data.split(b'\n')

# 3. Strip #class {…} {open|close} wrapping lines
lines = [l for l in lines if not class_pat.match(l)]

# 3b. Strip stray #var {_profile_loaded} {…} lines (infrastructure flag —
# never belongs in a profile file; cleans files polluted by an earlier bug
# where the flag was set inside the open profile class).
lines = [l for l in lines if not profile_loaded_pat.match(l)]

# 4. Strip leading blank lines (whitespace-only until first non-blank)
while lines and not lines[0].strip():
    lines.pop(0)

result = b'\n'.join(lines)

if result == raw:
    sys.exit(0)

dir_ = os.path.dirname(os.path.abspath(path))
fd, tmp = tempfile.mkstemp(dir=dir_)
try:
    with os.fdopen(fd, 'wb') as out:
        out.write(result)
    os.replace(tmp, path)
except Exception:
    os.unlink(tmp)
    raise
PYEOF
