# MRI and Segmentation Viewer

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![Streamlit](https://img.shields.io/badge/streamlit-1.55+-FF4B4B.svg)
![SimpleITK](https://img.shields.io/badge/SimpleITK-latest-green.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)

---

This project is a Streamlit application for viewing MRI images and their corresponding segmentations. The app allows users to select, view, and manage MRI/segmentation pairs. The motivation is to allow for quick checking of segmentations because most existing softwares (e.g., ITK-snap, Slicer3D) either require clumbersome IO that is quite time consuming. 

## Screen shot

![Demo](./assets/Demo.png)

## Features

- Load and display MRI images and segmentations.
- Navigate through pairs with next and previous buttons.
- Mark pairs as checked or needing fixes.
- Save progress to a CSV file.
- View progress through a progress bar.
- Save your settings to `.session.json` 

## Requirements

- Python 3.x
- Streamlit
- SimpleITK
- NumPy
- Pandas
- Streamlit

## Installation

1. Clone the parent repository:
   ```bash
   git clone <repository-url> 
   ```

2. Install uv if you haven't already:
   ```bash
   pip install uv # This still works if you are using conda
   ```

3. Sync env
   ```bash
   uv sync
   ```

## Usage

---

Navigate to the project directory and run the Streamlit app:
```Bash
streamlit run segmentation_check.py
```

Follow the instruction and access the webapp using latest browser. 

# License

This project is licensed under the MIT License.

---

# TODO

- [ ] Fix error when reaching the last sample
- [ ] Fix error requiring users select the pair twice sometimes
- [ ] Try to load only when both directories were entered and found
- [ ] Implement Async loading of the next pair
- [ ] Auto-save with confirmation