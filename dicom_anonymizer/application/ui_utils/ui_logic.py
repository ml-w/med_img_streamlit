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
