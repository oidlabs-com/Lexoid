import argparse
import pandas as pd
import re


def update_markdown(content, table_md):
    pattern = r"(##\s*Benchmark\s*\n(?:.*?\n)*?\n)(\| Rank .*?\n\|.*?\n(?:\|.*?\n)+)"
    replacement = r"\1" + table_md + "\n"
    return re.sub(pattern, replacement, content, flags=re.DOTALL)


def update_rst(content, table_rst):
    pattern = r"(Benchmark Results\s*-+\n.*?\n)(\s*\* - .*\n)+"
    return re.sub(pattern, f"\\1{table_rst}\n", content, flags=re.DOTALL)


def generate_markdown_table(df):
    header = "| Rank | Model | SequenceMatcher Similarity | TFIDF Similarity | Time (s) | Cost ($) |\n"
    sep = "| --- | --- | --- | --- | --- | --- |\n"
    rows = [
        f"| {i+1} | {row['Model']} | {row['sequence_matcher']} | {row['cosine']} | {row['Time (s)']:.2f} | {row['Cost ($)']:.5f} |"
        for i, row in df.iterrows()
    ]
    return header + sep + "\n".join(rows)


def generate_rst_table(df):
    header = "\n   * - Rank\n     - Model\n     - SequenceMatcher Similarity\n     - TFIDF Similarity.\n     - Time (s)\n     - Cost ($)"
    rows = [
        f"   * - {i+1}\n     - {row['Model']}\n     - {row['sequence_matcher']}\n     - {row['cosine']}\n     - {row['Time (s)']:.2f}\n     - {row['Cost ($)']:.5f}"
        for i, row in df.iterrows()
    ]
    return header + "\n" + "\n".join(rows)


def main(csv_path, md_path, rst_path):
    df = pd.read_csv(csv_path)
    df = df.sort_values(by="sequence_matcher", ascending=False).reset_index(drop=True)

    with open(md_path, "r", encoding="utf-8") as f:
        md_content = f.read()
    with open(rst_path, "r", encoding="utf-8") as f:
        rst_content = f.read()

    table_md = generate_markdown_table(df)
    table_rst = generate_rst_table(df)

    updated_md = update_markdown(md_content, table_md)
    updated_rst = update_rst(rst_content, table_rst)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(updated_md)
    with open(rst_path, "w", encoding="utf-8") as f:
        f.write(updated_rst)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Update benchmark tables in README.md and benchmark.rst from CSV"
    )
    parser.add_argument(
        "--csv", default="outputs/results.csv", help="Path to benchmark.csv"
    )
    parser.add_argument("--md", default="../README.md", help="Path to README.md")
    parser.add_argument(
        "--rst", default="../docs/benchmark.rst", help="Path to benchmark.rst"
    )
    args = parser.parse_args()

    main(args.csv, args.md, args.rst)
