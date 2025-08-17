import re
# Inititalize pre-defined values
# DICOM tags: used as Unique identifiers (list)
unique_ids = [
    'PatientName', 
    'PatientID', 
    'AccessionNumber'
]

# DICOM tags: to be Shown in template for user's reference (list)
ref_tags = [
    'PatientBirthDate', 
    'PatientSex', 
    'PatientAge', 
    'StudyDate', 
]

# DICOM tags: to be Anonymized default values or user's inputs (dict)
update_tags = {
    'PatientName':      '',                                     # for user's inputs
    'PatientID':        '',                                     # for user's inputs
    # 'InstitutionName':  '',                                     # for user's inputs
    # 'PatientBirthDate': '19700101',                             # reset patient's birth date to 0
    # 'AccessionNumber':  lambda x: re.sub(r'^[a-zA-Z]+', '', x)  # remove the first 3 characters
}

# DICOM tag: used as identifier in user-uploaded file (str)
upload_df_id = 'AccessionNumber'

# DICOM tags: to be Anonymized as empty string (None-default or list)
# >> Example: tags_2_anon = [(0x0010, 0x0010), (0x0010, 0x0020)]
tags_2_anon = None

# DICOM tags: Not anonymized (list)
tags_2_spare = []

# DICOM tags: to be Created (dict: 'TagName': (options))
new_tags = {
    'BodyPartExamined': ('Head', 'Thorax', 'Chest'),
}
