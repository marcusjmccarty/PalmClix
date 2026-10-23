#!/usr/bin/env python3
"""Recompute PalmClix DSC-matched color profile and independent photo-holdout error.

Source material: two owner-supplied successful XP USB captures and ten owner-supplied
original Windows DSC BMPs. Does not access USB hardware.
"""
from __future__ import annotations
import argparse
import json
import pathlib
import sys
import tempfile

import cv2
import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from palmclix import RecordedDevice, transfer
from decode_palmclix import DEFAULT_MATRIX, DSC_MATCHED_COEFFICIENTS

REFERENCES = ([('ten', 1, 'capturetest001.bmp'),
               ('ten', 7, 'calibrate001.bmp'),
               ('ten', 8, 'calibrate002.bmp')]
              + [('seven', i, f'troubleshoot{i:03d}.bmp') for i in range(1,8)])


def features(im):
    z = im.astype(np.float32) / 128
    r, g, b = (z[:,:,i:i+1] for i in range(3))
    return np.concatenate((z, z*z, r*g, r*b, g*b, np.ones_like(r)), axis=-1).reshape(-1,10)


def run():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=pathlib.Path,
                    help='Optional JSON validation report; stdout otherwise')
    args = ap.parse_args()
    rng = np.random.default_rng(2113)
    data = []
    with tempfile.TemporaryDirectory(prefix='palmclix_color_validation_') as temporary:
        tmp = pathlib.Path(temporary)
        for label, cap in [('ten', ROOT/'reference_capture.pcap'),
                           ('seven', ROOT/'tests/fixtures/seven_photo_capture.pcap')]:
            dev = RecordedDevice(cap)
            transfer(dev, 'auto', tmp/label, fmt='none')
            dev.finished()
        for label, number, basename in REFERENCES:
            raw = np.array(Image.open(tmp/label/f'PalmClix_{number:02d}.pgm').convert('L'))
            oriented = np.ascontiguousarray(raw[::-1])
            rgb = cv2.cvtColor(oriented, cv2.COLOR_BayerGB2RGB_VNG)
            legacy_rgb = cv2.cvtColor(oriented, cv2.COLOR_BayerGB2RGB)
            truth = np.array(Image.open(ROOT/'reference_bmps'/basename).convert('RGB'))
            assert rgb.shape == truth.shape == (480, 640, 3)
            x, y = features(rgb), truth.reshape(-1,3).astype(np.float64)
            sample = rng.choice(len(x), 9000, replace=False)
            legacy = np.clip(legacy_rgb.reshape(-1,3)[::17].astype(np.float64)
                             @ DEFAULT_MATRIX[:3] + DEFAULT_MATRIX[3],0,255)
            data.append((basename, x[sample].astype(np.float64), y[sample],
                         x[::17].astype(np.float64), y[::17], legacy))
    coefficients = np.linalg.lstsq(np.vstack([p[1] for p in data]),
                                    np.vstack([p[2] for p in data]), rcond=None)[0]
    errors = []
    for j, (name, _, _, x_test, y_test, legacy) in enumerate(data):
        x_train = np.vstack([v[1] for i,v in enumerate(data) if i != j])
        y_train = np.vstack([v[2] for i,v in enumerate(data) if i != j])
        loo = np.linalg.lstsq(x_train, y_train, rcond=None)[0]
        pred = np.clip(x_test @ loo, 0, 255)
        baseline = legacy
        errors.append({'file': name,
                       'legacy_mae': float(np.abs(baseline-y_test).mean()),
                       'dsc_matched_holdout_mae': float(np.abs(pred-y_test).mean())})
    delta = float(np.max(np.abs(coefficients - DSC_MATCHED_COEFFICIENTS)))
    report = {'n_reference_photos': 10, 'training_samples_per_photo': 9000,
              'validation': 'leave-one-entire-photo-out; every 17th pixel',
              'legacy_mean_mae': float(np.mean([r['legacy_mae'] for r in errors])),
              'dsc_matched_mean_mae': float(np.mean([r['dsc_matched_holdout_mae'] for r in errors])),
              'max_coefficient_difference_from_shipped_profile': delta,
              'per_photo': errors}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    if report['dsc_matched_mean_mae'] > report['legacy_mean_mae'] * 0.65:
        raise SystemExit('FAIL: color model did not improve cross-validated accuracy')
    if delta > .01:
        raise SystemExit('FAIL: shipped profile does not match input BMPs and raw captures')
    print('PASS: DSC-matched calibration reproducibly improves ten-photo holdout error.')


if __name__ == '__main__':
    run()
