import os
import json
import sys

from core.label_detector import detect_labels
from core.label_extractor import extract_label_data
from core.jobcard_extractor import extract_required_fields
from core.validator import validate
# pyrefly: ignore [missing-import]
from core.report_generator import generate_validation_report


# ============================
# GLOBAL OUTPUT CONFIGURATION
# ============================

OUTPUT_FOLDER = "output"


# ============================
# PROCESS ONE COMBINATION
# ============================

def process_single_combination(job_card_path, label_pdf_path, combo_index):
    """
    Process one job card + one label artwork PDF combination.
    Saves outputs inside:
        output/combination_1/
        output/combination_2/
        ...
    """

    combo_folder = os.path.join(OUTPUT_FOLDER, f"combination_{combo_index}")
    label_image_folder = os.path.join(combo_folder, "labels")

    job_output_path = os.path.join(combo_folder, "jobcard_data.json")
    label_output_path = os.path.join(combo_folder, "label_data.json")
    validation_output_path = os.path.join(combo_folder, "validation_result.json")
    report_output_path = os.path.join(combo_folder, "validation_report.pdf")

    os.makedirs(combo_folder, exist_ok=True)
    os.makedirs(label_image_folder, exist_ok=True)

    print(f"\n==============================")
    print(f"🚀 PROCESSING COMBINATION {combo_index}")
    print(f"==============================")

    # STEP 1 — JOB CARD EXTRACTION
    print("\n🔹 STEP 1: Extracting Job Card...")
    job_data = extract_required_fields(job_card_path)

    with open(job_output_path, "w", encoding="utf-8") as f:
        json.dump(job_data, f, indent=4, ensure_ascii=False)

    print("   ✅ Job card extracted")

    # STEP 2 — LABEL DETECTION
    print("\n🔹 STEP 2: Detecting Labels...")
    label_images = detect_labels(label_pdf_path, label_image_folder)

    if not label_images:
        print("   ⚠ No labels detected.")
        return {
            "combination": combo_index,
            "status": "failed",
            "reason": "No labels detected"
        }

    print(f"   ✅ {len(label_images)} labels detected")

    # STEP 3 — LABEL EXTRACTION
    print("\n🔹 STEP 3: Extracting Label Data...")
    all_label_data = {}

    for img_path in label_images:
        structured = extract_label_data(img_path)
        label_name = os.path.basename(img_path)
        all_label_data[label_name] = structured

    with open(label_output_path, "w", encoding="utf-8") as f:
        json.dump(all_label_data, f, indent=4, ensure_ascii=False)

    print("   ✅ Label data extracted")

    # STEP 4 — VALIDATION
    print("\n🔹 STEP 4: Validating Labels...")
    validation_results = {}

    for label_name, label_data in all_label_data.items():
        validation_results[label_name] = validate(job_data, label_data)

    with open(validation_output_path, "w", encoding="utf-8") as f:
        json.dump(validation_results, f, indent=4, ensure_ascii=False)

    print("   ✅ Validation completed")

    # STEP 5 — PDF REPORT
    print("\n🔹 STEP 5: Generating PDF Report...")
    generate_validation_report(validation_results, report_output_path)
    print("   ✅ PDF report generated")

    # SUMMARY
    passed = sum(1 for v in validation_results.values() if v["overall_pass"])
    failed = len(validation_results) - passed

    print("\n------------------------------")
    print(f"Combination {combo_index} Summary")
    print("------------------------------")
    print(f"Total Labels : {len(validation_results)}")
    print(f"Passed       : {passed}")
    print(f"Failed       : {failed}")
    print(f"📁 Output     : {combo_folder}")
    print("------------------------------\n")

    return {
        "combination": combo_index,
        "status": "success",
        "total_labels": len(validation_results),
        "passed": passed,
        "failed": failed,
        "output_folder": combo_folder
    }


# ============================
# PROCESS MULTIPLE COMBINATIONS
# ============================

def process_multiple_combinations(combinations):
    """
    combinations = [
        {"job_card": "...", "label_pdf": "..."},
        {"job_card": "...", "label_pdf": "..."},
        ...
    ]
    """

    summaries = []

    for idx, combo in enumerate(combinations, start=1):
        try:
            summary = process_single_combination(
                combo["job_card"],
                combo["label_pdf"],
                idx
            )
            summaries.append(summary)

        except Exception as e:
            print(f"\n❌ ERROR IN COMBINATION {idx}")
            print(str(e))
            summaries.append({
                "combination": idx,
                "status": "failed",
                "reason": str(e)
            })

    return summaries


# ============================
# ENTRY POINT
# ============================

def main():
    try:
        combinations = [
            {
                "job_card": "input/job_card_1.pdf",
                "label_pdf": "input/label_1.pdf"
            }
        ]

        # Example for multiple combinations:
        # combinations = [
        #     {"job_card": "input/job_card_1.pdf", "label_pdf": "input/label_1.pdf"},
        #     {"job_card": "input/job_card_2.pdf", "label_pdf": "input/label_2.pdf"},
        #     {"job_card": "input/job_card_3.pdf", "label_pdf": "input/label_3.pdf"},
        # ]

        if not combinations:
            print("No combinations provided.")
            return

        if len(combinations) > 5:
            print("Maximum 5 combinations are allowed.")
            return

        os.makedirs(OUTPUT_FOLDER, exist_ok=True)

        summaries = process_multiple_combinations(combinations)

        print("\n==============================")
        print("🎉 ALL PROCESSING COMPLETED")
        print("==============================")

        for s in summaries:
            if s["status"] == "success":
                print(
                    f"Combination {s['combination']} → SUCCESS "
                    f"(Passed: {s['passed']}, Failed: {s['failed']})"
                )
            else:
                print(
                    f"Combination {s['combination']} → FAILED "
                    f"({s.get('reason', 'Unknown error')})"
                )

        print("==============================\n")

    except Exception as e:
        print("\n❌ ERROR OCCURRED")
        print(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()