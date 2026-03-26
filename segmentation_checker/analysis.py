import numpy as np
import pandas as pd
import SimpleITK as sitk


def compute_label_statistics(
    mri_image: sitk.Image,
    seg_image: sitk.Image,
) -> pd.DataFrame:
    """Compute per-label signal intensity statistics from an MRI image and its segmentation.

    Args:
        mri_image: The MRI image (SimpleITK).
        seg_image: The labeled segmentation image (SimpleITK, integer labels).

    Returns:
        DataFrame with columns: Label, Voxel Count, Mean, Std, Min, Max, Median.
    """
    # Ensure segmentation shares exact physical metadata to avoid floating-point tolerance errors
    seg_image = sitk.Resample(
        seg_image, mri_image,
        sitk.Transform(),
        sitk.sitkNearestNeighbor,
        0,
        seg_image.GetPixelID(),
    )

    stats_filter = sitk.LabelIntensityStatisticsImageFilter()
    stats_filter.Execute(seg_image, sitk.Cast(mri_image, sitk.sitkFloat64))

    rows = []
    for label in stats_filter.GetLabels():
        if label == 0:
            continue
        rows.append({
            "Label": int(label),
            "Voxel Count": stats_filter.GetNumberOfPixels(label),
            "Mean": round(stats_filter.GetMean(label), 2),
            "Std": round(stats_filter.GetStandardDeviation(label), 2),
            "Min": round(stats_filter.GetMinimum(label), 2),
            "Max": round(stats_filter.GetMaximum(label), 2),
            "Median": round(stats_filter.GetMedian(label), 2),
        })

    return pd.DataFrame(rows)
