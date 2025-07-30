import os
import re
import glob
import csv
from benchmark_utils import calculate_similarities


GROUND_TRUTH_DIR = "examples/outputs"
PREDICTION_PATTERN = "tests/outputs/benchmark*/*_model=*, parser_type=*.md"
OUTPUT_CSV = "tests/outputs/document_results.csv"


def extract_metadata(pred_path):
    filename = os.path.basename(pred_path)
    doc_match = re.match(r"(.*?)_model=(.*?), parser_type=(.*?)\.md", filename)
    if not doc_match:
        raise ValueError(f"Filename {filename} does not match expected pattern")
    doc_name, model_name, parser_type = doc_match.groups()
    return doc_name, model_name, parser_type


def load_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def main():
    results = []
    prediction_files = sorted(glob.glob(PREDICTION_PATTERN, recursive=True))
    print(f"Found {len(prediction_files)} prediction files.")

    for pred_path in prediction_files:
        doc_name, model, parser_type = extract_metadata(pred_path)
        gt_path = os.path.join(GROUND_TRUTH_DIR, f"{doc_name}.md")
        if not os.path.exists(gt_path):
            print(f"Ground truth for {doc_name} not found, skipping.")
            continue

        pred_text = load_file(pred_path)
        gt_text = load_file(gt_path)
        sim_scores = calculate_similarities(pred_text, gt_text)

        results.append(
            {
                "Input File": doc_name,
                "sequence_matcher": sim_scores.get("sequence_matcher", ""),
                "cosine": sim_scores.get("cosine", ""),
                "jaccard": sim_scores.get("jaccard", ""),
                "precision": sim_scores.get("precision", ""),
                "recall": sim_scores.get("recall", ""),
                "f1_score": sim_scores.get("f1_score", ""),
                "model": model,
                "parser_type": parser_type,
            }
        )

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = [
            "Input File",
            "sequence_matcher",
            "cosine",
            "jaccard",
            "precision",
            "recall",
            "f1_score",
            "model",
            "parser_type",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"Similarity results saved to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
