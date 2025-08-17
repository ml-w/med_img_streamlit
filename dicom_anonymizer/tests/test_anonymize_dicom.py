import sys
from pathlib import Path

# Ensure repository root is on the path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import numpy as np
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
)


def _create_test_dicom(path: Path, patient_name: str = "John", patient_id: str = "12345") -> Path:
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


def test_create_output_dir(tmp_path):
    folder_dir = tmp_path / "dataset"
    sub_folder = folder_dir / "patient1"
    expected = tmp_path / "dataset-Anonymized" / "patient1"
    result = create_output_dir(sub_folder, folder_dir)
    assert result == str(expected)


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


def test_consolidate_tags():
    row = pd.Series({"Update_PatientName": "Anon", "Update_PatientID": "999"})
    update_tags = {"PatientName": None, "PatientID": None}
    result = consolidate_tags(row, update_tags)
    assert result[Tag((0x0010, 0x0010))] == "Anon"
    assert result[Tag((0x0010, 0x0020))] == "999"


def test_remove_info():
    ds = Dataset()
    ds.PatientName = "John"
    ds.AccessionNumber = "ACC"
    ds.PatientID = "123"

    remove_info(ds, ds["PatientName"], va_type=None, tags=[], update=None, tags_2_spare=[])
    assert ds.PatientName == "Anonymized"

    remove_info(ds, ds["AccessionNumber"], va_type=None, tags=[Tag((0x0008, 0x0050))], update=None, tags_2_spare=[])
    assert ds.AccessionNumber == ""

    remove_info(ds, ds["PatientID"], va_type=None, tags=[], update={Tag((0x0010, 0x0020)): "NEW"}, tags_2_spare=[])
    assert ds.PatientID == "NEW"


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
    assert out.PatientID == "12345"  # spared
    assert out.BodyPartExamined == "CHEST"
    assert out.PatientBirthDate == ""
