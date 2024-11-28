import cv2
import numpy as np
import SimpleITK as sitk
import streamlit as st

logger = st.logger.get_logger("App")

def make_grid(array, nrows=None, ncols=None, padding=2, normalize=False):
    """
    Convert a 3D numpy array to a grid of images.

    Args:
        array (np.ndarray): Input array to be converted, should be 3D (D x H x W).
        nrows (int): Number of images in each row.
        ncols (int): Number of images in each column.
        padding (int): Amount of padding between images.
        normalize (bool): If True, normalize each image to the range (0, 1).

    Returns:
        np.ndarray: An array containing the grid of images.
    """
    depth, height, width = array.shape

    # Calculate nrows and ncols if None
    if nrows is None and ncols is not None:
        nrows = max(int(np.ceil(depth / ncols)), 1)
    elif ncols is None and nrows is not None:
        ncols = max(int(np.ceil(depth / nrows)), 1)
    elif nrows is None and ncols is None:
        nrows = max(int(np.ceil(np.sqrt(depth))), 1)
        ncols = max(int(np.ceil(depth / nrows)), 1)

    # Normalize if needed
    if normalize:
        array = (array - array.min()) / (array.max() - array.min())

    # Calculate grid height and width
    grid_height = nrows * height + (nrows - 1) * padding
    grid_width = ncols * width + (ncols - 1) * padding

    # Initialize grid with zeros
    grid = np.zeros((grid_height, grid_width), dtype=array.dtype)

    # Populate grid
    for idx in range(min(depth, nrows * ncols)):
        row = idx // ncols
        col = idx % ncols
        start_y = row * (height + padding)
        start_x = col * (width + padding)
        grid[start_y:start_y + height, start_x:start_x + width] = array[idx]

    return grid


def draw_contour(grayscale_image, labeled_segmentation, width=1):
    """
    Draw contours from a labeled segmentation image onto a grayscale image using a qualitative color map.

    Args:
        grayscale_image (np.ndarray): The grayscale image (H x W).
        labeled_segmentation (np.ndarray): The labeled segmentation image (H x W).
        width (int): The width of the contour lines.

    Returns:
        np.ndarray: The grayscale image with the contour overlay.
    """
    # Ensure labeled_segmentation is of type np.uint8
    if labeled_segmentation.dtype != np.uint8:
        labeled_segmentation = labeled_segmentation.astype(np.uint8)

    # Convert grayscale image to BGR for contour drawing
    contour_image = cv2.cvtColor(grayscale_image, cv2.COLOR_GRAY2BGR)

    # Find unique labels (excluding background)
    unique_labels = np.unique(labeled_segmentation)
    unique_labels = unique_labels[unique_labels != 0]  # Exclude background (0)

    # Generate a colormap
    colormap = [
        (0, 0, 0),        # Black for label 0 (background)
        (255, 0, 0),      # Red for label 1
        (0, 255, 0),      # Green for label 2
        (0, 0, 255),      # Blue for label 3
        (255, 255, 0),    # Cyan for label 4
        (255, 0, 255),    # Magenta for label 5
        (0, 255, 255),    # Yellow for label 6
        (128, 0, 0),      # Dark Red for label 7
        (0, 128, 0),      # Dark Green for label 8
        (0, 0, 128),      # Dark Blue for label 9
        (128, 128, 0),    # Olive for label 10
        (128, 0, 128),    # Purple for label 11
        (0, 128, 128),    # Teal for label 12
        (192, 192, 192),  # Light Grey for label 13
        (128, 128, 128),  # Grey for label 14
        (255, 165, 0),    # Orange for label 15
        (255, 20, 147),   # Deep Pink for label 16
        (135, 206, 235),  # Sky Blue for label 17
        (255, 105, 180),  # Hot Pink for label 18
        (75, 0, 130)     # Indigo for label 19
    ]
    colormap = {i: colormap[i] for i in np.arange(len(colormap))}

    for label in unique_labels:
        # Create a binary mask for the current label
        mask = (labeled_segmentation == label).astype(np.uint8)

        # Find contours for the current label
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Use the colormap to get the color for the current label
        color_index = label % 20  # Use modulo to fit within the color range
        color = colormap[color_index]  # Get BGR color from colormap

        # Draw contours in the specified color
        cv2.drawContours(contour_image, contours, -1, color, width)

    return contour_image


def rescale_intensity(image, lower=25, upper=99):
    """Rescale the intensity of an image to map the 5th and 95th percentiles to 0 and 255."""
    lower, upper = np.percentile(image, [lower, upper])
    if lower == upper:
        raise ValueError("Min point and Max point are the same")
    rescaled_image = np.clip((image - lower) / (upper - lower) * 255, 0, 255)
    return rescaled_image.astype(np.uint8)


def crop_image_to_segmentation(mri_image: np.ndarray, seg_image: np.ndarray, padding: int = 50) -> (np.ndarray, np.ndarray):
    """
    Crop the MRI and segmentation images to the bounding box of the segmentation 
    with specified padding.

    Args:
        mri_image (np.ndarray): The MRI image as a 3D numpy array.
        seg_image (np.ndarray): The segmentation image as a 3D numpy array.
        padding (int, optional): Padding to add around the bounding box. Default is 50.

    Returns:
        Tuple[np.ndarray, np.ndarray]: 
            - Cropped MRI image.
            - Cropped segmentation image.

    Raises:
        ValueError: If the segmentation image is empty or has no positive regions.
    """
    # Find bounding box of the segmentation
    indices = np.argwhere(seg_image)
    if indices.size == 0:
        raise ValueError("Segmentation image is empty or has no positive regions.")

    top_left = indices.min(axis=0)
    bottom_right = indices.max(axis=0)

    # Add padding and ensure it doesn't exceed image boundaries
    padded_top_left = np.maximum(top_left - padding, 0)
    padded_bottom_right = np.minimum(bottom_right + padding + 1, np.array(mri_image.shape))
    padded_top_left[0] = top_left[0] - 2
    padded_bottom_right[0] = bottom_right[0] + 3

    # Crop the MRI and segmentation images
    slices = tuple(slice(start, end) for start, end in zip(padded_top_left, padded_bottom_right))
    cropped_mri_image = mri_image[slices]
    cropped_seg_image = seg_image[slices]

    return cropped_mri_image, cropped_seg_image

def crop_image_to_segmentation_sitk(mri_image: sitk.Image, seg_image: sitk.Image, padding: int = 50) -> (sitk.Image, sitk.Image):
    """
    Crop the MRI image to the bounding box of the segmented area in the 
    segmentation image.

    This function takes an MRI image and a corresponding segmentation image, 
    computes the bounding box of the largest segmented area, and returns the 
    cropped MRI image along with the cropped segmentation image, adding 
    optional padding around the segment.

    Args:
        mri_image (sitk.Image): The MRI image to be cropped.
        seg_image (sitk.Image): The segmentation image used to define the 
            cropping region.
        padding (int, optional): Amount of padding to add around the 
            segmentation area. Defaults to 50.

    Returns:
        Tuple[sitk.Image, sitk.Image]: A tuple containing the cropped MRI 
            image and the corresponding cropped segmentation image.

    Raises:
        ValueError: If the MRI and segmentation images do not have the 
            same dimension.
    """

    # Ensure the images are in the same space
    if mri_image.GetDimension() != seg_image.GetDimension():
        raise ValueError("MRI and segmentation images must have the same dimension.")
    if not all([a == b for a, b in zip(mri_image.GetSize(), seg_image.GetSize())]):
        raise ValueError("MRI and segmetnation images must have the same size!")

    # Compute the bounding box using LabelShapeStatisticsImageFilter
    label_shape_filter = sitk.LabelShapeStatisticsImageFilter()
    label_shape_filter.Execute(seg_image != 0)

    # Get the bounding box for the largest label (assuming the largest segment is of interest)
    largest_label = label_shape_filter.GetLabels()[0]
    bounding_box = label_shape_filter.GetBoundingBox(largest_label)

    # Extract bounding box coordinates
    x_min, y_min, z_min = bounding_box[0:3]
    x_max = x_min + bounding_box[3]
    y_max = y_min + bounding_box[4]
    z_max = z_min + bounding_box[5]

    # Apply padding
    x_min = max(0, x_min - padding)
    x_max = min(mri_image.GetSize()[0], x_max + padding)
    y_min = max(0, y_min - padding)
    y_max = min(mri_image.GetSize()[1], y_max + padding)
    z_min = max(0, z_min - padding)
    z_max = min(mri_image.GetSize()[2], z_max + padding)

    logger.info(f"Find bounding box: {[x_min, y_min, z_min, x_max, y_max, z_max] = }")

    # Crop the MRI and segmentation images using the calculated bounding box
    cropped_mri = sitk.RegionOfInterest(mri_image, [x_max - x_min, y_max - y_min, z_max - z_min], [x_min, y_min, z_min])
    cropped_seg = sitk.RegionOfInterest(seg_image, [x_max - x_min, y_max - y_min, z_max - z_min], [x_min, y_min, z_min])

    return cropped_mri, cropped_seg