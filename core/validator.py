import unicodedata
import re
import difflib


# ------------------------------------------------
# HELPERS
# ------------------------------------------------

def has_value(value):
    """
    Returns True only if the value is meaningful.
    Skips None, empty string, 'None', 'null', empty list, etc.
    """
    if value is None:
        return False

    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in ["", "none", "null", "nan", "-"]:
            return False
        return True

    if isinstance(value, list):
        cleaned_list = []
        for item in value:
            if item is None:
                continue
            item_str = str(item).strip()
            if item_str and item_str.lower() not in ["none", "null", "nan", "-"]:
                cleaned_list.append(item_str)
        return len(cleaned_list) > 0

    return True


# ------------------------------------------------
# NORMALIZE TEXT
# ------------------------------------------------

def collapse_duplicate_words(text):
    """
    Collapses consecutive duplicate words (e.g. 'le le' -> 'le', 'the the' -> 'the')
    """
    while True:
        # Match word boundary, word, spaces, and duplicate word
        new_text = re.sub(r"\b(\w+)(?:\s+\1\b)+", r"\1", text, flags=re.IGNORECASE)
        if new_text == text:
            break
        text = new_text
    return text


def normalize(text):
    """
    Original normalization, stripping non-alphanumeric except Chinese.
    Enhanced to strip accents and convert curly apostrophes first.
    """
    if not has_value(text):
        return ""

    text = str(text).replace("’", "'").replace("‘", "'")
    
    # Strip accents
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()

    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text)

    return text


def normalize_words(text):
    """
    Normalization that preserves word boundaries and collapses consecutive duplicate words.
    """
    if not has_value(text):
        return ""

    text = str(text).replace("’", "'").replace("‘", "'")
    
    # Strip accents
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()

    # Replace non-alphanumeric except Chinese with spaces, keeping straight apostrophes
    text = re.sub(r"[^a-z0-9'\u4e00-\u9fff]+", " ", text)
    
    # Collapse duplicate words
    text = collapse_duplicate_words(text)
    
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text).strip()

    return text


def is_phrase_in_text(phrase_norm, label_norm):
    """
    Checks if phrase_norm is found in label_norm, allowing minor variations
    (e.g., missing short words like 'on') using sliding window sequence matching.
    """
    if not phrase_norm:
        return True
    if not label_norm:
        return False

    # 1. Direct containment check (covers most cases)
    if phrase_norm in label_norm:
        return True

    # 2. Word-based sliding window check
    p_words = phrase_norm.split()
    l_words = label_norm.split()
    
    n_p = len(p_words)
    n_l = len(l_words)
    
    if n_p == 1:
        return p_words[0] in l_words

    best_ratio = 0.0
    
    # We look for matches in windows of size around n_p
    min_w = max(1, n_p - 2)
    max_w = min(n_l, n_p + 2)
    
    for window_size in range(min_w, max_w + 1):
        for i in range(n_l - window_size + 1):
            sub_seq = l_words[i : i + window_size]
            sub_phrase = " ".join(sub_seq)
            
            # Fast heuristic check before expensive SequenceMatcher
            common_words = set(p_words) & set(sub_seq)
            if len(common_words) / n_p < 0.5:
                continue

            ratio = difflib.SequenceMatcher(None, phrase_norm, sub_phrase).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                if best_ratio >= 0.85:
                    return True
                    
    return best_ratio >= 0.80


def contains(job_value, label_text, split_slashes=False):
    if not has_value(job_value):
        return True

    job_value_str = str(job_value)

    if split_slashes and "/" in job_value_str:
        # Normalize the whole label text to words
        label_norm = normalize_words(label_text)
        
        # Split and verify each part
        parts = [p.strip() for p in job_value_str.split("/") if p.strip()]
        if not parts:
            return True
            
        for part in parts:
            part_norm = normalize_words(part)
            if not part_norm:
                continue
            if not is_phrase_in_text(part_norm, label_norm):
                return False
        return True
    else:
        # Standard check
        return normalize(job_value_str) in normalize(label_text)


def find_matched_text(job_value, label_text, split_slashes=False):
    if not has_value(job_value):
        return None

    if contains(job_value, label_text, split_slashes=split_slashes):
        return job_value

    return None


# ------------------------------------------------
# FIBRE CHECK
# ------------------------------------------------

def fibre_check(job_fibre_text, label_text):

    if not has_value(job_fibre_text):
        return True, [], [], ""

    label_norm = normalize(label_text)

    missing_parts = []
    found_parts = []
    found_text_parts = []

    lines = [line.strip() for line in str(job_fibre_text).split("\n") if line.strip()]

    for line in lines:

        line_norm = normalize(line)

        if "%" in line:

            if line_norm in label_norm:
                found_parts.append(line)
                found_text_parts.append(line)
            else:
                missing_parts.append(line)

        else:

            parts = [p.strip() for p in line.split("/") if p.strip()]
            found_line_parts = []

            for part in parts:

                if normalize(part) in label_norm:
                    found_parts.append(part)
                    found_line_parts.append(part)
                else:
                    missing_parts.append(part)

            if found_line_parts:
                found_text_parts.append("/".join(found_line_parts))

    found_text = " ".join(found_text_parts) if found_text_parts else ""

    return len(missing_parts) == 0, missing_parts, found_parts, found_text


# ------------------------------------------------
# ADDITIONAL INFORMATION
# ------------------------------------------------

def find_additional_information(job_data, label_text):

    valid_values = []

    for v in job_data.values():
        if not has_value(v):
            continue

        if isinstance(v, list):
            valid_values.extend([str(x) for x in v if has_value(x)])
        else:
            valid_values.append(str(v))

    job_text = " ".join(valid_values)
    job_norm = normalize(job_text)

    additional = []

    # Standardise apostrophes
    label_text_clean = str(label_text).replace("’", "'").replace("‘", "'")

    # Match words containing letters, digits and middle apostrophes
    tokens = re.findall(r"[A-Za-z0-9']+", label_text_clean)

    for token in tokens:
        token = token.strip("'").strip()
        if not token:
            continue
        if normalize(token) not in job_norm:
            additional.append(token)

    additional = list(dict.fromkeys(additional))

    return additional


# ------------------------------------------------
# MISSING INFORMATION
# ------------------------------------------------

def find_missing_information(job_data, label_text):

    missing = []

    for key, value in job_data.items():

        # Skip size list because it is separately validated
        if key == "Size/Age Breakdown":
            continue

        if not has_value(value):
            continue

        if isinstance(value, list):
            values = [v for v in value if has_value(v)]
        else:
            values = [value]

        split_slashes = key in ["Country Of Origin", "Additional Instructions", "Care Phrases", "Pant Length"]

        for item in values:
            if not contains(item, label_text, split_slashes=split_slashes):
                missing.append(item)

    missing = list(dict.fromkeys(missing))

    return missing


# ------------------------------------------------
# MAIN VALIDATION
# ------------------------------------------------

def validate(job_data, label_data):

    label_text = label_data.get("raw_text", "")

    result = {
        "fields": {},
        "raw_label_text": label_text
    }

    overall_pass = True


    # ------------------------------------------------
    # SIMPLE FIELDS
    # ------------------------------------------------

    simple_fields = [
        "Brand",
        "Silhouette",
        "VSD",
        "RN",
        "CA",
        "Factory ID",
        "Date of MFR",
        "Country Of Origin",
        "Additional Instructions",
        "Care Phrases",
        "Pant Length"
    ]

    for field in simple_fields:

        job_val = job_data.get(field)

        # ✅ Skip null/empty fields completely
        if not has_value(job_val):
            continue

        # Convert list to string for validation
        if isinstance(job_val, list):
            job_val_str = " ".join([str(item) for item in job_val if has_value(item)])
        else:
            job_val_str = job_val

        # Set split_slashes=True for multi-phrase fields
        split_slashes = field in ["Country Of Origin", "Additional Instructions", "Care Phrases", "Pant Length"]

        match = contains(job_val_str, label_text, split_slashes=split_slashes)

        result["fields"][field] = {
            "jobcard": job_val,
            "label": find_matched_text(job_val_str, label_text, split_slashes=split_slashes),
            "match": match,
            "type": "contains"
        }

        if not match:
            overall_pass = False


    # ------------------------------------------------
    # FIBRE VALIDATION
    # ------------------------------------------------

    fibre_text = job_data.get("Garment Components & Fibre Contents")

    if has_value(fibre_text):
        fibre_match, missing, found, found_text = fibre_check(
            fibre_text,
            label_text
        )

        result["fields"]["Garment Components & Fibre Contents"] = {
            "jobcard": fibre_text,
            "label_found_parts": found,
            "missing_parts": missing,
            "label_found_text": found_text,
            "match": fibre_match,
            "type": "multi_line_contains"
        }

        if not fibre_match:
            overall_pass = False


    # ------------------------------------------------
    # SIZE VALIDATION
    # ------------------------------------------------

    job_sizes = job_data.get("Size/Age Breakdown", [])

    if has_value(job_sizes):

        found_sizes = []

        for size in job_sizes:
            if has_value(size) and contains(size, label_text):
                found_sizes.append(size)

        size_match = len(found_sizes) == 1

        result["fields"]["Size/Age Breakdown"] = {
            "expected_sizes": job_sizes,
            "label_found_sizes": found_sizes,
            "match": size_match,
            "type": "single_valid_size_required"
        }

        if not size_match:
            overall_pass = False


    # ------------------------------------------------
    # ADDITIONAL INFORMATION
    # ------------------------------------------------

    additional = find_additional_information(job_data, label_text)
    result["additional_information"] = additional


    # ------------------------------------------------
    # MISSING INFORMATION
    # ------------------------------------------------

    missing_info = find_missing_information(job_data, label_text)
    result["missing_information"] = missing_info


    result["overall_pass"] = overall_pass

    return result