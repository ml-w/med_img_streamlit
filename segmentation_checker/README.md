# MRI and Segmentation Viewer

This project is a Streamlit application for viewing MRI images and their corresponding segmentations. The app allows users to select, view, and manage MRI/segmentation pairs.

## Features

- Load and display MRI images and segmentations.
- Navigate through pairs with next and previous buttons.
- Mark pairs as checked or needing fixes.
- Save progress to a CSV file.
- View progress through a progress bar.

## Requirements

- Python 3.x
- Streamlit
- SimpleITK
- NumPy
- Pandas

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>

## Usage
Navigate to the project directory.
Run the Streamlit app:
Bash
Insert code

```
streamlit run <script-name>.py
```
Follow the on-screen instructions to view and manage MRI/segmentation pairs.
Directory Structure:

- `MRI_DIR`: Directory containing the MRI images.
- `SEG_DIR`: Directory containing the segmentation files.
- Checked_Images.csv: File where progress is saved.
# Customization

Modify `MRI_DIR` and `SEG_DIR` paths in the code to point to your data directories.
Adjust the id_globber pattern to match your file naming convention.

# Contributing

Feel free to open issues or submit pull requests for improvements.

# License

This project is licensed under the MIT License.

---

# TODO

- [ ] Fix error when reaching the last sample
- [ ] Fix error requiring users select the pair twice sometimes
- [ ] Try to load only when both directories were entered and found
- [ ] Implement Async loading of the next pair
- [ ] Auto-save with confirmation