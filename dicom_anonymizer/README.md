# DICOM Anonymizer Application

## Description
A Streamlit application for anonymizing DICOM files with an interactive user interface.

## Version
**Current Version**: 1.0.0

## Requirements

- Python=3.10
- Streamlit=1.29
- PyInstaller=5.10
- Pandas=2.2.3
- pydicom=3.0.1

## Usage
1. Run the application using executable (only support Windows): 
   Open `./dist/DicomAnonymizer.exe` and the application will be opened in your browser automatically. 

2. Run the application using terminal: 
   `streamlit run user_interface.py`
   Open the link provided in your terminal to access the application.

## Features
- User-Friendly Interface: Provides an intuitive web interface built with Streamlit for easy interaction and input management.
- Folder and File Format Input: Allows users to specify the directory containing DICOM files and the desired file format for processing.
- File Fetching: Fetches and displays unique identifiers from DICOM files in the specified directory, helping users quickly identify the cases available for anonymization.
- Data Editing: Users can upload a CSV or Excel file containing patient identifiers to update existing DICOM metadata, ensuring the correct anonymization process.
- Real-Time Data Validation: Checks the uploaded files for necessary columns (PatientID and Update_PatientID) and provides user feedback if any required data is missing.
- Downloadable Template: Offers a downloadable CSV template containing unique identifiers, allowing users to easily prepare their data for input.
- Anonymization Process: Anonymizes DICOM files by updating patient information based on user inputs, ensuring compliance with privacy standards.
- Output Management: Saves the anonymized files in a specified directory, clearly indicating where the processed files are stored.

## Contact
For questions, please contact admin.