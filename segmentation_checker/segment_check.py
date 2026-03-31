from genericpath import isfile
from multiprocessing import Value
import sys
import re
from turtle import onrelease
import numpy as np
import pandas as pd

from visualization import LABEL_COLORMAP
from render_utils import render_current_pair
from batch_export import batch_export
from pathlib import Path
from mnts.utils import get_fnames_by_IDs, get_unique_IDs

import streamlit as st
from pprint import pprint, pformat
import plotly.express as px
import numpy as np
import json

from typing import *
import logging, time
from rich.logging import RichHandler
from rich.traceback import install

NCOLS = 5
install()

# -- inistilize states
st.session_state['last_confirmation'] = st.session_state.get("last_confirmation", False)

st.set_page_config(layout="wide")  
st.write("# Segmentation Checker")

# -- Default values

MRI_DIR_DEFAULT = ""
SEG_DIR_DEFAULT = ""

# -- Add rich handler if it's not already there:
def setup_logger(logger):
    # Check if the RichHandler is already added
    if not any(isinstance(handler, RichHandler) for handler in logger.handlers):
        # Remove all existing handlers
        for handler in logger.handlers:
            logger.removeHandler(handler)
        
        # Add RichHandler if it's not present
        rich_handler = RichHandler(console=False, rich_tracebacks=True, tracebacks_show_locals=True, locals_max_length=20)
        logger.addHandler(rich_handler)
        logger.setLevel(logging.INFO)  # Set the logging level if needed

        # Log a test message
        logger.info("Logger setup complete with RichHandler.")

    return logger

# * Adding this handler to streamlit
# First remove the error message in streamlit by default
logger = st.logger.get_logger("streamlit.error_util")
for handler in logger.handlers:
    logger.removeHandler(handler)
# Setup the logger 
logger = st.logger.get_logger("App")
setup_logger(logger)

# Introduce my own error handling
def set_global_exception_handler(f):
    import sys
    error_util = sys.modules["streamlit.error_util"]
    error_util.handle_uncaught_app_exception = f
set_global_exception_handler(logger.error)

def _exception_hook(exctype, value, traceback):
    """Custom exception hook for logging uncaught exceptions."""
    if issubclass(exctype, KeyboardInterrupt):
        sys.__excepthook__(exctype, value, traceback)
        return
    logger.error("Uncaught exception", exc_info=(exctype, value, traceback))
sys.excepthook = _exception_hook

# -- Setup style
# Load the CSS file
def load_css(file_name):
    with open(file_name) as f:
        st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
load_css("./style.css")

# -- Define some useful functions
@st.cache_data
def load_pair(MRI_DIR: Path, SEG_DIR: Path, id_globber:str = r"\w+\d+"):
    r"""This handles the matching between segmentation and images"""
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

def clean_dataframe(frame_path: Path) -> None:
    r"""Delete the CSV tracking file from disk. Caller handles session state and UI."""
    if frame_path.is_file():
        frame_path.unlink()

def load_dataframe(p: Path) -> Optional[pd.DataFrame]:
    r"""Load the tracking dataframe from CSV. Returns None if the file does not exist."""
    if p.is_file():
        return pd.read_csv(p)
    return None

def save_dataframe(df: pd.DataFrame, frame_path: Path) -> None:
    r"""Save the tracking dataframe to CSV."""
    df.to_csv(frame_path, index=False)

def update_dataframe(df: pd.DataFrame, pair_id: str, need_fix: bool = False) -> pd.DataFrame:
    r"""Add a checked row for pair_id if not already present. Returns updated dataframe."""
    if not ((df["PairID"] == pair_id) & (df["Checked"])).any():
        new_row = pd.Series({"PairID": pair_id, "Checked": True, "NeedFix": need_fix})
        df = pd.concat([df, new_row.to_frame().T], ignore_index=True)
    return df

# -- Load the state if it exists
# Function to load state from a JSON file
def load_state(file_path):
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Failed to load state: {e}")
        return None

# Function to save state to a JSON file
def save_state(file_path, state):
    try:
        with open(file_path, 'w') as f:
            json.dump(state, f)
    except Exception as e:
        logging.error(f"Failed to save state: {e}")


# File path to save/load the session state
state_file = ".session.json"

if 'initialized' not in st.session_state:
    loaded_state = load_state(state_file)
    if loaded_state:
        st.session_state.mri_dir = Path(loaded_state.get('mri_dir', MRI_DIR_DEFAULT))
        st.session_state.seg_dir = Path(loaded_state.get('seg_dir', SEG_DIR_DEFAULT))
        st.session_state.id_globber = loaded_state.get('id_globber', r"\w{0,5}\d+")
        st.session_state.frame_path = Path(loaded_state.get('frame_path', "./Checked_Images.csv"))
    else:
        # Initialize default settings if loading failed
        st.session_state.mri_dir = Path(MRI_DIR_DEFAULT)
        st.session_state.seg_dir = Path(SEG_DIR_DEFAULT)
        st.session_state.id_globber = r"\w{0,5}\d+"
        st.session_state.frame_path = Path("Checked_Images.csv")
    st.session_state.initialized = True

with st.expander("Directory Setup", expanded=st.session_state.get("require_setup", False)):
    st.write("### Insert the local directory (where this app is running)")
    st.session_state.mri_dir = Path(st.text_input("<MRI_DIR>:", value=str(st.session_state.mri_dir)))
    st.session_state.seg_dir = Path(st.text_input("<SEG_DIR>:", value=str(st.session_state.seg_dir)))
    st.session_state.id_globber = st.text_input("Regex ID globber:", value=st.session_state.get('id_globber', r"\w{0,5}\d+"))
    st.session_state.frame_path = Path(st.text_input("Frame Path:", value=str(st.session_state.get('frame_path', "./Checked_Images.csv"))))
    
    col1, _ = st.columns([1, 3])
    with col1:
        if st.button("Reload Dataframe", use_container_width=True, key="btn_reload_dataframe"):
            df = load_dataframe(st.session_state.frame_path)
            if df is not None:
                st.session_state.dataframe = df
            st.rerun()

# Persist the current session inputs automatically
save_state(
    state_file,
    {
        'mri_dir': str(st.session_state.get('mri_dir', '')),
        'seg_dir': str(st.session_state.get('seg_dir', '')),
        'id_globber': st.session_state.get('id_globber', ''),
        'frame_path': str(st.session_state.get('frame_path', '')),
    },
)

# * Setup paths
# Target ID list
with st.expander("Specify ID"):
    target_ids = st.text_input("CSV string", value="")
    if len(target_ids):
        target_ids = list(set(target_ids.split(',')))

mri_dir = st.session_state.mri_dir
seg_dir = st.session_state.seg_dir
id_globber = st.session_state.id_globber

# Get paired MRI and segmentation
if mri_dir.is_dir() and seg_dir.is_dir():
    paired = load_pair(mri_dir, seg_dir)
    intersection = list(paired.keys())
    intersection.sort()
    # further filtering if target_ids specified
    if len(target_ids):
        intersection = set(intersection) & set(target_ids)
        if missing := set(target_ids) - set(intersection):
            st.warning(f"IDs specified but the following are missing: {','.join(missing)}")
        intersection = list(intersection)
    st.session_state.require_setup = False
else:
    st.error(f"`{str(mri_dir)}` or `{str(seg_dir)}` not found!")
    st.stop()

# -- Streamlit app
st.title("MRI and segmentation viewer")

# Load Excel file into session state
frame_path = st.session_state.frame_path
if 'dataframe' not in st.session_state:
    if frame_path.is_file() and not st.session_state.last_confirmation:
        logging.info(f"Loading dataframe from file: {frame_path}")
        dataframe = pd.read_csv(frame_path)
    else:
        dataframe = pd.DataFrame(columns=["PairID", "Checked", "NeedFix"])
    dataframe['PairID'] = dataframe['PairID'].astype(str)
    st.session_state.dataframe = dataframe
        
# Initialize session state
if 'selection_index' not in st.session_state:
    st.session_state.selection_index = 0

# Selection box
intersection.sort()
selected_index = st.selectbox("Select a pair", range(len(intersection)), format_func=lambda x: intersection[x], index=st.session_state.selection_index)
if not selected_index == st.session_state.selection_index:
    # Need to trigger rerun here because the state change is not immediately reflected until next refresh
    st.session_state.selection_index = selected_index
    st.rerun()
    
# Use try-except to catch user input that doesn't exist
try:
    selected_pair = str(intersection[selected_index])
    st.write(paired[selected_pair])
except:
    st.write("Your selected ID does not match with the records.")
    st.stop()


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
    if any(selected_pair == str(x) for x in st.session_state.dataframe['PairID']):
        st.warning("You have already seen this case!")
    
    # * Display
    with st.container(height=700):
        image_slot = st.empty()
    
    # Sliders for window levels and contour options
    lower, upper = st.slider(
            'Window Levels',
            min_value=0,
            max_value=99,
            value=(25, 99)
        )
    col_cw, col_ca = st.columns(2)
    with col_cw:
        contour_width = st.slider('Contour Width', min_value=1, max_value=10, value=2)
    with col_ca:
        contour_alpha = st.slider('Contour Alpha', min_value=0.0, max_value=1.0, value=1.0, step=0.05)

    
    intensity_stats = pd.DataFrame()  # safe default if rendering fails
    mri_path, seg_path = paired[selected_pair]
    with st.spinner("Running"):
        rendered_image, intensity_stats, _metadata_match, metadata_messages, warning_messages = render_current_pair(
            mri_path=mri_path,
            seg_path=seg_path,
            lower=lower,
            upper=upper,
            contour_width=contour_width,
            contour_alpha=contour_alpha,
            ncols=NCOLS,
            display_width=2800,
        )
        for level, text in metadata_messages:
            if level == 'success':
                st.success(text)
            else:
                st.error(text)
        for msg in warning_messages:
            st.warning(msg)
        if rendered_image is not None:
            image_slot.image(rendered_image, use_column_width=True, output_format="PNG")
        else:
            st.error("Rendering failed — see warnings above.")

    # Signal intensity statistics per segmentation label
    if not intensity_stats.empty:
        with st.expander("Signal Intensity Statistics", expanded=False):
            def _style_label_col(val):
                r, g, b = LABEL_COLORMAP[int(val) % len(LABEL_COLORMAP)]
                text = "white" if (r * 0.299 + g * 0.587 + b * 0.114) < 150 else "black"
                return f"background-color: rgb({r},{g},{b}); color: {text}"
            styled = intensity_stats.style.map(_style_label_col, subset=["Label"])
            st.dataframe(styled, use_container_width=True, hide_index=True)

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
        if st.button('➡️ Checked and Next', use_container_width=True):
            current_index = selected_index
            st.session_state.dataframe = update_dataframe(st.session_state.dataframe, intersection[current_index])
            next_index = (current_index + 1) % len(intersection)
            while str(intersection[next_index]) in st.session_state.dataframe['PairID'].values:
                if next_index >= len(intersection) - 1:
                    break
                else:
                    next_index += 1
            st.session_state.selection_index = next_index
            st.rerun()
        if st.button('➡️ Mark as need fix)', use_container_width=True):
            current_index = selected_index
            st.session_state.dataframe = update_dataframe(st.session_state.dataframe, intersection[current_index], True)
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
            st.warning("Dataframe deleted")
            logger.warning("Deleted the dataframe")
            clean_dataframe(st.session_state.frame_path)
            st.session_state.pop('dataframe', None)
            st.session_state.pop('last_confirmation', None)
            st.warning("CSV file deleted! Reloading in 3 seconds...")
            time.sleep(3)
            st.stop()
        else:
            st.session_state.pop('last_confirmation', None)

    # Example button to save the DataFrame
    if st.button('Save DataFrame'):
        save_dataframe(st.session_state.dataframe, st.session_state.frame_path)
        st.success("DataFrame saved!")

    if 'dataframe' in st.session_state:
        st.download_button(
            label='Download Dataframe',
            data=st.session_state.dataframe.to_csv(index=False).encode('utf-8'),
            file_name='dataframe.csv',
            mime='text/csv'
        )

        # Progress
        st.progress(len(st.session_state.dataframe) / float(len(intersection)),
                    text=f"Progress: ({len(st.session_state.dataframe)} / {len(intersection)})")
        if len(st.session_state.dataframe) == len(intersection):
            st.success("You've viewed all the cases!")

        # Show dataframe
        with st.popover("Data Overview", use_container_width=True):
            st.dataframe(st.session_state.dataframe, use_container_width=True)

            # Show statistics
            # Count the occurrences of each value in the 'NeedFix' column
            need_fix_counts = st.session_state.dataframe['NeedFix'].value_counts()

            # Create a pie chart using Plotly
            fig = px.pie(
                names=need_fix_counts.index,
                values=need_fix_counts.values,
                title="Need Fix Counts"
            )

            # Display the pie chart in Streamlit
            st.plotly_chart(fig)

    # -- Batch export all images
    with st.expander("Batch Export Images"):
        export_dir = st.text_input(
            "Output directory:",
            value=str(Path(st.session_state.mri_dir).parent / "exported_overlays"),
        )
        col_ew, col_et = st.columns(2)
        with col_ew:
            export_workers = st.number_input("Threads", min_value=1, max_value=16, value=4)
        with col_et:
            export_width = st.number_input("Image width (px)", min_value=800, max_value=4000, value=2800, step=200)

        if st.button("Export All", type="primary"):
            export_path = Path(export_dir)
            progress_bar = st.progress(0, text="Exporting...")

            def _update_progress(completed, total):
                progress_bar.progress(completed / total, text=f"Exported {completed}/{total}")

            results = batch_export(
                paired=paired,
                output_dir=export_path,
                max_workers=export_workers,
                progress_callback=_update_progress,
                ncols=NCOLS,
                contour_width=contour_width,
                contour_alpha=contour_alpha,
                window_lower=lower,
                window_upper=upper,
                display_width=export_width,
            )
            succeeded = sum(1 for _, ok, _ in results if ok)
            failed = [r for r in results if not r[1]]
            st.success(f"Exported {succeeded}/{len(results)} images to `{export_path}`")
            if failed:
                st.warning(f"{len(failed)} failed:")
                for pid, _, msg in failed:
                    st.text(f"  {pid}: {msg}")