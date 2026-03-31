import sys
from pathlib import Path

# Ensure repository root is on the path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from dicom_anonymizer.application.ui_utils.ui_logic import (
    create_update_cols,
    update_data_editor,
    check_unmatched_rows,
    validate_upload,
    highlight_updated_cells,
)


# ---------------------------------------------------------------------------
# create_update_cols
# ---------------------------------------------------------------------------

def test_create_update_cols():
    df = pd.DataFrame({"PatientName": ["Alice"], "PatientID": ["1"]})
    update_tags = {"PatientName": lambda x: x.upper(), "PatientID": "anon"}
    out = create_update_cols(df, update_tags)
    assert out["Update_PatientName"].tolist() == ["ALICE"]
    assert out["Update_PatientID"].tolist() == ["anon"]


def test_create_update_cols_empty_default():
    df = pd.DataFrame({"PatientName": ["Alice"]})
    out = create_update_cols(df, {"PatientName": ""})
    assert out["Update_PatientName"].tolist() == [""]


# ---------------------------------------------------------------------------
# update_data_editor
# ---------------------------------------------------------------------------

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

    result = update_data_editor(edit_df, upload_df, update_tags, "PatientID")
    row1 = result[result["PatientID"] == "1"].iloc[0]
    row2 = result[result["PatientID"] == "2"].iloc[0]
    assert row1["Update_PatientName"] == "ANN"
    assert row1["Update_PatientID"] == "99"
    assert row2["Update_PatientName"] == ""


def test_update_data_editor_no_match():
    """Rows with no matching upload entry are left at their default values."""
    edit_df = pd.DataFrame({"PatientID": ["1", "2"], "PatientName": ["Alice", "Bob"]})
    update_tags = {"PatientName": ""}
    edit_df = create_update_cols(edit_df, update_tags)

    upload_df = pd.DataFrame({"PatientID": ["99"], "Update_PatientName": ["X"]})
    result = update_data_editor(edit_df, upload_df, update_tags, "PatientID")
    assert result["Update_PatientName"].tolist() == ["", ""]


# ---------------------------------------------------------------------------
# check_unmatched_rows
# ---------------------------------------------------------------------------

def test_check_unmatched_rows_returns_missing():
    upload_df = pd.DataFrame({"PatientID": ["1"]})
    edit_df = pd.DataFrame({"PatientID": ["1", "2"]})
    result = check_unmatched_rows(upload_df, edit_df, "PatientID")
    assert result == ["2"]


def test_check_unmatched_rows_all_matched():
    upload_df = pd.DataFrame({"PatientID": ["1", "2"]})
    edit_df = pd.DataFrame({"PatientID": ["1", "2"]})
    result = check_unmatched_rows(upload_df, edit_df, "PatientID")
    assert result == []


def test_check_unmatched_rows_all_missing():
    upload_df = pd.DataFrame({"PatientID": ["99"]})
    edit_df = pd.DataFrame({"PatientID": ["1", "2"]})
    result = check_unmatched_rows(upload_df, edit_df, "PatientID")
    assert set(result) == {"1", "2"}


# ---------------------------------------------------------------------------
# validate_upload
# ---------------------------------------------------------------------------

def test_validate_upload_missing_matcher_column():
    """Error when the matcher column is absent from the upload."""
    edit_df = pd.DataFrame({"PatientID": ["1"], "Update_PatientName": [""]})
    upload_df = pd.DataFrame({"SomeOtherCol": ["1"]})
    result = validate_upload(edit_df, upload_df, {"PatientName": ""}, "PatientID")
    assert result is not None
    assert "PatientID" in result


def test_validate_upload_missing_update_col_for_matcher():
    """Error when the matcher is also an update tag but its Update_ column is missing."""
    edit_df = pd.DataFrame({"PatientID": ["1"], "Update_PatientID": [""]})
    upload_df = pd.DataFrame({"PatientID": ["1"]})  # missing Update_PatientID
    result = validate_upload(edit_df, upload_df, {"PatientID": ""}, "PatientID")
    assert result is not None
    assert "Update_PatientID" in result


def test_validate_upload_partial_match_is_allowed():
    """Partial upload (rows missing from CSV) should not be a validation error."""
    edit_df = pd.DataFrame({
        "PatientID": ["1", "2"],
        "Update_PatientName": ["", ""],
    })
    upload_df = pd.DataFrame({"PatientID": ["1"], "Update_PatientName": ["ANN"]})
    result = validate_upload(edit_df, upload_df, {"PatientName": ""}, "PatientID")
    assert result is None


def test_validate_upload_valid_full_match():
    edit_df = pd.DataFrame({
        "PatientID": ["1", "2"],
        "Update_PatientName": ["", ""],
    })
    upload_df = pd.DataFrame({
        "PatientID": ["1", "2"],
        "Update_PatientName": ["ANN", "BOB"],
    })
    result = validate_upload(edit_df, upload_df, {"PatientName": ""}, "PatientID")
    assert result is None


# ---------------------------------------------------------------------------
# highlight_updated_cells
# ---------------------------------------------------------------------------

def test_highlight_updated_cells_applies_yellow():
    """Changed Update_ cells are highlighted yellow."""
    df = pd.DataFrame(
        {"PatientName": ["Alice"], "Update_PatientName": ["ANN"]},
        index=pd.Index(["pk1"]),
    )
    styled = highlight_updated_cells(df, {"PatientName": ""})
    assert "background-color: yellow" in styled.to_html()


def test_highlight_updated_cells_no_highlight_when_unchanged():
    """Update_ cells matching the original value are not highlighted."""
    df = pd.DataFrame(
        {"PatientName": ["Alice"], "Update_PatientName": ["Alice"]},
        index=pd.Index(["pk1"]),
    )
    styled = highlight_updated_cells(df, {"PatientName": ""})
    assert "background-color: yellow" not in styled.to_html()


def test_highlight_updated_cells_no_highlight_when_empty():
    """Empty Update_ cells are not highlighted even when different from original."""
    df = pd.DataFrame(
        {"PatientName": ["Alice"], "Update_PatientName": [""]},
        index=pd.Index(["pk1"]),
    )
    styled = highlight_updated_cells(df, {"PatientName": ""})
    assert "background-color: yellow" not in styled.to_html()


def test_highlight_updated_cells_nonunique_index():
    """Non-unique index returns an unstyled Styler without raising."""
    df = pd.DataFrame(
        {"PatientName": ["Alice", "Bob"], "Update_PatientName": ["ANN", "BOB"]},
        index=pd.Index(["pk1", "pk1"]),
    )
    styled = highlight_updated_cells(df, {"PatientName": ""})
    assert "background-color: yellow" not in styled.to_html()
