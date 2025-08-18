import pydicom
from pydicom.errors import InvalidDicomError
from pydicom import *
from pathlib import Path
from typing import Optional
from pydicom.tag import Tag
import pandas as pd
import streamlit
from streamlit import logger

def create_output_dir(file_dir: str, folder_dir: Path) -> str:
    """
    Generates the output directory path for anonymized files.
    
    Args: 
        file_dir (str): The DICOM file path. 
        folder_dir (str): The folder directory of the DICOM file. 
    
    Returns:
        str: A string which represents the output file path. 
    """
    return str(file_dir).replace(str(folder_dir), str(folder_dir.parent / f"{folder_dir.name}-Anonymized"))

def create_dcm_df(
    folder: str,
    fformat: str,
    unique_ids: list,
    ref_tags: list,
    new_tags: list,
    series_mode: bool = False,
    progress_bar: 'ProgressMixin' = None
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
    Returns:
        pd.DataFrame: A dataframe which contains information of the dicom tags. 
    """
    folder_dir = Path(folder)

    # Combine all requested tags once to avoid duplicate entries when a tag
    # appears in multiple configuration lists (e.g., ``SeriesInstanceUID`` in
    # both ``unique_ids`` and ``ref_tags``). Using ``dict.fromkeys`` preserves
    # the original order while de-duplicating.
    all_tags = list(dict.fromkeys(unique_ids + ref_tags + new_tags))

    dcm_info = {
        'folder_dir': [],
        'output_dir': []
    }
    dcm_info.update({dcm_tag: [] for dcm_tag in all_tags})

    if series_mode:
        logger.get_logger('anonymizer').info("Executing in series mode")
        for file_dir in folder_dir.rglob(fformat):
        logger.get_logger('anonymizer').info("Executing in series mode")
        for file_dir in folder_dir.rglob(fformat):
            series_dir = file_dir.parent

            try:
                f = pydicom.dcmread(str(file_dir), stop_before_pixels=True)
            except Exception as e:
                continue

            dcm_info['folder_dir'].append(str(series_dir))
            dcm_info['output_dir'].append(create_output_dir(series_dir, folder_dir))

            # Gather information from DICOM tags
            for dcm_tag in all_tags:
                if dcm_tag == 'PatientName':
                    dcm_info[dcm_tag].append(''.join(getattr(f, dcm_tag, '')))
                else:
                    dcm_info[dcm_tag].append(getattr(f, dcm_tag, None))

        logger.get_logger('anonymizer').info(f"Length of each item in dcm_info: {', '.join([f'{key}: {len(value)}' for key, value in dcm_info.items()])}")
        df = pd.DataFrame(dcm_info)
        df.drop_duplicates(subset=unique_ids, inplace=True)
    else:
        if folder_dir.is_dir():
            processed = []
            # Get the all the files that need processing
            progress_bar.progress(0, text="Finding files to process...")
            file_list = list(folder_dir.rglob(fformat))
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
                dcm_info['output_dir'].append(create_output_dir(folder_dir.name, folder_dir.parent))

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
    # Incase nothing is read
    if len(dcm_info):
        df = pd.DataFrame(dcm_info)
    else:
        logger.get_logger('anonymizer').error("Something wrong, nothing is globbed")
        df = None
            
    if not df is None:
        df['PK'] = df[unique_ids].astype(str).agg('_'.join, axis=1)
        df.set_index('PK', inplace=True)
    else:
        logger.get_logger('anonymizer').error("Something wrong, nothing is globbed")
        df = None
            
    if not df is None:
        df['PK'] = df[unique_ids].astype(str).agg('_'.join, axis=1)
        df.set_index('PK', inplace=True)
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
        'BodyPartExamined':         Tag((0x0018, 0x0015))
    }
    
    update = {}
    for dcm_tag in update_tags:
        value = row.get(f'Update_{dcm_tag}')
        if pd.notna(value) and value != '':
            update[tag_dict[dcm_tag]] = value

    return update

def remove_info(dataset: Dataset,
                data_element: DataElement,
                va_type: Optional[list[str]],
                tags: Optional[list[tuple]],
                update: Optional[dict],
                tags_2_spare: list[tuple]):
    """
    Removes (anonymizes) or updates specific information from a DICOM dataset.

    Args:
        dataset: The DICOM dataset containing the data element to be modified.
        data_element: The specific data element (tag) to be processed.
        va_type (list, optional): A list of VR types that should be cleared.
        tags (list of tuples, optional): A list of DICOM tags for which the value should be cleared.
        update (dict, optional): A dictionary containing tags as keys and the new values as values. 
        tags_2_spare (list, optional): A list of tags that should be spared from deletion or anonymization. 

    Returns:
        None: The function modifies the data element in place and does not return a value.
    """
    va_type=["PN", "LO", "SH", "AE", "DT", "DA"]
    # Spare sequence name
    if data_element.tag in tags_2_spare:
        return

    # Delete by value group
    if data_element.VR.strip() in [v.strip() for v in va_type]:
        try:
            data_element.value = "Anonymized"
        except:
            data_element.value = ""
        
    # Delete by tag
    if data_element.tag in tags:
        data_element.value = ""

    if not update is None:
        keylist = list(update.keys())
        if data_element.tag in list(update.keys()):
            data_element.value = update[data_element.tag]
            
def anonymize(file_dir: str, 
              output_dir: str, 
              tags: Optional[list] = None, 
              update: Optional[dict] = None, 
              tags_2_spare: Optional[dict] = None,
              tags_2_create: Optional[dict] = None):
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
        update (dict, optional): A dictionary of tags and their new values for updates.
        tags_2_spare (list, optional): Tags that should not be modified.
        tags_2_create (list, optional): Tags to be created.

    Returns:
        int: Returns 0 upon successful processing.
    """
    # Default tags to remove for anonymization
    if tags is None:
        tags = [
            (0x0010, 0x0010),  # Patient's Name
            (0x0010, 0x0020),  # Patient ID
            (0x0010, 0x0030),  # Patient's Birth Date
            (0x0010, 0x0040),  # Patient's Sex
            (0x0010, 0x1040),  # Patient's Address
            (0x0010, 0x2154),  # Patient's Phone Number
            (0x0008, 0x0050),  # Accession Number
            (0x0020, 0x0010),  # Study ID
            (0x0008, 0x0080),  # Institution Name
            (0x0008, 0x0081),  # Institution Address
            (0x0008, 0x0090),  # Referring Physician's Name
            (0x0008, 0x1048),  # Physician(s) of Record
            (0x0008, 0x1050),  # Performing Physician's Name
            (0x0008, 0x1070),  # Operator's Name
            (0x0010, 0x1090),  # Medical Record Locator
            (0x0010, 0x21B0),  # Additional Patient History
            (0x0010, 0x4000),  # Patient Comments
            (0x0032, 0x1032),  # Requesting Physician
            (0x0008, 0x1040),  # Institutional Department Name
        ]
    try:
        f = pydicom.dcmread(str(file_dir))
        
        # Remove and update tags
        f.remove_private_tags()
        f.walk(lambda x1, x2: remove_info(x1, x2, tags=tags, va_type=[], update=update, tags_2_spare=tags_2_spare))
        
        # Create new tags
        for dcm_tag, value in tags_2_create.items():
            setattr(f, dcm_tag, value)
        
        # Write files
        Path(output_dir).parent.mkdir(parents=True, exist_ok=True)
        f.save_as(output_dir)
    except InvalidDicomError:
        print(f"Error when reading: {f}")
    return 0