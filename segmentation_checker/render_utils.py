import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import pandas as pd
import SimpleITK as sitk
from functools import lru_cache
from visualization import (
    crop_image_to_segmentation_sitk,
    draw_contour,
    make_grid,
    rescale_intensity_3d,
)
from analysis import compute_label_statistics
import streamlit as st # Just for cache

logger = logging.getLogger("App")


def check_image_metadata(
    img1: sitk.Image,
    img2: sitk.Image,
    tolerance: float = 1e-3,
) -> tuple[bool, list[tuple[str, str]]]:
    """Check whether two SimpleITK images share the same spatial metadata.

    Returns:
        (is_match, messages) where messages is a list of (level, text) tuples.
        level is 'success' or 'error'.
    """
    spacing_match = np.all(np.isclose(img1.GetSpacing(), img2.GetSpacing(), atol=tolerance))
    direction_match = np.all(np.isclose(img1.GetDirection(), img2.GetDirection(), atol=tolerance))
    origin_match = np.all(np.isclose(img1.GetOrigin(), img2.GetOrigin(), atol=tolerance))
    size_match = np.array_equal(img1.GetSize(), img2.GetSize())

    messages: list[tuple[str, str]] = []
    if spacing_match and direction_match and origin_match:
        messages.append(('success', "All metadata matches: spacing, direction, and origin."))
    else:
        if not spacing_match:
            messages.append(('error', f"Spacing does not match: {img1.GetSpacing() = } | {img2.GetSpacing() = }"))
        if not direction_match:
            messages.append(('error', f"Direction does not match: {img1.GetDirection() = } | {img2.GetDirection() = }"))
        if not origin_match:
            messages.append(('error', f"Origin does not match: {img1.GetOrigin() = } | {img2.GetOrigin() = }"))
        if not size_match:
            messages.append(('error', f"Size does not match: {img1.GetSize() = } | {img2.GetSize() = }"))

    is_match = all([spacing_match, direction_match, origin_match, size_match])
    return is_match, messages

st.cache_data
def render_current_pair(
    mri_path: Path,
    seg_path: Path,
    lower: int,
    upper: int,
    contour_width: int,
    contour_alpha: float,
    ncols: int = 5,
    display_width: int = 1400,
    crop_padding: int = 20,
) -> tuple[Optional[np.ndarray], pd.DataFrame, bool, list[tuple[str, str]], list[str]]:
    """Load, process, and render an MRI/segmentation pair into a displayable image.

    All rendering parameters are passed explicitly — no Streamlit calls inside.

    Returns:
        rendered_image:    BGR uint8 ndarray, or None if rendering failed fatally
        intensity_stats:   per-label signal statistics DataFrame (may be empty)
        metadata_match:    True if spatial metadata is consistent
        metadata_messages: list of (level, text) from check_image_metadata
        warning_messages:  list of human-readable warning strings
    """
    warning_messages: list[str] = []
    intensity_stats = pd.DataFrame()

    # Load images
    mri_image = sitk.ReadImage(str(mri_path))
    seg_image = sitk.ReadImage(str(seg_path))

    # Check spatial metadata consistency
    metadata_match, metadata_messages = check_image_metadata(mri_image, seg_image)
    if not metadata_match:
        warning_messages.append("Resampling segmentation to match MRI space.")
        seg_image = sitk.Resample(seg_image, mri_image)

    # Crop to segmentation bounding box; track originals for stats fallback
    mri_for_stats, seg_for_stats = mri_image, seg_image
    try:
        mri_image, seg_image = crop_image_to_segmentation_sitk(mri_image, seg_image, crop_padding)
        mri_for_stats, seg_for_stats = mri_image, seg_image
    except ValueError as e:
        warning_messages.append("Something wrong with the segmentation.")
        logger.error(e, exc_info=True)
    except IndexError as e:
        warning_messages.append("The segmentation seems to be empty.")
        logger.error(e, exc_info=True)

    # Compute per-label statistics on sitk images (before numpy conversion)
    intensity_stats = compute_label_statistics(mri_for_stats, seg_for_stats)

    # Convert to numpy
    mri_image = sitk.GetArrayFromImage(mri_image)
    seg_image = sitk.GetArrayFromImage(seg_image)

    # Rescale, grid layout, upscale
    mri_image = rescale_intensity_3d(mri_image, lower=lower, upper=upper)
    mri_image = make_grid(mri_image, ncols=ncols)
    seg_image = make_grid(seg_image, ncols=ncols).astype('int')

    scale = display_width / mri_image.shape[1]
    target_size = (display_width, int(mri_image.shape[0] * scale))
    mri_image = cv2.resize(mri_image, target_size, interpolation=cv2.INTER_CUBIC)
    seg_image = cv2.resize(seg_image.astype(np.uint8), target_size, interpolation=cv2.INTER_NEAREST).astype(int)

    # Draw contours
    rendered_image: Optional[np.ndarray] = None
    try:
        rendered_image = draw_contour(mri_image, seg_image, width=contour_width, alpha=contour_alpha)
    except ValueError:
        warning_messages.append("Something wrong with the segmentation contour.")

    return rendered_image, intensity_stats, metadata_match, metadata_messages, warning_messages
