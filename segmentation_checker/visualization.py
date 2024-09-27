import cv2
import numpy as np
import SimpleITK as sitk

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
        nrows = int(np.ceil(depth / ncols))
    elif ncols is None and nrows is not None:
        ncols = int(np.ceil(depth / nrows))
    elif nrows is None and ncols is None:
        nrows = int(np.ceil(np.sqrt(depth)))
        ncols = int(np.ceil(depth / nrows))

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


def draw_contour(grayscale_image, binary_segmentation, color=(0, 255, 0), width=1):
    """
    Draw contours from a binary segmentation image onto a grayscale image.

    Args:
        grayscale_image (np.ndarray): The grayscale image (H x W).
        binary_segmentation (np.ndarray): The binary segmentation image (H x W).
        color (tuple): The color of the contour in BGR format.
        width (int): The width of the contour lines.

    Returns:
        np.ndarray: The grayscale image with the contour overlay.
    """
    # Ensure binary_segmentation is of type np.uint8
    if binary_segmentation.dtype != np.uint8:
        binary_segmentation = binary_segmentation.astype(np.uint8)

    # Find contours
    contours, _ = cv2.findContours(binary_segmentation, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Convert grayscale image to BGR for contour drawing
    contour_image = cv2.cvtColor(grayscale_image, cv2.COLOR_GRAY2BGR)
    cv2.drawContours(contour_image, contours, -1, color, width)

    return contour_image


def rescale_intensity(image, lower=25, upper=99):
    """Rescale the intensity of an image to map the 5th and 95th percentiles to 0 and 255."""
    lower, upper = np.percentile(image, [lower, upper])
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
