import streamlit as st
import json
import pandas as pd
from pydicom.tag import Tag
from anonymizer_utils.anonymize_dicom import *
from ui_utils.ui_logic import *

def streamlit_app(): 
    # Initialize session states
    if 'user_folder' not in st.session_state:       # user input directory
        st.session_state['user_folder'] = ''
    if 'folder' not in st.session_state:            # folder path to glob files
        st.session_state['folder'] = ''
    if 'user_fformat' not in st.session_state:      # user input file format
        st.session_state['user_fformat'] = ''
    if 'fformat' not in st.session_state:           # file format to glob
        st.session_state['fformat'] = ''
    if 'dcm_info' not in st.session_state:          # all dcm files
        st.session_state['dcm_info'] = None 
    if 'uids' not in st.session_state:              # list of unique IDs
        st.session_state['uids'] = None
    if 'edit_df' not in st.session_state:           # data editor
        st.session_state['edit_df'] = None

        
    # Inititalize pre-defined values
    unique_ids = [
        'PatientName', 
        'PatientID', 
        'AccessionNum'
    ]

    predefined_tags = [
        'PatientID',
        'PatientName',
        'AccessionNumber',
        'StudyDate',
        'Modality',
        'StudyDescription',
        'PatientBirthDate', 
        'InstitutionName'
    ]

    default_tags = [
        (0x0010, 0x0030),  # Patient's Birth Date
        (0x0008, 0x0050),  # Accession Number
        (0x0008, 0x0080),  # Institution Name
    ]

    update_tags = [
        'PatientID'
    ]


    # Page user interface
    st.set_page_config(page_title = 'DICOM Anonymizer')
    st.write('# DICOM Anonymizer:hospital::card_file_box:')

    # Capture user's input of folder directory
    user_folder = st.text_input(
        'Please copy and paste the full directory of the folder with DICOM files.', 
        placeholder='Enter the full file directory, e.g., "C:/Users/Documents"'
    )

    user_fformat = st.text_input(
        'File format', 
        placeholder='e.g., "dcm"'
    )

    # When 'fetch' button is triggered, save user's inputs and reset last dcm_info in st.session_states
    if st.button('Fetch files', type='primary'): 
        if not user_folder == st.session_state['user_folder']: 
            st.session_state['user_folder'] = user_folder
            st.session_state['folder'] = user_folder.replace('\\', '/')
            st.session_state['dcm_info'] = None

        if not user_fformat == st.session_state['user_fformat']:
            st.session_state['user_fformat'] = user_fformat
            st.session_state['fformat'] = user_fformat.replace('.', '')
            st.session_state['dcm_info'] = None

    # Error handling: When user's inputs are empty, show error msg
    if (st.session_state['folder'] and st.session_state['fformat']) == '': 
        st.error(':warning: Please input file directory and file format.')
        
    # Error handling: to avoid rerun of fetch file function in every refresh
    elif st.session_state['dcm_info'] is not None and user_folder == st.session_state['user_folder']:
        pass
        
    # Feed user inputted folder dir and file format to fetch files
    else: 
        with st.spinner(text='Fetching files...'):
            try: 
                st.session_state['dcm_info'] = create_dcm_df(st.session_state['folder'], st.session_state['fformat'], unique_ids)
                st.session_state['uids'] = st.session_state['dcm_info'][unique_ids].drop_duplicates()
            except: 
                st.error(':warning: We cannot find any files in the file format in the directory.')

    # When fetch file function is not triggered, display nothing
    if st.session_state['dcm_info'] is None: 
        pass

    # When files are found, display unique ID df
    else: 
        st.success('''
                We have found the following unique cases - :card_file_box:  
                :point_down: You may download the auto-generated template by clicking the "Download" button below.
                ''')
        
        edit_df = st.session_state['uids']
        edit_df['Update_PatientID'] = ''
        edit_df['Update_PatientID'] = edit_df['Update_PatientID'].astype(str)
        st.session_state['edit_df'] = edit_df
        
        # A placeholder for download function
        download_function = st.empty()
        
        # A placeholder for display data editor
        display_data = st.empty()
        
        # Upload button for user to upload their csv/xls file
        upload_function = st.empty()
        
        # A placeholder for upload error message
        upload_error = st.empty()
        
        # Read user uploaded file
        upload_file = upload_function.file_uploader(
            label='Choose a csv/excel file, which must contain column "PatientID" as identifer.', 
            type=['csv', 'xsl', 'xslx']
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
            except: 
                upload_error.error(':warning: Error: Unable to read uploaded file. Please input your updates in the template and upload again.')
                readfile_error = True

            if readfile_error: 
                pass
            else: 
                # Error checking of columns in user uploaded file
                if 'Update_PatientID' not in upload_df:
                    upload_error.error(':warning: Error in uploaded file: **Column "Update_PatientID"** must be contained.')
                elif 'PatientID' not in upload_df:
                    upload_error.error(':warning: Error in uploaded file: **Column "PatientID"** must be contained.')
                # Error checking of unmatched PatientIDs
                elif (unmatched_ids := check_unmatched_patient_ids(upload_df, st.session_state['edit_df'])):
                    # Display PatientIDs in error message
                    unmatched_ids_str = ', '.join(map(str, unmatched_ids))
                    upload_error.error(
                        f':warning: Error in uploaded file: The following **PatientIDs** have no matches in the uploaded file - :blue-background[{unmatched_ids_str}].'
                    )
                
                # Match the uploaded file with data editor
                else:
                    upload_df = upload_df.fillna('')
                    upload_df['Update_PatientID'] = upload_df['Update_PatientID'].astype(str)
                    try: 
                        edit_df = update_data_editor(st.session_state['edit_df'], upload_df, update_tags)
                    except Exception as e: 
                        upload_error.error(':warning: Error: Unable to read uploaded file. Please input your updates in the template and upload again.')

        # Save latest version of edit_df to session state
        st.session_state['edit_df'] = edit_df

        # Display user's inputs
        config = {
            'PatientID': st.column_config.TextColumn(
                'PatientID', 
                disabled=True
                ),
            'PatientName': st.column_config.TextColumn(
                'PatientName', 
                disabled=True
                ),
            'AccessionNum': st.column_config.TextColumn(
                'AccessionNum', 
                disabled=True
                ), 
            'Update_PatientID': st.column_config.TextColumn(
                'Update_PatientID', 
                required=True,
                max_chars=256
                )
        }
        
        display_data.dataframe(
            st.session_state['edit_df'], 
            use_container_width=True, 
            column_config=config,
            hide_index=True
        )

        # Download button for csv template (edit_df)
        csv = st.session_state['edit_df'].reset_index(drop=True).to_csv(index=False).encode('utf-8')
        download_function.download_button(
            label='Download template as CSV', 
            data=csv, 
            file_name='unique_ids.csv'
        )
        
        # Capture user's input to write anonymized files 
        if st.button("Anonymize files", type='primary'): 
            # Check if user has entered all required field before writing files
            if edit_df['Update_PatientID'].isnull().any() or (edit_df['Update_PatientID'] == '').any(): 
                st.error(':warning: **Column "Update_PatientID"** cannot be empty. Please fill in all required fields. ')
            
            # Finalize user's inputs to anonymize function
            else: 
                anon_dcm_df = st.session_state['dcm_info'].copy()
                anon_dcm_df = anon_dcm_df.join(st.session_state['edit_df'][['Update_PatientID']])
                
                with st.spinner(text='Writing files...'): 
                    for _, row in anon_dcm_df.iterrows():
                        file_dir = row['file_dir']
                        output_dir = row['output_dir']
                        update = {
                            Tag((0x0010, 0x0010)): row['Update_PatientID'],     # Patient's Name
                            Tag((0x0010, 0x0020)): row['Update_PatientID']      # Patient's ID
                        }
                        anonymize(
                            file_dir=file_dir, 
                            output_dir=output_dir, 
                            update=update, 
                            tags_2_spare=default_tags
                        )
            
                st.write(f'''
                        :star2: Anonymized files are written in:  
                        :open_file_folder: :blue-background[{st.session_state['folder']}-Anonymized]
                        ''')