import sys
from pathlib import Path

# Ensure repository root is on the path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from dicom_anonymizer.application.ui_utils.ui_logic import (
    create_update_cols,
    update_data_editor,
)


def test_create_update_cols():
    df = pd.DataFrame({"PatientName": ["Alice"], "PatientID": ["1"]})
    update_tags = {"PatientName": lambda x: x.upper(), "PatientID": "anon"}
    out = create_update_cols(df, update_tags)
    assert out["Update_PatientName"].tolist() == ["ALICE"]
    assert out["Update_PatientID"].tolist() == ["anon"]


def test_update_data_editor():
    edit_df = pd.DataFrame({
        "PatientID": ["1", "2"],
        "PatientName": ["Alice", "Bob"],
    })
    update_tags = {"PatientName": "", "PatientID": ""}
    edit_df = create_update_cols(edit_df, update_tags)

    upload_df = pd.DataFrame({
        "PatientID": ["1"],
        "Update_PatientName": ["ANN"],
        "Update_PatientID": ["99"],
    })

    result = update_data_editor(edit_df, upload_df, update_tags, ["PatientID"])
    row1 = result[result["PatientID"] == "1"].iloc[0]
    row2 = result[result["PatientID"] == "2"].iloc[0]
    assert row1["Update_PatientName"] == "ANN"
    assert row1["Update_PatientID"] == "99"
    assert row2["Update_PatientName"] == ""
