import re
from turtle import onrelease
import SimpleITK as sitk
import numpy as np
import pandas as pd

from visualization import *
from pathlib import Path
from mnts.utils import get_fnames_by_IDs, get_unique_IDs

import streamlit as st
import pprint

st.set_page_config(layout="wide")  


@st.cache_data
def load_pair(MIR_DIR: Path, SEG_DIR: Path):
    # This should hold your nii.gz images
    MRI_DIR = Path("<MRI_DIR>")
    # This should hold your nii.gz segmentations
    SEG_DIR = Path("<SEG_DIR>")

    # This is used to glob a unique ID from the filename to match img and seg
    id_globber = r"\w+\d+"
    
    # Globbing files
    mri_files, seg_files = MRI_DIR.rglob("*nii.gz"), SEG_DIR.rglob("*nii.gz")
    mri_files = {re.search(id_globber, f.name).group(): f for f in mri_files}
    seg_files = {re.search(id_globber, f.name).group(): f for f in seg_files}

    # Get files with both segmentation and MRI
    intersection = list(set(mri_files.keys()).intersection(seg_files.keys()))
    intersection.sort()

    # Forming pairs
    paired = {sid: (mri_files[sid], seg_files[sid]) for sid in intersection}
    return paired



paired = load_pair()
intersection = list(paired.keys())
intersection.sort()

# Streamlit app
st.title("MRI and segmentation viewer")

# Load Excel file into session state
frame_path = Path("./Checked_Images.csv")
if 'dataframe' not in st.session_state:
    if frame_path.is_file():
        dataframe = pd.read_excel(frame_path)
    else:
        dataframe = pd.DataFrame(columns=["PairID", "Checked", "NeedFix"])
    st.session_state.dataframe = dataframe
        
# Initialize session state
if 'selection_index' not in st.session_state:
    st.session_state.selection_index = 0

# Selection box
selected_index = st.selectbox("Select a pair", range(len(intersection)), format_func=lambda x: intersection[x], index=st.session_state.selection_index)
st.session_state.selection_index = selected_index
selected_pair = str(intersection[selected_index])

# Function to save DataFrame
def save_dataframe():
    st.session_state.dataframe.to_csv(frame_path, index=False)

def update_dataframe(pair_id, need_fix=False):
    df = st.session_state.dataframe
    if not ((df["PairID"] == pair_id) & (df["Checked"])).any():
        new_row = pd.Series({"PairID": pair_id, "Checked": True, "NeedFix": need_fix})
        st.session_state.dataframe = df.append(new_row, ignore_index=True)

@st.dialog("Are you sure?")
def confirm_popup(text="Are you sure?"):
    st.error(text)
    if st.button(":red[Yes]"):
        st.session_state.last_confirmation = 1
        st.rerun()
    if st.button("No"):
        st.session_state.last_confirmation = 0
        st.rerun()

if selected_pair:
    if any(selected_pair == x for x in st.session_state.dataframe['PairID']):
        st.warning("You have already seen this case!")
    
    with st.container(height=700):
        image_slot = st.empty()
    
    # Sliders for window levels
    lower, upper = st.slider(
            'Window Levels',
            min_value=0,
            max_value=99,
            value=(25, 99)
        )

    
    with st.spinner("Running"):
        mri_path, seg_path = paired[selected_pair]

        # Load images
        mri_image = sitk.GetArrayFromImage(sitk.ReadImage(str(mri_path)))
        seg_image = sitk.GetArrayFromImage(sitk.ReadImage(str(seg_path)))

        mri_image, seg_image = crop_image_to_segmentation(mri_image, seg_image, 20)

        # Rescale
        ncols = 5
        mri_image = rescale_intensity(make_grid(mri_image, ncols=ncols), 
                                      lower = lower, 
                                      upper = upper)
        seg_image = make_grid((seg_image != 0), ncols=ncols).astype('int')

        mri_image = draw_contour(mri_image, seg_image != 0, width=2)

        # Display images
        image_slot.image(mri_image, use_column_width=True)

    # Button to go back one option
    col1, col2, col3 = st.columns([1, 1, 3])
    with col1:
        if st.button('⬅️', use_container_width=True):
            current_index = selected_index
            previous_index = (current_index - 1) % len(intersection)
            st.session_state.selection_index = previous_index
            st.rerun()
            # Button to clear the current record
        if st.button("↩️ Clear Current Record", use_container_width=True):
            st.session_state.dataframe = st.session_state.dataframe[st.session_state.dataframe["PairID"] != selected_pair]
            st.rerun()
    
    # Button to load the next option
    with col2:
        if st.button('➡️', use_container_width=True):
            current_index = selected_index
            update_dataframe(intersection[current_index])
            next_index = (current_index + 1) % len(intersection)
            while next_index != current_index:
                next_pair = intersection[next_index]
                if not st.session_state.dataframe.query(f"PairID == '{next_pair}' & Checked == True").empty:
                    next_index = (next_index + 1) % len(intersection)
                else:
                    break
            st.session_state.selection_index = next_index
            st.rerun()
        if st.button('➡️ (Need Fix)', use_container_width=True):
            current_index = selected_index
            update_dataframe(intersection[current_index], True)
            next_index = (current_index + 1) % len(intersection)
            while next_index != current_index:
                next_pair = intersection[next_index]
                if not st.session_state.dataframe.query(f"PairID == '{next_pair}' & Checked == True").empty:
                    next_index = (next_index + 1) % len(intersection)
                else:
                    break
            st.session_state.selection_index = next_index
            st.rerun()

    with col3:
        # Clear button to clear all content of the dataframe
        if st.button(':red[Delete All]'):
            confirm_popup("Are you absolutely sure? You will clear all records!")
            answer = st.session_state.get('last_confirmation', 0)
            if answer:
                st.write("Done")
            # if st.button(":red[Yes]"):
            #     # st.session_state.dataframe = pd.DataFrame(columns=["PairID", "Checked"])
            #     pass
            # if st.button("No"):
            #     pass
            
            

    # Example button to save the DataFrame
    if st.button('Save DataFrame'):
        save_dataframe()
        st.success("DataFrame saved!")

# Progress
st.progress(len(st.session_state.dataframe) / float(len(intersection)), 
            text=f"Progress: ({len(st.session_state.dataframe)} / {len(intersection)})")

# Ensure saving when the app closes
st.dataframe(st.session_state.dataframe, use_container_width=True)