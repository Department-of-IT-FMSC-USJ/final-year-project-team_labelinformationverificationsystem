import os
# pyrefly: ignore [missing-import]
import cv2
# pyrefly: ignore [missing-import]
import fitz  # PyMuPDF
# pyrefly: ignore [missing-import]
import numpy as np


def get_separated_masks(hsv_image):
    """Isolate the technical colors into separate masks because they require

    different processing strategies.
    """
    # 1. Magenta/Red tracking lines (Dashed - needs aggressive closing)
    lower_red1 = np.array([0, 60, 60])
    upper_red1 = np.array([15, 255, 255])
    lower_red2 = np.array([145, 60, 60])
    upper_red2 = np.array([180, 255, 255])

    mask_r1 = cv2.inRange(hsv_image, lower_red1, upper_red1)
    mask_r2 = cv2.inRange(hsv_image, lower_red2, upper_red2)
    magenta_mask = mask_r1 + mask_r2

    # 2. Cyan tracking lines (Solid & Close Together - needs delicate closing)
    lower_cyan = np.array([85, 100, 150])
    upper_cyan = np.array([115, 255, 255])
    cyan_mask = cv2.inRange(hsv_image, lower_cyan, upper_cyan)

    return magenta_mask, cyan_mask


def extract_technical_labels(pdf_path, output_folder):
    """Processes solid and dashed technical labels uniquely based on color cues

    to avoid label merging while successfully capturing dashed frames.
    """
    os.makedirs(output_folder, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]

    doc = fitz.open(pdf_path)
    label_count = 0
    saved_paths = []

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        pix = page.get_pixmap(dpi=300)

        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
        img = (
            cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            if pix.n == 4
            else cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        )

        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        magenta_mask, cyan_mask = get_separated_masks(hsv)

        # --- FIX: DUAL KERNEL STRATEGY ---
        # Large kernel bridges the wide gaps in the dashed Victoria's Secret frames
        kernel_large = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
        closed_magenta = cv2.morphologyEx(
            magenta_mask, cv2.MORPH_CLOSE, kernel_large
        )

        # Small kernel keeps adjacent solid-line PINK labels perfectly isolated
        kernel_small = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        closed_cyan = cv2.morphologyEx(cyan_mask, cv2.MORPH_CLOSE, kernel_small)

        # Combine both beautifully sealed masks
        combined_closed_mask = closed_magenta + closed_cyan

        # Find the overall contours
        contours, _ = cv2.findContours(
            combined_closed_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        page_h, page_w = img.shape[:2]

        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)

            # Ignore non-label artifacts or entire canvas frames
            if w < 150 or h < 150 or w > page_w * 0.95 or h > page_h * 0.95:
                continue

            # Density check to verify it's an open label box and not a solid ink swatch
            raw_box_area = (magenta_mask + cyan_mask)[y : y + h, x : x + w]
            color_density = np.sum(raw_box_area > 0) / (w * h)

            if color_density > 0.15:
                continue

            # Use a safe margin padding of 10 pixels
            pad = 10
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(page_w, x + w + pad)
            y2 = min(page_h, y + h + pad)

            cropped_label = img[y1:y2, x1:x2]
            label_count += 1

            output_file = os.path.join(
                output_folder, f"{base_name}_label_{label_count}.png"
            )
            cv2.imwrite(output_file, cropped_label)
            saved_paths.append(output_file)

    return saved_paths


def detect_labels(pdf_path, output_folder):
    """Compatibility wrapper named for the Streamlit and CLI entry points."""
    return extract_technical_labels(pdf_path, output_folder)