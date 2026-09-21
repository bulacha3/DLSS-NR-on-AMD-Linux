#!/usr/bin/env bash
# Publish only the successful build's portable archive. Never replace a release.
set -euo pipefail
: "${RELEASE_TAG:?}" "${GITHUB_SHA:?}" "${RUNNER_TEMP:?}" "${GH_REPO:?}"
python3 - <<'PY'
import json, os, re
from pathlib import Path
from urllib.parse import urljoin, urlsplit
manifest = json.loads(Path('assets/manifest.json').read_text())
version = manifest['version']
if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', version):
    raise SystemExit('Invalid release version format')
if version.split('-', 1)[0] != manifest['mod_version']:
    raise SystemExit('Release version must retain the upstream mod version')
assert os.environ['RELEASE_TAG'] == 'v' + version, 'Release/manifest version mismatch'
notes = Path('CHANGELOG.md').read_text()
base = f"https://github.com/{os.environ['GH_REPO']}/blob/{os.environ['GITHUB_SHA']}/"
def link(match):
    target = match.group(2)
    if urlsplit(target).scheme or target.startswith('//'):
        return match.group(0)
    resolved = base + 'CHANGELOG.md' + target if target.startswith('#') else urljoin(base, target)
    return match.group(1) + resolved + match.group(3)
notes = re.sub(r'(\[[^\]]+\]\()([^)]+)(\))', link, notes)
(Path(os.environ['RUNNER_TEMP']) / 'dlssnr-release-notes.md').write_text(notes)
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
        --target "$GITHUB_SHA" --title "${RELEASE_TAG#v} — Experimental" \
        --notes-file "$RUNNER_TEMP/dlssnr-release-notes.md"
fi
gh release upload "$RELEASE_TAG" \
    dist/dlssnr-linux-portable.tar.gz dist/dlssnr-linux-portable.tar.gz.sha256 --clobber
gh release edit "$RELEASE_TAG" --draft=false --prerelease --latest=false
