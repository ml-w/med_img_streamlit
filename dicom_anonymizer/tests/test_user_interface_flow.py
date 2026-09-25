"""
End-to-end regression tests for the Streamlit UI flow, driven via
streamlit.testing.v1.AppTest against DicomAnonymizer.py (the actual Streamlit
entry point -- user_interface.py only defines streamlit_app() and is never run
directly, see dicom_anonymizer/CLAUDE.md).

These tests run Fetch -> Confirm PK -> Step 3 and inspect
st.session_state.edit_df, which is exactly what backs the downloaded template
CSV (user_interface.py: `st.session_state.edit_df.reset_index(drop=True).to_csv(...)`).

Regression covered: the SeriesDir display column (added via add_series_dir())
was silently dropped from the template CSV whenever `dcm_info` in session state
lacked a SeriesDir column while `selected_display_tags` still requested it --
e.g. a live session whose dcm_info was fetched by an older app version and kept
alive across a Streamlit code hot-reload (dcm_info is excluded from the
persisted .session.json, so this can't be fixed by just restarting the app
process; only a fresh session/re-fetch would normally clear it). Step 3 now
lazily re-derives SeriesDir via add_series_dir() when this happens.

IMPORTANT: the app persists non-DataFrame session state to a `.session.json`
file in the current working directory (user_interface.py `_save_session`).
Every test here runs inside a monkeypatched tmp cwd so it never touches a real
`.session.json` anywhere in the repo.
"""
import json
import sys
from pathlib import Path

import pytest
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "dicom_anonymizer" / "application"

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

# The app's own modules use bare imports (`from app_settings.config import ...`),
# which only resolve when application/ is on sys.path -- exactly as it is when
# streamlit itself launches the app with application/ as the working directory.
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def _create_test_dicom(path: Path, patient_id: str, accession: str) -> Path:
    """Minimal DICOM file, same pattern as tests/test_anonymize_dicom.py."""
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = generate_uid()
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.PatientName = "John"
    ds.PatientID = patient_id
    ds.AccessionNumber = accession
    ds.PatientBirthDate = "19700101"
    ds.PatientSex = "M"
    ds.StudyDate = "20210101"
    ds.Modality = "OT"
    ds.SeriesInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.Rows = 1
    ds.Columns = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.SamplesPerPixel = 1
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.PixelData = b"\0\0"
    ds.save_as(path)
    return path


@pytest.fixture
def dicom_dataset(tmp_path):
    """Two nested series directories under a scanned root, per-patient."""
    base = tmp_path / "dicoms"
    nested = base / "Pt001" / "Study1" / "SE3"
    nested.mkdir(parents=True)
    _create_test_dicom(nested / "img.dcm", patient_id="P001", accession="ACC001")
    other = base / "Pt002" / "Study1" / "SE1"
    other.mkdir(parents=True)
    _create_test_dicom(other / "img.dcm", patient_id="P002", accession="ACC002")
    return base


def _fetch_and_confirm_pk(at: AppTest, folder: Path):
    at.text_input(key="folder").set_value(str(folder))
    at.text_input(key="fformat").set_value("*.dcm")
    at.run()
    assert not at.exception

    fetch_btn = next(b for b in at.button if b.label == "Fetch files")
    fetch_btn.click()
    at.run()
    assert not at.exception
    assert at.session_state["dcm_info"] is not None

    confirm_btn = next(b for b in at.button if b.label == "Confirm PK")
    confirm_btn.click()
    at.run()
    assert not at.exception
    assert at.session_state["pk_committed"] is True


def _template_csv_columns(at: AppTest) -> list[str]:
    edit_df = at.session_state["edit_df"]
    csv_text = edit_df.reset_index(drop=True).to_csv(index=False)
    return csv_text.splitlines()[0].split(",")


def test_series_dir_in_downloaded_template_csv(tmp_path, monkeypatch, dicom_dataset):
    """
    Normal flow: after Fetch -> Confirm PK, the SeriesDir column (selected by
    default alongside every other display option) must appear in edit_df and
    therefore in the downloaded template CSV, with the correct relative dirs.
    """
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    monkeypatch.chdir(workdir)  # isolates .session.json from the real repo

    at = AppTest.from_file(str(APP_DIR / "DicomAnonymizer.py"), default_timeout=60)
    at.run()
    assert not at.exception

    _fetch_and_confirm_pk(at, dicom_dataset)

    assert "SeriesDir" in at.session_state["selected_display_tags"]
    edit_df = at.session_state["edit_df"]
    assert "SeriesDir" in edit_df.columns

    columns = _template_csv_columns(at)
    assert "SeriesDir" in columns

    series_dirs = set(edit_df.set_index("PatientID")["SeriesDir"])
    assert series_dirs == {"Pt001/Study1/SE3", "Pt002/Study1/SE1"}


def test_series_dir_recovered_when_dcm_info_stale(tmp_path, monkeypatch, dicom_dataset):
    """
    Regression test for the reported bug: simulate a live session whose
    dcm_info was populated by a version of the app predating the SeriesDir
    column (e.g. carried across a Streamlit code hot-reload, since dcm_info is
    excluded from .session.json and so survives in memory across a rerun).
    Step 3 must lazily recompute SeriesDir instead of silently dropping it
    from the template CSV.
    """
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    at = AppTest.from_file(str(APP_DIR / "DicomAnonymizer.py"), default_timeout=60)
    at.run()
    assert not at.exception

    at.text_input(key="folder").set_value(str(dicom_dataset))
    at.text_input(key="fformat").set_value("*.dcm")
    at.run()
    fetch_btn = next(b for b in at.button if b.label == "Fetch files")
    fetch_btn.click()
    at.run()
    assert not at.exception

    # Simulate the stale-session condition directly: dcm_info in memory lacks
    # SeriesDir even though the UI still has it selected for display.
    dcm_info = at.session_state["dcm_info"]
    assert "SeriesDir" in dcm_info.columns  # sanity: current code does add it
    at.session_state["dcm_info"] = dcm_info.drop(columns=["SeriesDir"])

    confirm_btn = next(b for b in at.button if b.label == "Confirm PK")
    confirm_btn.click()
    at.run()
    assert not at.exception

    assert "SeriesDir" in at.session_state["selected_display_tags"]
    edit_df = at.session_state["edit_df"]
    assert "SeriesDir" in edit_df.columns, (
        "SeriesDir was dropped from edit_df/template CSV when dcm_info lacked "
        "it -- the Step 3 lazy re-derivation fix regressed."
    )
    columns = _template_csv_columns(at)
    assert "SeriesDir" in columns

    series_dirs = set(edit_df.set_index("PatientID")["SeriesDir"])
    assert series_dirs == {"Pt001/Study1/SE3", "Pt002/Study1/SE1"}


def test_series_dir_stays_deselected_if_user_removed_it(tmp_path, monkeypatch, dicom_dataset):
    """
    The lazy-recovery fix must not fight the user: once SeriesDir has been
    explicitly deselected, it must not reappear on a later rerun even if
    dcm_info happens to lack it.
    """
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    at = AppTest.from_file(str(APP_DIR / "DicomAnonymizer.py"), default_timeout=60)
    at.run()
    assert not at.exception

    _fetch_and_confirm_pk(at, dicom_dataset)
    assert "SeriesDir" in at.session_state["selected_display_tags"]

    # User deselects SeriesDir from the "Select columns to display" multiselect.
    remaining = [c for c in at.session_state["selected_display_tags"] if c != "SeriesDir"]
    at.multiselect(key="selected_display_tags").set_value(remaining)
    at.run()
    assert not at.exception

    assert "SeriesDir" not in at.session_state["selected_display_tags"]
    edit_df = at.session_state["edit_df"]
    assert "SeriesDir" not in edit_df.columns
