import os
import re
import fnmatch
import pydicom
from pydicom import *
from pathlib import Path
from typing import Any, Optional
from pydicom.tag import Tag
import pandas as pd
import streamlit
from streamlit import logger
import functools
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor, as_completed


def _read_tags(path: str, tags: list[str]) -> tuple[str, Optional[dict], Optional[str]]:
    """
    Worker: reads one DICOM file's header and extracts ``tags``. Module-level and
    Streamlit/logging-free so it can be pickled and run in a subprocess.

    Returns:
        (path, values_dict, None) on success, or (path, None, repr(error)) on failure.
    """
    try:
        f = pydicom.dcmread(path, stop_before_pixels=True)
    except Exception as e:
        return path, None, repr(e)

    values = {}
    for dcm_tag in tags:
        if dcm_tag == 'PatientName':
            values[dcm_tag] = ''.join(getattr(f, dcm_tag, ''))
        else:
            values[dcm_tag] = getattr(f, dcm_tag, None)
    return path, values, None

def find_files(folder_dir: Path, fformat: str) -> list[Path]:
    """
    Recursively finds files matching ``fformat`` under ``folder_dir``.

    Unlike ``Path.rglob``, this follows symlinked directories, so patient/series
    folders that are symlinks (common with PACS archives or mounted storage)
    are not silently skipped.

    Args:
        folder_dir (Path): The root folder to search.
        fformat (str): A glob-style filename pattern (e.g. ``*.dcm``).

    Returns:
        list[Path]: Matching file paths.
    """
    logger.get_logger('anonymizer').info(f"Scanning {folder_dir} for files matching '{fformat}'")
    files = [
        Path(dirpath) / fname
        for dirpath, _, filenames in os.walk(folder_dir, followlinks=True)
        for fname in filenames
        if fnmatch.fnmatch(fname, fformat)
    ]
    logger.get_logger('anonymizer').info(f"Found {len(files)} file(s) matching '{fformat}' under {folder_dir}")
    return files

def create_output_dir(file_dir: str | Path, folder_dir: Path) -> str:
    """
    Generates the output directory path for anonymized files.
    
    Args: 
        file_dir (str | Path): The DICOM file path. 
        folder_dir (Path): The folder directory of the DICOM file. 
    
    Returns:
        str: A string which represents the output file path. 
    """
    out_dir = str(file_dir).replace(str(folder_dir), str(folder_dir.parent / f"{folder_dir.name}-Anonymized"))
    logger.get_logger('anonymizer').debug(f"Output dir for {file_dir}: {out_dir}")
    return out_dir

def create_dcm_df(
    folder: str,
    fformat: str,
    unique_ids: list,
    ref_tags: list,
    new_tags: list,
    series_mode: bool = False,
    progress_bar: Any = None,
    max_workers: int = 8,
    parallel_threshold: int = 500,
) -> pd.DataFrame:
    """
    Gathers the meta data of each DICOM file from the folder. 
        
    Args: 
        folder (str): The directory of folder with dicom files.
        fformat (str): The file format of the targeted files. 
        unique_ids (list): The list of columns used as primary keys.
        ref_tags (list): The list of columns to be shown in template.
        new_tags (list): The list of tags to be determine its existence.
        progress_bar (streamlit.ProgressMixin): A progress bar to tell the progress.
        max_workers (int): Number of worker processes used to read files in parallel (series_mode only).
        parallel_threshold (int): Minimum number of files before the process pool is used (series_mode only).
    Returns:
        pd.DataFrame: A dataframe which contains information of the dicom tags.
    """
    folder_dir = Path(folder)

    if progress_bar is None:
        class _NoOpProgress:
            def progress(self, *args, **kwargs):
                pass

        progress_bar = _NoOpProgress()

    if "*" not in fformat:
        fformat = f"*.{fformat.lstrip('.')}"

    # Combine all requested tags once to avoid duplicate entries when a tag
    # appears in multiple configuration lists (e.g., ``SeriesInstanceUID`` in
    # both ``unique_ids`` and ``ref_tags``). Using ``dict.fromkeys`` preserves
    # the original order while de-duplicating.
    all_tags = list(dict.fromkeys(unique_ids + ref_tags + new_tags))

    dcm_info = {
        'folder_dir': [],
        'output_dir': [],
        'file_path': [],   # actual path of each DICOM file; used at anonymization time
    }
    dcm_info.update({dcm_tag: [] for dcm_tag in all_tags})

    if series_mode:
        logger.get_logger('anonymizer').info("Executing in series mode")
        # Get the all the files that need processing
        progress_bar.progress(0, text="Finding files to process...")
        file_dirs = find_files(folder_dir, fformat)
        p = 10.0
        progress_bar.progress(p / 100, text=f"Found {len(file_dirs)} files.")

        n_files = len(file_dirs)
        str_paths = [str(fd) for fd in file_dirs]
        worker = functools.partial(_read_tags, tags=all_tags)
        use_parallel = n_files >= parallel_threshold and max_workers > 1
        logger.get_logger('anonymizer').debug(
            f"Header scan: {n_files} file(s), threshold={parallel_threshold}, max_workers={max_workers} -> "
            f"{'parallel' if use_parallel else 'sequential'}"
        )
        last_pct = 10

        executor = None
        try:
            if use_parallel:
                # spawn (not fork): forking the multi-threaded Streamlit server can deadlock
                executor = ProcessPoolExecutor(
                    max_workers=max_workers,
                    mp_context=multiprocessing.get_context('spawn'),
                )
                results = executor.map(worker, str_paths, chunksize=64)
            else:
                results = map(worker, str_paths)

            for i, (path, values, err) in enumerate(results):
                pct = int(min(10.0 + 90.0 * (i + 1) / max(n_files, 1), 100.0))
                if pct != last_pct:
                    progress_bar.progress(pct / 100, text=f"Parsing series: {Path(path).parent}")
                    last_pct = pct

                if values is None:
                    logger.get_logger('anonymizer').warning(f"Cannot process file: {path}. Skipping...")
                    logger.get_logger('anonymizer').debug(f"Original error: {err}")
                    continue

                series_dir = Path(path).parent
                dcm_info['folder_dir'].append(str(series_dir))
                dcm_info['output_dir'].append(create_output_dir(series_dir, folder_dir))
                dcm_info['file_path'].append(path)
                for dcm_tag in all_tags:
                    dcm_info[dcm_tag].append(values[dcm_tag])
        finally:
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=True)

        logger.get_logger('anonymizer').info(f"Length of each item in dcm_info: {', '.join([f'{key}: {len(value)}' for key, value in dcm_info.items()])}")
        # No dedup here — each row is one file. The UI deduplicates for display/editing
        # (edit_df) via the user-selected PK, but dcm_info keeps every file so that the
        # Run step can process each file exactly once without any directory-based rglob.
        df = pd.DataFrame(dcm_info)
    else:
        if folder_dir.is_dir():
            processed = []
            # Get the all the files that need processing
            progress_bar.progress(0, text="Finding files to process...")
            file_list = find_files(folder_dir, fformat)
            p = 10.0
            progress_bar.progress(p / 100, text=f"Found {len(file_list)} files.")
            for file_dir in file_list:
                # Update progress
                p += 90 / len(file_list)
                
                if file_dir.is_dir():
                    logger.get_logger('anonymizer').debug(f"Skipping director {file_dir}")
                    continue
                if file_dir.parent in processed:
                    # Skip because we only look at first valid file per directory, this save us some time.
                    continue

                # Report progress
                logger.get_logger('anonymizer').debug(f"Parsing: {file_dir}")
                progress_bar.progress(p / 100, text=f"Parsing: {file_dir}")
                try:
                    f = pydicom.dcmread(str(file_dir), stop_before_pixels=True)
                except Exception as e:
                    logger.get_logger('anonymizer').warning(f"Cannot process file: {file_dir}. Skipping...")
                    logger.get_logger('anonymizer').debug(f"Original error: {e = }")
                    continue

                dcm_info['folder_dir'].append(str(file_dir.parent))
                dcm_info['output_dir'].append(create_output_dir(file_dir.parent, folder_dir))

                # Gather information from DICOM tags
                for dcm_tag in all_tags:
                    if dcm_tag == 'PatientName':
                        dcm_info[dcm_tag].append(''.join(getattr(f, dcm_tag, '')))
                    else:
                        dcm_info[dcm_tag].append(getattr(f, dcm_tag, None))
                
                logger.get_logger('anonymizer').debug(f'Successfully processed file: {file_dir}')
                # Add the paraent dir to processed file
                processed.append(file_dir.parent)

    # Incase nothing is read
    if len(dcm_info):
        df = pd.DataFrame(dcm_info)
    else:
        logger.get_logger('anonymizer').error("Something wrong, nothing is globbed")
        df = None
            
    if not df is None:
        df['PK'] = df[unique_ids].astype(str).agg('_'.join, axis=1)
        df.set_index('PK', inplace=True)
        logger.get_logger('anonymizer').debug(f"Built DataFrame with {len(df)} row(s) and {len(df.columns)} column(s)")
    return df

def consolidate_tags(row: pd.Series, update_tags: dict) -> dict: 
    """
    Consolidate a dictionary of DICOM tag series number based on their respective common name. 
    
    Args:
        row (pd.Series): The value represents the common name of the DICOM Tag.
        update_tags (dict): The dictionary containing common name of DICOM Tag as key.
        
    Returns:
        dict: An updated dictionary with DICOM tag series number as key.
    """
    # DICOM Tag Table
    tag_dict = {
        'PatientName':              Tag((0x0010, 0x0010)),
        'PatientID':                Tag((0x0010, 0x0020)),
        'PatientBirthDate':         Tag((0x0010, 0x0030)),
        'PatientSex':               Tag((0x0010, 0x0040)),
        'AccessionNumber':          Tag((0x0008, 0x0050)),
        'InstitutionName':          Tag((0x0008, 0x0080)),
        'StudyDate':                Tag((0x0008, 0x0020)),
        'StudyTime':                Tag((0x0008, 0x0031)),
        'BodyPartExamined':         Tag((0x0018, 0x0015)), 
        'PatientAge':               Tag((0x0010, 0x1010)),
    }
    
    update = {}
    for dcm_tag in update_tags:
        value = row.get(f'Update_{dcm_tag}')
        if pd.notna(value) and value != '':
            update[tag_dict[dcm_tag]] = value

    logger.get_logger('anonymizer').debug(
        f"Consolidated {len(update)} tag update(s) from {len(update_tags)} candidate(s): {sorted(str(t) for t in update)}"
    )
    return update

def remove_info(dataset: Dataset,
                data_element: DataElement,
                va_type: Optional[list[str]],
                tags: Optional[list[tuple]],
                update: Optional[dict],
                tags_2_spare: list[tuple],
                extra_tags_2_anon: Optional[list] = None,
                regex_pattern: Optional[str] = None):
    """
    Removes (anonymizes) or updates specific information from a DICOM dataset.

    Args:
        dataset: The DICOM dataset containing the data element to be modified.
        data_element: The specific data element (tag) to be processed.
        va_type (list, optional): A list of VR types that should be cleared.
        tags (list of tuples, optional): A list of DICOM tags for which the value should be cleared.
        update (dict, optional): A dictionary containing tags as keys and the new values as values.
        tags_2_spare (list, optional): A list of tags that should be spared from deletion or anonymization.
        extra_tags_2_anon (list, optional): Additional user-specified tags whose values are cleared.
        regex_pattern (str, optional): A regex pattern; any string value matching it is replaced with "Anonymized".

    Returns:
        None: The function modifies the data element in place and does not return a value.
    """
    # Spare sequence name — takes priority over everything
    if data_element.tag in tags_2_spare:
        return

    # Delete by value group
    if data_element.VR.strip() in [v.strip() for v in va_type]:
        try:
            data_element.value = "Anonymized"
        except:
            data_element.value = ""

    # Delete by built-in tag list
    if data_element.tag in tags:
        data_element.value = ""

    # Delete by user-specified extra tags to anonymize
    if extra_tags_2_anon and data_element.tag in extra_tags_2_anon:
        data_element.value = ""

    # Regex match anonymization — replaces matching string values with "Anonymized"
    if regex_pattern:
        val = data_element.value
        if isinstance(val, str) and re.search(regex_pattern, val):
            try:
                data_element.value = "Anonymized"
            except:
                data_element.value = ""

    if not update is None:
        if data_element.tag in list(update.keys()):
            data_element.value = update[data_element.tag]
            
def anonymize(file_dir: str,
              output_dir: str,
              tags: Optional[list] = None,
              va_type: Optional[list] = None,
              update: Optional[dict] = None,
              tags_2_spare: Optional[dict] = None,
              tags_2_create: Optional[dict] = None,
              extra_tags_2_anon: Optional[list] = None,
              regex_pattern: Optional[str] = None):
    """
    - Anonymizes a DICOM file by removing sensitive information based on specified tags. 
    - If no tags are provided, defaults to a predefined list. 
    - Saves the modified file to the specified output directory and handles invalid DICOM files.


    ..note::
        If you are using update, the regular paranthesis don't work in dictionary and
        will be converted to integer. You should use the format
        ```
        from pydicom.tag import Tag
        update = {
            Tag((0x0010, 0x0020)): "New name"
        }
        ```
        for this to work.


    Args:
        file_dir (str): The path to the input DICOM file.
        output_dir (str): The path where the modified DICOM file will be saved.
        tags (list of tuples, optional): A list of DICOM tags to be anonymized. If None, default tags for sensitive patient information are used.
        va_type (list of str, optional): VR types whose values are replaced with "Anonymized". If None, defaults to ["PN", "LO", "SH", "AE", "DT", "DA"].
        update (dict, optional): A dictionary of tags and their new values for updates.
        tags_2_spare (list, optional): Tags that should not be modified.
        tags_2_create (dict, optional): Tags to be created. ``None`` is treated as ``{}``.

    Returns:
        int: Returns 0 upon successful processing.

    Raises:
        Exception: Any error reading, walking, or writing the file (e.g.
            ``pydicom.errors.InvalidDicomError``, ``OSError``) propagates to the
            caller instead of being swallowed — callers that process many files
            (e.g. ``_anonymize_series``) catch per-file so one bad file doesn't
            abort the rest.
    """
    # Default VR types to anonymize
    if va_type is None:
        va_type = ["PN", "LO", "SH", "AE", "DT", "DA"]
    # Default tags to remove for anonymization — defined in app_settings/config.py
    # (default_tags_2_anon) so the UI can reason about the same default list.
    if tags is None:
        try:
            # Works when ``application/`` is on sys.path (app runtime).
            from app_settings.config import default_tags_2_anon
        except ImportError:
            # Works when this module is imported as part of the ``dicom_anonymizer``
            # package (e.g. from tests), where app_settings isn't a top-level module.
            from ..app_settings.config import default_tags_2_anon
        tags = default_tags_2_anon

    f = pydicom.dcmread(str(file_dir))

    # Remove and update tags
    f.remove_private_tags()
    f.walk(lambda x1, x2: remove_info(
        x1, x2,
        tags=tags,
        va_type=va_type,
        update=update,
        tags_2_spare=tags_2_spare,
        extra_tags_2_anon=extra_tags_2_anon,
        regex_pattern=regex_pattern,
    ))

    # Create new tags
    for dcm_tag, value in (tags_2_create or {}).items():
        setattr(f, dcm_tag, value)

    # Write files
    Path(output_dir).parent.mkdir(parents=True, exist_ok=True)
    f.save_as(output_dir)
    return 0


def _anonymize_series(
    task: tuple,
    *,
    tags: Optional[list],
    va_type: Optional[list],
    tags_2_spare: Optional[list],
    tags_2_create: Optional[dict],
    extra_tags_2_anon: Optional[list],
    regex_pattern: Optional[str],
) -> tuple[str, int, list[tuple[str, str]]]:
    """
    Worker: anonymizes every file belonging to one series. Module-level and
    Streamlit/logging-free so it can be pickled and run in a subprocess (same
    constraints as ``_read_tags``).

    Args:
        task: ``(series_key, [(src_path, dst_path, update_dict), ...])``.
        tags, va_type, tags_2_spare, tags_2_create, extra_tags_2_anon, regex_pattern:
            forwarded as-is to ``anonymize()`` for every file in the series.
            ``tags`` is always passed explicitly (never ``None``) so the worker
            never hits ``anonymize()``'s own config-import fallback, which would
            re-import ``app_settings.config`` in every subprocess.

    Returns:
        tuple[str, int, list[tuple[str, str]]]: ``(series_key, n_ok, errors)``
            where ``errors`` is a list of ``(src_path, repr(exception))`` for
            files that failed -- one bad file does not abort the rest of the
            series.
    """
    series_key, files = task
    n_ok = 0
    errors: list[tuple[str, str]] = []
    for src_path, dst_path, update in files:
        try:
            anonymize(
                file_dir=src_path,
                output_dir=dst_path,
                tags=tags,
                va_type=va_type,
                update=update,
                tags_2_spare=tags_2_spare,
                tags_2_create=tags_2_create,
                extra_tags_2_anon=extra_tags_2_anon,
                regex_pattern=regex_pattern,
            )
            n_ok += 1
        except Exception as e:
            errors.append((src_path, repr(e)))
    return series_key, n_ok, errors


def run_anonymization(
    tasks: list,
    settings: dict,
    max_workers: int,
    parallel_threshold: int,
    on_progress: Optional[Any] = None,
) -> tuple[int, list[tuple[str, str]]]:
    """
    Anonymizes a list of per-series tasks, one series at a time per worker,
    optionally in parallel across series.

    Args:
        tasks (list): One entry per series:
            ``(series_key, [(src_path, dst_path, update_dict), ...])``. Target
            paths are expected to already be planned and unique (see
            ``ui_utils.ui_logic.plan_output_paths``), so the completion order
            of parallel tasks doesn't matter.
        settings (dict): kwargs forwarded to ``_anonymize_series``/``anonymize()``
            for every file: ``tags``, ``va_type``, ``tags_2_spare``,
            ``tags_2_create``, ``extra_tags_2_anon``, ``regex_pattern``.
        max_workers (int): Worker processes to use.
        parallel_threshold (int): Minimum total file count (summed across all
            tasks) before the process pool is used; below it (and with a
            single task, or ``max_workers <= 1``), tasks run sequentially in
            the main process -- spawning workers costs ~1-2s, not worth it for
            small jobs.
        on_progress (callable, optional): ``on_progress(done_files, total_files,
            series_key)``, called in the main process once a series finishes.

    Returns:
        tuple[int, list[tuple[str, str]]]: ``(total_ok, all_errors)`` --
            ``total_ok`` is the number of successfully anonymized files across
            all series; ``all_errors`` is a list of ``(src_path,
            repr(exception))`` for every file that failed, including every file
            of a task whose future itself raised (e.g. a broken worker
            process).
    """
    total_files = sum(len(files) for _, files in tasks)
    use_parallel = max_workers > 1 and total_files >= parallel_threshold and len(tasks) > 1
    log = logger.get_logger('anonymizer')
    start_time = time.perf_counter()
    log.info(f"Starting anonymization: {total_files} file(s) in {len(tasks)} series task(s)")
    log.debug(
        f"Anonymization mode: {'parallel' if use_parallel else 'sequential'} "
        f"(max_workers={max_workers}, parallel_threshold={parallel_threshold}, "
        f"total_files={total_files}, tasks={len(tasks)})"
    )
    # NOTE: logging is done here in the main process only; the per-series worker
    # (_anonymize_series / anonymize / remove_info) must stay logging-free because
    # it runs in spawned subprocesses.

    worker = functools.partial(_anonymize_series, **settings)

    total_ok = 0
    all_errors: list[tuple[str, str]] = []
    done_files = 0

    executor = None
    try:
        if use_parallel:
            # spawn (not fork): forking the multi-threaded Streamlit server can deadlock
            executor = ProcessPoolExecutor(
                max_workers=min(max_workers, len(tasks)),
                mp_context=multiprocessing.get_context('spawn'),
            )
            futures = {executor.submit(worker, task): task for task in tasks}
            for future in as_completed(futures):
                series_key, task_files = futures[future]
                try:
                    _, n_ok, errors = future.result()
                except Exception as e:
                    # e.g. a broken/killed worker process -- the whole task's
                    # files are unaccounted for; report them all as failed
                    # rather than silently dropping them or crashing the run.
                    n_ok = 0
                    errors = [(src_path, repr(e)) for src_path, _, _ in task_files]
                total_ok += n_ok
                all_errors.extend(errors)
                done_files += len(task_files)
                log.debug(f"Series {series_key}: {n_ok}/{len(task_files)} file(s) anonymized")
                for src_path, err in errors:
                    log.warning(f"Failed to anonymize {src_path}: {err.split('(')[0]}")
                if on_progress is not None:
                    on_progress(done_files, total_files, series_key)
        else:
            for task in tasks:
                series_key, task_files = task
                _, n_ok, errors = worker(task)
                total_ok += n_ok
                all_errors.extend(errors)
                done_files += len(task_files)
                log.debug(f"Series {series_key}: {n_ok}/{len(task_files)} file(s) anonymized")
                for src_path, err in errors:
                    log.warning(f"Failed to anonymize {src_path}: {err.split('(')[0]}")
                if on_progress is not None:
                    on_progress(done_files, total_files, series_key)
    finally:
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    log.info(
        f"Anonymization finished in {time.perf_counter() - start_time:.2f}s: "
        f"{total_ok} succeeded, {len(all_errors)} failed, {total_files} total"
    )
    return total_ok, all_errors