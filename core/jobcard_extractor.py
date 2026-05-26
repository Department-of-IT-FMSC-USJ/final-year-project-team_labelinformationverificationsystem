import pdfplumber
import re
import json


def clean_value(value):
    if value is None:
        return None

    value = str(value).strip()

    if value == "":
        return None

    if value.lower() in ["none", "null", "nan", "-"]:
        return None

    return value


def extract_inline_field(line, label, prefix=None):
    """
    Extract value from a line like:
    'RN#: 54867'
    'Factory ID: 36015502'
    'Country Of Origin made in Sri Lanka/...'

    If no value exists, returns None.
    """

    if not line.startswith(label):
        return None

    value = line[len(label):].strip()

    value = clean_value(value)

    if value is None:
        return None

    if prefix:
        value = f"{prefix}{value}"

    return value


def extract_required_fields(pdf_path):

    data = {
        "Brand": None,
        "Silhouette": None,
        "Size/Age Breakdown": [],
        "VSD": None,
        "VSS": None,
        "RN": None,
        "CA": None,
        "Factory ID": None,
        "Date of MFR": None,
        "Country Of Origin": None,
        "Additional Instructions": None,
        "Garment Components & Fibre Contents": None,
        "Care Phrases": [],
        "Pant Length": None
    }

    # ---------------------------
    # Extract Full Text
    # ---------------------------
    with pdfplumber.open(pdf_path) as pdf:

        full_text = ""

        for page in pdf.pages:

            text = page.extract_text()

            if text:
                full_text += text + "\n"

    # ---------------------------
    # Split into clean lines
    # ---------------------------
    lines = [
        line.strip()
        for line in full_text.split("\n")
        if line.strip()
    ]

    # ---------------------------
    # Basic Fields
    # ---------------------------
    for line in lines:

        if line.startswith("Silhouette:"):

            data["Silhouette"] = extract_inline_field(
                line,
                "Silhouette:"
            )

        elif line.startswith("VSD#:"):

            data["VSD"] = extract_inline_field(
                line,
                "VSD#:"
            )

        elif line.startswith("VSS#:"):

            data["VSS"] = extract_inline_field(
                line,
                "VSS#:"
            )

        elif line.startswith("RN#:"):

            data["RN"] = extract_inline_field(
                line,
                "RN#:",
                prefix="RN"
            )

        elif line.startswith("CA#:"):

            data["CA"] = extract_inline_field(
                line,
                "CA#:",
                prefix="CA"
            )

        elif line.startswith("Factory ID:"):

            data["Factory ID"] = extract_inline_field(
                line,
                "Factory ID:",
                prefix="ID"
            )

        elif line.startswith("Date of MFR#:"):

            data["Date of MFR"] = extract_inline_field(
                line,
                "Date of MFR#:"
            )

        elif line.startswith("Country Of Origin"):

            value = line[len("Country Of Origin"):].strip()

            data["Country Of Origin"] = clean_value(value)

        elif line.startswith("Additional Instructions:"):

            data["Additional Instructions"] = extract_inline_field(
                line,
                "Additional Instructions:"
            )

    # ---------------------------
    # Brand Name Extraction
    # ---------------------------
    brand_match = re.search(
        r"WORKS ORDER(?:\s*:)?(?:\s*-\s*COPY)?\s+(.*?)\s+(?:PO\s+to\s+ITL|PO#)",
        full_text,
        re.IGNORECASE | re.DOTALL
    )
    if brand_match:
        data["Brand"] = clean_value(brand_match.group(1).strip())

    # ---------------------------
    # Size/Age Breakdown & Pant Length
    # ---------------------------
    size_block = re.search(
        r"Size/Age Breakdown:(.*?)(?:VSD#|VSS#|RN#|CA#|Factory ID:|Date of MFR#|Country Of Origin|Additional Instructions:)",
        full_text,
        re.DOTALL
    )

    if size_block:
        size_lines = [line.strip() for line in size_block.group(1).split("\n") if line.strip()]
        
        size_pattern = r"\b(?:XXXL|XXS|XS|S|M|L|XL|XXL|3XL)(?:\s*[\/|]\s*[A-Z]{1,4})*\s*[\/|]\s*\d{3}\s*[\/|]\s*\d{2,3}[A-Z]\b"
        
        sizes = []
        pant_lengths = []
        
        for line in size_lines:
            match = re.search(size_pattern, line)
            if match:
                size_str = match.group(0)
                sizes.append(size_str)
                
                # Extract Pant Length: content between size string and trailing quantity
                qty_match = re.search(r"(\d+)\s*$", line)
                if qty_match:
                    qty_start = qty_match.start()
                    size_end = match.end()
                    if qty_start > size_end:
                        middle = line[size_end:qty_start].strip()
                        if middle and middle.lower() not in ["none", "null", "nan", "-"]:
                            pant_lengths.append(middle)
                            
        data["Size/Age Breakdown"] = sizes
        if pant_lengths:
            unique_pant_lengths = list(dict.fromkeys(pant_lengths))
            data["Pant Length"] = " / ".join(unique_pant_lengths)

    # ---------------------------
    # Garment Components & Fibre Contents
    # ---------------------------
    start = full_text.find("Garment Components")
    end = full_text.find("Care Instructions")

    if start != -1 and end != -1:

        block = full_text[start:end]

        block = re.sub(r"Garment Components\s*&?", "", block)
        block = re.sub(r"Fibre Contents:", "", block)

        block = re.sub(
            r"100\s*%\s*\(Total\)",
            "",
            block,
            flags=re.IGNORECASE
        )

        block = block.replace(":", "")

        fibre_lines = [
            line.strip()
            for line in block.split("\n")
            if line.strip()
        ]

        cleaned_block = "\n".join(fibre_lines)

        data["Garment Components & Fibre Contents"] = clean_value(
            cleaned_block
        )

    # ---------------------------
    # Care Phrases Extraction
    # ---------------------------
    care_phrases = []

    # Delimit Care Instructions section to prevent pulling in later fields (e.g. Technical Specifications)
    care_start = full_text.find("Care Instructions")
    if care_start != -1:
        delimiters = [
            "Technical Specifications", 
            "TECHNICAL SPECIFICATIONS",
            "Technical Specification",
            "TECHNICAL SPECIFICATION",
            "General Specification",
            "GENERAL SPECIFICATION",
            "End of Works Order"
        ]
        care_end = -1
        for delim in delimiters:
            idx = full_text.find(delim, care_start)
            if idx != -1:
                if care_end == -1 or idx < care_end:
                    care_end = idx
        
        if care_end == -1:
            care_block = full_text[care_start:]
        else:
            care_block = full_text[care_start:care_end]
    else:
        care_block = full_text

    # Extract everything after each "Care Phrases:"
    # until next "Care Instruction Set" or end of the care block
    matches = re.finditer(
        r"Care Phrases:\s*(.*?)(?=Care Instruction Set \d+:|End of Works Order|$)",
        care_block,
        re.DOTALL
    )

    for match in matches:

        phrase = match.group(1).strip()

        # Clean spaces/newlines
        phrase = re.sub(r"\s+", " ", phrase)

        phrase = clean_value(phrase)

        if phrase:
            care_phrases.append(phrase)

    data["Care Phrases"] = care_phrases

    return data


# ---------------------------
# RUN
# ---------------------------
if __name__ == "__main__":

    pdf_path = "job_card.pdf"

    extracted_data = extract_required_fields(pdf_path)

    print(json.dumps(
        extracted_data,
        indent=4,
        ensure_ascii=False
    ))