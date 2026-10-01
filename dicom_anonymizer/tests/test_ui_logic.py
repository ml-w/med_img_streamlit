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
    add_series_dir,
    dedup_display_rows,
    safe_path_component,
    plan_output_paths,
    count_nameless_series,
    NAMELESS_DIR,
)


# ---------------------------------------------------------------------------
# add_series_dir
# ---------------------------------------------------------------------------

def test_add_series_dir_nested(tmp_path):
    """A nested series folder becomes its path relative to the root, forward-slashed."""
    series_dir = tmp_path / "Pt001" / "Study1" / "SE3"
    df = pd.DataFrame({"folder_dir": [str(series_dir)]})
    out = add_series_dir(df, str(tmp_path))
    assert out["SeriesDir"].tolist() == ["Pt001/Study1/SE3"]


def test_add_series_dir_file_directly_in_root(tmp_path):
    """A file sitting directly in the scanned root gets '.'."""
    df = pd.DataFrame({"folder_dir": [str(tmp_path)]})
    out = add_series_dir(df, str(tmp_path))
    assert out["SeriesDir"].tolist() == ["."]


def test_add_series_dir_no_folder_dir_column_is_noop():
    """Without a folder_dir column, the DataFrame is returned unchanged."""
    df = pd.DataFrame({"PatientID": ["1"]})
    out = add_series_dir(df, "/some/root")
    assert "SeriesDir" not in out.columns


# ---------------------------------------------------------------------------
# dedup_display_rows
# ---------------------------------------------------------------------------

def test_dedup_display_rows_aggregates_series_dir_for_coarse_pk():
    """A PK spanning two series directories collapses to one row with values joined."""
    df = pd.DataFrame(
        {"PatientID": ["1", "1"], "SeriesDir": ["a/b", "c/d"]},
        index=pd.Index(["PK1", "PK1"], name="PK"),
    )
    out = dedup_display_rows(df, agg_col="SeriesDir")
    assert len(out) == 1
    assert out.loc["PK1", "SeriesDir"] == "a/b; c/d"


def test_dedup_display_rows_single_dir_pk_gives_single_value():
    """A PK backed by a single directory keeps just that one value."""
    df = pd.DataFrame(
        {"SeriesDir": ["a/b"]},
        index=pd.Index(["PK1"], name="PK"),
    )
    out = dedup_display_rows(df, agg_col="SeriesDir")
    assert out.loc["PK1", "SeriesDir"] == "a/b"


def test_dedup_display_rows_dedupes_repeated_identical_values():
    """Repeated identical SeriesDir values within one PK are not duplicated in the join."""
    df = pd.DataFrame(
        {"SeriesDir": ["a/b", "a/b"]},
        index=pd.Index(["PK1", "PK1"], name="PK"),
    )
    out = dedup_display_rows(df, agg_col="SeriesDir")
    assert out.loc["PK1", "SeriesDir"] == "a/b"


def test_dedup_display_rows_without_agg_col_keeps_first_row_behaviour():
    """When agg_col isn't present, dedup falls back to first-row-wins, like before."""
    df = pd.DataFrame(
        {"PatientName": ["Alice", "Bob"]},
        index=pd.Index(["PK1", "PK1"], name="PK"),
    )
    out = dedup_display_rows(df, agg_col="SeriesDir")
    assert len(out) == 1
    assert out.loc["PK1", "PatientName"] == "Alice"


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


def test_update_data_editor_ignores_extra_series_dir_column():
    """An uploaded CSV carrying the display-only SeriesDir column still validates
    and merges Update_* values normally — SeriesDir is never read by these helpers."""
    edit_df = pd.DataFrame({
        "PatientID": ["1", "2"],
        "SeriesDir": ["a/b", "c/d"],
    })
    update_tags = {"PatientName": ""}
    edit_df = create_update_cols(edit_df, update_tags)

    upload_df = pd.DataFrame({
        "PatientID": ["1"],
        "SeriesDir": ["a/b"],
        "Update_PatientName": ["ANN"],
    })

    error = validate_upload(edit_df, upload_df, update_tags, "PatientID")
    assert error is None

    result = update_data_editor(edit_df, upload_df, update_tags, "PatientID")
    row1 = result[result["PatientID"] == "1"].iloc[0]
    assert row1["Update_PatientName"] == "ANN"
    assert row1["SeriesDir"] == "a/b"  # untouched display-only column


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


# ---------------------------------------------------------------------------
# safe_path_component
# ---------------------------------------------------------------------------

def test_safe_path_component_person_name_caret():
    assert safe_path_component("Doe^John") == "Doe_John"


def test_safe_path_component_slashes_and_backslashes():
    assert safe_path_component("a/b\\c") == "a_b_c"


def test_safe_path_component_empty_string():
    assert safe_path_component("") == ""


def test_safe_path_component_none():
    assert safe_path_component(None) == ""


def test_safe_path_component_nan():
    assert safe_path_component(float("nan")) == ""


def test_safe_path_component_unicode_name_survives():
    """Non-ASCII names must survive -- unicode \\w matches them."""
    assert safe_path_component("陈大文") == "陈大文"


def test_safe_path_component_strips_leading_trailing_dot_and_underscore():
    assert safe_path_component("__weird..name__") == "weird..name"


def test_safe_path_component_caps_at_100_chars():
    result = safe_path_component("a" * 150)
    assert result == "a" * 100


def test_safe_path_component_reserved_chars_collapsed_to_single_underscore():
    assert safe_path_component('a:b*c?d"e<f>g|h') == "a_b_c_d_e_f_g_h"


# ---------------------------------------------------------------------------
# plan_output_paths -- mirror layout
# ---------------------------------------------------------------------------

def test_plan_output_paths_mirror_matches_old_formula():
    df = pd.DataFrame(
        {
            "output_dir": ["/out/Pt1/SE1", "/out/Pt2/SE1"],
            "file_path": ["/in/Pt1/SE1/a.dcm", "/in/Pt2/SE1/b.dcm"],
            "folder_dir": ["/in/Pt1/SE1", "/in/Pt2/SE1"],
        },
        index=pd.Index(["PK1", "PK2"], name="PK"),
    )
    out = plan_output_paths(df, layout="mirror", base_output="/out")
    assert out["target_path"].tolist() == [
        "/out/Pt1/SE1/a.dcm",
        "/out/Pt2/SE1/b.dcm",
    ]


def test_plan_output_paths_series_key_uses_series_instance_uid_or_folder_dir():
    df = pd.DataFrame(
        {
            "output_dir": ["/out/s1", "/out/s2"],
            "file_path": ["/in/a1.dcm", "/in/b1.dcm"],
            "folder_dir": ["/in/s1", "/in/s2"],
            "SeriesInstanceUID": ["uid1", None],
        }
    )
    out = plan_output_paths(df, layout="mirror", base_output="/out")
    assert out["series_key"].tolist() == ["uid1", "/in/s2"]


def test_plan_output_paths_does_not_mutate_input_and_preserves_index():
    df = pd.DataFrame(
        {
            "output_dir": ["/out/s1"],
            "file_path": ["/in/a1.dcm"],
            "folder_dir": ["/in/s1"],
        },
        index=pd.Index(["PK1"], name="PK"),
    )
    original_columns = list(df.columns)
    out = plan_output_paths(df, layout="mirror", base_output="/out")
    assert list(df.columns) == original_columns
    assert "series_key" not in df.columns
    assert "target_path" not in df.columns
    assert list(out.index) == ["PK1"]
    assert "series_key" in out.columns
    assert "target_path" in out.columns


# ---------------------------------------------------------------------------
# plan_output_paths -- by_tag layout
# ---------------------------------------------------------------------------

def test_plan_output_paths_by_tag_series_numbering_within_shared_folder():
    """Two distinct series sharing the same (sanitized) tag value get
    series_001/series_002 under the same top-level folder."""
    df = pd.DataFrame(
        {
            "file_path": ["/in/a1.dcm", "/in/b1.dcm"],
            "folder_dir": ["/in/s1", "/in/s2"],
            "output_dir": ["/out/s1", "/out/s2"],
            "SeriesInstanceUID": ["uid1", "uid2"],
            "Update_PatientID": ["Doe^01", "Doe^01"],
            "PatientID": ["orig1", "orig2"],
        }
    )
    out = plan_output_paths(df, layout="by_tag", base_output="/out", subfolder_tag="PatientID")
    assert out["target_path"].tolist() == [
        "/out/Doe_01/series_001/a1.dcm",
        "/out/Doe_01/series_002/b1.dcm",
    ]


def test_plan_output_paths_by_tag_falls_back_to_original_value():
    df = pd.DataFrame(
        {
            "file_path": ["/in/a1.dcm"],
            "folder_dir": ["/in/s1"],
            "output_dir": ["/out/s1"],
            "SeriesInstanceUID": ["uid1"],
            "Update_PatientID": [""],
            "PatientID": ["orig1"],
        }
    )
    out = plan_output_paths(df, layout="by_tag", base_output="/out", subfolder_tag="PatientID")
    assert out["target_path"].tolist() == ["/out/orig1/series_001/a1.dcm"]


def test_plan_output_paths_by_tag_unknown_fallback():
    df = pd.DataFrame(
        {
            "file_path": ["/in/a1.dcm"],
            "folder_dir": ["/in/s1"],
            "output_dir": ["/out/s1"],
            "SeriesInstanceUID": ["uid1"],
            "Update_PatientID": [""],
            "PatientID": [""],
        }
    )
    out = plan_output_paths(df, layout="by_tag", base_output="/out", subfolder_tag="PatientID")
    assert out["target_path"].tolist() == ["/out/Unknown/series_001/a1.dcm"]


# ---------------------------------------------------------------------------
# plan_output_paths -- per_series layout
# ---------------------------------------------------------------------------

def test_plan_output_paths_per_series_unique_names():
    df = pd.DataFrame(
        {
            "file_path": ["/in/a1.dcm", "/in/b1.dcm"],
            "folder_dir": ["/in/s1", "/in/s2"],
            "SeriesInstanceUID": ["uid1", "uid2"],
            "Update_PatientID": ["P001", "P002"],
            "SeriesDescription": ["Desc1", "Desc2"],
        }
    )
    out = plan_output_paths(df, layout="per_series", base_output="/out", series_name_tag="PatientID")
    assert out["target_path"].tolist() == [
        "/out/P001/a1.dcm",
        "/out/P002/b1.dcm",
    ]


def test_plan_output_paths_per_series_clash_distinct_descriptions():
    df = pd.DataFrame(
        {
            "file_path": ["/in/a1.dcm", "/in/b1.dcm"],
            "folder_dir": ["/in/s1", "/in/s2"],
            "SeriesInstanceUID": ["uid1", "uid2"],
            "Update_PatientID": ["P001", "P001"],
            "SeriesDescription": ["T1", "T2"],
        }
    )
    out = plan_output_paths(df, layout="per_series", base_output="/out", series_name_tag="PatientID")
    assert out["target_path"].tolist() == [
        "/out/P001/T1/a1.dcm",
        "/out/P001/T2/b1.dcm",
    ]


def test_plan_output_paths_per_series_clash_missing_description_goes_direct():
    """A clashing series with no (or empty) SeriesDescription is placed
    directly in the shared name folder instead of a description subfolder."""
    df = pd.DataFrame(
        {
            "file_path": ["/in/a1.dcm", "/in/b1.dcm"],
            "folder_dir": ["/in/s1", "/in/s2"],
            "SeriesInstanceUID": ["uid1", "uid2"],
            "Update_PatientID": ["P001", "P001"],
            "SeriesDescription": ["T1", ""],
        }
    )
    out = plan_output_paths(df, layout="per_series", base_output="/out", series_name_tag="PatientID")
    assert out["target_path"].tolist() == [
        "/out/P001/T1/a1.dcm",
        "/out/P001/b1.dcm",
    ]


def test_plan_output_paths_per_series_missing_update_value_goes_nameless():
    df = pd.DataFrame(
        {
            "file_path": ["/in/a1.dcm"],
            "folder_dir": ["/in/s1"],
            "SeriesInstanceUID": ["uid1"],
            "PatientID": ["orig1"],  # no Update_PatientID column at all
        }
    )
    out = plan_output_paths(df, layout="per_series", base_output="/out", series_name_tag="PatientID")
    assert out["target_path"].tolist() == [f"/out/{NAMELESS_DIR}/a1.dcm"]


def test_plan_output_paths_per_series_nameless_clash_gets_description_subfolder():
    df = pd.DataFrame(
        {
            "file_path": ["/in/a1.dcm", "/in/b1.dcm"],
            "folder_dir": ["/in/s1", "/in/s2"],
            "SeriesInstanceUID": ["uid1", "uid2"],
            "Update_PatientID": ["", ""],
            "SeriesDescription": ["T1", "T2"],
        }
    )
    out = plan_output_paths(df, layout="per_series", base_output="/out", series_name_tag="PatientID")
    assert out["target_path"].tolist() == [
        f"/out/{NAMELESS_DIR}/T1/a1.dcm",
        f"/out/{NAMELESS_DIR}/T2/b1.dcm",
    ]


def test_plan_output_paths_per_series_series_instance_uid_option():
    df = pd.DataFrame(
        {
            "file_path": ["/in/a1.dcm"],
            "folder_dir": ["/in/s1"],
            "SeriesInstanceUID": ["uid.1.2.3"],
        }
    )
    out = plan_output_paths(df, layout="per_series", base_output="/out", series_name_tag="SeriesInstanceUID")
    assert out["target_path"].tolist() == ["/out/uid.1.2.3/a1.dcm"]


def test_plan_output_paths_per_series_patient_name_never_uses_original():
    """PatientName folder naming must only ever look at Update_PatientName --
    never the original (PII) PatientName column, even when present."""
    df = pd.DataFrame(
        {
            "file_path": ["/in/a1.dcm"],
            "folder_dir": ["/in/s1"],
            "SeriesInstanceUID": ["uid1"],
            "PatientName": ["Doe^John"],
        }
    )
    out = plan_output_paths(df, layout="per_series", base_output="/out", series_name_tag="PatientName")
    assert out["target_path"].tolist() == [f"/out/{NAMELESS_DIR}/a1.dcm"]


def test_plan_output_paths_filename_collision_renaming():
    """Two clashing series with no SeriesDescription both land directly in the
    same name folder with the same original filename -- the second must be
    renamed for uniqueness."""
    df = pd.DataFrame(
        {
            "file_path": ["/in/s1/img.dcm", "/in/s2/img.dcm"],
            "folder_dir": ["/in/s1", "/in/s2"],
            "SeriesInstanceUID": ["uid1", "uid2"],
            "Update_PatientID": ["P001", "P001"],
            "SeriesDescription": ["", ""],
        }
    )
    out = plan_output_paths(df, layout="per_series", base_output="/out", series_name_tag="PatientID")
    assert out["target_path"].tolist() == [
        "/out/P001/img.dcm",
        "/out/P001/img_1.dcm",
    ]


# ---------------------------------------------------------------------------
# count_nameless_series
# ---------------------------------------------------------------------------

def test_count_nameless_series_counts_distinct_series():
    df = pd.DataFrame(
        {
            "file_path": ["/in/a1.dcm", "/in/a2.dcm", "/in/b1.dcm"],
            "folder_dir": ["/in/s1", "/in/s1", "/in/s2"],
            "SeriesInstanceUID": ["uid1", "uid1", "uid2"],
            # no Update_PatientID -> both series go to Nameless
        }
    )
    out = plan_output_paths(df, layout="per_series", base_output="/out", series_name_tag="PatientID")
    assert count_nameless_series(out, "/out") == 2


def test_count_nameless_series_zero_when_no_clash():
    df = pd.DataFrame(
        {
            "file_path": ["/in/a1.dcm"],
            "folder_dir": ["/in/s1"],
            "SeriesInstanceUID": ["uid1"],
            "Update_PatientID": ["P001"],
        }
    )
    out = plan_output_paths(df, layout="per_series", base_output="/out", series_name_tag="PatientID")
    assert count_nameless_series(out, "/out") == 0
