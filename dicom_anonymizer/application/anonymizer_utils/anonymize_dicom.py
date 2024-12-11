import pydicom
from pydicom.errors import InvalidDicomError
from pydicom import *
from pathlib import Path
from typing import Optional
from pydicom.tag import Tag
import pandas as pd

def create_output_dir(file_dir: str, folder_dir: Path) -> str:
    """Generates the output directory path for anonymized files."""
    return str(file_dir).replace(str(folder_dir), str(folder_dir.parent / f"{folder_dir.name}-Anonymized"))

def create_dcm_df(folder: str, fformat: str, unique_ids: list, ref_tags: list, new_tags: list) -> pd.DataFrame:
    """
    Gathers the meta data of each DICOM file from the folder. 
        
    Args: 
    - folder (str): The directory of folder with dicom files.
    - fformat (str): The file format of the targeted files. 
    - unique_ids (list): The list of columns used as primary keys.
    - ref_tags (list): The list of columns to be shown in template.
    - new_tags (list): The list of tags to be determine its existence. 
        
    Returns:
    - dcm_info (pd.DataFrame): information of the dicom tags. 
    """
    folder_dir = Path(folder)
    dcm_info = {
        'folder_dir': [], 
        'output_dir': []
    }
    dcm_info.update({dcm_tag: [] for dcm_tag in (unique_ids + ref_tags + new_tags)})
    
    for sub_folder in folder_dir.iterdir():
        if sub_folder.is_dir():
            for file_dir in sub_folder.rglob(f"*.{fformat}"):
                dcm_info['folder_dir'].append(str(sub_folder))
                dcm_info['output_dir'].append(create_output_dir(sub_folder, folder_dir))

                try:
                    f = pydicom.dcmread(str(file_dir), stop_before_pixels=True)
                    
                    # Gather information from DICOM tags
                    for dcm_tag in (unique_ids + ref_tags + new_tags):
                        if dcm_tag == 'PatientName': 
                            dcm_info[dcm_tag].append(''.join(getattr(f, dcm_tag, '')))
                        else: 
                            dcm_info[dcm_tag].append(getattr(f, dcm_tag, None))
                    
                except Exception as e:
                    print(f"{e = }")

                break   # only the read the 1st file of the subholder
    
    df = pd.DataFrame(dcm_info)
    df['PK'] = df[unique_ids].astype(str).agg('_'.join, axis=1)
    df.set_index('PK', inplace=True)
    
    return df

def consolidate_tags(row, update_tags): 
    # DICOM Tag Table
    tag_dict = {
        'PatientName':              Tag((0x0010, 0x0010)),
        'PatientID':                Tag((0x0010, 0x0020)),
        'PatientBirthDate':         Tag((0x0010, 0x0030)),
        'PatientSex':               Tag((0x0010, 0x0040)),
        'AccessionNumber':          Tag((0x0008, 0x0050)),
        'InstitutionName':          Tag((0x0008, 0x0080)),
        'StudyDate':                Tag((0x0008, 0x0020))
    }
    
    update = {}
    for dcm_tag in update_tags:
        update[tag_dict[dcm_tag]] = row[f'Update_{dcm_tag}']
    
    return update

def remove_info(dataset,
                data_element,
                va_type,
                tags,
                update: Optional[dict],
                tags_2_spare):
    """
    Removes (anonymizes) or updates specific information from a DICOM dataset.

    Args:
    - dataset: The DICOM dataset containing the data element to be modified.
    - data_element: The specific data element (tag) to be processed.
    - va_type (list, optional): A list of VR types that should be cleared.
    - tags (list of tuples, optional): A list of DICOM tags for which the value should be cleared.
    - update (dict, optional): A dictionary containing tags as keys and the new values as values. 
    - tags_2_spare (list, optional): A list of tags that should be spared from deletion or anonymization. 

    Returns:
    - None: The function modifies the data element in place and does not return a value.
    """
    va_type=["PN", "LO", "SH", "AE", "DT", "DA"]
    # Spare sequence name
    if data_element.tag in tags_2_spare:
        return

    # Delete by value group
    if data_element.VR.strip() in [v.strip() for v in va_type]:
        data_element.value = ""
        

    # Delete by tag
    if data_element.tag in tags:
        data_element.value = ""

    if not update is None:
        keylist = list(update.keys())
        if data_element.tag in list(update.keys()):
            data_element.value = update[data_element.tag]


def anonymize(file_dir, output_dir, tags=None, update: Optional[dict] = None, tags_2_spare: Optional[dict] = None,
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
    - file_dir (str): The path to the input DICOM file.
    - output_dir (str): The path where the modified DICOM file will be saved.
    - tags (list of tuples, optional): A list of DICOM tags to be anonymized. If None, default tags for sensitive patient information are used.
    - update (dict, optional): A dictionary of tags and their new values for updates.
    - tags_2_spare (list, optional): Tags that should not be modified.
    - tags_2_create (list, optional): Tags to be created.

    Returns:
    - int: Returns 0 upon successful processing.

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