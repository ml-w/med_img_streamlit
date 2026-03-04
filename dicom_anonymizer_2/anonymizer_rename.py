#!/usr/bin/env python3
"""
DICOM Anonymizer with CSV-based Mapping (Multiprocessing Version)

A two-stage workflow script for anonymizing DICOM files:
1. Generate a CSV template with SeriesInstanceUID as key (with multiprocessing)
2. Apply user-modified CSV to update DICOM tags (with multiprocessing)

Usage:
    # Generate template
    python anonymizer_rename.py generate \
        --input-dir /path/to/dicom/data \
        --template-csv template.csv \
        [--num-workers N]

    # Apply updates
    python anonymizer_rename.py apply \
        --input-dir /path/to/dicom/data \
        --mapping-csv modified.csv \
        --output-dir /path/to/output \
        [--num-workers N] \
        [--dry-run]
"""

import re
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import logging
from rich.logging import RichHandler
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

import click
import pandas as pd
from pydicom import dcmread
from pydicom.errors import InvalidDicomError
from pydicom.tag import Tag
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn

# Suppress pydicom warnings about invalid VR TM values globally
warnings.filterwarnings('ignore', message='Invalid value for VR TM')

console = Console()

# Define the DICOM tags to extract and update
TAG_DICT = {
    'PatientName':              Tag((0x0010, 0x0010)),
    'PatientID':                Tag((0x0010, 0x0020)),
    'PatientBirthDate':         Tag((0x0010, 0x0030)),
    'PatientSex':               Tag((0x0010, 0x0040)),
    'AccessionNumber':          Tag((0x0008, 0x0050)),
    'InstitutionName':          Tag((0x0008, 0x0080)),
    'StudyDate':                Tag((0x0008, 0x0020)),
    'StudyTime':                Tag((0x0008, 0x0030)),
    'StudyInstanceUID':         Tag((0x0020, 0x000d)),
    'SeriesInstanceUID':        Tag((0x0020, 0x000e)),
    'BodyPartExamined':         Tag((0x0018, 0x0015))
}


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the script."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[RichHandler(rich_tracebacks=True, show_time=True, show_path=False)]
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


def process_single_file_for_metadata(filepath: str) -> Optional[Dict[str, any]]:
    """
    Process a single DICOM file and extract metadata.
    This function is designed to be called by multiprocessing workers.
    
    Args:
        filepath: Path to the DICOM file
        
    Returns:
        Dictionary containing metadata and filepath, or None if failed
    """
    try:
        # Read DICOM file (stop before pixel data for efficiency)
        dataset = dcmread(filepath, stop_before_pixels=True)

        # Get SeriesInstanceUID
        series_uid = getattr(dataset, 'SeriesInstanceUID', None)
        if not series_uid:
            return None

        # Extract metadata
        metadata = {'FilePath': filepath}
        for tag_name in TAG_DICT.keys():
            value = getattr(dataset, tag_name, None)

            # Special handling for PatientName (PersonName objects)
            if tag_name == 'PatientName' and value is not None:
                value = ''.join(str(value).split('^')) if value else ''
            
            # Special handling for time fields - keep original format
            elif tag_name == 'StudyTime' and value is not None:
                value = str(value) if value else ''
            
            # Convert to string for CSV compatibility
            metadata[tag_name] = str(value) if value is not None else ''

        return metadata

    except (InvalidDicomError, Exception):
        return None


def extract_series_metadata_parallel(dicom_files: List[Path], num_workers: int) -> dict:
    """
    Extract metadata from DICOM files in parallel, grouped by SeriesInstanceUID.

    Args:
        dicom_files: List of DICOM file paths
        num_workers: Number of parallel workers

    Returns:
        Dictionary mapping SeriesInstanceUID to metadata and file list
        {
            'series_uid': {
                'metadata': {tag_name: value, ...},
                'files': [Path, Path, ...]
            }
        }
    """
    logging.info("Extracting metadata from DICOM files using multiprocessing...")
    
    series_data = defaultdict(lambda: {'metadata': {}, 'files': []})
    failed_count = 0
    
    # Convert Path objects to strings for multiprocessing
    file_paths = [str(f) for f in dicom_files]
    
    # Process files in parallel with rich progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        
        task = progress.add_task("[cyan]Extracting metadata...", total=len(file_paths))
        
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            # Submit all files for processing
            future_to_file = {executor.submit(process_single_file_for_metadata, filepath): filepath
                            for filepath in file_paths}
            
            # Process completed tasks
            for future in as_completed(future_to_file):
                filepath = future_to_file[future]
                try:
                    result = future.result()
                    if result:
                        series_uid = result['SeriesInstanceUID']
                        file_path = Path(result['FilePath'])
                        
                        # Add file to series
                        series_data[series_uid]['files'].append(file_path)
                        
                        # If this is the first file in the series, store metadata
                        if not series_data[series_uid]['metadata']:
                            metadata = {k: v for k, v in result.items() if k != 'FilePath'}
                            series_data[series_uid]['metadata'] = metadata
                        
                        progress.update(task, advance=1,
                                      description=f"[cyan]Processing: {Path(filepath).name}")
                    else:
                        failed_count += 1
                        progress.update(task, advance=1)
                except Exception as e:
                    logging.warning(f"Error processing {filepath}: {e}")
                    failed_count += 1
                    progress.update(task, advance=1)

    logging.info(f"Successfully processed {len(file_paths) - failed_count}/{len(file_paths)} files")
    logging.info(f"Found {len(series_data)} unique series")
    
    if failed_count > 0:
        logging.warning(f"Failed to process {failed_count} files")

    return dict(series_data)


def generate_template_csv(series_data: dict, template_path: str) -> None:
    """
    Generate a CSV template from series metadata.

    Args:
        series_data: Dictionary from extract_series_metadata_parallel()
        template_path: Path for output CSV template
    """
    logging.info("Generating CSV template...")

    # Prepare data for DataFrame
    rows = []
    for series_uid, data in series_data.items():
        row = data['metadata'].copy()
        row['FileCount'] = len(data['files'])
        rows.append(row)

    # Create DataFrame with SeriesInstanceUID as first column
    df = pd.DataFrame(rows)
    
    # Reorder columns: SeriesInstanceUID first, then others, FileCount last
    tag_columns = [tag for tag in TAG_DICT.keys() if tag != 'SeriesInstanceUID']
    column_order = ['SeriesInstanceUID'] + tag_columns + ['FileCount']
    df = df[column_order]

    # Sort by SeriesInstanceUID for consistency
    df = df.sort_values('SeriesInstanceUID')

    # Save to CSV
    output_path = Path(template_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    logging.info(f"Template CSV generated: {template_path}")
    logging.info(f"Total series: {len(df)}")
    logging.info(f"Total files: {df['FileCount'].sum()}")


def validate_tag_value(tag_name: str, value: str) -> tuple[bool, str]:
    """
    Validate a DICOM tag value format.

    Args:
        tag_name: Name of the DICOM tag
        value: Value to validate

    Returns:
        (is_valid, error_message)
    """
    # Empty values are allowed
    if not value or pd.isna(value):
        return True, ""

    value = str(value).strip()

    # Date fields: YYYYMMDD format
    if tag_name in ['StudyDate', 'PatientBirthDate']:
        if not re.match(r'^\d{8}$', value):
            return False, f"{tag_name} must be in YYYYMMDD format (8 digits)"

    # Time fields: Accept any numeric format (DICOM TM can be flexible)
    elif tag_name == 'StudyTime':
        # Accept any numeric value with optional decimal point (very permissive)
        if not re.match(r'^\d+(\.\d+)?$', value):
            return False, f"{tag_name} must contain only digits (with optional decimal point)"

    # Sex field: M, F, O, or empty
    elif tag_name == 'PatientSex':
        if value.upper() not in ['M', 'F', 'O', '']:
            return False, f"{tag_name} must be M, F, O, or empty"

    return True, ""


def load_and_validate_mapping_csv(csv_path: str) -> pd.DataFrame:
    """
    Load and validate a CSV mapping file.

    Args:
        csv_path: Path to the CSV file

    Returns:
        Validated DataFrame

    Raises:
        ValueError: If validation fails
    """
    logging.info(f"Loading mapping CSV: {csv_path}")

    # Load CSV
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        raise ValueError(f"Failed to read CSV file: {e}")

    # Check for required column
    if 'SeriesInstanceUID' not in df.columns:
        raise ValueError("CSV must contain 'SeriesInstanceUID' column")

    # Check for duplicate SeriesInstanceUID
    duplicates = df['SeriesInstanceUID'].duplicated()
    if duplicates.any():
        dup_uids = df[duplicates]['SeriesInstanceUID'].tolist()
        raise ValueError(f"Duplicate SeriesInstanceUID found: {dup_uids}")

    # Validate tag values
    errors = []
    for idx, row in df.iterrows():
        for tag_name in TAG_DICT.keys():
            if tag_name == 'SeriesInstanceUID':
                continue  # Skip the key column
            
            if tag_name in row:
                value = row[tag_name]
                is_valid, error_msg = validate_tag_value(tag_name, value)
                if not is_valid:
                    errors.append(f"Row {idx + 2}: {error_msg}")

    if errors:
        error_summary = "\n".join(errors[:10])  # Show first 10 errors
        if len(errors) > 10:
            error_summary += f"\n... and {len(errors) - 10} more errors"
        raise ValueError(f"CSV validation failed:\n{error_summary}")

    logging.info("CSV validation passed")
    logging.info(f"Found {len(df)} series in mapping CSV")

    return df


def update_dicom_tags(dataset, tag_updates: dict) -> None:
    """
    Update DICOM dataset tags in-place.

    Args:
        dataset: pydicom Dataset object
        tag_updates: Dictionary mapping tag names to new values
    """
    import warnings
    
    for tag_name, new_value in tag_updates.items():
        if tag_name == 'SeriesInstanceUID':
            continue  # Never update the key

        # Skip empty values (keep original)
        if pd.isna(new_value) or str(new_value).strip() == '':
            continue

        # Set the attribute
        try:
            # Suppress pydicom validation warnings for time fields
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', message='Invalid value for VR TM')
                setattr(dataset, tag_name, str(new_value))
        except Exception as e:
            logging.warning(f"Failed to set {tag_name} to '{new_value}': {e}")


def process_single_file_for_update(args: Tuple[str, dict, str, Path, bool]) -> Tuple[bool, str]:
    """
    Process a single DICOM file for update.
    This function is designed to be called by multiprocessing workers.
    
    Args:
        args: Tuple of (filepath, tag_updates, anonymized_patient_id, output_dir, dry_run)
        
    Returns:
        Tuple of (success, error_message)
    """
    filepath, tag_updates, anonymized_patient_id, output_dir, dry_run = args
    
    try:
        # Read DICOM file
        dataset = dcmread(filepath)

        # Update tags
        update_dicom_tags(dataset, tag_updates)

        if not dry_run:
            # Compute output path: output_dir / anonymized_patient_id / series_folder / filename
            file_path = Path(filepath)
            
            # Create subfolder structure: anonymized_patient_id / original_parent_folder_name
            # Use the immediate parent folder name to group files from the same series
            parent_folder_name = file_path.parent.name
            
            output_path = output_dir / anonymized_patient_id / parent_folder_name / file_path.name
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Save file
            dataset.save_as(str(output_path))

        return (True, "")

    except Exception as e:
        return (False, str(e))


def apply_updates_from_csv_parallel(
    series_data: dict,
    mapping_df: pd.DataFrame,
    output_dir: Path,
    num_workers: int,
    dry_run: bool = False
) -> dict:
    """
    Apply CSV mapping updates to DICOM files using multiprocessing.

    Args:
        series_data: Dictionary from extract_series_metadata_parallel()
        mapping_df: DataFrame with mapping information
        output_dir: Output directory
        num_workers: Number of parallel workers
        dry_run: If True, simulate without writing files

    Returns:
        Statistics dictionary
    """
    mode_prefix = "[DRY RUN] " if dry_run else ""
    logging.info(f"{mode_prefix}Applying updates to DICOM files using multiprocessing...")

    # Create mapping from SeriesInstanceUID to tag updates
    mapping_dict = {}
    for _, row in mapping_df.iterrows():
        series_uid = row['SeriesInstanceUID']
        tag_updates = {tag: row.get(tag, '') for tag in TAG_DICT.keys() if tag != 'SeriesInstanceUID'}
        mapping_dict[series_uid] = tag_updates

    # Statistics
    stats = {
        'total_series_in_csv': len(mapping_df),
        'total_series_in_dicom': len(series_data),
        'updated_series': 0,
        'total_files': 0,
        'updated_files': 0,
        'failed_files': 0,
        'skipped_files': 0,
        'unmatched_series_in_csv': [],
        'unmatched_series_in_dicom': []
    }

    # Find unmatched series
    csv_series = set(mapping_dict.keys())
    dicom_series = set(series_data.keys())
    stats['unmatched_series_in_csv'] = list(csv_series - dicom_series)
    stats['unmatched_series_in_dicom'] = list(dicom_series - csv_series)

    if stats['unmatched_series_in_csv']:
        logging.warning(f"Series in CSV but not in DICOM files: {len(stats['unmatched_series_in_csv'])}")
        for uid in stats['unmatched_series_in_csv'][:5]:
            logging.debug(f"  - {uid}")

    if stats['unmatched_series_in_dicom']:
        logging.info(f"Series in DICOM but not in CSV (will be skipped): {len(stats['unmatched_series_in_dicom'])}")
        for uid in stats['unmatched_series_in_dicom'][:5]:
            logging.debug(f"  - {uid}")

    # Prepare tasks for multiprocessing
    tasks = []
    for series_uid, data in series_data.items():
        if series_uid not in mapping_dict:
            # Skip series not in CSV
            stats['skipped_files'] += len(data['files'])
            continue

        tag_updates = mapping_dict[series_uid]
        files = data['files']
        stats['total_files'] += len(files)
        
        # Get anonymized patient ID from the mapping
        anonymized_patient_id = tag_updates.get('PatientID', 'UNKNOWN')
        if not anonymized_patient_id or pd.isna(anonymized_patient_id) or str(anonymized_patient_id).strip() == '':
            anonymized_patient_id = 'UNKNOWN'

        # Create tasks for each file in this series
        for file_path in files:
            tasks.append((str(file_path), tag_updates, anonymized_patient_id, output_dir, dry_run))

    # Process files in parallel with rich progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        
        task = progress.add_task(f"[cyan]{mode_prefix}Updating files...", total=len(tasks))
        
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            # Submit all tasks
            future_to_task = {executor.submit(process_single_file_for_update, task_args): task_args
                            for task_args in tasks}
            
            # Process completed tasks
            for future in as_completed(future_to_task):
                task_args = future_to_task[future]
                filepath = task_args[0]
                try:
                    success, error_msg = future.result()
                    if success:
                        stats['updated_files'] += 1
                        progress.update(task, advance=1,
                                      description=f"[cyan]{mode_prefix}Processing: {Path(filepath).name}")
                    else:
                        logging.error(f"Failed to update {filepath}: {error_msg}")
                        stats['failed_files'] += 1
                        progress.update(task, advance=1)
                except Exception as e:
                    logging.error(f"Error processing {filepath}: {e}")
                    stats['failed_files'] += 1
                    progress.update(task, advance=1)

    # Count updated series (series with at least one successfully updated file)
    for series_uid in series_data.keys():
        if series_uid in mapping_dict:
            stats['updated_series'] += 1

    logging.info(f"{mode_prefix}Update complete!")

    return stats


def print_statistics(stats: dict, output_dir: Optional[Path] = None, dry_run: bool = False) -> None:
    """
    Print statistics summary.

    Args:
        stats: Statistics dictionary from apply_updates_from_csv_parallel()
        output_dir: Output directory path
        dry_run: Whether this was a dry run
    """
    mode_text = " (DRY RUN)" if dry_run else ""
    
    logging.info("=" * 60)
    logging.info(f"SUMMARY{mode_text}")
    logging.info("=" * 60)
    logging.info(f"Series in CSV: {stats['total_series_in_csv']}")
    logging.info(f"Series in DICOM files: {stats['total_series_in_dicom']}")
    logging.info(f"Successfully updated series: {stats['updated_series']}")
    logging.info(f"Total files to process: {stats['total_files']}")
    logging.info(f"Successfully updated files: {stats['updated_files']}")
    logging.info(f"Failed files: {stats['failed_files']}")
    logging.info(f"Skipped files (not in CSV): {stats['skipped_files']}")
    
    if stats['unmatched_series_in_csv']:
        logging.info(f"Series in CSV but not found in DICOM: {len(stats['unmatched_series_in_csv'])}")
    
    if stats['unmatched_series_in_dicom']:
        logging.info(f"Series in DICOM but not in CSV (skipped): {len(stats['unmatched_series_in_dicom'])}")
    
    if output_dir and not dry_run:
        logging.info(f"Output directory: {output_dir}")
        logging.info(f"Files organized by anonymized PatientID in subfolders")
    
    if dry_run:
        logging.info("No files were modified (dry-run mode)")
    
    logging.info("=" * 60)


# Click CLI
@click.group()
@click.option('--verbose', is_flag=True, help='Enable verbose logging')
@click.pass_context
def cli(ctx, verbose):
    """
    DICOM Anonymizer with CSV-based Mapping (Multiprocessing Version)
    
    Two-stage workflow for flexible DICOM anonymization:
    1. Generate a CSV template with current DICOM tag values (parallel processing)
    2. Edit the CSV and apply changes to DICOM files (parallel processing)
    
    Files are organized by anonymized PatientID in the output directory.
    """
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose
    setup_logging(verbose)


@cli.command()
@click.option(
    '--input-dir',
    required=True,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help='Root directory containing DICOM files'
)
@click.option(
    '--template-csv',
    required=True,
    type=click.Path(),
    help='Path for output CSV template'
)
@click.option(
    '-n', '--num-workers',
    default=None,
    type=int,
    help='Number of parallel workers (default: CPU count)'
)
@click.option(
    '--verbose',
    is_flag=True,
    help='Enable verbose logging'
)
@click.pass_context
def generate(ctx, input_dir, template_csv, num_workers, verbose):
    """
    Generate a CSV template from DICOM files using multiprocessing.
    
    Scans all DICOM files in the input directory, groups them by
    SeriesInstanceUID, and creates a CSV template with current tag values
    that can be edited by the user.
    """
    # Setup logging with verbose flag
    if verbose:
        setup_logging(verbose=True)
    
    # Determine number of workers
    if num_workers is None:
        num_workers = multiprocessing.cpu_count()
    
    try:
        logging.info("=" * 60)
        logging.info("DICOM Anonymizer - Generate Template (Multiprocessing)")
        logging.info("=" * 60)
        logging.info(f"Workers: {num_workers}")

        # Step 1: Discover DICOM files
        dicom_files = discover_dicom_files(input_dir)
        if not dicom_files:
            logging.error("No DICOM files found. Exiting.")
            return

        # Step 2: Extract metadata grouped by series (parallel)
        series_data = extract_series_metadata_parallel(dicom_files, num_workers)
        if not series_data:
            logging.error("No valid series found. Exiting.")
            return

        # Step 3: Generate CSV template
        generate_template_csv(series_data, template_csv)

        logging.info("=" * 60)
        logging.info("Template generation complete!")
        logging.info("=" * 60)
        logging.info(f"Next steps:")
        logging.info(f"1. Edit the CSV file: {template_csv}")
        logging.info(f"2. Run: python {Path(__file__).name} apply --input-dir {input_dir} --mapping-csv {template_csv} --output-dir <output>")
        logging.info("=" * 60)

    except Exception as e:
        logging.error(f"An error occurred: {e}", exc_info=verbose)
        raise


@cli.command()
@click.option(
    '--input-dir',
    required=True,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help='Root directory containing DICOM files'
)
@click.option(
    '--mapping-csv',
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help='Path to modified CSV mapping file'
)
@click.option(
    '--output-dir',
    type=click.Path(),
    help='Output directory for updated DICOM files (default: <input-dir>-Updated)'
)
@click.option(
    '-n', '--num-workers',
    default=None,
    type=int,
    help='Number of parallel workers (default: CPU count)'
)
@click.option(
    '--dry-run',
    is_flag=True,
    help='Simulate updates without modifying files'
)
@click.option(
    '--verbose',
    is_flag=True,
    help='Enable verbose logging'
)
@click.pass_context
def apply(ctx, input_dir, mapping_csv, output_dir, num_workers, dry_run, verbose):
    """
    Apply CSV mapping to update DICOM files using multiprocessing.
    
    Reads the modified CSV file and updates DICOM tags for all files
    in each series according to the SeriesInstanceUID mapping.
    
    Files not in the CSV will be skipped (not anonymized).
    Output files are organized by anonymized PatientID in subfolders.
    """
    # Setup logging with verbose flag
    if verbose:
        setup_logging(verbose=True)
    
    # Determine number of workers
    if num_workers is None:
        num_workers = multiprocessing.cpu_count()
    
    try:
        mode_text = " (DRY RUN)" if dry_run else ""
        logging.info("=" * 60)
        logging.info(f"DICOM Anonymizer - Apply Updates{mode_text} (Multiprocessing)")
        logging.info("=" * 60)
        logging.info(f"Workers: {num_workers}")

        # Set default output directory
        if not output_dir:
            output_dir = Path(input_dir).parent / f"{Path(input_dir).name}-Updated"
        output_dir = Path(output_dir)

        # Step 1: Load and validate CSV
        mapping_df = load_and_validate_mapping_csv(mapping_csv)

        # Step 2: Discover DICOM files
        dicom_files = discover_dicom_files(input_dir)
        if not dicom_files:
            logging.error("No DICOM files found. Exiting.")
            return

        # Step 3: Extract metadata grouped by series (parallel)
        series_data = extract_series_metadata_parallel(dicom_files, num_workers)
        if not series_data:
            logging.error("No valid series found. Exiting.")
            return

        # Step 4: Apply updates (parallel)
        stats = apply_updates_from_csv_parallel(
            series_data,
            mapping_df,
            output_dir,
            num_workers,
            dry_run
        )

        # Step 5: Print summary
        print_statistics(stats, output_dir, dry_run)

        if not dry_run:
            logging.info("=" * 60)
            logging.info("Update complete!")
            logging.info("=" * 60)
        else:
            logging.info("=" * 60)
            logging.info("Dry run complete - no files were modified")
            logging.info("Remove --dry-run flag to apply changes")
            logging.info("=" * 60)

    except Exception as e:
        logging.error(f"An error occurred: {e}", exc_info=verbose)
        raise


if __name__ == "__main__":
    cli()
