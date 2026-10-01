import sys
from pathlib import Path

# Ensure repository root is on the path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import pytest
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from pydicom.tag import Tag
import pydicom

from dicom_anonymizer.application.anonymizer_utils.anonymize_dicom import (
    create_output_dir,
    create_dcm_df,
    consolidate_tags,
    remove_info,
    anonymize,
    _anonymize_series,
    run_anonymization,
)
from dicom_anonymizer.application.app_settings.config import default_tags_2_anon
from dicom_anonymizer.application.ui_utils.ui_logic import compute_effective_tags_2_anon, add_series_dir


def _create_test_dicom(path: Path, patient_name: str = "John", patient_id: str = "12345",
                        series_uid: str | None = None) -> Path:
    """Create a minimal DICOM file for testing."""
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = generate_uid()
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.PatientBirthDate = "19700101"
    ds.PatientSex = "M"
    ds.StudyDate = "20210101"
    ds.Modality = "OT"
    ds.SeriesInstanceUID = series_uid or generate_uid()
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


# ---------------------------------------------------------------------------
# create_output_dir
# ---------------------------------------------------------------------------

def test_create_output_dir(tmp_path):
    folder_dir = tmp_path / "dataset"
    sub_folder = folder_dir / "patient1"
    expected = tmp_path / "dataset-Anonymized" / "patient1"
    result = create_output_dir(sub_folder, folder_dir)
    assert result == str(expected)


# ---------------------------------------------------------------------------
# create_dcm_df
# ---------------------------------------------------------------------------

def test_create_dcm_df(tmp_path):
    base = tmp_path / "data"
    patient_folder = base / "p1"
    patient_folder.mkdir(parents=True)
    _create_test_dicom(patient_folder / "img.dcm")

    df = create_dcm_df(
        folder=str(base),
        fformat="dcm",
        unique_ids=["PatientID"],
        ref_tags=["PatientID", "PatientName"],
        new_tags=["StudyDate"],
    )

    assert list(df.index) == ["12345"]
    assert df.loc["12345", "PatientName"] == "John"
    expected_out = create_output_dir(patient_folder, base)
    assert df.loc["12345", "output_dir"] == expected_out
    assert set(["folder_dir", "output_dir", "PatientID", "PatientName", "StudyDate"]).issubset(df.columns)


def test_create_dcm_df_series_mode(tmp_path):
    """series_mode=True reads each file and produces one row per unique PK."""
    base = tmp_path / "data"
    series1 = base / "series1"
    series2 = base / "series2"
    series1.mkdir(parents=True)
    series2.mkdir(parents=True)
    _create_test_dicom(series1 / "img.dcm", patient_id="P001")
    _create_test_dicom(series2 / "img.dcm", patient_id="P002")

    df = create_dcm_df(
        folder=str(base),
        fformat="*.dcm",
        unique_ids=["PatientID"],
        ref_tags=["PatientName"],
        new_tags=[],
        series_mode=True,
    )

    assert set(df.index) == {"P001", "P002"}
    assert set(["folder_dir", "output_dir", "PatientID", "PatientName"]).issubset(df.columns)


def test_create_dcm_df_series_mode_one_dir_multiple_series(tmp_path):
    """
    Several files from DIFFERENT series/patients living in ONE directory must each
    produce their own row carrying their own values — no sharing of tags across files.
    """
    base = tmp_path / "data"
    one_dir = base / "mixed"
    one_dir.mkdir(parents=True)
    _create_test_dicom(one_dir / "a.dcm", patient_name="Alice", patient_id="P001")
    _create_test_dicom(one_dir / "b.dcm", patient_name="Bob", patient_id="P002")
    _create_test_dicom(one_dir / "c.dcm", patient_name="Carol", patient_id="P003")

    df = create_dcm_df(
        folder=str(base),
        fformat="*.dcm",
        unique_ids=["PatientID"],
        ref_tags=["PatientName", "SeriesInstanceUID"],
        new_tags=[],
        series_mode=True,
    )

    assert len(df) == 3
    assert set(df.index) == {"P001", "P002", "P003"}
    name_by_pid = df["PatientName"].to_dict()
    assert name_by_pid == {"P001": "Alice", "P002": "Bob", "P003": "Carol"}
    # Each file must carry its own SeriesInstanceUID, not one shared across the folder
    assert df["SeriesInstanceUID"].nunique() == 3


def test_create_dcm_df_series_mode_parallel_matches_sequential(tmp_path):
    """
    The parallel (ProcessPoolExecutor) and sequential code paths must produce
    identical DataFrames, and both must silently skip unreadable files.
    """
    base = tmp_path / "data"
    one_dir = base / "mixed"
    one_dir.mkdir(parents=True)
    _create_test_dicom(one_dir / "a.dcm", patient_name="Alice", patient_id="P001")
    _create_test_dicom(one_dir / "b.dcm", patient_name="Bob", patient_id="P002")
    _create_test_dicom(one_dir / "c.dcm", patient_name="Carol", patient_id="P003")
    _create_test_dicom(one_dir / "d.dcm", patient_name="Dave", patient_id="P004")
    (one_dir / "junk.dcm").write_text("not a dicom file")

    kwargs = dict(
        folder=str(base),
        fformat="*.dcm",
        unique_ids=["PatientID"],
        ref_tags=["PatientName", "SeriesInstanceUID"],
        new_tags=[],
        series_mode=True,
    )

    df_sequential = create_dcm_df(**kwargs, parallel_threshold=10**9, max_workers=2)
    df_parallel = create_dcm_df(**kwargs, parallel_threshold=0, max_workers=2)

    assert "junk" not in " ".join(df_sequential["file_path"])
    assert "junk" not in " ".join(df_parallel["file_path"])
    assert len(df_sequential) == 4
    assert len(df_parallel) == 4

    pd.testing.assert_frame_equal(df_sequential, df_parallel)


def test_create_dcm_df_series_mode_with_series_dir(tmp_path):
    """
    End-to-end: add_series_dir() layered on top of create_dcm_df() output computes
    SeriesDir relative to the scanned root — nested series get their relative path,
    a file sitting directly in the root gets '.'.
    """
    base = tmp_path / "data"
    nested = base / "Pt001" / "Study1" / "SE3"
    nested.mkdir(parents=True)
    _create_test_dicom(nested / "img.dcm", patient_id="P001")
    _create_test_dicom(base / "img2.dcm", patient_id="P002")

    df = create_dcm_df(
        folder=str(base),
        fformat="*.dcm",
        unique_ids=["PatientID"],
        ref_tags=["PatientName"],
        new_tags=[],
        series_mode=True,
    )
    df = add_series_dir(df, str(base))

    assert df.loc["P001", "SeriesDir"] == "Pt001/Study1/SE3"
    assert df.loc["P002", "SeriesDir"] == "."


# ---------------------------------------------------------------------------
# consolidate_tags
# ---------------------------------------------------------------------------

def test_consolidate_tags():
    row = pd.Series({"Update_PatientName": "Anon", "Update_PatientID": "999"})
    update_tags = {"PatientName": None, "PatientID": None}
    result = consolidate_tags(row, update_tags)
    assert result[Tag((0x0010, 0x0010))] == "Anon"
    assert result[Tag((0x0010, 0x0020))] == "999"


def test_consolidate_tags_accession_number():
    row = pd.Series({"Update_AccessionNumber": "ACC001"})
    update_tags = {"AccessionNumber": None}
    result = consolidate_tags(row, update_tags)
    assert result[Tag((0x0008, 0x0050))] == "ACC001"


def test_consolidate_tags_empty_value_excluded():
    """Empty Update_ values must not appear in the returned dict."""
    row = pd.Series({"Update_PatientName": "", "Update_PatientID": "999"})
    update_tags = {"PatientName": None, "PatientID": None}
    result = consolidate_tags(row, update_tags)
    assert Tag((0x0010, 0x0010)) not in result
    assert result[Tag((0x0010, 0x0020))] == "999"


# ---------------------------------------------------------------------------
# remove_info
# ---------------------------------------------------------------------------

def test_remove_info_by_vr_type():
    """Tags matching the va_type list are replaced with 'Anonymized'."""
    ds = Dataset()
    ds.PatientName = "John"
    remove_info(ds, ds["PatientName"], va_type=["PN"], tags=[], update=None, tags_2_spare=[])
    assert ds.PatientName == "Anonymized"


def test_remove_info_by_tag():
    """Tags in the explicit tag list are blanked to ''."""
    ds = Dataset()
    ds.AccessionNumber = "ACC"
    remove_info(ds, ds["AccessionNumber"], va_type=[], tags=[Tag((0x0008, 0x0050))], update=None, tags_2_spare=[])
    assert ds.AccessionNumber == ""


def test_remove_info_update():
    """Update dict sets the tag to the supplied replacement value."""
    ds = Dataset()
    ds.PatientID = "123"
    remove_info(ds, ds["PatientID"], va_type=[], tags=[], update={Tag((0x0010, 0x0020)): "NEW"}, tags_2_spare=[])
    assert ds.PatientID == "NEW"


def test_remove_info_spare():
    """Tags in tags_2_spare are not modified even when matched by VR type."""
    ds = Dataset()
    ds.PatientName = "John"
    spare = [Tag((0x0010, 0x0010))]
    remove_info(ds, ds["PatientName"], va_type=["PN"], tags=[], update=None, tags_2_spare=spare)
    assert ds.PatientName == "John"


def test_remove_info_update_overrides_blank():
    """Update value is applied last, overriding any earlier VR-type or tag blanking."""
    ds = Dataset()
    ds.PatientName = "John"
    tag = Tag((0x0010, 0x0010))
    remove_info(ds, ds["PatientName"], va_type=["PN"], tags=[tag], update={tag: "Override"}, tags_2_spare=[])
    assert ds.PatientName == "Override"


# ---------------------------------------------------------------------------
# anonymize
# ---------------------------------------------------------------------------

def test_anonymize(tmp_path):
    src = tmp_path / "in.dcm"
    dst = tmp_path / "out" / "anon.dcm"
    dst.parent.mkdir()
    _create_test_dicom(src)

    update = {Tag((0x0010, 0x0010)): "Anon"}
    spare = [Tag((0x0010, 0x0020))]
    create = {"BodyPartExamined": "CHEST"}

    anonymize(str(src), str(dst), update=update, tags_2_spare=spare, tags_2_create=create)

    out = pydicom.dcmread(str(dst))
    assert out.PatientName == "Anon"
    assert out.PatientID == "12345"   # spared
    assert out.BodyPartExamined == "CHEST"
    assert out.PatientBirthDate == ""


def test_anonymize_custom_va_type(tmp_path):
    """Only the specified VR types are anonymized; others remain unchanged."""
    src = tmp_path / "in.dcm"
    dst = tmp_path / "out" / "anon.dcm"
    dst.parent.mkdir()
    _create_test_dicom(src)

    # Anonymize only PN; DA (StudyDate) and LO (PatientID) should be untouched
    anonymize(str(src), str(dst), va_type=["PN"], tags=[], tags_2_spare=[], tags_2_create={})

    out = pydicom.dcmread(str(dst))
    assert out.PatientName == "Anonymized"
    assert out.StudyDate == "20210101"   # DA not in va_type
    assert out.PatientID == "12345"      # LO not in va_type


def test_anonymize_spare_tag(tmp_path):
    """A tag in tags_2_spare is never modified regardless of VR type."""
    src = tmp_path / "in.dcm"
    dst = tmp_path / "out" / "anon.dcm"
    dst.parent.mkdir()
    _create_test_dicom(src)

    spare = [Tag((0x0010, 0x0010))]  # PatientName
    anonymize(str(src), str(dst), va_type=["PN"], tags=[], tags_2_spare=spare, tags_2_create={})

    out = pydicom.dcmread(str(dst))
    assert out.PatientName == "John"  # spared


def test_anonymize_unselected_update_tag_falls_back_to_vr_pass(tmp_path):
    """
    Regression test: a tag removed from the blank list (because its "columns to
    update" checkbox is unselected in the UI) must fall back to the VR-type
    "Anonymized" pass instead of being forced to "" by the blank list.

    PatientName (VR=PN) is removed from the effective tags_2_anon list, so with
    va_type=["PN"] it should become "Anonymized". PatientID (VR=LO, not in
    va_type) stays in the list, so it should still be blanked to "".
    """
    src = tmp_path / "in.dcm"
    dst = tmp_path / "out" / "anon.dcm"
    dst.parent.mkdir()
    _create_test_dicom(src)

    tags = [t for t in default_tags_2_anon if Tag(t) != Tag((0x0010, 0x0010))]
    assert Tag((0x0010, 0x0020)) in [Tag(t) for t in tags]  # PatientID still listed

    anonymize(str(src), str(dst), va_type=["PN"], tags=tags, tags_2_spare=[], tags_2_create={})

    out = pydicom.dcmread(str(dst))
    assert out.PatientName == "Anonymized"  # VR pass, not blanked to ""
    assert out.PatientID == ""              # still in the blank list


def test_anonymize_invalid_dicom_raises(tmp_path):
    """
    Regression test: anonymize() used to swallow read failures with
    ``except InvalidDicomError: print(f"Error when reading: {f}")``, which
    referenced ``f`` before it was ever assigned (dcmread raised before the
    assignment completed) -- an UnboundLocalError masking the real error.
    anonymize() now lets the error propagate so callers (_anonymize_series)
    can catch and report it per file.
    """
    src = tmp_path / "bad.dcm"
    src.write_text("not a dicom file")
    dst = tmp_path / "out" / "bad.dcm"

    with pytest.raises(Exception):
        anonymize(str(src), str(dst), tags=[], va_type=[], tags_2_spare=[], tags_2_create={})


def test_anonymize_tags_2_create_none_does_not_crash(tmp_path):
    """tags_2_create=None must be treated as {} rather than crashing on .items()."""
    src = tmp_path / "in.dcm"
    dst = tmp_path / "out" / "anon.dcm"
    dst.parent.mkdir()
    _create_test_dicom(src)

    anonymize(str(src), str(dst), tags=[], va_type=[], tags_2_spare=[], tags_2_create=None)
    assert dst.exists()


# ---------------------------------------------------------------------------
# _anonymize_series
# ---------------------------------------------------------------------------

def _default_settings(**overrides):
    settings = dict(
        tags=default_tags_2_anon,
        va_type=["PN"],
        tags_2_spare=[],
        tags_2_create={},
        extra_tags_2_anon=None,
        regex_pattern=None,
    )
    settings.update(overrides)
    return settings


def test_anonymize_series_happy_path(tmp_path):
    src1 = tmp_path / "a.dcm"
    src2 = tmp_path / "b.dcm"
    _create_test_dicom(src1, patient_id="P001")
    _create_test_dicom(src2, patient_id="P001")
    dst1 = tmp_path / "out" / "a.dcm"
    dst2 = tmp_path / "out" / "b.dcm"

    task = (
        "series1",
        [
            (str(src1), str(dst1), {Tag((0x0010, 0x0010)): "Anon"}),
            (str(src2), str(dst2), {}),
        ],
    )
    series_key, n_ok, errors = _anonymize_series(task, **_default_settings())

    assert series_key == "series1"
    assert n_ok == 2
    assert errors == []
    out1 = pydicom.dcmread(str(dst1))
    assert out1.PatientName == "Anon"
    assert dst2.exists()


def test_anonymize_series_corrupt_file_reported_others_still_written(tmp_path):
    """One bad file in a series must not abort the rest -- it's reported as an
    error and the remaining files in the series are still anonymized."""
    good1 = tmp_path / "good1.dcm"
    good2 = tmp_path / "good2.dcm"
    bad = tmp_path / "bad.dcm"
    _create_test_dicom(good1, patient_id="P001")
    _create_test_dicom(good2, patient_id="P001")
    bad.write_text("not a dicom file")

    dst_good1 = tmp_path / "out" / "good1.dcm"
    dst_bad = tmp_path / "out" / "bad.dcm"
    dst_good2 = tmp_path / "out" / "good2.dcm"

    task = (
        "series1",
        [
            (str(good1), str(dst_good1), {}),
            (str(bad), str(dst_bad), {}),
            (str(good2), str(dst_good2), {}),
        ],
    )
    series_key, n_ok, errors = _anonymize_series(task, **_default_settings())

    assert series_key == "series1"
    assert n_ok == 2
    assert len(errors) == 1
    assert errors[0][0] == str(bad)
    assert dst_good1.exists()
    assert dst_good2.exists()
    assert not dst_bad.exists()


# ---------------------------------------------------------------------------
# run_anonymization
# ---------------------------------------------------------------------------

def test_run_anonymization_parallel_matches_sequential(tmp_path):
    """
    Parallel (max_workers=2, parallel_threshold=0) and sequential
    (max_workers=1) execution over the same series must produce byte-identical
    output files -- mirrors test_create_dcm_df_series_mode_parallel_matches_sequential.
    """
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    patient_ids = ["P001", "P002", "P003"]
    for pid in patient_ids:
        _create_test_dicom(src_dir / f"{pid}.dcm", patient_id=pid)

    settings = _default_settings()

    def _make_tasks(out_dir):
        return [
            (f"series-{pid}", [(str(src_dir / f"{pid}.dcm"), str(out_dir / f"{pid}.dcm"), {})])
            for pid in patient_ids
        ]

    seq_out = tmp_path / "seq_out"
    par_out = tmp_path / "par_out"
    seq_out.mkdir()
    par_out.mkdir()

    total_ok_seq, errors_seq = run_anonymization(
        _make_tasks(seq_out), settings, max_workers=1, parallel_threshold=10**9,
    )
    total_ok_par, errors_par = run_anonymization(
        _make_tasks(par_out), settings, max_workers=2, parallel_threshold=0,
    )

    assert total_ok_seq == len(patient_ids)
    assert total_ok_par == len(patient_ids)
    assert errors_seq == []
    assert errors_par == []

    for pid in patient_ids:
        seq_bytes = (seq_out / f"{pid}.dcm").read_bytes()
        par_bytes = (par_out / f"{pid}.dcm").read_bytes()
        assert seq_bytes == par_bytes


def test_run_anonymization_on_progress_called_once_per_series(tmp_path):
    """on_progress fires once per finished series (regardless of completion
    order under the parallel path), with the final call's done == total."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    patient_ids = ["P001", "P002", "P003"]
    for pid in patient_ids:
        _create_test_dicom(src_dir / f"{pid}.dcm", patient_id=pid)

    out_dir = tmp_path / "out"
    tasks = [
        (f"series-{pid}", [(str(src_dir / f"{pid}.dcm"), str(out_dir / f"{pid}.dcm"), {})])
        for pid in patient_ids
    ]

    calls = []
    total_ok, errors = run_anonymization(
        tasks,
        _default_settings(),
        max_workers=2,
        parallel_threshold=0,
        on_progress=lambda done, total, series_key: calls.append((done, total, series_key)),
    )

    assert total_ok == len(patient_ids)
    assert errors == []
    assert len(calls) == len(patient_ids)  # exactly once per series
    final_done, final_total, _ = calls[-1]
    assert final_done == final_total == len(patient_ids)


# ---------------------------------------------------------------------------
# compute_effective_tags_2_anon
# ---------------------------------------------------------------------------

def test_compute_effective_tags_2_anon_drops_unselected():
    """Tags for update_tag_defaults keys not in selected_update_tags are removed."""
    update_tag_defaults = {"PatientName": "", "PatientID": "", "InstitutionName": "Anonymized"}
    selected = ["PatientID"]  # PatientName, InstitutionName not selected

    result = compute_effective_tags_2_anon(default_tags_2_anon, update_tag_defaults, selected)

    assert Tag((0x0010, 0x0010)) not in [Tag(t) for t in result]  # PatientName dropped
    assert Tag((0x0008, 0x0080)) not in [Tag(t) for t in result]  # InstitutionName dropped
    assert Tag((0x0010, 0x0020)) in [Tag(t) for t in result]      # PatientID kept (selected)
    # Tags unrelated to any update_tag_defaults keyword are always kept
    assert Tag((0x0010, 0x1040)) in [Tag(t) for t in result]      # Patient's Address


def test_compute_effective_tags_2_anon_all_selected_is_noop():
    """When every update key is selected, the base list is returned unchanged."""
    update_tag_defaults = {"PatientName": "", "PatientID": ""}
    selected = ["PatientName", "PatientID"]

    result = compute_effective_tags_2_anon(default_tags_2_anon, update_tag_defaults, selected)

    assert [Tag(t) for t in result] == [Tag(t) for t in default_tags_2_anon]
