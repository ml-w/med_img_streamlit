# DICOM X-Ray Anonymizer

## Usage

There are two steps to use this simple DICOM anonymizer cli. First to generate the csv template for changing the tags. 
Second to apply the changes to the DICOM files. 

### Generate csv

```bash
python anonymizer_rename.py generate --input-dir [directory] --template-csv [csv_file_name] --verbose --num-workers 8
```
After the CSV is generate, make necessary changes. Leave field you prefer to be unchanged alone or delete the column. 
Remove the rows to exclude the series from anonymization. Each series will be put in a directory named after the PID.
More than one series can be sorted into the same folder if therea are duplicated PIDs. 

### Apply csv

```bash
python anonymizer_renmae.py apply --input-dir [directory] --modified-csv [csv_file_name] --output-dir [output_directory]
  --verbose --num-workers 8
```

## Error Handling

The script handles common errors gracefully:

- **Invalid DICOM files**: Logged as warnings, processing continues
- **Missing metadata**: Missing tags are stored as `None`
- **File I/O errors**: Logged with detailed error messages
- **Missing directories**: Input directory validation before processing

## Limitations

- Only processes files with `.dcm` extension
- Requires `SeriesInstanceUID` for series-based grouping
- Maximum 86 series per patient before switching to `_scanN` suffix format
- Does not anonymize other patient identifiers besides `AccessionNumber`

## Related Projects

This script is part of the `med_img_streamlit` repository, which also includes:
- [dicom_anonymizer](../dicom_anonymizer/) - Interactive Streamlit web application for DICOM anonymization
- [segmentation_checker](../segmentation_checker/) - MRI segmentation visualization tool

## License

Part of the medical imaging Streamlit applications repository.
