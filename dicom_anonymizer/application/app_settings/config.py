import re
# Inititalize pre-defined values
# DICOM tags: used as Unique identifiers (list)
unique_ids = [
    'PatientName', 
    'PatientID', 
    'AccessionNumber'
]

# DICOM tags: available to be shown in template for user's reference (list)
ref_tag_options = [
    'PatientBirthDate',
    'PatientSex',
    'PatientAge',
    'StudyDate',
    'StudyTime',
    'BodyPartExamined'
]

# DICOM tags: available to be anonymized with default values or user's inputs (dict)
update_tag_defaults = {
    'PatientName':      '',                                     # for user's inputs
    'PatientID':        '',                                     # for user's inputs
    'BodyPartExamined': ''
    # 'InstitutionName':  '',                                     # for user's inputs
    # 'PatientBirthDate': '19700101',                             # reset patient's birth date to 0
    # 'AccessionNumber':  lambda x: re.sub(r'^[a-zA-Z]+', '', x)  # remove the first 3 characters
}

# DICOM tag: used as identifier in user-uploaded file (str)
upload_df_id = 'AccessionNumber'
series_upload_df_id = 'SeriesInstanceUID'

# Series level configuration
# DICOM tags: used as Unique identifiers when anonymizing per series (list)
series_unique_ids = [
    'PatientID',
    'SeriesInstanceUID'
]

# DICOM tags: available to be shown in template for user's reference at series level (list)
series_ref_tag_options = ref_tag_options + ['SeriesInstanceUID']

# DICOM tags: available to be anonymized default values or user's inputs at series level (dict)
series_update_tag_defaults = update_tag_defaults | {
    'SeriesDescription': ''
}

# DICOM tags: to be Anonymized as empty string (None-default or list)
# >> Example: tags_2_anon = [(0x0010, 0x0010), (0x0010, 0x0020)]
tags_2_anon = None

# DICOM tags: Not anonymized (list)
tags_2_spare = []

# DICOM tags: to be Created (dict: 'TagName': (options))
new_tags = {
    'BodyPartExamined': ('Head', 'Thorax', 'Chest'),
}
