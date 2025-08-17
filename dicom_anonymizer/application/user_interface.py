import streamlit as st
import json
import pandas as pd

from anonymizer_utils.anonymize_dicom import *
from ui_utils.ui_logic import *
from app_settings.config import (
    unique_ids,
    ref_tags,
    update_tags,
    upload_df_id,
    series_upload_df_id,
    tags_2_anon,
    tags_2_spare,
    new_tags,
    series_unique_ids,
    series_ref_tags,
    series_update_tags,
)

def streamlit_app(): 
    # Initialize session states
    if 'user_folder' not in st.session_state:       # user input directory
        st.session_state['user_folder'] = ''
    if 'folder' not in st.session_state:            # folder path to glob files
        st.session_state['folder'] = ''
    if 'user_fformat' not in st.session_state:      # user input file extension
        st.session_state['user_fformat'] = ''
    if 'fformat' not in st.session_state:           # file extension to glob
        st.session_state['fformat'] = ''
    if 'dcm_info' not in st.session_state:          # all dcm files
        st.session_state['dcm_info'] = None
    if 'uids' not in st.session_state:              # list of unique IDs
        st.session_state['uids'] = None
    if 'edit_df' not in st.session_state:           # data editor
        st.session_state['edit_df'] = None
    if 'uploader_key' not in st.session_state:      # key (instance) of file_uploader
        st.session_state['uploader_key'] = 0
    if 'series_mode' not in st.session_state:       # anonymize per series or patient
        st.session_state['series_mode'] = False
    if 'matcher_id' not in st.session_state:        # identifier column in templates
        st.session_state['matcher_id'] = upload_df_id

    # Page user interface
    st.set_page_config(page_title = 'DICOM Anonymizer')
    st.write('# DICOM Anonymizer:hospital::card_file_box:')
    
    
    # Capture user's input of folder directory
    user_folder = st.text_input(
        'Please copy and paste the full directory of the folder with DICOM files.', 
        placeholder='Enter the full file directory, e.g., "C:/Users/Documents"'
    )

    user_fformat = st.text_input(
        'File extension',
        placeholder='e.g., "dcm"'
    )

    series_mode_box = st.checkbox("Anonymize per series", value=st.session_state['series_mode'])
    if series_mode_box != st.session_state['series_mode']:
        st.session_state['dcm_info'] = None
    st.session_state['series_mode'] = series_mode_box

    if st.session_state['series_mode']:
        st.session_state['matcher_id'] = series_upload_df_id
    elif st.session_state['matcher_id'] == series_upload_df_id:
        st.session_state['matcher_id'] = upload_df_id

    active_unique_ids = series_unique_ids if st.session_state['series_mode'] else unique_ids
    active_ref_tags = series_ref_tags if st.session_state['series_mode'] else ref_tags
    active_update_tags = series_update_tags if st.session_state['series_mode'] else update_tags
    active_upload_df_id = st.session_state['matcher_id']

    # A container of user instruction
    with st.expander(':bulb: **Click Here for User Tips on Best Practices**'):
        st.markdown(
            f'''
            ### Folder Preparation
            - :red[Large Folders]: If your folder contains more than 10,000 DICOM files, consider splitting it into smaller batches to optimize processing time.
            - :red[Scan Position]: It is recommended to include only one body part scanned per folder for consistency.

            ### Modification of DICOM Tag values
            - :red[Update Input Template]: Update your inputs using the automatically generated template. If you prefer to use your own template, please ensure that you include the column "{active_upload_df_id}" as an identifier for the cases.
            - :red[Avoid Empty Fields]: When uploading the updated template, ensure that there are NO empty inputs in the columns that start with "Update" (e.g. `Update_PatientName`). The values under these columns will be directly applied to the anonymized files.
            - :red[Default values]: You can modify the following DICOM tags. For your convenience, default values have been pre-set for certain tags to streamline the anonymization process.

            | DICOM Tag           | Default value     |
            |---------------------|-----------------------------------------------------------------------------------------------|
            | Patient Name        | No default value. We advise using case numbers / random characters.     |
            | Patient ID          | No default value. We advise using case numbers / random characters.     |
            | Institution Name    | No default value. We advise using your initial.     |
            | Patient Birth Date  | `1970/01/01` (Format: YYYY/MM/DD)       |
            | Accession Number    | The first few characters representing the institution is removed. (e.g. `PXH12345` becomes `12345`) |

            - The other DICOM tags are anonymized by wiping out the original values.

            ### Folder Output
            - The anonymized files will be saved in a new folder named `"[your file path]-Anonymized"`. For example, if you file path is `"C:/Documents/dicom"`, the destination will be `"C:/Documents/dicom-Anonymized"`.

            '''
        )

    # When 'fetch' button is triggered, save user's inputs and reset last dcm_info in st.session_states
    if st.button('Fetch files', type='primary'): 
        if not user_folder == st.session_state['user_folder']: 
            st.session_state['user_folder'] = user_folder
            st.session_state['folder'] = user_folder.replace('\\', '/')
            st.session_state['dcm_info'] = None
            st.session_state['uploader_key'] += 1

        if not user_fformat == st.session_state['user_fformat']:
            st.session_state['user_fformat'] = user_fformat
            st.session_state['fformat'] = user_fformat.replace('.', '')
            st.session_state['dcm_info'] = None

    # Error handling: When user's inputs are empty, show error msg
    if (st.session_state['folder'] and st.session_state['fformat']) == '': 
        st.error(':warning: Please input file directory and file extension.')
        
    # Error handling: to avoid rerun of fetch file function in every refresh
    elif st.session_state['dcm_info'] is not None and user_folder == st.session_state['user_folder']:
        pass
        
    # Feed user inputted folder dir and file extension to fetch files
    else: 
        with st.spinner(text='Fetching files...'):
            try:
                st.session_state['dcm_info'] = create_dcm_df(
                    folder=st.session_state['folder'],
                    fformat=st.session_state['fformat'],
                    unique_ids=active_unique_ids,
                    ref_tags=active_ref_tags,
                    new_tags=list(new_tags.keys()),
                    series_mode=st.session_state['series_mode']
                )
                uids_df = st.session_state['dcm_info'][active_unique_ids + active_ref_tags]
                if not st.session_state['series_mode']:
                    uids_df = uids_df.drop_duplicates()
                st.session_state['uids'] = uids_df
            except Exception:
                st.error(':warning: We cannot find any files in the file extension in the directory.')

    # When fetch file function is not triggered, display nothing
    if st.session_state['dcm_info'] is None:
        pass

    # When files are found, display unique ID df
    else:
        if (not st.session_state['series_mode'] and
                st.session_state['dcm_info'][upload_df_id].isnull().any()):
            st.warning(':warning: Some DICOM files are missing AccessionNumber. Please select a matcher column.')
            options = [col for col in [upload_df_id, 'PatientID', 'SeriesInstanceUID', 'SOPInstanceUID']
                       if col in st.session_state['dcm_info'].columns]
            st.session_state['matcher_id'] = st.selectbox(
                'Select matcher column',
                options,
                index=options.index(st.session_state['matcher_id']) if st.session_state['matcher_id'] in options else 0,
            )
        active_upload_df_id = st.session_state['matcher_id']

        edit_df = create_update_cols(st.session_state['uids'], active_update_tags)
        st.session_state['edit_df'] = edit_df

        case_desc = 'unique series' if st.session_state['series_mode'] else 'unique cases'
        st.success(
            f'''
                We have found the following {case_desc} - :card_file_box:
                :point_down: You may download the auto-generated template by clicking the "Download" button below.
                '''
        )
        
        # A placeholder for description of creating new tags
        desc_new_tag = st.empty()
        
        # A placeholder for selectbox of creating new tags
        create_new_tag = st.empty()
        
        # A placeholder for download function
        download_function = st.empty()
        
        # A placeholder for display data editor
        display_data = st.empty()
        
        # Upload button for user to upload their csv/xls file
        upload_function = st.empty()
        
        # A placeholder for upload error message
        upload_error = st.empty()
        
        
        # Get user uploaded file
        upload_file = upload_function.file_uploader(
            label=f'Choose a csv/excel file, which must contain column "{active_upload_df_id}" as identifer.',
            type=['csv', 'xsl', 'xslx'],
            key = st.session_state['uploader_key']
            )
        
        
        # Read user uploaded file
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
            except: 
                upload_error.error(':warning: Error: Unable to read uploaded file. Please input your updates in the template and upload again.')
                readfile_error = True

            if readfile_error: 
                pass
            else: 
                # Error checking
                error_message = validate_upload(st.session_state['edit_df'], upload_df, active_update_tags, active_upload_df_id)

                if error_message:
                    st.error(error_message)
                
                # Match the uploaded file with data editor
                else:
                    upload_df = upload_df.fillna('').astype(str)
                    try: 
                        edit_df = update_data_editor(st.session_state['edit_df'], upload_df, active_update_tags, active_unique_ids)
                    except Exception as e: 
                        upload_error.error(':warning: Error: Unable to read uploaded file. Please input your updates in the template and upload again.')

        # Save latest version of edit_df to session state
        st.session_state['edit_df'] = edit_df
        
        display_data.dataframe(
            st.session_state['edit_df'], 
            use_container_width=True, 
            hide_index=True
        )

        # Download button for csv template (edit_df)
        csv = st.session_state['edit_df'].reset_index(drop=True).to_csv(index=False).encode('utf-8')
        download_function.download_button(
            label='Download template as CSV', 
            data=csv, 
            file_name='unique_ids.csv'
        )
        
        # Selectbox for selecting values for new tag
        tags_2_create = {}
        for dcm_tag, options in new_tags.items():
            if st.session_state['dcm_info'][dcm_tag].isnull().any():
                
                notag_ids = st.session_state['dcm_info'].loc[st.session_state['dcm_info'][dcm_tag].isnull(), active_upload_df_id].unique().tolist()
                notag_ids_str = ','.join(notag_ids)
                desc_new_tag.warning(
                    f'''
                    :warning: We have identified that some DICOM series are missing the DICOM Tag :blue[{dcm_tag}] - {active_upload_df_id}: `{notag_ids_str}`.
                    '''
                )
                tags_2_create[dcm_tag] = create_new_tag.selectbox(f'Please select a value for DICOM Tag: `{dcm_tag}`.', options)
        
        # Capture user's input to write anonymized files 
        if st.button("Anonymize files", type='primary'): 
            if upload_file is None: 
                st.warning(':warning: Please upload a file as your inputs before file anonymization.')
            else:
                anon_dcm_df = st.session_state['dcm_info'].copy().filter(like='dir', axis=1)
                anon_dcm_df = anon_dcm_df.join(st.session_state['edit_df'].filter(like='Update_', axis=1))
                
                with st.spinner(text='Creating anonymized files...'): 
                    for _, row in anon_dcm_df.iterrows():
                        folder_dir = Path(row['folder_dir'])
                        for file_dir in folder_dir.rglob(f"*.{st.session_state['fformat']}"):                        
                            output_dir = f"{row['output_dir']}/{Path(file_dir).name}"
                            update = consolidate_tags(row, active_update_tags)

                            anonymize(
                                file_dir=file_dir, 
                                output_dir=output_dir, 
                                tags=tags_2_anon,
                                update=update,
                                tags_2_spare=tags_2_spare, 
                                tags_2_create=tags_2_create
                            )
            
                st.write(f'''
                        :star2: Anonymized files are written in:
                        :open_file_folder: :blue[{st.session_state['folder']}-Anonymized]
                        ''')
