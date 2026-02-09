# DICOM X-Ray Anonymizer

A standalone Python script for anonymizing X-Ray DICOM files with series-based Scan ID assignment. This tool implements a chronology-based anonymization strategy where each scan series per patient receives a unique identifier assigned to the `AccessionNumber` field.

## Overview

This anonymizer processes DICOM files by:
1. Discovering all DICOM files recursively in a directory
2. Extracting metadata (patient info, study details, series info)
3. Generating Scan IDs based on scan chronology per patient
4. Assigning Scan IDs to the `AccessionNumber` field
5. Saving both original and anonymized metadata to CSV files
6. Optionally writing anonymized DICOM files to an output directory

## Key Features

- **Series-Based Anonymization**: Each unique series per patient gets a distinct Scan ID
- **Chronological Ordering**: Scan IDs are assigned based on StudyDate and StudyTime
- **Suffix System**: Uses a printable ASCII suffix sequence (first scan: no suffix, then A-Z, then symbols)
- **Metadata Export**: Generates CSV files with both original and anonymized metadata
- **CSV-Only Mode**: Option to generate metadata without modifying DICOM files
- **Preserves Directory Structure**: Maintains relative paths in the output directory

## Anonymization Logic

### Scan ID Generation

The script assigns a Scan ID (stored in `AccessionNumber`) to each series using this logic:

1. **Group by Patient**: All files are grouped by `PatientID`
2. **Identify Series**: Within each patient, unique series are identified by `SeriesInstanceUID`
3. **Sort Chronologically**: Series are sorted by `StudyDate` then `StudyTime` (ascending)
4. **Assign Suffixes**:
   - **First series**: Scan ID = `PatientID` (no suffix)
   - **Second series**: Scan ID = `PatientID` + "A"
   - **Third series**: Scan ID = `PatientID` + "B"
   - **And so on...**
5. **Apply to All Files**: All DICOM files within the same series receive the same Scan ID

### Suffix Sequence

The suffix sequence follows this order (86 total suffixes):
- Empty string (first scan)
- Uppercase letters: A-Z (26 characters)
- Symbols and digits: `!"#$%&'()*+,-./0-9:;<=>?@[\]^_{|}~` (59 characters)

If a patient has more than 86 series, the suffix format switches to `_scanN`.

## Installation

### Requirements

- Python 3.9+
- Dependencies:
  ```bash
  pip install pydicom pandas
  ```

### Using uv (Recommended)

If using `uv` package manager:
```bash
uv sync
```

## Usage

### Basic Usage

```bash
python anonymizer_rename.py \
    --input-dir /path/to/xray/data \
    --output-csv-original /path/to/original_metadata.csv \
    --output-csv-anon /path/to/anonymized_metadata.csv
```

This will:
- Read DICOM files from `/path/to/xray/data`
- Create anonymized DICOM files in `/path/to/xray/data-Anonymized`
- Save original metadata to `original_metadata.csv`
- Save anonymized metadata to `anonymized_metadata.csv`

### CSV-Only Mode

To generate metadata without modifying DICOM files:

```bash
python anonymizer_rename.py \
    --input-dir /path/to/xray/data \
    --output-csv-original original.csv \
    --output-csv-anon anonymized.csv \
    --csv-only
```

### Custom Output Directory

Specify a custom output directory for anonymized DICOM files:

```bash
python anonymizer_rename.py \
    --input-dir /path/to/xray/data \
    --output-csv-original original.csv \
    --output-csv-anon anonymized.csv \
    --output-dir /custom/output/path
```

### Verbose Logging

Enable detailed logging for debugging:

```bash
python anonymizer_rename.py \
    --input-dir /path/to/xray/data \
    --output-csv-original original.csv \
    --output-csv-anon anonymized.csv \
    --verbose
```

## Command-Line Options

| Option | Required | Description |
|--------|----------|-------------|
| `--input-dir` | Yes | Root directory containing DICOM files |
| `--output-csv-original` | Yes | Path for original metadata CSV output |
| `--output-csv-anon` | Yes | Path for anonymized metadata CSV output |
| `--output-dir` | No | Custom output directory (default: `<input-dir>-Anonymized`) |
| `--csv-only` | No | Only generate CSV files without modifying DICOM files |
| `--verbose` | No | Enable verbose logging (DEBUG level) |

## Output Structure

### Anonymized DICOM Files

By default, anonymized files are saved to a sibling directory:
```
/path/to/xray/data/              # Input directory
/path/to/xray/data-Anonymized/   # Output directory (created automatically)
```

The directory structure is preserved:
```
Input:
  /path/to/xray/data/patient1/series1/image001.dcm

Output:
  /path/to/xray/data-Anonymized/patient1/series1/image001.dcm
```

### CSV Metadata Files

Both CSV files contain the following columns:

#### Original Metadata CSV
- `PatientName`
- `PatientID`
- `PatientBirthDate`
- `PatientSex`
- `AccessionNumber` (original)
- `InstitutionName`
- `StudyDate`
- `StudyTime`
- `SeriesInstanceUID`
- `BodyPartExamined`

#### Anonymized Metadata CSV
Same columns as above, but `AccessionNumber` is replaced with the anonymized Scan ID.

## Example

Given a patient with ID `P001` who has 3 X-ray series taken on different dates:

| Series | StudyDate | Original AccessionNumber | New AccessionNumber (Scan ID) |
|--------|-----------|-------------------------|------------------------------|
| Series 1 | 2025-01-10 | ACC001 | `P001` |
| Series 2 | 2025-01-15 | ACC002 | `P001A` |
| Series 3 | 2025-01-20 | ACC003 | `P001B` |

All DICOM files within Series 1 will have `AccessionNumber = "P001"`, all files in Series 2 will have `AccessionNumber = "P001A"`, and so on.

## Extracted DICOM Tags

The script extracts the following DICOM tags:

| Tag Name | Tag ID | Description |
|----------|--------|-------------|
| PatientName | (0x0010, 0x0010) | Patient's full name |
| PatientID | (0x0010, 0x0020) | Primary patient identifier |
| PatientBirthDate | (0x0010, 0x0030) | Patient's birth date |
| PatientSex | (0x0010, 0x0040) | Patient's sex |
| AccessionNumber | (0x0008, 0x0050) | Study accession number (modified during anonymization) |
| InstitutionName | (0x0008, 0x0080) | Institution name |
| StudyDate | (0x0008, 0x0020) | Study date |
| StudyTime | (0x0008, 0x0031) | Study time |
| SeriesInstanceUID | (0x0020, 0x000e) | Unique series identifier |
| BodyPartExamined | (0x0018, 0x0015) | Body part examined |

## Logging

The script provides informative logging at two levels:

- **INFO** (default): Progress updates, statistics, and summary
- **DEBUG** (`--verbose`): Detailed file-by-file processing information

Example output:
```
2025-01-20 14:30:00 - INFO - Searching for DICOM files in: /path/to/data
2025-01-20 14:30:02 - INFO - Found 150 DICOM files
2025-01-20 14:30:05 - INFO - Successfully processed 150/150 files
2025-01-20 14:30:05 - INFO - Generated anonymized names for 25 patients
2025-01-20 14:30:10 - INFO - Anonymization complete: 150 successful, 0 failed
```

## Error Handling

The script handles common errors gracefully:

- **Invalid DICOM files**: Logged as warnings, processing continues
- **Missing metadata**: Missing tags are stored as `None`
- **File I/O errors**: Logged with detailed error messages
- **Missing directories**: Input directory validation before processing

## Limitations

- Only processes files with `.dcm` extension
- Requires `SeriesInstanceUID` for series-based grouping
- Maximum 86 series per patient before switching to `_scanN` suffix format
- Does not anonymize other patient identifiers besides `AccessionNumber`

## Related Projects

This script is part of the `med_img_streamlit` repository, which also includes:
- [dicom_anonymizer](../dicom_anonymizer/) - Interactive Streamlit web application for DICOM anonymization
- [segmentation_checker](../segmentation_checker/) - MRI segmentation visualization tool

## License

Part of the medical imaging Streamlit applications repository.
