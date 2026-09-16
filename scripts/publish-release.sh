#!/usr/bin/env bash
# Publish only the successful build's portable archive. Never replace a release.
set -euo pipefail
: "${RELEASE_TAG:?}" "${GITHUB_SHA:?}" "${RUNNER_TEMP:?}"
python3 - <<'PY'
import json, os
from pathlib import Path
version = json.loads(Path('assets/manifest.json').read_text())['version']
assert os.environ['RELEASE_TAG'] == 'v' + version, 'Release/manifest version mismatch'
PY
(cd dist && sha256sum -c dlssnr-linux-portable.tar.gz.sha256)
if gh release view "$RELEASE_TAG" --json isDraft,targetCommitish > "$RUNNER_TEMP/dlssnr-release.json" 2>/dev/null; then
    if [ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["isDraft"])' "$RUNNER_TEMP/dlssnr-release.json")" = "False" ]; then
        echo 'Release already published; leaving it unchanged.'
        exit 0
    fi
    python3 - "$RUNNER_TEMP/dlssnr-release.json" <<'PY'
import json, os, sys
assert json.load(open(sys.argv[1]))['targetCommitish'] == os.environ['GITHUB_SHA'], 'Existing draft targets another commit'
PY
else
    gh release create "$RELEASE_TAG" --draft --prerelease --latest=false \
        --target "$GITHUB_SHA" --title '0.3.1 Linux — Experimental' \
        --notes-file CHANGELOG.md
fi
gh release upload "$RELEASE_TAG" \
    dist/dlssnr-linux-portable.tar.gz dist/dlssnr-linux-portable.tar.gz.sha256 --clobber
gh release edit "$RELEASE_TAG" --draft=false --prerelease --latest=false
