#!/usr/bin/env python3
"""Offline validation of the original DSC exports against frames 1,7,8.

Do not treat color calibration MAE on frame 1 as independent validation:
frame 1 was used to train the provided matrix. Frames 7 and 8 were not.
"""
from pathlib import Path
import sys
import numpy as np
import cv2
from PIL import Image
from decode_palmclix import DEFAULT_MATRIX

root = Path(__file__).resolve().parent
pgms = root / 'reference_raw'
refs = {1: root/'reference_bmps'/'capturetest001.bmp',
        7: root/'reference_bmps'/'calibrate001.bmp',
        8: root/'reference_bmps'/'calibrate002.bmp'}
for i, filename in refs.items():
    if not filename.exists():
        print(f'Missing {filename}; put reference BMPs in reference_bmps/ to run the check.')
        sys.exit(2)
    source = pgms/f'PalmClix_{i:02d}.pgm'
    if not source.exists():
        print('Missing reference_raw; run the --simulate command with --output reference_raw')
        sys.exit(2)
    mosaic = np.asarray(Image.open(source).convert('L'))
    decoded = cv2.cvtColor(np.ascontiguousarray(mosaic[::-1,:]), cv2.COLOR_BayerGB2RGB)
    output = np.clip(decoded.astype(np.float32) @ DEFAULT_MATRIX[:3].astype(np.float32) + DEFAULT_MATRIX[3].astype(np.float32),0,255)
    target = np.asarray(Image.open(filename).convert('RGB')).astype(np.float32)
    mae = np.abs(output-target).mean()
    correlation = np.corrcoef(output.mean(2).ravel()[::20],target.mean(2).ravel()[::20])[0,1]
    print(f'frame {i:02}: per-channel MAE={mae:.2f}/255; intensity correlation={correlation:.4f}' + (' (training image)' if i==1 else ' (independent image)'))
