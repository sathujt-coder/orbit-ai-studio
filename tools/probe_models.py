#!/usr/bin/env python3
"""Check model routing configuration or explicitly perform two short provider calls."""
import argparse
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
import model_provider

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute',action='store_true')
    p.add_argument('--confirm',default='')
    a=p.parse_args(argv)
    try:
        lanes=model_provider.require_distinct_real(model_provider.load_config(os.environ))
        if not a.execute:
            print(json.dumps({'mode':'configuration_only','configuration':model_provider.public_config(lanes)},indent=2))
            return 0
        if a.confirm!='PROBE REAL MODELS':raise ValueError('Explicit confirmation PROBE REAL MODELS required')
        report=model_provider.probe(lanes)
        print(json.dumps(report,indent=2))
        return 0 if report['both_responded'] else 2
    except ValueError as exc:
        print('Configuration error: '+str(exc),file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())
