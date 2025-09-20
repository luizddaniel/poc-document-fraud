# Advanced PDF Analysis API

## Overview

This project is a powerful **FastAPI-based web service** designed to perform a deep forensic analysis of PDF files. It's particularly tailored to detect potential signs of manipulation in documents like Bank of America statements.

The API inspects multiple layers of a PDF, including its metadata, internal structure, font usage, and embedded images. It then aggregates these findings into a comprehensive JSON report, which includes a summary of potential edits and an extraction of key financial data from the statement. As a final output, it generates a new PDF with suspicious text regions highlighted for easy visual inspection.

---

## Key Features 🕵️‍♀️

* **Metadata Analysis**: Uses **PyMuPDF** to extract detailed metadata, comparing creation and modification dates to flag potential edits.
* **Image Forensics**: Performs **Error Level Analysis (ELA)** on embedded images to detect manipulations that might not be visible to the naked eye.
* **Low-Level Structural Inspection**: Leverages `pdfplumber` to analyze the PDF's internal objects, identifying non-standard fonts and suspicious JavaScript or action triggers.
* **Data Extraction**: Intelligently parses text to extract structured financial data from Bank of America statements, such as account holder name, balances, and transaction lists.
* **Visual Highlighting**: Generates a copy of the analyzed PDF (`analyzed_<filename>.pdf`) with rectangles drawn around text that uses non-standard fonts, making it easy to spot potential alterations.
* **Comprehensive Reporting**: Outputs a detailed JSON object containing all analysis results, including a final summary of whether edits are likely.

---

## How to Run the Application

Follow these steps to get the API up and running on your local machine.

### 1. Prerequisites

Before you begin, ensure you have the following installed on your system:

* **Python 3.10+**

### 2. Setup and Installation

**Clone the repository (or save the code)**

First, save the Python code into a file named `main.py`.

**Create a Virtual Environment**

It's highly recommended to use a virtual environment to manage dependencies.

```bash
# Create the virtual environment
python -m venv venv

# Activate it
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
```

### 3. Install the dependencies:
```bash
pip install -r requirements.txt
```

### 4. Run the server
```bash
uvicorn main:app --reload
```
The service will be available in `http://127.0.0.1:8000`.

The API docs will be available in `http://127.0.0.1:8000/docs`.