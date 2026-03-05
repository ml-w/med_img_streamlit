# DICOM Anonymizer

A Streamlit application for anonymizing DICOM medical image files with an interactive web interface.

## Requirements

- Python 3.10+

## Installation

**uv (recommended):**
```bash
cd dicom_anonymizer
uv sync               # installs all dependencies into .venv
uv sync --group dev   # also installs pytest
```

**conda:**
```bash
conda env create -n streamlit-dicomanonymizer -f environment.yml
conda activate streamlit-dicomanonymizer
```

**pip:**
```bash
pip install -r requirements.txt
```

## Running the App

**Recommended — via `run_app.py` (Rich logging, configurable port):**
```bash
cd dicom_anonymizer
uv run python run_app.py            # uv — default port 8501
uv run python run_app.py --port 8502
uv run python run_app.py --log-level INFO
# or with conda/pip:
python run_app.py --help
```

**Via Streamlit directly:**
```bash
cd dicom_anonymizer/application
streamlit run user_interface.py
```

**Via `streamlit run` from project root:**
```bash
streamlit run dicom_anonymizer/run_app.py
```

## Workflow

1. **Fetch files** — enter the folder path and file extension (e.g. `*.dcm`). The app scans all DICOM files recursively and reads their metadata.

2. **Configure Primary Key (PK)** — select which DICOM tags form the unique identifier for each anonymization row (default: `PatientID + SeriesInstanceUID`). A live preview shows how many unique rows the chosen PK produces. Removing `SeriesInstanceUID` collapses all series for a patient into one row (patient-level anonymization).

3. **Edit and anonymize** — the app displays one editable row per PK. You can:
   - Fill in replacement values directly in the table
   - Download the auto-generated CSV template, fill it in, and re-upload
   - Upload a partial CSV — rows not present keep empty defaults; optionally skip them entirely

4. **Run** — anonymized files are written to `<input_folder>-Anonymized/`.

## Configuration

All defaults are in `application/app_settings/config.py`:

| Variable | Purpose |
|---|---|
| `pk_tag_options` / `pk_default` | Tags available for PK building; default selection |
| `ref_tag_options` | Tags shown as read-only reference columns |
| `update_tag_defaults` | Tags with editable `Update_*` columns; value is the default (empty string, literal, or callable) |
| `upload_df_id` | Column used as matcher when uploading a CSV |
| `tags_2_anon` | Explicit tag list to blank (uses built-in list if `None`) |
| `tags_2_spare` | Tags never modified, even if their VR type is selected |
| `vr_type_options` / `vr_type_defaults` | VR types available/selected by default for blanking |
| `new_tags` | Tags to create if missing from a file |

## Anonymization Settings (UI)

Accessible via the **⚙ Anonymization settings** expander before Run:

- **Skip unmatched cases** — exclude cases absent from the uploaded CSV entirely (not copied to output).
- **Organize output by tag** — use the anonymized value of a chosen tag as a top-level subfolder, replacing the original directory structure (avoids PII embedded in folder names). Series are placed in sequentially numbered subdirectories (`series_001`, `series_002`, …).
- **VR types to anonymize** — checkboxes for each DICOM Value Representation; checked types have their values replaced with `"Anonymized"`.
- **Additional tags to spare** — hex tag pairs in `(XXXX|XXXX)` format that are never modified regardless of VR type.

## Output

Anonymized files are written to `<input_folder>-Anonymized/`. The original files are not modified.

When **Organize output by tag** is enabled, the structure is:
```
<input_folder>-Anonymized/
  <tag_value>/
    series_001/
      file.dcm
    series_002/
      file.dcm
```

Otherwise the original subdirectory structure is mirrored under the output root.

## Creating a Binary Executable (Windows)

A self-contained `.exe` can be built with PyInstaller. The hook at `hooks/hook-streamlit.py` bundles Streamlit's static assets automatically.

**1. Install build dependencies:**
```bash
uv sync --group build   # installs pyinstaller into the venv
# or: pip install "pyinstaller<=5.10.0"
```

**2. Generate the spec file:**
```bash
cd dicom_anonymizer
pyi-makespec --onefile --additional-hooks-dir=./hooks run_app.py
```

**3. Edit `run_app.spec` — add the `application/` directory to `datas`:**

Find the `datas=[...]` list inside the `Analysis(...)` block and add:
```python
datas=[
    ("<path_to_env>/Lib/site-packages/streamlit/static", "./streamlit/static"),
    ("<path_to_app>/application", "./application"),
],
```
Replace `<path_to_env>` with your virtual environment path (e.g. `.venv`) and `<path_to_app>` with the path to this directory.

**4. Build:**
```bash
pyinstaller run_app.spec --clean
```

The executable is written to `dist/run_app.exe`. Double-clicking it launches the app in your browser on port 8501 with no terminal interaction required.

> **Note:** PyInstaller support targets Windows. macOS/Linux builds are not tested. The pinned `pyinstaller<=5.10.0` version matches the tested configuration; later versions may work but are untested.

