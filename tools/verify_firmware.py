#!/usr/bin/env python3
"""Verify the acquired corpus and record lossless roundtrips without retaining binaries."""
import argparse
import json
from pathlib import Path
import tempfile
from firmware import analyze, compare, digest, extract, checked_image, rebuild, require_target, revision, write_report

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'research/firmware-results.json')
    p.add_argument('--reports-dir',type=Path,default=ROOT/'artifacts/reports');args=p.parse_args()
    acquisition=json.loads((ROOT/'research/acquisition.json').read_text())
    results=[];images=[]
    for record in acquisition['releases']:
        version=record['version'];image=checked_image(ROOT/f'artifacts/original/7300_{version}.dat', 'analyze');images.append(image)
        if digest(image)!=record['image_sha256']:raise ValueError('Acquired image hash mismatch')
        report=analyze(image);write_report(report,args.reports_dir/version)
        with tempfile.TemporaryDirectory(prefix='ic7300-roundtrip-') as tmp:
            folder=Path(tmp)/'extracted';manifest=extract(image,folder)
            rebuilt=rebuild(folder)
            require_target(rebuilt, 'rebuild')
            if rebuilt!=image:raise ValueError('Roundtrip mismatch')
        results.append({'version':version,'roundtrip_identical':True,'sha256':digest(image),
                        'parts':manifest['parts'],'decoded':manifest['decoded']})
        print(version,'all payload digests, decompression and roundtrip verified')
    result={'source_revision':revision(),'releases':results,
            'diffs':[compare(images[i],images[i+1]) for i in range(len(images)-1)]}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
