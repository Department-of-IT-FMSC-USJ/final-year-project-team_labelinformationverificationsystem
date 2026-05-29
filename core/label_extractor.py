import requests
import unicodedata
import time
# pyrefly: ignore [missing-import]
from PIL import Image
import io
import os
# pyrefly: ignore [missing-import]
import fitz
import cv2
import numpy as np
import re

# ============================
# CONFIG
# ============================

import os
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

load_dotenv()  # read .env in project root

API_KEY = os.getenv("OCR_SPACE_API_KEY")
if not API_KEY:
    raise RuntimeError("OCR_SPACE_API_KEY not set in environment")

OCR_URL = "https://api.ocr.space/parse/image"

MAX_WIDTH = 1500
RETRY_COUNT = 3
DELAY_BETWEEN_IMAGES = 2


# ============================
# IMAGE RESIZE (Prevents Timeout)
# ============================

def resize_image_if_needed(image_path, max_width=MAX_WIDTH):
    img = Image.open(image_path)

    if img.width > max_width:
        ratio = max_width / float(img.width)
        new_height = int(img.height * ratio)
        img = img.resize((max_width, new_height), Image.LANCZOS)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


# ============================
# OCR WITH RETRY
# ============================

def extract_text_from_image(image_path, retries=RETRY_COUNT):

    for attempt in range(retries):
        try:
            image_buffer = resize_image_if_needed(image_path)

            files = {
                "file": ("image.png", image_buffer, "image/png")
            }

            response = requests.post(
                OCR_URL,
                files=files,
                data={
                    "apikey": API_KEY,
                    "language": "eng",
                    "isOverlayRequired": False,
                    "OCREngine": 3
                },
                timeout=30
            )

            result = response.json()

            if result.get("IsErroredOnProcessing"):
                error = result.get("ErrorMessage", "")
                print(f"API Error: {error}")

                if "Timed out" in str(error):
                    print(f"Retrying... ({attempt+1}/{retries})")
                    time.sleep(3)
                    continue
                else:
                    return None

            return result["ParsedResults"][0]["ParsedText"]

        except Exception as e:
            print("Request failed:", e)
            time.sleep(3)

    return None


# ============================
# TEXT NORMALIZATION (Optional)
# ============================

def normalize_text(text):
    text = unicodedata.normalize("NFKC", text)
    return text.strip()


# ============================
# PROCESS SINGLE LABEL
# ============================

def extract_label_data(image_path):

    print(f"\n🔹 Processing: {image_path}")

    raw_text = extract_text_from_image(image_path)

    if not raw_text:
        print("❌ No text extracted.")
        return None

    cleaned_text = normalize_text(raw_text)

    print("   ✅ Text extracted")

    return {
        "raw_text": cleaned_text
    }


# ============================
# EXTRACT CARE CODE FROM LABEL PDF
# ============================

def extract_care_code_from_pdf(pdf_path):
    """
    Renders the top 25% of the first page of the label PDF,
    saves it to a temp file, runs OCR on it, and extracts the care code.
    """
    print(f"\n[INFO] Extracting Care Code from: {pdf_path}")
    try:
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            print("[ERROR] Empty PDF document.")
            return None
        page = doc[0]
        pix = page.get_pixmap(dpi=300)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR) if pix.n == 4 else cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        
        h, w = img.shape[:2]
        crop_h = int(h * 0.25)
        cropped = img[0:crop_h, 0:w]
        
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_img:
            temp_img_path = temp_img.name
        
        try:
            cv2.imwrite(temp_img_path, cropped)
            ocr_text = extract_text_from_image(temp_img_path)
            if ocr_text:
                match = re.search(r"CARE\s*CODE\s*:\s*([A-Za-z0-9]+)", ocr_text, re.IGNORECASE)
                if match:
                    code = match.group(1).strip()
                    print(f"   [SUCCESS] Care Code extracted: {code}")
                    return code
                else:
                    print("   [WARN] No Care Code found in top header OCR text.")
            else:
                print("   [ERROR] OCR on top header returned empty text.")
        finally:
            try:
                os.unlink(temp_img_path)
            except:
                pass
    except Exception as e:
        print(f"[ERROR] Error extracting care code from PDF: {e}")
    return None


# ============================
# BATCH PROCESS FOLDER
# ============================

def process_folder(folder_path):

    results = {}

    for file in os.listdir(folder_path):
        if file.lower().endswith((".png", ".jpg", ".jpeg")):

            full_path = os.path.join(folder_path, file)

            data = extract_label_data(full_path)
            results[file] = data

            time.sleep(DELAY_BETWEEN_IMAGES)

    return results


# ============================
# RUN
# ============================

if __name__ == "__main__":

    folder_path = "labels"   # Folder containing label images

    final_results = process_folder(folder_path)

    print("\n\n===== FINAL OUTPUT =====\n")

    for file, data in final_results.items():
        print(f"\n📄 {file}")
        print(data)