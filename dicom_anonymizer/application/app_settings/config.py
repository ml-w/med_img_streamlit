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

  tags_2_anon           list|None  Tags blanked to ""; None = use hardcoded
                                   defaults inside anonymize().
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

# DICOM tags: available to be anonymized with default values or user's inputs (dict)
update_tag_defaults = {
    'PatientName':      '',                                     # for user's inputs
    'PatientID':        '',                                     # for user's inputs
    'AccessionNumber':  '',                                     # for user's inputs
    'BodyPartExamined': '',
    'InstitutionName':  'Anonymized'                                     # for user's inputs
    # 'PatientBirthDate': '19700101',                             # reset patient's birth date to 0
}

# DICOM tag: used as identifier in user-uploaded file (str)
upload_df_id: str = 'AccessionNumber'

# DICOM tags: to be blanked as empty string during anonymization (None = use hardcoded defaults in anonymize())
# >> Example: tags_2_anon = [(0x0010, 0x0010), (0x0010, 0x0020)]
tags_2_anon: list | None = None

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
