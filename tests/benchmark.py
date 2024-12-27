from glob import glob
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Tuple
from statistics import mean
from pathlib import Path

from dotenv import load_dotenv

from lexoid.api import parse
from lexoid.core.utils import calculate_similarity

load_dotenv()


@dataclass
class BenchmarkResult:
    config: Dict
    similarity: float
    execution_time: float
    error: str = None


def get_input_output_pairs(input_path: str, output_dir: str) -> List[Tuple[str, str]]:
    """Get matching input and ground truth file pairs."""
    if os.path.isfile(input_path):
        # Single file mode
        base_name = Path(input_path).stem
        ground_truth_path = os.path.join(output_dir, f"{base_name}.md")
        if os.path.exists(ground_truth_path):
            return [(input_path, ground_truth_path)]
        return []

    # Directory mode
    input_files = glob(os.path.join(input_path, "*"))
    pairs = []

    for input_file in input_files:
        base_name = Path(input_file).stem
        ground_truth_path = os.path.join(output_dir, f"{base_name}.md")

        if os.path.exists(ground_truth_path):
            pairs.append((input_file, ground_truth_path))

    return pairs


def run_benchmark_config(
    input_path: str, ground_truth: str, config: Dict, output_save_dir: str = None
) -> BenchmarkResult:
    """Run a single benchmark configuration."""
    try:
        start_time = time.time()
        result = parse(input_path, raw=True, **config)
        execution_time = time.time() - start_time

        if output_save_dir:
            filename = (
                f"{Path(input_path).stem}_"
                + ", ".join(
                    [
                        f"{key}={value.replace("/", "_")}"
                        for key, value in config.items()
                    ]
                )
                + ".md"
            )
            with open(os.path.join(output_save_dir, filename), "w") as fp:
                fp.write(result)

        similarity = calculate_similarity(result, ground_truth)

        return BenchmarkResult(
            config=config, similarity=similarity, execution_time=execution_time
        )
    except Exception as e:
        print(f"Error running benchmark for config: {config}\n{e}")
        return BenchmarkResult(
            config=config, similarity=0.0, execution_time=0.0, error=str(e)
        )


def aggregate_results(results: List[BenchmarkResult]) -> BenchmarkResult:
    """Aggregate multiple benchmark results into a single result."""
    if not results:
        return None

    valid_results = [r for r in results if r.error is None]
    if valid_results:
        avg_similarity = mean(r.similarity for r in valid_results)
        avg_execution_time = mean(r.execution_time for r in valid_results)
        error = (
            None
            if len(valid_results) == len(results)
            else f"Failed: {len(results) - len(valid_results)}/{len(results)}"
        )
    else:
        avg_similarity = 0.0
        avg_execution_time = 0.0
        error = f"Failed: {len(results)}/{len(results)}"

    return BenchmarkResult(
        config=results[0].config,
        similarity=avg_similarity,
        execution_time=avg_execution_time,
        error=error,
    )


def generate_test_configs(input_path: str, test_attributes: List[str]) -> List[Dict]:
    """
    Generate different configuration combinations to test based on specified attributes.

    Args:
        input_path (str): Path to input file
        test_attributes (List[str]): List of attributes to test, can include:
            'parser_type', 'model', 'framework', 'pages_per_split', 'max_threads', 'as_pdf'
    """
    config_options = {
        "parser_type": ["LLM_PARSE", "STATIC_PARSE"],
        "model": [
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            "gpt-4o",
            "gpt-4o-mini",
            "meta-llama/Llama-3.2-11B-Vision-Instruct",
        ],
        "framework": ["pdfminer", "pdfplumber"],
        "pages_per_split": [1, 2, 4, 8],
        "max_threads": [1, 2, 4, 8],
        "as_pdf": [True, False],
    }

    # Only test as_pdf if input is not a PDF
    is_pdf = input_path.lower().endswith(".pdf")
    if is_pdf and "as_pdf" in test_attributes:
        test_attributes.remove("as_pdf")

    configs = [{}]

    for attr in test_attributes:
        new_configs = []
        for config in configs:
            if attr == "parser_type":
                for value in config_options[attr]:
                    new_config = config.copy()
                    new_config[attr] = value
                    new_configs.append(new_config)
            elif attr == "model" and (
                "parser_type" not in config or config.get("parser_type") == "LLM_PARSE"
            ):
                for value in config_options[attr]:
                    new_config = config.copy()
                    new_config[attr] = value
                    new_configs.append(new_config)
            elif attr == "framework" and (
                "parser_type" not in config
                or config.get("parser_type") == "STATIC_PARSE"
            ):
                for value in config_options[attr]:
                    new_config = config.copy()
                    new_config[attr] = value
                    new_configs.append(new_config)
            elif attr in ("pages_per_split", "max_threads"):
                for value in config_options[attr]:
                    new_config = config.copy()
                    new_config[attr] = value
                    new_configs.append(new_config)
            elif attr == "as_pdf" and not is_pdf:
                for value in config_options[attr]:
                    new_config = config.copy()
                    new_config[attr] = value
                    new_configs.append(new_config)
            else:
                new_configs.append(config)
        configs = new_configs

    # Filter out invalid combinations
    valid_configs = []
    for config in configs:
        if config.get("parser_type") == "LLM_PARSE":
            if "framework" not in config and "model" in config:
                valid_configs.append(config)
        elif config.get("parser_type") == "STATIC_PARSE":
            if "model" not in config and "framework" in config:
                valid_configs.append(config)
        else:
            valid_configs.append(config)

    return valid_configs


def format_results(results: List[BenchmarkResult]) -> str:
    """Format benchmark results as a markdown table."""
    sorted_results = sorted(results, key=lambda x: x.similarity, reverse=True)

    md_lines = [
        "# Parser Benchmark Results\n",
        "| Rank | Parser Type | Model/Framework | Pages/Split | Threads | PDF Conv. | Similarity | Time (s) | Error |",
        "|------|-------------|-----------------|-------------|----------|-----------|------------|----------|--------|",
    ]

    for i, result in enumerate(sorted_results, 1):
        config = result.config
        error_msg = result.error if result.error else "-"

        row = [
            str(i),
            config.get("parser_type", "-"),
            config.get("model", config.get("framework", "-")),
            str(config.get("pages_per_split", "-")),
            str(config.get("max_threads", "-")),
            str(config.get("as_pdf", "-")),
            f"{result.similarity:.3f}",
            f"{result.execution_time:.2f}",
            error_msg,
        ]
        md_lines.append("| " + " | ".join(row) + " |")

    return "\n".join(md_lines)


def run_benchmarks(
    input_path: str,
    output_dir: str,
    test_attributes: List[str],
    benchmark_output_dir: str,
) -> List[BenchmarkResult]:
    """Run all benchmarks for given input(s) and return results."""
    # Get input/output file pairs
    file_pairs = get_input_output_pairs(input_path, output_dir)
    if not file_pairs:
        print("No matching input/output file pairs found!")
        return []

    # Generate test configurations based on first input file
    configs = generate_test_configs(file_pairs[0][0], test_attributes)

    # Run benchmarks
    results = []
    total_configs = len(configs)
    total_files = len(file_pairs)

    print(
        f"Running {total_configs} configurations across {total_files} file{'s' if total_files > 1 else ''}..."
    )

    for i, config in enumerate(configs, 1):
        print(f"Progress: {i}/{total_configs} - Testing config: {config}")

        # Run benchmark for each file
        file_results = []
        for input_file, ground_truth_path in file_pairs:
            with open(ground_truth_path, "r", encoding="utf-8") as f:
                ground_truth = f.read()
            result = run_benchmark_config(
                input_file, ground_truth, config, benchmark_output_dir
            )
            file_results.append(result)

        # Aggregate results if multiple files
        if len(file_results) > 1:
            result = aggregate_results(file_results)
        else:
            result = file_results[0]

        results.append(result)

    return results


def main():
    # Can be either a single file or directory
    input_path = "examples/inputs"
    output_dir = "examples/outputs"

    benchmark_output_dir = f"tests/outputs/benchmark_{int(time.time())}/"
    result_path = os.path.join(benchmark_output_dir, "results.md")
    os.makedirs(benchmark_output_dir, exist_ok=True)

    # Specify which attributes to test
    test_attributes = [
        # "parser_type",
        "model",
        # "framework",
        # "pages_per_split",
        # "max_threads",
        # "as_pdf",
    ]

    results = run_benchmarks(
        input_path, output_dir, test_attributes, benchmark_output_dir
    )
    if not results:
        return

    # Format and save results
    markdown_report = format_results(results)
    with open(result_path, "w", encoding="utf-8") as f:
        f.write(markdown_report)

    print(f"\nBenchmark complete! Results saved to {result_path}")

    # Print top 3 configurations
    top_results = sorted(results, key=lambda x: x.similarity, reverse=True)[:3]
    print("\nTop 3 Configurations:")
    for i, result in enumerate(top_results, 1):
        print(
            f"{i}. Similarity: {result.similarity:.3f}, Time: {result.execution_time:.2f}s"
        )
        print(f"   Config: {result.config}")


if __name__ == "__main__":
    main()
