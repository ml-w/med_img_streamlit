import re

# DICOM VR types available for user selection; values replace tag contents with "Anonymized"
# Keys = VR code, values = human-readable description shown in the UI
vr_type_options = {
    'PN': 'Person Name — patient/physician names',
    'LO': 'Long String — IDs, institution names, descriptions',
    'SH': 'Short String — short identifiers and codes',
    'AE': 'Application Entity — device/workstation names',
    'DA': 'Date',
    'DT': 'Date Time',
    'TM': 'Time',
    'AS': 'Age String — patient age',
    'CS': 'Code String — coded values (may carry institution codes)',
    'LT': 'Long Text — free-text fields',
    'ST': 'Short Text — short free-text fields',
    'UT': 'Unlimited Text — large free-text fields',
}

# VR types selected by default (matches historical hardcoded behaviour)
vr_type_defaults = ['PN', 'LO', 'SH', 'AE', 'DA', 'DT']

# Tags scanned during fetch; user picks from these to form the PK
pk_tag_options = [
    'PatientID',
    'AccessionNumber',
    'PatientName',
    'StudyInstanceUID',
    'SeriesInstanceUID',
    'Modality',
    'StudyDate',
    'SeriesNumber',
    'StudyID',
]

# Default PK columns pre-selected in the PK builder
pk_default = ['PatientID', 'SeriesInstanceUID']

# DICOM tags: available to be shown in template for user's reference (list)
ref_tag_options = [
    'PatientBirthDate',
    'PatientSex',
    'PatientAge',
    'StudyDate',
    'StudyTime',
    'BodyPartExamined',
    'SeriesInstanceUID',
]

# DICOM tags: available to be anonymized with default values or user's inputs (dict)
update_tag_defaults = {
    'PatientName':      '',                                     # for user's inputs
    'PatientID':        '',                                     # for user's inputs
    'AccessionNumber':  '',                                     # for user's inputs
    'BodyPartExamined': ''
    # 'InstitutionName':  '',                                     # for user's inputs
    # 'PatientBirthDate': '19700101',                             # reset patient's birth date to 0
}

# DICOM tag: used as identifier in user-uploaded file (str)
upload_df_id = 'AccessionNumber'

# DICOM tags: to be Anonymized as empty string (None-default or list)
# >> Example: tags_2_anon = [(0x0010, 0x0010), (0x0010, 0x0020)]
tags_2_anon = None

# DICOM tags: Not anonymized (list)
tags_2_spare = [
    (0x0008, 0x1090),   # Model name
    (0x0008, 0x1030),   # Study Description
    (0x0008, 0x103e)    # Series description
]

# DICOM tags: to be Created (dict: 'TagName': (options))
new_tags = {}
