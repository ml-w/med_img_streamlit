"""Batch export of MRI + segmentation overlay images using multi-threading."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Tuple

import cv2
import numpy as np

from render_utils import render_current_pair

logger = logging.getLogger("App")


def render_pair(
    mri_path: Path,
    seg_path: Path,
    ncols: int = 5,
    contour_width: int = 2,
    contour_alpha: float = 1.0,
    window_lower: int = 25,
    window_upper: int = 99,
    display_width: int = 2800,
    crop_padding: int = 20,
) -> np.ndarray:
    """Render a single MRI/segmentation pair to an RGB overlay image.

    Delegates to render_utils.render_current_pair — single canonical implementation.

    Returns:
        BGR uint8 image (H, W, 3).
    Raises:
        RuntimeError: if rendering failed (e.g. empty segmentation after crop).
    """
    rendered_image, _, _, _, _ = render_current_pair(
        mri_path=mri_path,
        seg_path=seg_path,
        lower=window_lower,
        upper=window_upper,
        contour_width=contour_width,
        contour_alpha=contour_alpha,
        ncols=ncols,
        display_width=display_width,
        crop_padding=crop_padding,
    )
    if rendered_image is None:
        raise RuntimeError(f"render_current_pair returned None for {mri_path}")
    return rendered_image


def _export_one(
    pair_id: str,
    mri_path: Path,
    seg_path: Path,
    output_dir: Path,
    **render_kwargs,
) -> Tuple[str, bool, str]:
    """Export a single pair. Returns (pair_id, success, message)."""
    try:
        image = render_pair(mri_path, seg_path, **render_kwargs)
        out_path = output_dir / f"{pair_id}.png"
        cv2.imwrite(str(out_path), image)
        return (pair_id, True, str(out_path))
    except Exception as e:
        logger.error(f"Failed to export {pair_id}: {e}", exc_info=True)
        return (pair_id, False, str(e))


def batch_export(
    paired: Dict[str, Tuple[Path, Path]],
    output_dir: Path,
    max_workers: int = 4,
    progress_callback=None,
    **render_kwargs,
) -> list:
    """Export all paired images to output_dir using a thread pool.

    Args:
        paired: Dict mapping pair_id -> (mri_path, seg_path).
        output_dir: Directory to write PNG files.
        max_workers: Number of threads.
        progress_callback: Optional callable(completed, total) called after
            each image finishes.
        **render_kwargs: Forwarded to render_pair (ncols, contour_width, etc.).

    Returns:
        List of (pair_id, success, message) tuples.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(paired)
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _export_one, pair_id, mri_path, seg_path, output_dir, **render_kwargs
            ): pair_id
            for pair_id, (mri_path, seg_path) in paired.items()
        }
        for i, future in enumerate(as_completed(futures), 1):
            results.append(future.result())
            if progress_callback:
                progress_callback(i, total)

    return results
