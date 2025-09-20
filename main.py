import fitz  # PyMuPDF
import pdfplumber
import io
import os
import subprocess
import json
import re
from typing import Dict, List, Optional, Tuple
from fastapi import FastAPI, UploadFile, File, HTTPException
from pypdf import PdfReader
from datetime import datetime


app = FastAPI(
    title="Advanced PDF Analysis API",
    description="Analyzes metadata, images, and internal structure of PDFs",
    version="1.1.0"
)

DEFAULT_FONTS_BANK_OF_AMERICAN = [
    "AAAAAH+ConnectionsIta_CZEX0AC0",
    "AAAAAB+ITC_Franklin_Gothic_Book_CZEX0080",
    "AAAAAD+HigherStandards_CZEX0660",
    "AAAAAL+ConnectionsBold_CZEX0AA0",
    "AAAAAJ+Connections_Medium_CZEX0A80",
    "AAAAAF+Connections_CZEX0A60"
]


def analyze_image(image_data, quality=95, scale=15):
    """Advanced analysis with ELA using OpenCV."""
    try:
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return {"error": "Unable to load image"}

        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            cv2.imwrite(tmp.name, img, [cv2.IMWRITE_JPEG_QUALITY, quality])
            compressed = cv2.imread(tmp.name)
            os.unlink(tmp.name)

        if compressed is None:
            return {"error": "Error recompressing image"}

        diff = cv2.absdiff(img, compressed)
        ela = np.uint8(diff * scale)
        ela_gray = cv2.cvtColor(ela, cv2.COLOR_BGR2GRAY)
        std_dev = float(np.std(ela_gray))
        '''Adjustment for 20'''
        possible_manipulation = bool(std_dev > 20) 

        return {
            "image_stats": {
                "ela_std_dev": std_dev,
                "ela_shape": list(ela.shape),
                "format": "JPEG"
            },
            "possible_manipulation": possible_manipulation,
            "manipulation_note": "High deviation in ELA indicates editing" if possible_manipulation else "Uniform ELA"
        }
    except Exception as e:
        return {"error": f"Error in ELA analysis: {str(e)}"}


def extract_metadata(metadata):
    """Extract metadata"""
    try:

        creation_date = metadata.get("creationDate", 'Unknown')
        mod_date = metadata.get("modDate", 'Unknown')
        producer = metadata.get("producer", 'Unknown') 
        creator = metadata.get("creator", 'Unknown')
        author = metadata.get("author", 'Unknown')
        # revisions = len(reader.trailer.get("/Root", {}).get("/VersionHistory", []))

        edited_by_dates = mod_date != creation_date and mod_date != "Unknown"
        edit_softwares = ["Acrobat", "Photoshop", "Word", "GIMP", "Illustrator"]
        edited_by_software = any(software.lower() in str(producer + creator).lower() for software in edit_softwares)

        return {
            "metadata": {
                "creation_date": creation_date,
                "modification_date": mod_date,
                "producer": producer,
                "creator": creator,
                "author": author
            },
            "analysis_editions": {
                "edited_by_dates": edited_by_dates,
                "edited_by_software": edited_by_software
            }
        }
    except Exception as e:
        return {"error": f"Error running ExifTool: {str(e)}"}


def format_pdf_date(pdf_date: str) -> str:
    """
    Converts a date in PDF format (e.g. D:20250731144353-05'00) to YYYY-MM-DD HH:MM:SS.
    """
    try:
        if pdf_date.startswith("D:"):
            '''Remove the prefix "D:"'''
            pdf_date = pdf_date[2:] 
        
        date_obj = datetime.strptime(pdf_date[:14], "%Y%m%d%H%M%S")
        formatted_date = date_obj.strftime("%Y-%m-%d %H:%M:%S")
        timezone = pdf_date[14:] if len(pdf_date) > 14 else ""
        timezone_replaced = timezone.replace("'", ":")
        return f"{formatted_date}{timezone_replaced}" if timezone else formatted_date
    except ValueError:
        '''Returns original if cannot format'''
        return pdf_date  


def parse_pdf_low_level(pdf_path):
    """Use pdfplumber to inspect internal structure and identify suspicious font positions."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            fonts = set()
            suspicious_regions = []
            for page_num, page in enumerate(pdf.pages, 1):
                if page.chars:
                    for char in page.chars:
                        font = char.get("fontname", "unknown")
                        fonts.add(font)
                        if font not in DEFAULT_FONTS_BANK_OF_AMERICAN:
                            bbox = (
                                char.get("x0", 0),
                                char.get("top", 0),
                                char.get("x1", 0),
                                char.get("bottom", 0)
                            )
                            suspicious_regions.append({
                                "page": page_num,
                                "fontname": font,
                                "bbox": bbox,  '''(x0, top, x1, bottom) - coordinates in PDF'''
                                "text": char.get("text", ""),
                                "width": char.get("width", 0),
                                "height": char.get("height", 0)
                            })
            
            revisions = len(pdf.metadata.get("XMP:VersionHistory", [])) if pdf.metadata else 0
            suspicious_objects = any(
                obj.get("type") in ["/JavaScript", "/OpenAction"]
                for page in pdf.pages
                for obj in page.objects.get("xobject", {}).values()
            )

            num_suspicious_chars = len(suspicious_regions)

            return {
                "revisions": revisions,
                "font_count": len(fonts),
                "fonts_used": list(fonts),
                "suspicious_regions": suspicious_regions,
                "suspicious_objects": bool(suspicious_objects),
                "note": (
                    f"{len(fonts)} fonts detected; multiple fonts may indicate manipulation."
                    f"Found {num_suspicious_chars} occurrences of suspicious fonts at specific positions."
                    f"{'Suspicious objects found' if suspicious_regions or bool(suspicious_objects) else 'No suspicious objects'}."
                )
            }
    except Exception as e:
        return {"error": f"Error running pdfplumber: {str(e)}"}


def highlight_suspicious_fonts(pdf_path, suspicious_regions, output_path="pdf_analysed.pdf"):
    """Creates a copy of the PDF with highlights in the suspicious regions."""
    doc = fitz.open(pdf_path)

    for region in suspicious_regions:
        page_num = region["page"] - 1 
        bbox = fitz.Rect(region["bbox"])
        if bbox.is_valid:  
            page = doc[page_num]
            page.add_highlight_annot(bbox) 

    doc.save(output_path)
    doc.close()
    print(f"PDF with highlights saved in: {output_path}")


def extract_account_number(full_text: str) -> str | None:
    """
    Search for an account number in a bank statement text.

    The function searches for the patterns "Account number:" or "Account #" and captures
    the number that follows them.

    Args:
        full_text: A string containing the entire extract.

    Returns:
        The account number as a string, or None if not found.
    """    
    default_account = re.compile(r"Account (?:number:|#)\s*([\d\s]+)")
    match = default_account.search(full_text)

    if match:
        account_number = match.group(1).strip()
        return account_number    
    return None


def structure_extract_in_json(full_text: str) -> str:
    """
    Extracts information from a bank statement, makes the cardholder name dynamic
    and structures the result into a formatted JSON string.

    Args:
        full_text: A string containing the entire bank statement.

    Returns:
        A JSON-formatted string with the extracted data, or an error message.
    """
    structured_data = {}
    default_name = re.search(r"^([A-Z\s]+)\nAccount summary", full_text, re.MULTILINE)
    
    if default_name:
        structured_data["account_holder"] = default_name.group(1).strip()
    else:
        structured_data["account_holder"] = "Name not found"


    def find_value(default, text, negative=False):
        match = re.search(default, text)
        if match:
            value_str = match.group(1).replace(',', '')
            value_float = float(value_str)
            return -value_float if negative else value_float
        return 0.00

    account_summary = {
        "account_number": extract_account_number(full_text), 
        "initial_balance": find_value(r"Beginning balance on .*? \$([\d,]+\.\d{2})", full_text),
        "deposits_additions": find_value(r"Deposits and other (?:additions|credits)\s+([\d,]+\.\d{2})", full_text),
        "card_withdrawals": find_value(r"ATM and debit card subtractions\s+-([\d,]+\.\d{2})", full_text, negative=True),
        "other_withdrawals": find_value(r"Other subtractions\s+-([\d,]+\.\d{2})", full_text, negative=True) or find_value(r"Withdrawals and other debits\s+-([\d,]+\.\d{2})", full_text, negative=True),
        "service_fees": find_value(r"Service fees\s+-([\d,]+\.\d{2})", full_text, negative=True),
        "final_balance": find_value(r"Ending balance on .*? \$([\d,]+\.\d{2})", full_text)
    }
    structured_data["account_summary"] = account_summary

    total_transactions = {
        "total_deposits_additions": find_value(r"Total deposits and other (?:additions|credits)\s+\$([\d,]+\.\d{2})", full_text),
        "total_card_withdrawals": find_value(r"Total ATM and debit card subtractions\s+-\$([\d,]+\.\d{2})", full_text, negative=True),
        "total_other_withdrawals": find_value(r"Total (?:other subtractions|withdrawals and other debits)\s+-\$([\d,]+\.\d{2})", full_text, negative=True)
    }
    structured_data["total_transactions"] = total_transactions

    default = re.compile(r"^(\d{2}/\d{2}/\d{2})\s+.*?\s+(-?[\d,]+\.\d{2})$", re.MULTILINE)
    matches = default.findall(full_text)

    transactions_list = []
    for date, value_str in matches:
        
        value_float = float(value_str.replace(',', ''))
        
        transactions_list.append({
            "date": date,
            "value": value_float
        })

    structured_data["transactions"] = transactions_list
    return structured_data


def extract_bank_statement(pdf_path: str, DEFAULT_FONTS_BANK_OF_AMERICAN: set = None, bank_type: str = "BofA") -> Dict:
    """
    Extracts key information from a PDF bank statement (focus on Bank of America Business Advantage).
    
    Args:
        pdf_path (str): Path to PDF file.
        DEFAULT_FONTS_BANK_OF_AMERICAN (set, optional): Standard font set for anti-fraud validation.
        bank_type (str): Bank type ('BofA' para Bank of America).
    
    Returns:
        Dict: Dictionary with extractions: client_name, transactions, balances, suspicious_info.
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            
            for page in pdf.pages:
                full_text += page.extract_text() or ""
            
            result = structure_extract_in_json(full_text)
            return result
    
    except Exception as e:
        return {"error": f"Error processing PDF: {str(e)}"}


@app.post("/analyze-pdf")
async def analyze_pdf(files: List[UploadFile] = File(...)):
    final_result = []
    for file in files:
        """Analyzes metadata, images and internal structure of PDFs."""
        if not file.filename.endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported.")

        temp_file_path = "temp.pdf"
        try:
            content = await file.read()

            with open(temp_file_path, "wb") as temp_file:
                temp_file.write(content)

            pdf = fitz.open(stream=content, filetype="pdf")
            metadata_orig = pdf.metadata
            pdf.close()

            metadata_extracted = extract_metadata(metadata_orig)            
            creation_date = format_pdf_date(metadata_orig.get("creationDate"))
            mod_date = format_pdf_date(metadata_orig.get("modDate"))
            producer = metadata_orig.get("producer") 
            creator = metadata_orig.get("creator")
            author = metadata_orig.get("author")
    

            image_analysis = []
            doc = fitz.open(stream=content, filetype="pdf")
            for page_num in range(len(doc)):
                page = doc[page_num]
                images = page.get_images(full=True)
                for img_index, img in enumerate(images):
                    xref = img[0]
                    base_image = doc.extract_image(xref)
                    image_data = base_image["image"]
                    image_result = analyze_image(image_data)
                    image_analysis.append({
                        "page": page_num + 1,
                        "image_index": img_index,
                        "analysis": image_result
                    })

            doc.close()

            low_level_analysis = parse_pdf_low_level(temp_file_path)

            analysed_file_name = f"analyzed_{file.filename}"
            highlight_suspicious_fonts(
                pdf_path=temp_file_path, 
                suspicious_regions=low_level_analysis.get('suspicious_regions'), 
                output_path=analysed_file_name
            )

            result = extract_bank_statement(temp_file_path)

            possible_edits = {
                "edited_by_dates": metadata_extracted["analysis_editions"]["edited_by_dates"],
                "edited_by_software": metadata_extracted["analysis_editions"]["edited_by_software"],
                "image_analysis_summary": any(img["analysis"].get("possible_manipulation", False) for img in image_analysis),
                "low_level_analysis_summary": low_level_analysis.get("suspicious_objects", False),
                "summary": "Possible edit detected" if (
                    metadata_extracted["analysis_editions"]["edited_by_dates"] or
                    metadata_extracted["analysis_editions"]["edited_by_software"] or
                    any(img["analysis"].get("possible_manipulation", False) for img in image_analysis) or
                    sorted(DEFAULT_FONTS_BANK_OF_AMERICAN) != sorted(low_level_analysis.get("fontes_used", []))
                ) else "No obvious edits detected."
            }
            
            final_result.append({
                "metadata": {
                    "file_name": file.filename,
                    "analysed_file_name": analysed_file_name,
                    "creation_date": creation_date,
                    "modification_date": mod_date,
                    "producer": producer,
                    "creator": creator,
                    "author": author
                },
                "low_level_analysis": low_level_analysis,
                "analysis_editions": possible_edits,
                "bank_result": result,
                "image_analysis": image_analysis
            })

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error processing PDF: {str(e)}")
        finally:
            if os.path.exists(temp_file_path):
               os.remove(temp_file_path)
    
    return final_result