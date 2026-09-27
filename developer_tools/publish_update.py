"""Publish only the built installer and signed manifest to the public updates repository."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from developer_tools.license_generator import DEFAULT_PRIVATE_KEY
from developer_tools.prepare_update import prepare_update
from sanitary_pos.updater import UPDATE_REPOSITORY, UPDATE_MANIFEST_URL
from sanitary_pos.version import APP_VERSION


def github_token():
    # Ask the configured credential helper; never print or persist its response.
    result = subprocess.run(
        ['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
        capture_output=True, text=True, cwd=ROOT,
        env=os.environ | {'GCM_INTERACTIVE': 'Never', 'GIT_TERMINAL_PROMPT': '0'}, timeout=30,
    )
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if result.returncode or not values.get('password'):
        raise RuntimeError('GitHub sign-in is required. Sign in through Git Credential Manager, then retry.')
    return values['password']


class GitHub:
    def __init__(self, token):
        self.token = token

    def request(self, method, path, document=None, asset=None):
        url = path if path.startswith('https://') else 'https://api.github.com' + path
        if urllib.parse.urlsplit(url).hostname not in {'api.github.com', 'uploads.github.com'}:
            raise ValueError('Unexpected GitHub API host.')
        headers = {'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                   'User-Agent': 'SanitaryShopPOS-Publisher', 'X-GitHub-Api-Version': '2022-11-28'}
        data = None
        if asset is not None:
            data = Path(asset).read_bytes()
            headers['Content-Type'] = 'application/octet-stream'
        elif document is not None:
            data = json.dumps(document).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)


def publish(api, installer, notes, private_key):
    owner, name = UPDATE_REPOSITORY.split('/')
    account = api.request('GET', '/user')
    if account['login'].lower() != owner.lower():
        raise RuntimeError(f'Sign in as {owner} before publishing.')
    tag = 'v' + APP_VERSION
    base = '/repos/' + UPDATE_REPOSITORY
    installer = Path(installer)
    if not installer.is_file() or installer.stat().st_size < 1024:
        raise ValueError('Build the installer first using build.ps1.')
    metadata_path = installer.parent / 'release-build.json'
    if not metadata_path.is_file():
        raise ValueError('Installer build metadata is missing. Run build.ps1 before publishing.')
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    with installer.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if metadata != {'version': APP_VERSION, 'sha256': digest, 'manifest_url': UPDATE_MANIFEST_URL}:
        raise ValueError('The installer does not match the current release. Run build.ps1 again.')
    manifest_path = installer.parent / 'update.json'
    download_url = f'https://github.com/{UPDATE_REPOSITORY}/releases/download/{tag}/SanitaryShopPOS-Setup.exe'
    manifest = prepare_update(installer, download_url, manifest_path, notes, private_key=private_key)
    try:
        repository = api.request('GET', base)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        repository = api.request('POST', '/user/repos', {
            'name': name, 'description': 'Official Sanitary Shop POS Windows installers and update feed.',
            'private': False, 'auto_init': True,
        })
    if repository.get('private'):
        raise RuntimeError('The updates repository is private. Client downloads require a public repository.')
    releases = api.request('GET', base + '/releases?per_page=100')
    release = next((item for item in releases if item['tag_name'] == tag), None)
    if release and not release['draft']:
        raise RuntimeError(f'{tag} is already published. Increase APP_VERSION before publishing another update.')
    body = '\n'.join('- ' + note for note in notes)
    if not release:
        release = api.request('POST', base + '/releases', {
            'tag_name': tag, 'name': 'Sanitary Shop POS ' + APP_VERSION,
            'body': body, 'draft': True, 'prerelease': False,
        })
    assets = {item['name']: item for item in release.get('assets', [])}
    for path, name in ((installer, 'SanitaryShopPOS-Setup.exe'), (manifest_path, 'update.json')):
        expected_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        existing = assets.get(name)
        if existing:
            if existing.get('digest') != 'sha256:' + expected_hash or existing['size'] != path.stat().st_size:
                raise RuntimeError(f'The existing draft asset {name} differs. Remove that draft asset in GitHub and retry.')
            continue
        print(f'Uploading {name}...', flush=True)
        url = release['upload_url'].split('{', 1)[0] + '?name=' + urllib.parse.quote(name)
        uploaded = api.request('POST', url, asset=path)
        if uploaded['size'] != path.stat().st_size or uploaded.get('state') != 'uploaded':
            raise RuntimeError('Upload incomplete. The release has been left as a draft.')
        if uploaded.get('digest') and uploaded['digest'] != 'sha256:' + expected_hash:
            raise RuntimeError('Upload hash mismatch. The release has been left as a draft.')
    release = api.request('PATCH', base + '/releases/' + str(release['id']), {
        'draft': False, 'make_latest': 'true', 'body': body,
    })
    print('Published: ' + release['html_url'])
    print('Installer SHA-256: ' + manifest['sha256'])
    return release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true', help='Upload and publish the current built version')
    parser.add_argument('--installer', type=Path, default=ROOT / 'dist' / 'SanitaryShopPOS-Setup.exe')
    parser.add_argument('--private-key', type=Path, default=DEFAULT_PRIVATE_KEY)
    parser.add_argument('--notes', type=Path, default=ROOT / 'developer_tools' / 'release-notes.txt')
    args = parser.parse_args()
    try:
        api = GitHub(github_token())
        if not args.publish:
            account = api.request('GET', '/user')
            print('GitHub account: ' + account['login'])
            print('Update repository: ' + UPDATE_REPOSITORY)
            return
        notes = [line.strip() for line in args.notes.read_text(encoding='utf-8').splitlines() if line.strip()]
        publish(api, args.installer, notes, args.private_key)
    except urllib.error.HTTPError as error:
        raise SystemExit(f'GitHub request failed (HTTP {error.code}). Check account access and retry.') from None
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None


if __name__ == '__main__':
    main()
