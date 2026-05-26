import os
import tempfile
import json
import shutil

# pyrefly: ignore [missing-import]
import streamlit as st
import pandas as pd
import requests

from core.jobcard_extractor import extract_required_fields
from core.label_detector import detect_labels
from core.label_extractor import extract_label_data
from core.validator import validate


OUTPUT_FOLDER = "output"
MAX_PAIRS = 5


# -------------------------------------------------------
# HELPER
# -------------------------------------------------------

def has_value(value):
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


def is_connected(url="https://www.google.com/", timeout=3):
    try:
        requests.get(url, timeout=timeout)
        return True
    except requests.RequestException:
        return False


def get_friendly_error_message(error, pair_index=None):
    error_text = str(error).strip()

    prefix = f"Combination {pair_index}: " if pair_index else ""

    if "No labels detected" in error_text:
        return (
            f"{prefix}We could not detect any label areas in the uploaded label artwork PDF. "
            "Please check whether the PDF contains clear label sections and try again."
        )

    if "OCR failed after 3 attempts" in error_text:
        return (
            f"{prefix}Text extraction failed for one of the detected labels. "
            "Text from the label was not successfully extracted.Please try again."
        )

    if "OCR_SPACE_API_KEY not set in environment" in error_text:
        return (
            f"{prefix}The OCR service is not configured properly. "
            "Please add the OCR API key to the environment settings before running the system."
        )

    if "timed out" in error_text.lower():
        return (
            f"{prefix}The request took too long to complete. "
            "Please try again in a moment."
        )

    if "cannot identify image file" in error_text.lower():
        return (
            f"{prefix}One of the generated label images could not be read properly. "
            "Please try uploading the files again."
        )

    return (
        f"{prefix}Something went wrong while processing this combination. "
        f"Technical details: {error_text}"
    )


# -------------------------------------------------------
# PROCESS ONE COMBINATION
# -------------------------------------------------------

def run_single_pipeline(job_card_path, label_pdf_path, combo_index, progress=None):
    def _update(pct, msg=""):
        if progress:
            progress(pct, msg)

    combo_folder = os.path.join(OUTPUT_FOLDER, f"combination_{combo_index}")
    label_image_folder = os.path.join(combo_folder, "labels")

    # Clean old output for this combination only
    if os.path.exists(combo_folder):
        shutil.rmtree(combo_folder)

    os.makedirs(label_image_folder, exist_ok=True)

    # STEP 1 — JOB CARD EXTRACTION
    _update(0.05, f"[Combination {combo_index}] Extracting job card...")
    job_data = extract_required_fields(job_card_path)
    _update(0.15, f"[Combination {combo_index}] Job card extracted")

    # STEP 2 — LABEL DETECTION
    _update(0.20, f"[Combination {combo_index}] Detecting labels...")
    label_images = detect_labels(label_pdf_path, label_image_folder)

    if not label_images:
        raise RuntimeError("No labels detected in the uploaded artwork.")

    _update(0.30, f"[Combination {combo_index}] {len(label_images)} labels detected")

    # STEP 3 — OCR EXTRACTION
    all_label_data = {}
    total = len(label_images)

    for idx, img_path in enumerate(label_images, start=1):
        _update(
            0.30 + 0.30 * (idx / total),
            f"[Combination {combo_index}] Extracting label {idx}/{total}"
        )

        structured = extract_label_data(img_path)
        label_name = os.path.basename(img_path)

        if structured is None or not structured.get("raw_text"):
            raise RuntimeError(
                f"OCR failed after 3 attempts. Failed label: {label_name}"
            )

        all_label_data[label_name] = structured

    _update(0.60, f"[Combination {combo_index}] Label text extracted")

    # STEP 4 — VALIDATION
    validation_results = {}

    for idx, (label_name, label_data) in enumerate(all_label_data.items(), start=1):
        validation_results[label_name] = validate(job_data, label_data)
        _update(
            0.60 + 0.40 * (idx / total),
            f"[Combination {combo_index}] Validating label {idx}/{total}"
        )

    _update(1.0, f"[Combination {combo_index}] Validation completed")

    # SAVE JSON OUTPUTS
    with open(os.path.join(combo_folder, "jobcard_data.json"), "w", encoding="utf-8") as f:
        json.dump(job_data, f, indent=4, ensure_ascii=False)

    with open(os.path.join(combo_folder, "label_data.json"), "w", encoding="utf-8") as f:
        json.dump(all_label_data, f, indent=4, ensure_ascii=False)

    with open(os.path.join(combo_folder, "validation_result.json"), "w", encoding="utf-8") as f:
        json.dump(validation_results, f, indent=4, ensure_ascii=False)

    return job_data, all_label_data, validation_results, label_images, label_image_folder


# -------------------------------------------------------
# DISPLAY RESULTS
# -------------------------------------------------------

def render_results(validation_results, label_image_folder, combo_index):
    st.markdown(f"## Results - Combination {combo_index}")

    total_labels = len(validation_results)
    passed = sum(1 for v in validation_results.values() if v["overall_pass"])
    failed = total_labels - passed

    st.write(f"**Total Labels:** {total_labels}")


    for label_name, result in validation_results.items():
        st.markdown("---")

        cols = st.columns([1, 2])
        img_path = os.path.join(label_image_folder, label_name)

        if os.path.exists(img_path):
            cols[0].image(img_path, caption=label_name)

        cols[1].subheader(f"Label: {label_name}")

        rows = []

        for field, field_data in result["fields"].items():

            if field not in ["Size/Age Breakdown", "Garment Components & Fibre Contents"]:
                job_val_raw = field_data.get("jobcard", "")
                if not has_value(job_val_raw):
                    continue

            if field == "Size/Age Breakdown":
                expected_sizes = field_data.get("expected_sizes", [])
                found_sizes = field_data.get("label_found_sizes", [])

                expected = ", ".join([str(x) for x in expected_sizes if has_value(x)])
                label_val = ", ".join([str(x) for x in found_sizes if has_value(x)])

            elif field == "Garment Components & Fibre Contents":
                jobcard_val = field_data.get("jobcard", "")
                label_found_text = field_data.get("label_found_text", "")

                if not has_value(jobcard_val):
                    continue

                expected = str(jobcard_val)
                label_val = str(label_found_text) if has_value(label_found_text) else ""

            elif field == "Care Phrases":
                jobcard_val = field_data.get("jobcard", "")
                label_val = field_data.get("label", "")

                if not has_value(jobcard_val):
                    continue

                # Format list as bullet points for display
                if isinstance(jobcard_val, list):
                    expected = "\n".join([f" {str(item)}" for item in jobcard_val if has_value(item)])
                else:
                    expected = str(jobcard_val)

                label_val = str(label_val) if has_value(label_val) else ""

            else:
                expected = str(field_data.get("jobcard", "")) if has_value(field_data.get("jobcard", "")) else ""
                label_val = str(field_data.get("label", "")) if has_value(field_data.get("label", "")) else ""

            status = "✅" if field_data.get("match") else "❌"

            rows.append([field, expected, label_val, status])

        additional = result.get("additional_information", [])
        if additional:
            cleaned_additional = [str(x) for x in additional if has_value(x)]
            if cleaned_additional:
                rows.append([
                    "Additional Information",
                    "-",
                    ", ".join(cleaned_additional),
                    "⚠️"
                ])

        missing = result.get("missing_information", [])
        if missing:
            cleaned_missing = [str(x) for x in missing if has_value(x)]
            if cleaned_missing:
                rows.append([
                    "Missing Information",
                    "-",
                    ", ".join(cleaned_missing),
                    "❓"
                ])

        df = pd.DataFrame(
            rows,
            columns=[
                "Field",
                "Job Card Requirement",
                "Label Extracted",
                "Status"
            ]
        )

        cols[1].table(df)


# -------------------------------------------------------
# METRICS HELPERS
# -------------------------------------------------------

def collect_field_metrics(all_results):
    field_counts = {}

    for combo in all_results:
        for result in combo["validation_results"].values():
            for field, field_data in result.get("fields", {}).items():
                if not isinstance(field_data, dict):
                    continue

                if "match" not in field_data:
                    continue

                entry = field_counts.setdefault(
                    field,
                    {
                        "passed": 0,
                        "total": 0
                    }
                )

                entry["total"] += 1
                if field_data.get("match"):
                    entry["passed"] += 1

    metrics = []
    for field, counts in sorted(field_counts.items(), key=lambda item: item[0]):
        total = counts["total"]
        passed = counts["passed"]
        metrics.append({
            "Field": field,
            "Passed": passed,
            "Total Checks": total,
            "Pass Rate (%)": round((passed / total) * 100, 1) if total else 0.0
        })

    return metrics


def compute_pipeline_metrics(all_results, requested_combinations):
    successful_combinations = len(all_results)
    failed_combinations = max(0, requested_combinations - successful_combinations)

    total_labels = 0
    passed_labels = 0
    total_additional = 0
    total_missing = 0

    combo_rows = []

    for combo in all_results:
        validation_results = combo["validation_results"]
        labels = len(validation_results)
        passed = sum(1 for result in validation_results.values() if result.get("overall_pass"))
        failed = labels - passed

        total_labels += labels
        passed_labels += passed
        total_additional += sum(len(result.get("additional_information", [])) for result in validation_results.values())
        total_missing += sum(len(result.get("missing_information", [])) for result in validation_results.values())

        combo_rows.append({
            "Combination": combo["pair_index"],
            "Labels Detected": labels,
            "Labels Passed": passed,
            "Labels Failed": failed,
            "Pass Rate (%)": round((passed / labels) * 100, 1) if labels else 0.0
        })

    return {
        "requested_combinations": requested_combinations,
        "successful_combinations": successful_combinations,
        "failed_combinations": failed_combinations,
        "total_labels": total_labels,
        "passed_labels": passed_labels,
        "failed_labels": total_labels - passed_labels,
        "label_pass_rate": round((passed_labels / total_labels) * 100, 1) if total_labels else 0.0,
        "average_labels_per_combo": round((total_labels / successful_combinations), 2) if successful_combinations else 0,
        "total_additional_information": total_additional,
        "total_missing_information": total_missing,
        "combination_summary": combo_rows
    }


def render_pipeline_metrics(all_results, requested_combinations):
    metrics = compute_pipeline_metrics(all_results, requested_combinations)

    cols = st.columns(3)
    cols[0].metric("Combinations Processed", metrics["requested_combinations"], delta=f"{metrics['failed_combinations']} failed")
    cols[1].metric("Labels Processed", metrics["total_labels"], f"Pass Rate: {metrics['label_pass_rate']}%")
    cols[2].metric("Average Labels/Combo", metrics["average_labels_per_combo"])

    cols = st.columns(3)
    cols[0].metric("Successful Combinations", metrics["successful_combinations"])
    cols[1].metric("Failed Combinations", metrics["failed_combinations"])
    cols[2].metric("Missing Info Items", metrics["total_missing_information"])

    st.markdown("#### Combination-level Summary")
    st.dataframe(pd.DataFrame(metrics["combination_summary"]))

    field_metrics = collect_field_metrics(all_results)
    if field_metrics:
        st.markdown("#### Field-level Match Rates")
        st.dataframe(pd.DataFrame(field_metrics))


# -------------------------------------------------------
# STREAMLIT UI
# -------------------------------------------------------

def main():
    st.set_page_config(
        page_title="Automated Label Verification System",
        layout="wide"
    )

    st.title("Automated Label Verification System")

    st.write(
        "Upload **Job Card PDF** and **Label Artwork PDF** as combinations. "
        "You can process from **1 up to 5 combinations**."
    )

    # --------------------------------------------
    # SESSION STATE FOR NUMBER OF PAIRS
    # --------------------------------------------
    if "pair_count" not in st.session_state:
        st.session_state.pair_count = 1

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Add Another Combination"):
            if st.session_state.pair_count < MAX_PAIRS:
                st.session_state.pair_count += 1
            else:
                st.warning("You can add up to 5 combinations only.")

    with col2:
        if st.button("Remove Last Combination"):
            if st.session_state.pair_count > 1:
                st.session_state.pair_count -= 1
            else:
                st.warning("At least one combination must remain visible.")

    st.info(f"Currently active combinations: {st.session_state.pair_count}")

    uploaded_pairs = []

    # --------------------------------------------
    # COMBINATION-BASED UPLOAD SECTIONS
    # --------------------------------------------
    for i in range(1, st.session_state.pair_count + 1):
        st.markdown("---")
        st.subheader(f"Combination {i}")

        col1, col2 = st.columns(2)

        with col1:
            job_file = st.file_uploader(
                f"Upload Job Card PDF - Combination {i}",
                type=["pdf"],
                key=f"job_file_{i}"
            )

        with col2:
            label_file = st.file_uploader(
                f"Upload Label Artwork PDF - Combination {i}",
                type=["pdf"],
                key=f"label_file_{i}"
            )

        uploaded_pairs.append({
            "pair_index": i,
            "job_file": job_file,
            "label_file": label_file
        })

    # --------------------------------------------
    # PROCESS BUTTON
    # --------------------------------------------
    if st.button("Extract and Validate All Combinations"):

        valid_pairs = []
        incomplete_pairs = []

        for pair in uploaded_pairs:
            job_file = pair["job_file"]
            label_file = pair["label_file"]

            if job_file is None and label_file is None:
                continue

            if job_file is None or label_file is None:
                incomplete_pairs.append(pair["pair_index"])
            else:
                valid_pairs.append(pair)

        if incomplete_pairs:
            st.warning(
                "Please upload both the Job Card PDF and the Label Artwork PDF for "
                f"Combination(s): {', '.join(map(str, incomplete_pairs))}."
            )
            return

        if not valid_pairs:
            st.warning("Please upload at least one complete combination before processing.")
            return

        if not is_connected():
            st.error(
                "An internet connection is required to continue because label text extraction uses an online OCR service."
            )
            return

        os.makedirs(OUTPUT_FOLDER, exist_ok=True)

        all_results = []

        for pair in valid_pairs:
            pair_index = pair["pair_index"]
            job_file = pair["job_file"]
            label_file = pair["label_file"]

            st.markdown("---")
            st.subheader(f"Processing Combination {pair_index}")

            job_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            job_tmp.write(job_file.read())
            job_tmp.close()

            label_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            label_tmp.write(label_file.read())
            label_tmp.close()

            progress_bar = st.progress(0)
            status_text = st.empty()

            def progress_callback(fraction, message=""):
                progress_bar.progress(min(max(int(fraction * 100), 0), 100))
                status_text.text(message)

            try:
                job_data, all_label_data, validation_results, label_images, label_image_folder = run_single_pipeline(
                    job_tmp.name,
                    label_tmp.name,
                    combo_index=pair_index,
                    progress=progress_callback
                )

                all_results.append({
                    "pair_index": pair_index,
                    "validation_results": validation_results,
                    "label_image_folder": label_image_folder
                })

                st.success(f"Combination {pair_index} was processed successfully.")

            except RuntimeError as e:
                st.error(get_friendly_error_message(e, pair_index))

            except Exception as e:
                st.error(get_friendly_error_message(e, pair_index))

            finally:
                try:
                    os.unlink(job_tmp.name)
                except:
                    pass

                try:
                    os.unlink(label_tmp.name)
                except:
                    pass

        # --------------------------------------------
        # FINAL RESULTS
        # --------------------------------------------
        if all_results:
            st.markdown("---")
            st.header("Final Results")

            render_pipeline_metrics(all_results, len(valid_pairs))

            for result in all_results:
                render_results(
                    result["validation_results"],
                    result["label_image_folder"],
                    result["pair_index"]
                )

    st.markdown("---")
    st.write("Label Information Verification System")


if __name__ == "__main__":
    main()