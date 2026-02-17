import re
from difflib import SequenceMatcher
from typing import Dict

from markdown import markdown
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Source: https://stackoverflow.com/a/12982689
HTML_TAG_PATTERN = re.compile("<.*?>|&([a-z0-9]+|#[0-9]{1,6}|#x[0-9a-f]{1,6});")


def remove_html_tags(text: str):
    html = markdown(text, extensions=["tables"])
    return re.sub(HTML_TAG_PATTERN, " ", html)


def clean_text(txt):
    # Remove LaTeX commands (e.g. \command, \command[args]{args})
    txt = re.sub(r"\\[a-zA-Z]+(\[[^\]]*\])?(\{[^}]*\})?", " ", txt)

    # Replace all blocks of whitespace (including tabs and newlines) with a single space
    txt = re.sub(r"\s+", " ", txt)

    # Remove all non-alphanumeric characters except spaces
    txt = re.sub(r"[^a-zA-Z0-9 ]", " ", txt)

    return txt.strip()


def cosine_text_similarity(text1, text2):
    texts = [clean_text(text1), clean_text(text2)]
    vectorizer = TfidfVectorizer().fit_transform(texts)
    return cosine_similarity(vectorizer[0], vectorizer[1])[0][0]


def jaccard_text_similarity(text1: str, text2: str) -> float:
    set1 = set(clean_text(text1).split())
    set2 = set(clean_text(text2).split())
    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))
    return intersection / union if union > 0 else 0.0


def precision_recall_f1_score(text1: str, text2: str) -> Dict[str, float]:
    """
    Calculate precision, recall, and F1 score between two texts.
    Precision = TP / (TP + FP)
    Recall = TP / (TP + FN)
    F1 Score = 2 * (Precision * Recall) / (Precision + Recall)
    """
    set1 = set(clean_text(text1).split())
    set2 = set(clean_text(text2).split())

    true_positive = len(set1.intersection(set2))
    false_positive = len(set2 - set1)
    false_negative = len(set1 - set2)

    precision = (
        true_positive / (true_positive + false_positive)
        if (true_positive + false_positive) > 0
        else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if (true_positive + false_negative) > 0
        else 0.0
    )
    f1_score = (
        2 * (precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "precision": precision,
        "recall": recall,
        "f1_score": f1_score,
    }


def calculate_similarities(
    text1: str,
    text2: str,
    ignore_html: bool = True,
    diff_save_path: str = "",
) -> dict:
    """Calculate similarity ratio between two texts using SequenceMatcher."""
    if ignore_html:
        text1 = remove_html_tags(text1)
        text2 = remove_html_tags(text2)

    text1 = clean_text(clean_text(text1))
    text2 = clean_text(clean_text(text2))

    similarities = {}

    sm = SequenceMatcher(None, text1, text2)
    similarities["sequence_matcher"] = sm.ratio()
    # Save the diff and the texts for debugging
    if diff_save_path:
        with open(diff_save_path, "w") as f:
            f.write(f"Text 1:\n{text1}\n\n")
            f.write(f"Text 2:\n{text2}\n\n")
            f.write("Differences:\n")
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag == "equal":
                    continue
                f.write(f"{tag} {text1[i1:i2]} -> {text2[j1:j2]}\n")
    similarities["cosine"] = cosine_text_similarity(text1, text2)
    similarities["jaccard"] = jaccard_text_similarity(text1, text2)
    similarities.update(precision_recall_f1_score(text1, text2))

    return similarities


METRIC_NAMES = (
    "sequence_matcher",
    "cosine",
    "jaccard",
    "precision",
    "recall",
    "f1_score",
)
