# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a medical imaging Streamlit applications repository containing two independent applications:

1. **DICOM Anonymizer** ([dicom_anonymizer/](dicom_anonymizer/)) - A web application for anonymizing DICOM medical imaging files with privacy compliance features.
2. **Segmentation Checker** ([segmentation_checker/](segmentation_checker/)) - A web application for viewing MRI images and their corresponding segmentations side-by-side.

Both applications are built with Streamlit and use medical imaging libraries (pydicom, SimpleITK, OpenCV).

## Development Commands

### Dependency Management

The project uses `uv` as the package manager:

```bash
# Install dependencies
uv sync

# Add a new dependency
uv add <package>

# Run Python in the virtual environment
uv run python <script>
```

For the DICOM Anonymizer, there's also a [requirements.txt](dicom_anonymizer/requirements.txt) in that subdirectory.

### Running Applications

```bash
# Run DICOM Anonymizer
cd dicom_anonymizer
python run_app.py
# Or with uv: uv run python run_app.py

# Run Segmentation Checker
cd segmentation_checker
streamlit run segment_check.py
```

### Testing

Tests use pytest and are located in [dicom_anonymizer/tests/](dicom_anonymizer/tests/):

```bash
# Run all tests
pytest

# Run specific test file
pytest dicom_anonymizer/tests/test_anonymize_dicom.py

# Run with verbose output
pytest -v
```

Test configuration is in [pytest.ini](pytest.ini).

## Architecture

### DICOM Anonymizer Structure

The DICOM Anonymizer follows a modular architecture under [dicom_anonymizer/application/](dicom_anonymizer/application/):

- **DicomAnonymizer.py** - Entry point that imports and calls `streamlit_app()` from [user_interface.py](dicom_anonymizer/application/user_interface.py)
- **user_interface.py** - Main Streamlit UI with session persistence ([user_interface.py:27-51](dicom_anonymizer/application/user_interface.py#L27-L51)), state management, and UI layout
- **anonymizer_utils/** - Core anonymization logic:
  - [anonymize_dicom.py](dicom_anonymizer/application/anonymizer_utils/anonymize_dicom.py) - DICOM processing functions (`create_dcm_df`, `anonymize`, `remove_info`)
- **ui_utils/** - UI helper functions:
  - [ui_logic.py](dicom_anonymizer/application/ui_utils/ui_logic.py) - Data validation, CSV upload handling, DataFrame updates
- **app_settings/** - Configuration:
  - [config.py](dicom_anonymizer/application/app_settings/config.py) - DICOM tag definitions, anonymization rules, unique IDs

**Key Design Patterns:**

1. **Session Persistence** - The app uses [`.session.json`](dicom_anonymizer/.session.json) to persist Streamlit session state across restarts. Large DataFrames are excluded from persistence via `SESSION_EXCLUDE` ([user_interface.py:28](dicom_anonymizer/application/user_interface.py#L28)).

2. **Two-Level Operation Mode** - The app can operate in either patient-level or series-level anonymization mode, controlled by `st.session_state.series_mode` ([user_interface.py:88-98](dicom_anonymizer/application/user_interface.py#L88-L98)).

3. **Configuration-Driven** - All DICOM tags to anonymize, spare, or create are defined in [config.py](dicom_anonymizer/application/app_settings/config.py). The `tags_2_anon` list specifies tags to empty, `tags_2_spare` preserves specific tags, and `new_tags` can create new ones.

4. **Rich Logging** - Both [run_app.py](dicom_anonymizer/run_app.py) and [segment_check.py](segmentation_checker/segment_check.py) inject `RichHandler` into Streamlit's logger for enhanced console output with tracebacks and local variable inspection.

### Segmentation Checker Structure

- **segment_check.py** - Main Streamlit app with MRI/segmentation viewing workflow
- **visualization.py** - Image processing utilities including `make_grid()` for creating image grids from 3D numpy arrays
- **style.css** - Custom CSS for the UI

The app pairs MRI and segmentation files by ID using regex pattern matching ([segment_check.py:83-96](segmentation_checker/segment_check.py#L83-L96)) and displays them with navigation controls.

## Working with This Codebase

### Modifying Anonymization Rules

Edit [dicom_anonymizer/application/app_settings/config.py](dicom_anonymizer/application/app_settings/config.py):
- `unique_ids` - Tags used as primary keys for matching
- `update_tag_defaults` - Tags with default values or transformation functions
- `tags_2_anon` - Tags to empty (set to `None` to disable)
- `tags_2_spare` - Tags to preserve from anonymization
- `new_tags` - New DICOM tags to create

### Session State

The DICOM Anonymizer uses Streamlit's session state heavily. When modifying the UI:
- Initialize defaults with `st.session_state.setdefault()` ([user_interface.py:57-69](dicom_anonymizer/application/user_interface.py#L57-L69))
- Exclude large objects from session persistence via `SESSION_EXCLUDE`
- The session JSON file is automatically saved/loaded on each app run

### File Path Handling

- The app normalizes Windows paths by replacing backslashes with forward slashes ([user_interface.py:86](dicom_anonymizer/application/user_interface.py#L86), [user_interface.py:46](dicom_anonymizer/application/user_interface.py#L46))
- Output directories are created as `[original_folder_name]-Anonymized` sibling to the input folder ([anonymize_dicom.py:12-23](dicom_anonymizer/application/anonymizer_utils/anonymize_dicom.py#L12-L23))

### Medical Imaging File Formats

- DICOM files processed with `pydicom` library
- NIfTI files (.nii.gz) processed with `SimpleITK`
- Both apps support recursive file discovery using `Path.rglob()`
