#!/usr/bin/env python3
"""Acquire official archives using the download links on Icom's release pages."""
import argparse
import datetime
import hashlib
import html
import io
import json
from pathlib import Path
import re
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RELEASES = {'140': 3248, '141': 3339, '142': 4102}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024:
            raise ValueError('download exceeds size limit')
        return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='verify against tracked manifest')
    args = parser.parse_args()
    original = ROOT / 'artifacts/original'
    original.mkdir(parents=True, exist_ok=True)
    manifest_path = ROOT / 'research/acquisition.json'
    expected = json.loads(manifest_path.read_text()) if args.verify else None
    records = []
    for version, post in RELEASES.items():
        page = f'https://www.icomjapan.com/support/firmware_driver/{post}/'
        content = fetch(page).decode('utf-8')
        match = re.search(r"/api/download\.php\?post_id=\d+&(?:amp;)?fl=[A-Za-z0-9=+/]+", content)
        if not match:
            raise ValueError(f'No official download link on {page}')
        url = 'https://www.icomjapan.com' + html.unescape(match.group())
        archive = fetch(url)
        name = f'7300_{version}.dat'
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            if z.namelist() != [name] or z.getinfo(name).file_size > 16 * 1024 * 1024:
                raise ValueError('Unexpected ZIP content')
            data = z.read(name)  # validates ZIP CRC; not cryptographic authentication
        record = dict(version=version, page=page, url=url,
                      acquired_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      archive_bytes=len(archive), archive_sha256=sha(archive),
                      image_bytes=len(data), image_sha256=sha(data))
        if expected:
            old = next(r for r in expected['releases'] if r['version'] == version)
            for field in ('archive_sha256', 'image_sha256'):
                if old[field] != record[field]:
                    raise ValueError(f'Upstream bytes changed: {version} {field}')
        for filename, blob in ((f'7300_{version}.zip', archive), (name, data)):
            target = original / filename
            if target.exists() and target.read_bytes() != blob:
                raise ValueError(f'Refusing to replace different artifact: {target}')
            target.write_bytes(blob)
        records.append(record)
        print(version, len(data), sha(data))
    if not expected:
        mirror = Path('/tmp/7300_142.dat')
        result = dict(source_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                      releases=records,
                      mirror_comparison={'path': str(mirror), 'sha256': sha(mirror.read_bytes()),
                                         'matches_official_142': sha(mirror.read_bytes()) == records[-1]['image_sha256']} if mirror.exists() else None)
        manifest_path.parent.mkdir(exist_ok=True)
        manifest_path.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
