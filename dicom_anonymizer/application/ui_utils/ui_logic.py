from pathlib import Path

import pandas as pd
from pydicom.datadict import tag_for_keyword
from pydicom.tag import Tag

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

    return [t for t in base_tags if Tag(t) not in drop_tags]

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
        return df

    root = Path(root_folder)
    try:
        root_resolved = root.resolve()
    except OSError:
        root_resolved = root

    def _relative(folder_dir: str) -> str:
        p = Path(folder_dir)

        def _fmt(rel: Path) -> str:
            return '.' if str(rel) == '.' else rel.as_posix()

        try:
            return _fmt(p.resolve().relative_to(root_resolved))
        except (OSError, ValueError):
            pass
        try:
            return _fmt(p.relative_to(root))
        except ValueError:
            return p.as_posix()

    df[col] = df['folder_dir'].apply(_relative)
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
    for _, row_udf in upload_df.iterrows():
        mask = edit_df[upload_df_id] == row_udf[upload_df_id]
        matching_row = edit_df[mask]

        if not matching_row.empty:
            idx = matching_row.index[0]

            for tag, _ in update_tags.items():
                col = f'Update_{tag}'
                edit_df.at[idx, col] = row_udf[col]
        
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
    return unmatched_patient_ids[f'{upload_df_id}'].unique().tolist()

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
        return f':warning: Error in uploaded file: **Column "{upload_df_id}"** must be contained.'

    if upload_df_id in update_tags and f'Update_{upload_df_id}' not in upload_df:
        return f':warning: Error in uploaded file: **Column "Update_{upload_df_id}"** must be contained.'
    
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
