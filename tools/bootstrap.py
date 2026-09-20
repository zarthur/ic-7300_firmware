#!/usr/bin/env python3
"""Fetch pinned source dependencies without modifying their tracked content."""
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
for dependency in json.loads((root / 'research/dependencies.json').read_text()).values():
    target = root / dependency['location']
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', dependency['url'], str(target)], check=True)
    current = subprocess.check_output(['git', '-C', str(target), 'rev-parse', 'HEAD'], text=True).strip()
    if current != dependency['revision']:
        if subprocess.check_output(['git', '-C', str(target), 'status', '--porcelain'], text=True).strip():
            raise SystemExit(f'Refusing to change dirty dependency {target}')
        subprocess.run(['git', '-C', str(target), 'checkout', '--detach', dependency['revision']], check=True)
    print(target.name, dependency['revision'])
