#!/usr/bin/env python3
"""PalmClix SQ905 offline Bayer decoder.

'dsc-matched' is a learned approximation, NOT a bit-for-bit port of SQDLL.dll.
It was calibrated from ten matched USB raw frames and Windows DSC bitmap exports,
with leave-one-photo-out validation (see COLOR_VALIDATION.json).

The 'legacy' decoder reproduces the earlier 0.4 calibration for comparison.
All operations are offline; neither decoder interacts with the camera.
"""
import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

DEFAULT_MATRIX = np.array([
    [1.53020974, -0.02232883, -0.03983049],
    [0.38313870,  1.77005671,  0.36287548],
    [-0.47752352, -0.42182485, 0.94828424],
    [15.10806425, 15.33150761, 12.97009732],
], dtype=np.float64)

# 10-feature quadratic RGB model (raw channels normalized to 128):
# r,g,b,r²,g²,b²,rg,rb,gb,1. Calibrated from 10 original DSC BMPs.
# Coefficients are a documented empirical fit, not the original DSC source.
DSC_MATCHED_COEFFICIENTS = np.array([
    [209.09491340, -43.65797390, -80.46794133],
    [47.65050875, 282.97481703, 128.56010420],
    [24.30034297, -8.66160650, 228.16234164],
    [-50.55282211, 0.96443395, -8.35555699],
    [11.72628396, -97.80939667, -124.32720134],
    [-37.19104166, -17.28987641, -118.97571047],
    [-58.65060882, 24.74919185, 62.23517454],
    [56.76371475, -2.00142655, -4.66443317],
    [0.59471555, 37.81088564, 117.10363157],
    [2.97209076, 7.27202760, 5.60694143],
], dtype=np.float32)


def decode_mosaic(path, *, profile='dsc-matched'):
    gray = np.asarray(Image.open(path).convert('L'), dtype=np.uint8)
    if gray.shape != (480, 640):
        raise ValueError(f'{path}: expected 640x480, found {gray.shape[::-1]}')
    oriented = np.ascontiguousarray(gray[::-1, :])
    if profile == 'dsc-matched':
        # VNG demosaicing scored marginally better against the independent DSC
        # reference exports than bilinear demosaicing.
        return cv2.cvtColor(oriented, cv2.COLOR_BayerGB2RGB_VNG)
    if profile == 'legacy':
        return cv2.cvtColor(oriented, cv2.COLOR_BayerGB2RGB)
    raise ValueError(f'Unsupported color profile {profile!r}')


def fit_matrix(decoded, reference):
    """Legacy 4x3 affine calibration API retained for compatibility."""
    target = np.asarray(Image.open(reference).convert('RGB'), dtype=np.uint8)
    if target.shape != decoded.shape:
        raise ValueError('Calibration BMP must be 640x480 RGB')
    valid = ((target.min(axis=2) > 8) & (target.max(axis=2) < 248)
             & (decoded.min(axis=2) > 5) & (decoded.max(axis=2) < 250))
    rgb = decoded[valid].astype(np.float64)
    ref = target[valid].astype(np.float64)
    if len(rgb) < 1000:
        raise ValueError('Insufficient unsaturated pixels for fitting')
    return np.linalg.lstsq(np.column_stack((rgb[::5], np.ones(len(rgb[::5])))), ref[::5], rcond=None)[0]


def calibrate(image, matrix=DEFAULT_MATRIX):
    rgb = image.astype(np.float32) @ matrix[:3, :].astype(np.float32) + matrix[3, :].astype(np.float32)
    return np.clip(rgb, 0, 255).astype('uint8')


def dsc_matched(image):
    """Apply the learned non-linear DSC-style color curve without large intermediates."""
    # Work in float32, with only a few 640x480 temporary arrays (<35 MB).
    rgb = image.astype(np.float32) / 128.0
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    features = (r, g, b, r*r, g*g, b*b, r*g, r*b, g*b)
    result = np.empty_like(rgb)
    for channel in range(3):
        v = np.full(r.shape, DSC_MATCHED_COEFFICIENTS[9, channel], dtype=np.float32)
        for k, feature in enumerate(features):
            v += DSC_MATCHED_COEFFICIENTS[k, channel] * feature
        result[:, :, channel] = np.clip(v, 0, 255)
    return result.astype(np.uint8)


def convert_raw(path, profile='dsc-matched'):
    raw = decode_mosaic(path, profile=profile)
    if profile == 'dsc-matched':
        return dsc_matched(raw)
    return calibrate(raw, DEFAULT_MATRIX)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw_folder', type=Path)
    parser.add_argument('--output', type=Path, default=Path('palmclix_photos'))
    parser.add_argument('--profile', choices=['dsc-matched','legacy'], default='dsc-matched')
    parser.add_argument('--reference', type=Path,
                        help='Legacy mode only: fit an affine matrix to a DSC export of photo 1')
    args = parser.parse_args(argv)
    sources = sorted(args.raw_folder.glob('PalmClix_*.pgm'))
    if not sources:
        parser.error('No PalmClix_*.pgm files found')
    args.output.mkdir(parents=True, exist_ok=True)
    matrix = DEFAULT_MATRIX
    if args.reference:
        if args.profile != 'legacy':
            parser.error('--reference is supported with --profile legacy only')
        matrix = fit_matrix(decode_mosaic(args.raw_folder/'PalmClix_01.pgm', profile='legacy'), args.reference)
    if args.profile == 'legacy':
        np.savetxt(args.output/'calibration_matrix.txt', matrix, fmt='%.9f')
    for source in sources:
        rgb = (calibrate(decode_mosaic(source, profile='legacy'), matrix) if args.reference
               else convert_raw(source, profile=args.profile))
        destination = args.output/f'{source.stem}_color.png'
        Image.fromarray(rgb,'RGB').save(destination)
        print(f'Wrote {destination}')


if __name__ == '__main__':
    main()
