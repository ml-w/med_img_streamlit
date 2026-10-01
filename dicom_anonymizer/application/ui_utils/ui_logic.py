import logging
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from pydicom.datadict import tag_for_keyword
from pydicom.tag import Tag

try:
    # Reuse Streamlit's logger factory (same handler/level setup as the other
    # modules, so run_app.py's --log-level applies). Only the logger module is
    # used; nothing here depends on Streamlit UI calls.
    from streamlit.logger import get_logger as _get_logger
    logger = _get_logger("ui_logic")
except ImportError:  # pragma: no cover - streamlit not installed
    logger = logging.getLogger("ui_logic")

def compute_effective_tags_2_anon(base_tags: list, update_tag_defaults: dict, selected_update_tags: list) -> list:
    """
    Remove tags for unselected "columns to update" from the base blank-anonymization list.

    Without this, a tag that the user did not choose to update (e.g. PatientName left
    out of "columns to update") would still be blanked to "" by the hardcoded/base
    tags_2_anon safety net, overriding the VR-type "Anonymized" pass. Dropping it from
    the list here lets the VR-type pass (or a real update value, if the tag is kept
    because it IS selected) handle it instead.

    Args:
        base_tags (list): (group, element) tuples to blank; either the config
            ``tags_2_anon`` override or the built-in ``default_tags_2_anon``.
        update_tag_defaults (dict): All configurable "columns to update" keywords.
        selected_update_tags (list): Keywords currently selected for update.

    Returns:
        list: ``base_tags`` with tags for unselected keywords removed. Tags for
            selected keywords are kept — an applied update overrides the blank
            anyway, and an unfilled update falls back to blanking as before.
    """
    unselected = [k for k in update_tag_defaults if k not in selected_update_tags]
    drop_tags = set()
    for keyword in unselected:
        tag_int = tag_for_keyword(keyword)
        if tag_int is None:
            continue
        drop_tags.add(Tag(tag_int))

    result = [t for t in base_tags if Tag(t) not in drop_tags]
    logger.debug("compute_effective_tags_2_anon: %d base tag(s) -> %d after dropping %d unselected update tag(s)",
                 len(base_tags), len(result), len(drop_tags))
    return result

def add_series_dir(df: pd.DataFrame, root_folder: str, col: str = 'SeriesDir') -> pd.DataFrame:
    """
    Add a display-only column with each row's series directory (the parent folder of
    its DICOM file, from the ``folder_dir`` column) expressed relative to the scanned
    root folder, e.g. ``Pt001/Study1/SE3``. Uses forward slashes (``Path.as_posix()``);
    a file sitting directly in the root becomes ``'.'``.

    Robust to trailing slashes / symlink resolution differences between ``folder_dir``
    and ``root_folder``: falls back to the unresolved paths, and finally to the
    absolute ``folder_dir`` string, if a relative path cannot be computed.

    Args:
        df (pd.DataFrame): DataFrame with a ``folder_dir`` column, as produced by
            ``create_dcm_df``.
        root_folder (str): The folder path passed to ``create_dcm_df`` as ``folder``.
        col (str): Name of the column to add.

    Returns:
        pd.DataFrame: ``df`` with the new column added (modified in place and returned).
    """
    if 'folder_dir' not in df.columns:
        logger.debug("add_series_dir: no 'folder_dir' column, skipping")
        return df

    root = Path(root_folder)
    try:
        root_resolved = root.resolve()
    except OSError:
        logger.debug("add_series_dir: could not resolve root folder %s, using unresolved path", root)
        root_resolved = root

    def _relative(folder_dir: str) -> str:
        p = Path(folder_dir)

        def _fmt(rel: Path) -> str:
            return '.' if str(rel) == '.' else rel.as_posix()

        try:
            return _fmt(p.resolve().relative_to(root_resolved))
        except (OSError, ValueError):
            logger.debug("add_series_dir: resolved relative path failed for %s, trying unresolved", folder_dir)
        try:
            return _fmt(p.relative_to(root))
        except ValueError:
            logger.debug("add_series_dir: %s is not under root, falling back to absolute path", folder_dir)
            return p.as_posix()

    df[col] = df['folder_dir'].apply(_relative)
    logger.debug("add_series_dir: added '%s' for %d row(s)", col, len(df))
    return df


def dedup_display_rows(df: pd.DataFrame, agg_col: str = 'SeriesDir', sep: str = '; ') -> pd.DataFrame:
    """
    Collapse a per-file display DataFrame to one row per PK (index value).

    For ``agg_col`` (when present in ``df``), the unique values across all rows
    sharing a PK are joined with ``sep`` in first-seen order — e.g. a coarser PK
    spanning two series directories collapses to a single ``'a/b; c/d'``-style value.
    Every other column keeps the existing first-row-wins dedup behaviour.

    Args:
        df (pd.DataFrame): PK-indexed DataFrame with one row per underlying file/series.
        agg_col (str): Column to aggregate instead of keeping only the first row's value.
        sep (str): Separator used to join aggregated unique values.

    Returns:
        pd.DataFrame: One row per unique index value.
    """
    first = df.loc[~df.index.duplicated()].copy()
    if agg_col in df.columns:
        joined = df[agg_col].astype(str).groupby(df.index).agg(lambda s: sep.join(dict.fromkeys(s)))
        first[agg_col] = first.index.map(joined)
    return first



# ---------------------------------------------------------------------------
# Output path planning
# ---------------------------------------------------------------------------

# Folder name used for a per_series output when the chosen naming tag has no
# usable (anonymized) value. Hardcoded per product decision, not config-driven.
NAMELESS_DIR = 'Nameless'

_UNSAFE_PATH_CHARS_RE = re.compile(r'[^\w.\-]+')


def safe_path_component(value) -> str:
    """
    Sanitize an arbitrary DICOM tag value into a string safe for use as a
    single path component (file or folder name).

    Args:
        value: Any DICOM tag value (may be a pydicom valuerep object such as
            ``PersonName``), or ``None``/NaN.

    Returns:
        str: ``''`` for ``None``/NaN. Otherwise ``str(value)`` with every run
            of characters other than word characters (unicode-aware, so
            non-ASCII names survive), ``.`` and ``-`` collapsed to a single
            ``_`` (turning ``^``, ``/``, ``\\``, spaces, ``:*?"<>|`` etc. into
            ``_``); leading/trailing ``.``/``_`` characters are then stripped
            and the result capped at 100 characters. ``''`` if nothing usable
            remains.
    """
    if value is None:
        return ''
    try:
        if pd.isna(value):
            return ''
    except (TypeError, ValueError):
        # pd.isna() can raise/return non-bool for exotic array-like objects;
        # treat those as present rather than failing sanitization.
        pass

    text = _UNSAFE_PATH_CHARS_RE.sub('_', str(value))
    text = text.strip('._')
    return text[:100]


def _by_tag_folder_name(row: pd.Series, subfolder_tag: str) -> str:
    """Folder name for the ``by_tag`` layout: ``Update_<tag>`` or original
    ``<tag>`` or ``'Unknown'``, sanitized. Preserves the pre-phase-A inline
    selection logic from user_interface.py, only sanitizing the final value."""
    update_col = f'Update_{subfolder_tag}' if subfolder_tag else None
    raw = (row.get(update_col, '') if update_col else '') \
        or (row.get(subfolder_tag, '') if subfolder_tag else '') \
        or 'Unknown'
    return safe_path_component(raw) or 'Unknown'


def _plan_by_tag(df: pd.DataFrame, base_output: str, subfolder_tag: str, basenames: pd.Series) -> pd.Series:
    """
    Target paths for the ``by_tag`` layout: ``<base>/<tag value>/series_NNN/<file>``.

    Series index numbers (``series_NNN``) are assigned per folder-name value,
    in first-appearance order of (folder name, SeriesInstanceUID) pairs -- two
    distinct series sharing the same folder name get ``series_001``,
    ``series_002``, ...
    """
    counters: dict = defaultdict(int)
    series_index: dict = {}
    paths = []
    for (_, row), basename in zip(df.iterrows(), basenames):
        folder_name = _by_tag_folder_name(row, subfolder_tag)
        series_uid = str(row.get('SeriesInstanceUID', ''))
        key = (folder_name, series_uid)
        if key not in series_index:
            counters[folder_name] += 1
            series_index[key] = counters[folder_name]
        idx = series_index[key]
        paths.append(str(Path(base_output) / folder_name / f"series_{idx:03d}" / basename))
    return pd.Series(paths, index=df.index)


def _per_series_name_value(row: pd.Series, series_name_tag: str, columns) -> object:
    """
    Raw (pre-sanitization) value used to name a series' output folder for the
    ``per_series`` layout.

    For PatientID/PatientName, only the anonymized ``Update_<tag>`` value is
    used -- the original value is PII and must never appear in an output
    path. For SeriesInstanceUID, ``Update_SeriesInstanceUID`` is used if
    present and non-empty, else the original ``SeriesInstanceUID`` (the
    anonymizer does not change UIDs, so there normally is no ``Update_``
    column for it).
    """
    if series_name_tag == 'SeriesInstanceUID':
        if 'Update_SeriesInstanceUID' in columns:
            candidate = row.get('Update_SeriesInstanceUID')
            if safe_path_component(candidate):
                return candidate
        return row.get('SeriesInstanceUID')
    return row.get(f'Update_{series_name_tag}')


def _plan_per_series(df: pd.DataFrame, base_output: str, series_name_tag: str, basenames: pd.Series) -> pd.Series:
    """
    Target paths for the ``per_series`` layout.

    Each series (grouped by ``series_key``) is named from its anonymized
    ``series_name_tag`` value (sanitized; empty/missing -> ``NAMELESS_DIR``).
    When two or more series resolve to the same folder name (including
    multiple series landing in ``NAMELESS_DIR``), each such series is placed
    under an additional subfolder named after its sanitized
    ``SeriesDescription``; a series with no (or empty) ``SeriesDescription``
    goes directly into the shared folder instead.
    """
    columns = df.columns

    # One representative row per series, in first-appearance order. Files of
    # the same series share the same Update_*/tag values (joined from a
    # single edit_df row), so the first row seen is representative.
    series_rows: dict = {}
    for _, row in df.iterrows():
        sk = row['series_key']
        if sk not in series_rows:
            series_rows[sk] = row

    folder_names = {
        sk: (safe_path_component(_per_series_name_value(row, series_name_tag, columns)) or NAMELESS_DIR)
        for sk, row in series_rows.items()
    }
    name_counts = Counter(folder_names.values())

    clash_subdirs = {}
    for sk, row in series_rows.items():
        if name_counts[folder_names[sk]] > 1:
            desc = row.get('SeriesDescription') if 'SeriesDescription' in columns else None
            clash_subdirs[sk] = safe_path_component(desc)

    n_clashing = sum(1 for sk in series_rows if name_counts[folder_names[sk]] > 1)
    logger.debug("_plan_per_series: %d series, %d distinct folder name(s), %d series in clashing folders "
                 "(%d given a description subfolder), %d nameless",
                 len(series_rows), len(name_counts), n_clashing,
                 sum(1 for v in clash_subdirs.values() if v),
                 sum(1 for v in folder_names.values() if v == NAMELESS_DIR))

    paths = []
    for (_, row), basename in zip(df.iterrows(), basenames):
        sk = row['series_key']
        name = folder_names[sk]
        if name_counts[name] > 1 and clash_subdirs.get(sk):
            paths.append(str(Path(base_output) / name / clash_subdirs[sk] / basename))
        else:
            paths.append(str(Path(base_output) / name / basename))
    return pd.Series(paths, index=df.index)


def _uniquify_target_paths(paths: pd.Series) -> pd.Series:
    """
    Guarantee uniqueness of planned output paths by walking rows in order and
    renaming any repeat to ``<stem>_<n><suffix>`` using the smallest ``n >= 1``
    not already taken.
    """
    seen: set = set()
    result = []
    for p in paths:
        candidate = p
        if candidate in seen:
            path_obj = Path(p)
            n = 1
            while True:
                candidate = str(path_obj.with_name(f"{path_obj.stem}_{n}{path_obj.suffix}"))
                if candidate not in seen:
                    break
                n += 1
        seen.add(candidate)
        result.append(candidate)
    n_renamed = sum(1 for a, b in zip(paths, result) if a != b)
    logger.debug("_uniquify_target_paths: %d of %d path(s) renamed to resolve collisions", n_renamed, len(result))
    return pd.Series(result, index=paths.index)


def plan_output_paths(
    df: pd.DataFrame,
    layout: str,
    base_output: str,
    subfolder_tag: str | None = None,
    series_name_tag: str | None = None,
) -> pd.DataFrame:
    """
    Pure path planner: given one row per DICOM file (as in ``dcm_info``/the
    Run-step join with ``edit_df``), compute each row's output file path
    without touching the filesystem. Extracted from the Run step so path
    planning can be unit-tested independently of Streamlit and, later,
    parallelized per series.

    Args:
        df (pd.DataFrame): One row per file. Must contain ``file_path`` and
            ``folder_dir``; ``output_dir`` is required for ``layout='mirror'``.
            ``SeriesInstanceUID``, ``SeriesDescription`` and ``Update_*``
            columns are used when present.
        layout (str): One of ``'mirror'``, ``'by_tag'``, ``'per_series'`` (see
            ``app_settings.config.output_layout_options``).
        base_output (str): Output root folder.
        subfolder_tag (str, optional): DICOM tag keyword used to build the
            top-level subfolder for ``layout='by_tag'``.
        series_name_tag (str, optional): One of
            ``app_settings.config.series_folder_name_options`` used to name
            each series' output folder for ``layout='per_series'``.

    Returns:
        pd.DataFrame: A copy of ``df`` (same index, input not mutated) with
            two added columns:
              - ``series_key``: ``str(SeriesInstanceUID)`` when that column
                exists and the value is non-null/non-empty, else the row's
                ``folder_dir``. Identifies which series a file belongs to.
              - ``target_path``: the planned output file path (str), unique
                across the returned DataFrame.
    """
    out = df.copy()
    logger.debug("plan_output_paths: layout=%s, base_output=%s, rows=%d, subfolder_tag=%s, series_name_tag=%s",
                 layout, base_output, len(out), subfolder_tag, series_name_tag)

    if 'SeriesInstanceUID' in out.columns:
        suid = out['SeriesInstanceUID']
        suid_str = suid.astype(str)
        valid = suid.notna() & (suid_str.str.strip() != '')
        out['series_key'] = suid_str.where(valid, out['folder_dir'].astype(str))
    else:
        out['series_key'] = out['folder_dir'].astype(str)

    basenames = out['file_path'].apply(lambda p: Path(str(p)).name)

    if layout == 'mirror':
        target_paths = out['output_dir'].astype(str) + '/' + basenames
    elif layout == 'by_tag':
        target_paths = _plan_by_tag(out, base_output, subfolder_tag, basenames)
    elif layout == 'per_series':
        target_paths = _plan_per_series(out, base_output, series_name_tag, basenames)
    else:
        logger.error("plan_output_paths: unknown output layout %r", layout)
        raise ValueError(f'Unknown output layout: {layout!r}')

    out['target_path'] = _uniquify_target_paths(target_paths.astype(str))
    logger.info("plan_output_paths: layout=%s, base_output=%s, %d file(s) in %d series planned",
                layout, base_output, len(out), out['series_key'].nunique())
    return out


def count_nameless_series(planned_df: pd.DataFrame, base_output: str) -> int:
    """
    Count distinct series (by ``series_key``) whose ``per_series`` output
    folder resolved to ``NAMELESS_DIR`` directly under ``base_output``. Used
    by the UI to warn the user before Run.

    Args:
        planned_df (pd.DataFrame): Output of
            ``plan_output_paths(..., layout='per_series')``.
        base_output (str): The same ``base_output`` passed to
            ``plan_output_paths``.

    Returns:
        int: Number of distinct series placed under ``NAMELESS_DIR``.
    """
    nameless_prefix = str(Path(base_output) / NAMELESS_DIR) + '/'
    mask = planned_df['target_path'].astype(str).str.startswith(nameless_prefix)
    n_nameless = int(planned_df.loc[mask, 'series_key'].nunique())
    logger.debug("count_nameless_series: %d nameless series", n_nameless)
    return n_nameless


def create_update_cols(udf: pd.DataFrame, update_tags: dict) -> pd.DataFrame:
    """
    Create new columns in udf for updating values of the defined DICOM tags. 
    
    Args:
        udf (pd.DataFrame): DataFrame of uniquely identified cases.
        update_tags (dict): Keys represent the DICOM tags to be updated, values represent the rules of creating default values. 
    
    Returns: 
        pd.DataFrame: The modified udf with columns in default values.
    """
    for tag, rule in update_tags.items():
        if callable(rule): 
            udf.loc[:, f'Update_{tag}'] = udf[tag].apply(rule)
        else: 
            udf.loc[:, f'Update_{tag}'] = rule
    return udf
            

def update_data_editor(edit_df: pd.DataFrame, upload_df: pd.DataFrame, update_tags: dict, upload_df_id: str) -> pd.DataFrame:
    """
    Updates the specified columns in an existing DataFrame (edit_df) with values from an uploaded DataFrame (upload_df).

    Args:
        edit_df (pd.DataFrame): DataFrame containing the original data to be updated.
        upload_df (pd.DataFrame): DataFrame with new values to apply to matching rows.
        update_tags (dict): Column tags to update in the edit_df.
        upload_df_id (str): Column used to identify matching rows.

    Returns:
        pd.DataFrame: The modified edit_df with updated values where matches were found.
    """
    n_matched = 0
    for _, row_udf in upload_df.iterrows():
        mask = edit_df[upload_df_id] == row_udf[upload_df_id]
        matching_row = edit_df[mask]

        if not matching_row.empty:
            idx = matching_row.index[0]
            n_matched += 1

            for tag, _ in update_tags.items():
                col = f'Update_{tag}'
                edit_df.at[idx, col] = row_udf[col]

    logger.debug("update_data_editor: matched %d of %d uploaded row(s) on '%s', updating %d column(s)",
                 n_matched, len(upload_df), upload_df_id, len(update_tags))
    return edit_df

def check_unmatched_rows(upload_df: pd.DataFrame, edit_df: pd.DataFrame, upload_df_id: str) -> list:
    """
    Checks for identifier in the edit_df that are not present in the upload_df.

    Args:
        upload_df (pd.DataFrame): The DataFrame uploaded by the user.
        edit_df (pd.DataFrame): The DataFrame from session state containing existing identifier.
        upload_df_id (str): The identifier DICOM tag used to represent any unmatched data. 

    Returns:
        list: A list of unmatched PatientIDs.
    """
    unmatched_patient_ids = edit_df[~edit_df[f'{upload_df_id}'].isin(upload_df[f'{upload_df_id}'])]
    unmatched = unmatched_patient_ids[f'{upload_df_id}'].unique().tolist()
    logger.debug("check_unmatched_rows: %d unmatched '%s' value(s)", len(unmatched), upload_df_id)
    return unmatched

def validate_upload(edit_df: pd.DataFrame, upload_df: pd.DataFrame, update_tags: dict, upload_df_id: str):
    """
    Validate the user-uploaded DataFrame against the specified update rules.

    This function checks for the following conditions:
    1. The presence of required columns in the uploaded DataFrame.
    2. Unmatched Patient IDs between the uploaded DataFrame and the edit DataFrame.

    Args:
        edit_df (pd.DataFrame): The DataFrame containing the original data that needs to be updated.
        upload_df (pd.DataFrame): The user-uploaded DataFrame that contains the updates.
        update_tags (dict): Dictionary of tags corresponding to the columns that need to be validated.
        upload_df_id (str): The identifier for the specific column being validated in the uploaded DataFrame.

    Returns:
        str or None: Returns an error message if any validation checks fail; otherwise, returns None.
    """
    
    # Error checking of columns in user uploaded file
    if f'{upload_df_id}' not in upload_df:
        logger.debug("validate_upload: failed, matcher column '%s' missing from upload", upload_df_id)
        return f':warning: Error in uploaded file: **Column "{upload_df_id}"** must be contained.'

    if upload_df_id in update_tags and f'Update_{upload_df_id}' not in upload_df:
        logger.debug("validate_upload: failed, column 'Update_%s' missing from upload", upload_df_id)
        return f':warning: Error in uploaded file: **Column "Update_{upload_df_id}"** must be contained.'
    
    logger.debug("validate_upload: passed")
    return None  # No errors found


def highlight_updated_cells(df: pd.DataFrame, update_tags: dict):
    """Return a Styler that highlights updated cells.

    Args:
        df (pd.DataFrame): DataFrame containing original and updated columns.
        update_tags (dict): Dictionary of selected tags to update.

    Returns:
        pandas.io.formats.style.Styler: Styled DataFrame with updates highlighted.
            Styling is skipped (plain Styler returned) if the index is non-unique,
            as pandas Styler does not support non-unique indices.
    """
    if not df.index.is_unique:
        return df.style

    def _highlight(data: pd.DataFrame) -> pd.DataFrame:
        colors = pd.DataFrame('', index=data.index, columns=data.columns)
        for tag in update_tags:
            orig_col = tag
            upd_col = f'Update_{tag}'
            if orig_col in data.columns and upd_col in data.columns:
                diff = (data[orig_col].astype(str) != data[upd_col].astype(str)) & (data[upd_col].astype(str) != '')
                colors.loc[diff, upd_col] = 'background-color: yellow'
        return colors

    return df.style.apply(_highlight, axis=None)
