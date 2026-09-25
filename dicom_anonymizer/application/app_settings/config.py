"""
app_settings/config.py — Centralised configuration for the DICOM Anonymizer.

All behaviour-controlling defaults live here. No magic values should appear in
the UI or anonymization logic — import from this module instead.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ANONYMIZATION PIPELINE (applied in this order per data element)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. tags_2_spare          → SKIP element entirely (highest priority).
  2. vr_type_defaults      → Set to "Anonymized" if VR type matches.
  3. tags_2_anon           → Set to "" if tag is in the explicit blank list.
  4. tags_2_anon_extra     → Set to "" for additional config-level tags
                             (merged with the UI "Tags to anonymize" input).
  5. regex_pattern_default → Set to "Anonymized" if string value matches
                             (merged with the UI "Regex pattern" input).
  6. update_tag_defaults   → Overwrite with user-supplied value (last-wins).

Tags listed in tags_2_spare are never modified regardless of any other rule.
Tags in both tags_2_spare and tags_2_anon_extra are silently spared.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
QUICK REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  vr_type_options       dict   VR codes shown as checkboxes in the UI.
  vr_type_defaults      list   VR codes checked by default.

  pk_tag_options        list   DICOM tags available as primary key columns.
  pk_default            list   PK columns pre-selected on first load.

  ref_tag_options       list   Tags shown as read-only reference columns.
  update_tag_defaults   dict   Tags editable by the user; value = default
                               ('' = blank, literal string, or callable).
  upload_df_id          str    Column used to match user-uploaded CSV rows.

  tags_2_anon           list|None  Tags blanked to ""; None = use
                                   default_tags_2_anon (below) inside anonymize().
  default_tags_2_anon   list   VR-independent safety net used when tags_2_anon
                               is None; always blanks these identifying tags.
  tags_2_spare          list   Tags never modified (model name, descriptions).
  tags_2_anon_extra     list   Extra tags to blank; config-level complement to
                               the UI "Additional tags to anonymize" input.
  regex_pattern_default str|None  Regex applied to all string values; matches
                                  become "Anonymized". Seeds the UI field.

  new_tags              dict   Tags created when absent from the DICOM file.
                               Format: {'TagName': (option1, option2, ...)}.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TAG FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Tags are expressed as (group, element) integer tuples using hex literals:
      (0x0010, 0x0010)  →  Patient's Name
  The UI accepts the equivalent text format: (0010|0010)
"""

import re

# DICOM VR types available for user selection; values replace tag contents with "Anonymized"
# Keys = VR code, values = human-readable description shown in the UI
vr_type_options: dict = {
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
vr_type_defaults: list = ['PN', 'LO', 'SH', 'AE', 'DA', 'DT']

# Tags scanned during fetch; user picks from these to form the PK
pk_tag_options: list = [
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

# Display-only columns computed from file paths rather than read from DICOM headers.
# These are NOT DICOM tags: create_dcm_df() never sees them, and they must never be
# added to pk_tag_options (there is no header value to key on). Offered alongside
# ref_tag_options in the "Select columns to display" multiselect.
derived_display_options = ['SeriesDir']

# DICOM tags: available to be anonymized with default values or user's inputs (dict)
default_update_tags = ['PatientName', 'PatientID', 'AccessionNumber']
update_tag_defaults = {
    'PatientName':      '',                                     # for user's inputs
    'PatientID':        '',                                     # for user's inputs
    'AccessionNumber':  '',                                     # for user's inputs
    'BodyPartExamined': '',
    'InstitutionName':  'Anonymized',                           # for user's inputs
    'PatientAge':       '000Y',                                 # reset patient age to 0 years
    'PatientBirthDate': '19700101',                             # reset patient's birth date to 0
    'PatientSex':       'O',
}

# DICOM tag: used as identifier in user-uploaded file (str)
upload_df_id: str = 'AccessionNumber'

# DICOM tags: to be blanked as empty string during anonymization (None = use default_tags_2_anon below)
# >> Example: tags_2_anon = [(0x0010, 0x0010), (0x0010, 0x0020)]
tags_2_anon: list | None = None

# DICOM tags: hardcoded fallback used by anonymize() when tags_2_anon (above) is None.
# This is a VR-independent safety net — these identifying tags are always blanked to "",
# even for a tag whose VR type was not selected for anonymization. The UI removes tags
# from this list for update_tag_defaults keys the user did not select to update, so an
# unselected tag falls back to the VR-type "Anonymized" pass instead of being blanked.
default_tags_2_anon: list = [
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

# DICOM tags: never modified, even if their VR type is selected for anonymization (list of (group, element) tuples)
# tags_2_spare takes priority over tags_2_anon_extra and the UI "tags to anonymize" input.
tags_2_spare: list | None = [
    (0x0008, 0x1090),   # Model name
    (0x0008, 0x1030),   # Study Description
    (0x0008, 0x103e),   # Series description
]

# DICOM tags: always blanked to "" in addition to the built-in tags_2_anon list (list of (group, element) tuples)
# These are the config-level counterpart to the UI "Additional tags to anonymize" input.
# Tags present in tags_2_spare are silently ignored (spare takes priority).
# >> Example: tags_2_anon_extra = [(0x0010, 0x1000), (0x0010, 0x1040)]
tags_2_anon_extra: list = []

# Regex pattern applied to every string-valued DICOM element; matches are replaced with "Anonymized".
# Set to None to disable. Must be a valid Python regex string.
# The UI "Regex pattern" field overrides this when non-empty.
# >> Example: regex_pattern_default = r'\b\d{3}-\d{2}-\d{4}\b'  # US SSN pattern
regex_pattern_default: str | None = None

# DICOM tags: to be Created (dict: 'TagName': (options))
new_tags = {}

# Number of worker processes used to read DICOM headers in parallel during the folder scan.
scan_max_workers: int = 8

# Minimum number of files in a scan before the process pool is used (small scans run sequentially).
scan_parallel_threshold: int = 500
