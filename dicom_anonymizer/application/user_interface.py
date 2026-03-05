import re
import streamlit as st
import json
import pandas as pd
from pathlib import Path

logger = st.logger.get_logger("ui")

from anonymizer_utils.anonymize_dicom import *
from ui_utils.ui_logic import *
from app_settings.config import (
    pk_tag_options,
    pk_default,
    ref_tag_options,
    update_tag_defaults,
    upload_df_id,
    tags_2_anon,
    tags_2_spare,
    new_tags,
    vr_type_options,
    vr_type_defaults,
)

# ---------------------------------------------------------------------------
# Session persistence utilities
# ---------------------------------------------------------------------------
SESSION_FILE = Path.cwd() / ".session.json"
SESSION_EXCLUDE = {"dcm_info", "uids", "edit_df", "upload_file"}


def _load_session():
    if SESSION_FILE.exists():
        try:
            with SESSION_FILE.open("r") as f:
                data = json.load(f)
            for k, v in data.items():
                st.session_state.setdefault(k, v)
        except Exception:
            pass


def _save_session():
    data = {k: v for k, v in st.session_state.items()
            if k not in SESSION_EXCLUDE and not isinstance(v, pd.DataFrame)}
    if isinstance(data.get('folder'), str):
        data['folder'] = data['folder'].replace('\\', '/')
    try:
        with SESSION_FILE.open("w") as f:
            json.dump(data, f)
    except Exception:
        pass


def _parse_spare_tags(text: str) -> list:
    """Parse a tag string like '(0008|1030),(0010|0020)' into a list of (group, element) tuples."""
    matches = re.findall(r'\(([0-9A-Fa-f]{4})\|([0-9A-Fa-f]{4})\)', text)
    return [(int(g, 16), int(e, 16)) for g, e in matches]


def streamlit_app():
    _load_session()

    defaults = {
        "folder": "",
        "fformat": "*.dcm",
        "dcm_info": None,
        "uids": None,
        "edit_df": None,
        "pk_columns": pk_default,
        "pk_committed": False,
        "matcher_id": upload_df_id,
        "selected_display_tags": [],
        "selected_update_tags": [],
        "spare_tags_input": "",
        "skip_unmatched": False,
        "unmatched_upload_ids": [],
        "subfolder_tag": "",
    }
    # Per-VR checkbox defaults (only applied once; session/JSON takes over after first run)
    for vr in vr_type_options:
        defaults[f'vr_{vr}'] = vr in vr_type_defaults
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)

    st.set_page_config(page_title='DICOM Anonymizer')
    st.write('# DICOM Anonymizer:hospital::card_file_box:')

    st.text_input(
        'Please copy and paste the full directory of the folder with DICOM files.',
        placeholder='Enter the full file directory, e.g., "C:/Users/Documents"',
        key='folder'
    )
    st.text_input(
        'File extension',
        placeholder='e.g., "*.dcm"',
        key='fformat'
    )

    # Normalize folder path for processing without mutating widget state
    folder = st.session_state.folder.replace('\\', '/')

    with st.expander(':bulb: **Click Here for User Tips on Best Practices**'):
        st.markdown(
            """
            ### Folder Preparation
            - :red[Large Folders]: If your folder contains more than 10,000 DICOM files, consider splitting it into smaller batches to optimize processing time.
            - :red[Scan Position]: It is recommended to include only one body part scanned per folder for consistency.

            ### Modification of DICOM Tag values
            - :red[Update Input Template]: Update your inputs using the automatically generated template. If you prefer to use your own template, please ensure that you include the matcher column as an identifier for the cases.
            - :red[Optional Updates]: The template contains columns starting with "Update" (e.g. `Update_PatientName`). Leave a field blank if you do not wish to modify that value.
            - :red[Default values]: You can modify the following DICOM tags. For your convenience, default values have been pre-set for certain tags to streamline the anonymization process.

            | DICOM Tag           | Default value     |
            |---------------------|---------------------------------------------------------------------------------------------|
            | Patient Name        | No default value. We advise using case numbers / random characters.     |
            | Patient ID          | No default value. We advise using case numbers / random characters.     |
            | Institution Name    | No default value. We advise using your initial.     |
            | Patient Birth Date  | `1970/01/01` (Format: YYYY/MM/DD)       |
            | Accession Number    | The first few characters representing the institution is removed. (e.g. `PXH12345` becomes `12345`) |

            - The other DICOM tags are anonymized by wiping out the original values.

            ### Folder Output
            - The anonymized files will be saved in a new folder named `"[your file path]-Anonymized"`. For example, if you file path is `"C:/Documents/dicom"`, the destination will be `"C:/Documents/dicom-Anonymized"`.
            """
        )

    # ─── Step 1: Fetch files ─────────────────────────────────────────────────────
    if st.button('Fetch files', type='primary'):
        if not st.session_state.folder or not st.session_state.fformat:
            st.error(':warning: Please input file directory and file extension.')
        else:
            st.session_state.dcm_info = None
            st.session_state.pk_committed = False
            st.session_state.edit_df = None
            st.session_state.unmatched_upload_ids = []
            st.session_state.pop('upload_file', None)
            with st.spinner(text='Fetching files...'):
                progress_bar = st.progress(0, text="Initiating read...")
                try:
                    all_ref_tags = list(dict.fromkeys(ref_tag_options + list(update_tag_defaults.keys())))
                    raw = create_dcm_df(
                        folder=folder,
                        fformat=st.session_state.fformat,
                        unique_ids=pk_tag_options,
                        ref_tags=all_ref_tags,
                        new_tags=list(new_tags.keys()),
                        series_mode=True,   # always scan at series level
                        progress_bar=progress_bar,
                    )
                    # Store with RangeIndex; the PK is built on Confirm PK below
                    st.session_state.dcm_info = raw.reset_index(drop=True)
                except Exception as e:
                    st.error(f':warning: We cannot find any files in the file extension in the directory.\nOriginal error: {e}')
                    logger.exception(e)

    # ─── Step 2: PK Builder ───────────────────────────────────────────────────────
    if st.session_state.dcm_info is not None and not st.session_state.pk_committed:
        st.divider()
        st.subheader('Step 2: Configure Primary Key')

        with st.expander(':warning: **Limitations of custom PK — read before confirming**'):
            st.markdown(
                """
                - **Null tags**: if a chosen PK tag is missing from a DICOM file, that series' PK component becomes `"None"`. Multiple series with the same missing tag collapse into a single PK row, silently losing distinct records.
                - **String-join collision**: the PK is built as `tagA_tagB_...`. If tag values contain `_`, two distinct records could theoretically produce the same PK. Rare with DICOM UIDs; possible with free-text tags.
                - **Static tag scan**: only tags defined in `pk_tag_options` (config) are available here. Tags not in that list require a config change and a re-fetch.
                - **Folder-level anonymization**: a coarser PK (e.g. `PatientID` only) means all series directories for that patient share one set of replacement values and are all anonymized together.
                """
            )

        prev_pk_columns = list(st.session_state.pk_columns)
        st.multiselect(
            'Select PK columns',
            options=pk_tag_options,
            key='pk_columns',
            help='Removing SeriesInstanceUID groups all series for a patient into one edit row.',
        )
        pk_columns = st.session_state.pk_columns

        if pk_columns != prev_pk_columns:
            st.session_state.selected_display_tags = []
            st.session_state.selected_update_tags = []

        # Null warnings per column
        dcm_raw = st.session_state.dcm_info  # RangeIndex at this point
        for col in pk_columns:
            if col in dcm_raw.columns and dcm_raw[col].isnull().any():
                null_count = int(dcm_raw[col].isnull().sum())
                st.warning(f':warning: **{col}** is missing in {null_count} series — may cause PK collisions.')

        # Live preview
        if pk_columns:
            preview_cols = list(dict.fromkeys(
                pk_columns + [c for c in ref_tag_options if c in dcm_raw.columns]
            ))
            preview_df = dcm_raw[preview_cols].drop_duplicates(subset=pk_columns)
            st.caption(f'Preview: {len(preview_df)} unique rows after grouping by selected PK columns '
                       f'(from {len(dcm_raw)} series total).')
            st.dataframe(preview_df, use_container_width=True, hide_index=True)
        else:
            st.info('Select at least one PK column to preview.')

        if st.button('Confirm PK', type='primary', disabled=not bool(pk_columns)):
            # Reset to RangeIndex (safe whether current index is RangeIndex or a prior PK),
            # then build the user-chosen PK string and set as index.
            dcm = st.session_state.dcm_info.reset_index(drop=True).copy()
            dcm['PK'] = dcm[pk_columns].astype(str).agg('_'.join, axis=1)
            dcm = dcm.set_index('PK')
            # dcm may have multiple rows per PK (e.g. patient-level PK covering many series)
            st.session_state.dcm_info = dcm
            st.session_state.pk_committed = True
            # Default matcher to the last PK column (most specific identifier)
            st.session_state.matcher_id = pk_columns[-1]
            st.session_state.selected_display_tags = []
            st.session_state.selected_update_tags = []
            st.rerun()

    # ─── Step 3: Anonymization workflow ──────────────────────────────────────────
    if st.session_state.dcm_info is not None and st.session_state.pk_committed:
        active_unique_ids = st.session_state.pk_columns
        active_upload_df_id = st.session_state.matcher_id

        options = [col for col in active_unique_ids if col in st.session_state.dcm_info.columns]
        st.selectbox(
            'Select matcher column',
            options,
            index=options.index(st.session_state.matcher_id) if st.session_state.matcher_id in options else 0,
            key='matcher_id'
        )
        active_upload_df_id = st.session_state.matcher_id
        if st.session_state.dcm_info[active_upload_df_id].isnull().any():
            st.warning(':warning: Some DICOM files are missing the selected matcher column.')

        if not st.session_state.selected_display_tags:
            st.session_state.selected_display_tags = ref_tag_options
        if not st.session_state.selected_update_tags:
            st.session_state.selected_update_tags = list(update_tag_defaults.keys())

        st.multiselect('Select columns to display', ref_tag_options, key='selected_display_tags')
        st.multiselect('Select columns to update', list(update_tag_defaults.keys()), key='selected_update_tags')

        active_ref_tags = st.session_state.selected_display_tags
        active_update_tags = {k: update_tag_defaults[k] for k in st.session_state.selected_update_tags}

        display_cols = list(dict.fromkeys(active_unique_ids + active_ref_tags + list(active_update_tags.keys())))
        display_cols = [c for c in display_cols if c in st.session_state.dcm_info.columns]
        uids_df = st.session_state.dcm_info[display_cols]
        # edit_df: one row per PK (deduped), PK index preserved for the Run-step join
        uids_df = uids_df.loc[~uids_df.index.duplicated()]
        st.session_state.uids = uids_df

        edit_df = create_update_cols(uids_df.copy(), active_update_tags)
        st.session_state.edit_df = edit_df

        st.success(
            """
                We have found the following unique cases - :card_file_box:
                :point_down: You may download the auto-generated template by clicking the "Download" button below.
                """
        )

        desc_new_tag = st.empty()
        create_new_tag = st.empty()
        download_function = st.empty()
        display_data = st.empty()
        upload_error = st.empty()

        upload_file = st.file_uploader(
            label=f'Choose a csv/excel file, which must contain column "{active_upload_df_id}" as identifer.',
            type=['csv', 'xsl', 'xslx'],
            key='upload_file'
        )

        if upload_file is not None:
            file_extension = Path(upload_file.name).suffix
            readfile_error = False
            try:
                if file_extension == '.csv':
                    upload_df = pd.read_csv(upload_file)
                elif file_extension in ['.xls', '.xlsx']:
                    upload_df = pd.read_excel(upload_file)
                else:
                    upload_error.error(':warning: Error in uploaded file: Unsupported file type.')
            except Exception:
                upload_error.error(':warning: Error: Unable to read uploaded file. Please input your updates in the template and upload again.')
                readfile_error = True

            if not readfile_error:
                error_message = validate_upload(st.session_state.edit_df, upload_df, active_update_tags, active_upload_df_id)
                if error_message:
                    st.error(error_message)
                else:
                    upload_df = upload_df.fillna('').astype(str)
                    try:
                        edit_df = update_data_editor(st.session_state.edit_df, upload_df, active_update_tags, active_unique_ids)
                        st.session_state.edit_df = edit_df
                        unmatched = check_unmatched_rows(upload_df, edit_df, active_upload_df_id)
                        st.session_state.unmatched_upload_ids = unmatched
                        if unmatched:
                            skip_note = 'Enable **Skip unmatched cases** in Anonymization settings to exclude them.' if not st.session_state.skip_unmatched else 'These cases will be **skipped** (not copied to output).'
                            upload_error.warning(
                                f':warning: {len(unmatched)} case(s) in **{active_upload_df_id}** were not found in the uploaded file. {skip_note}'
                            )
                            with st.expander(f'Show {len(unmatched)} unmatched {active_upload_df_id} value(s)'):
                                st.write(', '.join(map(str, unmatched)))
                    except Exception:
                        upload_error.error(':warning: Error: Unable to read uploaded file. Please input your updates in the template and upload again.')
        else:
            st.session_state.unmatched_upload_ids = []

        # Highlight cells that are going to be updated
        styled_df = highlight_updated_cells(st.session_state.edit_df, active_update_tags)
        display_data.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True
        )

        csv = st.session_state.edit_df.reset_index(drop=True).to_csv(index=False).encode('utf-8')
        download_function.download_button(
            label='Download template as CSV',
            data=csv,
            file_name='unique_ids.csv'
        )

        tags_2_create = {}
        for dcm_tag, options in new_tags.items():
            if st.session_state.dcm_info[dcm_tag].isnull().any():
                notag_ids = st.session_state.dcm_info.loc[
                    st.session_state.dcm_info[dcm_tag].isnull(), active_upload_df_id
                ].unique().tolist()
                notag_ids_str = ','.join(str(x) for x in notag_ids)
                desc_new_tag.warning(
                    f"""
                    :warning: We have identified that some DICOM series are missing the DICOM Tag :blue[{dcm_tag}] - {active_upload_df_id}: `{notag_ids_str}`.
                    """
                )
                tags_2_create[dcm_tag] = create_new_tag.selectbox(f'Please select a value for DICOM Tag: `{dcm_tag}`.', options)

        # ─── Anonymization settings (collapsed) ──────────────────────────────────
        with st.expander(':gear: **Anonymization settings**', expanded=False):
            st.checkbox(
                'Skip unmatched cases — exclude cases not found in uploaded file from the output entirely',
                key='skip_unmatched',
                help='When enabled, any case whose matcher ID is absent from the uploaded CSV will not be anonymized or copied to the output directory.',
            )
            st.divider()
            subfolder_options = [''] + [c for c in active_unique_ids if c in st.session_state.dcm_info.columns]
            st.selectbox(
                'Organize output into subfolders by tag',
                options=subfolder_options,
                format_func=lambda x: '(mirror original directory structure)' if x == '' else x,
                key='subfolder_tag',
                help='When set, the anonymized value of the chosen tag is used as a top-level subfolder under the output root, '
                     'replacing the original directory structure. Use an Update_ tag value to avoid PII in output paths.',
            )
            st.divider()
            st.caption('**VR types to anonymize** — all data elements with these Value Representations '
                       'will have their value replaced with "Anonymized".')
            col1, col2 = st.columns(2)
            for i, (vr, desc) in enumerate(vr_type_options.items()):
                with (col1 if i % 2 == 0 else col2):
                    st.checkbox(f'`{vr}` — {desc}',
                                key=f'vr_{vr}')

            st.divider()
            st.caption('**Additional tags to spare** — values in these tags are never modified, '
                       'even if their VR type is selected above. '
                       'Format: `(XXXX|XXXX),(YYYY|YYYY)` using 4-digit hex group and element numbers. '
                       'Example: `(0008|1030),(0008|103e)`')
            st.text_input('Tags to spare', key='spare_tags_input',
                          placeholder='(0008|1030),(0008|103e)')
            user_spare = _parse_spare_tags(st.session_state.spare_tags_input)
            if user_spare:
                st.success(f'Parsed {len(user_spare)} additional spare tag(s): '
                           + ', '.join(f'({g:04X}|{e:04X})' for g, e in user_spare))
            elif st.session_state.spare_tags_input.strip():
                st.warning(':warning: No valid tags found — check the format `(XXXX|XXXX)`.')

        # Collect active VR types and effective spare tags for the run
        active_va_types = [vr for vr in vr_type_options if st.session_state.get(f'vr_{vr}', vr in vr_type_defaults)]
        effective_tags_2_spare = list(tags_2_spare) + _parse_spare_tags(st.session_state.spare_tags_input)

        if st.button("Run", type='primary'):
            if st.session_state.get('dcm_info') is None or st.session_state.get('edit_df') is None:
                st.warning(':warning: Please fetch files and provide updates before file anonymization.')
            else:
                # Join on PK index: dcm_info (all series rows, PK index, may be non-unique for
                # coarse PKs) × edit_df (one row per PK). Each series directory gets the update
                # values from its matching PK row.
                dcm_copy = st.session_state.dcm_info.copy()
                if st.session_state.skip_unmatched and st.session_state.unmatched_upload_ids:
                    unmatched_set = set(map(str, st.session_state.unmatched_upload_ids))
                    dcm_copy = dcm_copy[~dcm_copy[active_upload_df_id].astype(str).isin(unmatched_set)]
                subfolder_tag = st.session_state.subfolder_tag
                dir_df = dcm_copy.filter(like='dir', axis=1)
                # Include original tag column when subfolder grouping is active (fallback when Update_ is empty)
                if subfolder_tag and subfolder_tag in dcm_copy.columns:
                    dir_df = dir_df.join(dcm_copy[[subfolder_tag]])
                anon_dcm_df = dir_df.join(st.session_state.edit_df.filter(like='Update_', axis=1))

                pattern = st.session_state.fformat if '*' in st.session_state.fformat else f"*.{st.session_state.fformat.lstrip('.')}"
                with st.spinner(text='Creating anonymized files...'):
                    total_files = sum(
                        len(list(Path(row['folder_dir']).rglob(pattern)))
                        for _, row in anon_dcm_df.iterrows()
                    )
                    processed = 0
                    progress_bar = st.progress(0, text="Initiating anonymization...")

                    base_output = f"{folder}-Anonymized"
                    series_counters: dict = {}  # subfolder_val → count, used to name series subdirs without PII
                    for _, row in anon_dcm_df.iterrows():
                        folder_dir = Path(row['folder_dir'])
                        if subfolder_tag:
                            update_col = f'Update_{subfolder_tag}'
                            subfolder_val = str(row.get(update_col, '') or row.get(subfolder_tag, '') or 'Unknown').strip() or 'Unknown'
                            # Use a sequential index instead of the original directory name to avoid PII in output paths
                            series_idx = series_counters.get(subfolder_val, 0) + 1
                            series_counters[subfolder_val] = series_idx
                            series_output = str(Path(base_output) / subfolder_val / f"series_{series_idx:03d}")
                        else:
                            series_output = row['output_dir']
                        for file_dir in folder_dir.rglob(pattern):
                            output_dir = f"{series_output}/{Path(file_dir).name}"
                            update = consolidate_tags(row, active_update_tags)

                            logger.get_logger('streamlit').debug(f"Anonymizing {file_dir} -> {output_dir}")

                            anonymize(
                                file_dir=file_dir,
                                output_dir=output_dir,
                                tags=tags_2_anon,
                                va_type=active_va_types,
                                update=update,
                                tags_2_spare=effective_tags_2_spare,
                                tags_2_create=tags_2_create
                            )

                            processed += 1
                            progress_bar.progress(processed / total_files, text=f"Anonymizing: {file_dir}")

                    progress_bar.progress(1.0, text="Anonymization complete")

                st.write(f"""
                        :star2: Anonymized files are written in:
                        :open_file_folder: :blue[{folder}-Anonymized]
                        """)

    _save_session()
