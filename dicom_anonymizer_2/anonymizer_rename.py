"""
DICOM X-Ray Anonymizer

A standalone script that anonymizes X-Ray DICOM files by implementing a
series-based PatientName naming convention based on scan chronology per patient.

Usage:
    python anonymize_ngtcxr.py \
        --input-dir /path/to/xray/data \
        --output-csv-original /path/to/original_metadata.csv \
        --output-csv-anon /path/to/anonymized_metadata.csv
"""

import argparse
import logging
from pathlib import Path
from typing import Optional

import pandas as pd
from pydicom import dcmread
from pydicom.errors import InvalidDicomError
from pydicom.tag import Tag


# Define the DICOM tags to extract
TAG_DICT = {
    'PatientName':              Tag((0x0010, 0x0010)),
    'PatientID':                Tag((0x0010, 0x0020)),
    'PatientBirthDate':         Tag((0x0010, 0x0030)),
    'PatientSex':               Tag((0x0010, 0x0040)),
    'AccessionNumber':          Tag((0x0008, 0x0050)),
    'InstitutionName':          Tag((0x0008, 0x0080)),
    'StudyDate':                Tag((0x0008, 0x0020)),
    'StudyTime':                Tag((0x0008, 0x0031)),
    'SeriesInstanceUID':        Tag((0x0020, 0x000e)),
    'BodyPartExamined':         Tag((0x0018, 0x0015))
}


# Suffix sequence for anonymization (printable ASCII table, excluding uppercase)
# Starts with empty string, then lowercase letters (a-z), then continues with
# printable ASCII symbols and digits: !"#$%&'()*+,-./0-9:;<=>?@[\]^_`{|}~
# Excludes uppercase letters A-Z (ASCII 65-90)
SUFFIXES = ['']
# First: lowercase letters a-z (ASCII 97-122)
SUFFIXES += [chr(i) for i in range(ord('a'), ord('z') + 1)]
# Then: symbols and digits from ! to @ (ASCII 33-64, before uppercase letters)
SUFFIXES += [chr(i) for i in range(33, 65)]
# Then: symbols from [ to ` (ASCII 91-96, after uppercase letters, before lowercase)
SUFFIXES += [chr(i) for i in range(91, 97)]
# Finally: remaining symbols { | } ~ (ASCII 123-126, after lowercase letters)
SUFFIXES += [chr(i) for i in range(123, 127)]


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the script."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def discover_dicom_files(root_dir: str) -> list[Path]:
    """
    Discover all DICOM files in the root directory recursively.

    Args:
        root_dir: Root directory path to search for DICOM files

    Returns:
        List of Path objects for all .dcm files found
    """
    root_path = Path(root_dir)
    if not root_path.is_dir():
        raise ValueError(f"Input directory does not exist: {root_dir}")

    logging.info(f"Searching for DICOM files in: {root_dir}")
    dicom_files = list(root_path.rglob("*.dcm"))
    logging.info(f"Found {len(dicom_files)} DICOM files")

    return dicom_files


def compute_output_path(file_path: Path, root_dir: Path, output_dir: Optional[Path] = None) -> Path:
    """
    Compute the output path for an anonymized DICOM file.

    Args:
        file_path: Original file path
        root_dir: Original root directory
        output_dir: Custom output directory (optional)

    Returns:
        Path for the anonymized file
    """
    if output_dir is None:
        # Default: create sibling directory with "-Anonymized" suffix
        output_base = root_dir.parent / f"{root_dir.name}-Anonymized"
    else:
        output_base = Path(output_dir)

    # Maintain relative directory structure
    relative_path = file_path.relative_to(root_dir)
    return output_base / relative_path


def extract_metadata(dicom_files: list[Path], root_dir: str, output_dir: Optional[Path] = None) -> pd.DataFrame:
    """
    Extract metadata from DICOM files into a DataFrame.

    Args:
        dicom_files: List of DICOM file paths
        root_dir: Root directory path
        output_dir: Custom output directory (optional)

    Returns:
        DataFrame with extracted metadata
    """
    root_path = Path(root_dir)

    # Initialize data storage
    data = {
        'file_path': [],
        'output_path': [],
        **{tag_name: [] for tag_name in TAG_DICT.keys()}
    }

    failed_files = []
    processed_count = 0

    logging.info("Extracting metadata from DICOM files...")

    for file_path in dicom_files:
        try:
            # Read DICOM file (stop before pixel data for efficiency)
            dataset = dcmread(str(file_path), stop_before_pixels=True)

            # Store paths
            data['file_path'].append(str(file_path))
            data['output_path'].append(str(compute_output_path(file_path, root_path, output_dir)))

            # Extract DICOM tags
            for tag_name in TAG_DICT.keys():
                value = getattr(dataset, tag_name, None)

                # Special handling for PatientName (PersonName objects)
                if tag_name == 'PatientName' and value is not None:
                    # Convert PersonName to string
                    value = ''.join(str(value).split('^')) if value else ''

                data[tag_name].append(value)

            processed_count += 1

            if processed_count % 100 == 0:
                logging.debug(f"Processed {processed_count}/{len(dicom_files)} files")

        except InvalidDicomError as e:
            logging.warning(f"Invalid DICOM file: {file_path} - {e}")
            failed_files.append(str(file_path))
        except Exception as e:
            logging.warning(f"Error processing file {file_path}: {e}")
            failed_files.append(str(file_path))

    logging.info(f"Successfully processed {processed_count}/{len(dicom_files)} files")
    if failed_files:
        logging.warning(f"Failed to process {len(failed_files)} files")

    # Create DataFrame
    df = pd.DataFrame(data)

    return df


def generate_anonymized_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate anonymized PatientName values based on scan chronology per patient.

    Logic:
    1. Group by PatientID, then by unique SeriesInstanceUID to identify series
    2. Sort series by StudyDate, then StudyTime (ascending)
    3. First series: PatientName = PatientID (no suffix)
    4. Later series: PatientName = PatientID + suffix (a, b, c, ...)
    5. All files within the same series get the same anonymized name

    Args:
        df: DataFrame with original metadata

    Returns:
        DataFrame with added 'Anonymized_PatientName' column
    """
    logging.info("Generating anonymized patient names...")

    # Make a copy to avoid SettingWithCopyWarning
    df = df.copy()

    # Handle missing StudyDate/StudyTime for sorting (treat as earliest)
    df['StudyDate'] = df['StudyDate'].fillna('')
    df['StudyTime'] = df['StudyTime'].fillna('')
    # Handle missing SeriesInstanceUID
    df['SeriesInstanceUID'] = df['SeriesInstanceUID'].fillna('')

    # Group by PatientID
    grouped = df.groupby('PatientID', dropna=False)

    anonymized_names = []

    for patient_id, group in grouped:
        # Get unique series and sort them chronologically
        unique_series = group.drop_duplicates(subset=['SeriesInstanceUID']).sort_values(
            ['StudyDate', 'StudyTime'], ascending=True
        )

        # Create mapping from SeriesInstanceUID to suffix index
        series_to_suffix = {}
        for idx, (_, series_row) in enumerate(unique_series.iterrows()):
            series_to_suffix[series_row['SeriesInstanceUID']] = idx

        # Assign names to all files based on their series
        for _, row in group.iterrows():
            series_idx = series_to_suffix[row['SeriesInstanceUID']]

            if series_idx == 0:
                # First series: no suffix
                new_name = str(patient_id) if pd.notna(patient_id) else ''
            else:
                # Later series: add suffix from ASCII table sequence
                suffix = SUFFIXES[series_idx] if series_idx < len(SUFFIXES) else f"_scan{series_idx}"
                new_name = f"{patient_id}{suffix}"

            anonymized_names.append((row.name, new_name))

    # Sort by original index to maintain DataFrame order
    anonymized_names.sort(key=lambda x: x[0])

    # Create the new column
    df['Anonymized_PatientName'] = [name for _, name in anonymized_names]

    # Log statistics
    unique_patients = df['PatientID'].nunique()
    logging.info(f"Generated anonymized names for {unique_patients} patients")

    # Log anonymization details per patient
    for patient_id, group in grouped:
        # Count unique series (not total files)
        unique_series_count = group.drop_duplicates(subset=['SeriesInstanceUID']).shape[0]
        total_files = len(group)
        first_name = group.iloc[0]['PatientName']
        logging.debug(f"PatientID {patient_id}: {unique_series_count} series, {total_files} files, original name '{first_name}'")

    return df


def save_metadata_csv(df: pd.DataFrame, output_path: str, anonymized: bool = False) -> None:
    """
    Save metadata to a CSV file.

    Args:
        df: DataFrame with metadata
        output_path: Path for output CSV file
        anonymized: If True, save anonymized PatientName; otherwise save original
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Select columns to save
    if anonymized:
        df_to_save = df.copy()
        # Replace PatientName with anonymized version
        df_to_save['PatientName'] = df_to_save['Anonymized_PatientName']
        # Drop internal columns
        columns_to_drop = ['file_path', 'output_path', 'Anonymized_PatientName']
        df_to_save = df_to_save.drop(columns=[col for col in columns_to_drop if col in df_to_save.columns])
    else:
        # Drop internal columns
        columns_to_drop = ['file_path', 'output_path', 'Anonymized_PatientName']
        df_to_save = df.drop(columns=[col for col in columns_to_drop if col in df.columns])

    df_to_save.to_csv(output_path, index=False)
    logging.info(f"Saved {'anonymized' if anonymized else 'original'} metadata to: {output_path}")


def anonymize_dicom_files(df: pd.DataFrame) -> None:
    """
    Anonymize DICOM files by modifying PatientName and saving to output directory.

    Args:
        df: DataFrame with file paths and anonymized names
    """
    logging.info("Anonymizing DICOM files...")

    success_count = 0
    failed_count = 0

    for idx, row in df.iterrows():
        input_path = Path(row['file_path'])
        output_path = Path(row['output_path'])
        new_name = row['Anonymized_PatientName']

        try:
            # Read DICOM file
            dataset = dcmread(str(input_path))

            # Log before modification
            original_name = dataset.PatientName
            logging.debug(f"File: {input_path.name}")
            logging.debug(f"  Original PatientName: {original_name}")
            logging.debug(f"  New PatientName: {new_name}")

            # Update PatientName
            dataset.PatientName = str(new_name)

            # Verify the change
            logging.debug(f"  Verified PatientName after update: {dataset.PatientName}")

            # Create output directory
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Save anonymized file
            dataset.save_as(str(output_path))

            # Verify saved file
            verification_ds = dcmread(str(output_path))
            logging.debug(f"  Saved file PatientName: {verification_ds.PatientName}")

            success_count += 1

            if success_count % 100 == 0:
                logging.debug(f"Anonymized {success_count}/{len(df)} files")

        except Exception as e:
            logging.error(f"Failed to anonymize {input_path}: {e}")
            import traceback
            logging.error(traceback.format_exc())
            failed_count += 1

    logging.info(f"Anonymization complete: {success_count} successful, {failed_count} failed")


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description='Anonymize DICOM X-Ray files based on series chronology',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--input-dir',
        required=True,
        help='Root directory containing DICOM files'
    )

    parser.add_argument(
        '--output-csv-original',
        required=True,
        help='Path for original metadata CSV output'
    )

    parser.add_argument(
        '--output-csv-anon',
        required=True,
        help='Path for anonymized metadata CSV output'
    )

    parser.add_argument(
        '--output-dir',
        default=None,
        help='Custom output directory (default: <input-dir>-Anonymized)'
    )

    parser.add_argument(
        '--csv-only',
        action='store_true',
        help='Only generate CSV files without modifying DICOM files'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)

    logging.info("=" * 60)
    logging.info("DICOM X-Ray Anonymizer")
    logging.info("=" * 60)

    try:
        # Step 1: Discover DICOM files
        dicom_files = discover_dicom_files(args.input_dir)
        if not dicom_files:
            logging.error("No DICOM files found. Exiting.")
            return

        # Step 2: Extract metadata
        df = extract_metadata(dicom_files, args.input_dir, args.output_dir)

        # Step 3: Save original metadata CSV
        save_metadata_csv(df, args.output_csv_original, anonymized=False)

        # Step 4: Generate anonymized names
        df = generate_anonymized_names(df)

        # Step 5: Save anonymized metadata CSV
        save_metadata_csv(df, args.output_csv_anon, anonymized=True)

        # Step 6: Anonymize DICOM files (skip if csv-only mode)
        if not args.csv_only:
            anonymize_dicom_files(df)
        else:
            logging.info("CSV-only mode: Skipping DICOM file modification")

        # Print summary
        logging.info("=" * 60)
        logging.info("SUMMARY")
        logging.info("=" * 60)
        logging.info(f"Total DICOM files found: {len(dicom_files)}")
        logging.info(f"Unique patients: {df['PatientID'].nunique()}")

        if args.csv_only:
            logging.info("Mode: CSV-only (no DICOM files modified)")
        else:
            logging.info(f"Files successfully anonymized: {len(df)}")

        logging.info(f"Original metadata: {args.output_csv_original}")
        logging.info(f"Anonymized metadata: {args.output_csv_anon}")

        if not args.csv_only:
            if args.output_dir:
                logging.info(f"Anonymized files: {args.output_dir}")
            else:
                output_dir = Path(args.input_dir).parent / f"{Path(args.input_dir).name}-Anonymized"
                logging.info(f"Anonymized files: {output_dir}")

        logging.info("=" * 60)
        logging.info("Anonymization complete!")
        logging.info("=" * 60)

    except Exception as e:
        logging.error(f"An error occurred: {e}", exc_info=args.verbose)
        raise


if __name__ == "__main__":
    main()
