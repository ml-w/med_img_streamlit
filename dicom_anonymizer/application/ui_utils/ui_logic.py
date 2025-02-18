import pandas as pd

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
            udf[f'Update_{tag}'] = udf[tag].apply(rule)
        else: 
            udf[f'Update_{tag}'] = rule
    return udf
            

def update_data_editor(edit_df: pd.DataFrame, upload_df: pd.DataFrame, update_tags: dict) -> pd.DataFrame:
    """
    Updates the specified columns in an existing DataFrame (edit_df) with values from an uploaded DataFrame (upload_df). 

    Args:
        edit_df (pd.DataFrame): DataFrame containing the original data to be updated.
        upload_df (pd.DataFrame): DataFrame with new values to apply to matching rows.
        update_tags (dict): Column tags to update in the edit_df.

    Returns:
        pd.DataFrame: The modified edit_df with updated values where matches were found.
    """
    for _, row_udf in upload_df.iterrows():
    # Check if the current row_udf matches the edit_df
        matching_row = edit_df[(edit_df['PatientID'] == row_udf['PatientID'])]
    
        # Update only if row_udf matches
        if not matching_row.empty:
            idx = matching_row.index[0]  # Get the index of the matching row_udf
            
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
    unmatched_patient_ids = edit_df[~edit_df[f'{upload_df_id}'].isin(upload_df[f'{upload_df_id}']) & 
                                      ~edit_df[f'{upload_df_id}'].isin(upload_df[f'Update_{upload_df_id}'])]
    return unmatched_patient_ids[f'{upload_df_id}'].unique().tolist()

def check_empty_cols(edit_df: pd.DataFrame, update_tags: dict) -> list:
    """
    Check for empty update columns in edit_df. 
    
    Args:
        edit_df (pd.DataFrame): The DataFrame from session state with user's edits. 
        update_tags (dict): The dictionary of DICOM tags to be updated. 
    
    Returns:
        list: A list of string, representing the name of empty columns. 

    """
    empty_col = []
    for tag, _ in update_tags.items():
        if edit_df[f'Update_{tag}'].isnull().any() or (edit_df[f'Update_{tag}'] == '').any(): 
            empty_col.append(f'Update_{tag}')
    return empty_col

def validate_upload(edit_df: pd.DataFrame, upload_df: pd.DataFrame, update_tags: dict, upload_df_id: str):
    """
    Validate the user-uploaded DataFrame against the specified update rules.

    This function checks for the following conditions:
    1. Empty values in specified columns of the edit DataFrame.
    2. The presence of required columns in the uploaded DataFrame.
    3. Unmatched Patient IDs between the uploaded DataFrame and the edit DataFrame.

    Args:
        edit_df (pd.DataFrame): The DataFrame containing the original data that needs to be updated.
        upload_df (pd.DataFrame): The user-uploaded DataFrame that contains the updates.
        update_tags (list): A list of tags corresponding to the columns that need to be validated.
        upload_df_id (str): The identifier for the specific column being validated in the uploaded DataFrame.

    Returns:
        str or None: Returns an error message if any validation checks fail; otherwise, returns None.
    """
    
    # Error checking of empty columns in "Update"
    empty_col = check_empty_cols(upload_df, update_tags)
    if len(empty_col) > 0:
        return f':warning: Error in uploaded file: There are empty values in the following columns: :blue[{", ".join(empty_col)}]'
    
    # Error checking of columns in user uploaded file
    if f'Update_{upload_df_id}' not in upload_df:
        return f':warning: Error in uploaded file: **Column "Update_{upload_df_id}"** must be contained.'
    
    if f'{upload_df_id}' not in upload_df:
        return f':warning: Error in uploaded file: **Column "{upload_df_id}"** must be contained.'
    
    # Error checking of unmatched PatientIDs
    unmatched_ids = check_unmatched_rows(upload_df, edit_df, upload_df_id)
    if unmatched_ids:
        unmatched_ids_str = ', '.join(map(str, unmatched_ids))
        return f':warning: Error in uploaded file: The following **{upload_df_id}** have no matches in the uploaded file - :blue[{unmatched_ids_str}].'
    
    return None  # No errors found