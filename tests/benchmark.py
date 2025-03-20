from glob import glob
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from statistics import mean, stdev
from pathlib import Path

from dotenv import load_dotenv

from lexoid.api import parse
from lexoid.core.utils import calculate_similarity

load_dotenv()


@dataclass
class BenchmarkResult:
    config: Dict
    similarity: List[float]  # Store all similarity scores for iterations
    execution_time: List[float]  # Store all execution times for iterations
    cost: Optional[List[float]] = None
    error: Optional[str] = None


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
    input_path: str,
    ground_truth: str,
    config: Dict,
    output_save_dir: str = None,
    iterations: int = 1,
) -> BenchmarkResult:
    """Run a single benchmark configuration for a specified number of iterations."""
    similarities = []
    execution_times = []
    costs = []
    error = None

    for _ in range(iterations):
        try:
            start_time = time.time()
            config["api_cost_mapping"] = "tests/api_cost_mapping.json"
            result = parse(input_path, "LLM_PARSE", **config)
            execution_time = time.time() - start_time

            if output_save_dir:
                filename = (
                    f"{Path(input_path).stem}_"
                    + ", ".join(
                        [
                            f"{key}={str(value).replace('/', '_')}"
                            for key, value in config.items()
                        ]
                    )
                    + ".md"
                )
                with open(os.path.join(output_save_dir, filename), "w") as fp:
                    fp.write(result["raw"])

            similarity = calculate_similarity(result["raw"], ground_truth)
            similarities.append(similarity)
            execution_times.append(execution_time)
            costs.append(
                result["token_cost"]["output"] if "token_cost" in result else 0.0
            )
        except Exception as e:
            print(f"Error running benchmark for config: {config}\n{e}")
            error = str(e)
            break  # Stop further iterations if an error occurs

    return BenchmarkResult(
        config=config,
        similarity=similarities,
        execution_time=execution_times,
        cost=costs,
        error=error,
    )


def aggregate_results(results: List[BenchmarkResult]) -> BenchmarkResult:
    """Aggregate multiple benchmark results into a single result."""
    if not results:
        return None

    valid_results = [r for r in results if r.error is None]
    if valid_results:
        all_similarities = [s for r in valid_results for s in r.similarity]
        all_execution_times = [t for r in valid_results for t in r.execution_time]
        all_costs = [c for r in valid_results for c in r.cost]
        avg_similarity = mean(all_similarities)
        std_similarity = stdev(all_similarities) if len(all_similarities) > 1 else 0.0
        avg_execution_time = mean(all_execution_times)
        avg_cost = mean(all_costs)
        error = (
            None
            if len(valid_results) == len(results)
            else f"Failed: {len(results) - len(valid_results)}/{len(results)}"
        )
    else:
        avg_similarity = 0.0
        std_similarity = 0.0
        avg_execution_time = 0.0
        avg_cost = 0.0
        error = f"Failed: {len(results)}/{len(results)}"

    return BenchmarkResult(
        config=results[0].config,
        similarity=[avg_similarity, std_similarity],  # Store mean and std dev
        execution_time=[avg_execution_time],
        cost=[avg_cost],
        error=error,
    )


def generate_test_configs(input_path: str, test_attributes: List[str]) -> List[Dict]:
    """
    Generate different configuration combinations to test based on specified attributes.
    """
    config_options = {
        "parser_type": ["LLM_PARSE", "STATIC_PARSE"],
        "model": [
            # Google models
            "gemini-2.0-pro-exp",
            "gemini-2.0-flash",
            "gemini-2.0-flash-thinking-exp",
            "gemini-2.0-flash-001",
            "gemini-1.5-flash-8b",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            # OpenAI models
            "gpt-4o",
            "gpt-4o-mini",
            # Meta-LLAMA models through HF Hub
            "meta-llama/Llama-3.2-11B-Vision-Instruct",
            # Meta-LLAMA models through Together AI
            "meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo",
            "meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo",
            "meta-llama/Llama-Vision-Free",
            # Model through OpenRouter
            "google/gemma-3-27b-it",
            "qwen/qwen-2.5-vl-7b-instruct",
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


def format_results(results: List[BenchmarkResult], test_attributes: List[str]) -> str:
    """Format benchmark results as a markdown table, including only tested attributes."""
    sorted_results = sorted(results, key=lambda x: x.similarity[0], reverse=True)

    # Dynamically generate table headers based on test_attributes
    headers = ["Rank"]
    for attr in test_attributes:
        headers.append(attr.replace("_", " ").title())
    headers.extend(["Mean Similarity", "Std. Dev.", "Time (s)", "Cost ($)", "Error"])

    md_lines = [
        "# Parser Benchmark Results\n",
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]

    for i, result in enumerate(sorted_results, 1):
        config = result.config
        error_msg = result.error if result.error else "-"

        row = [str(i)]
        for attr in test_attributes:
            row.append(str(config.get(attr, "-")))
        row.extend(
            [
                f"{result.similarity[0]:.3f}",
                f"{result.similarity[1]:.3f}",
                f"{result.execution_time[0]:.2f}",
                f"{result.cost[0]}",
                error_msg,
            ]
        )
        md_lines.append("| " + " | ".join(row) + " |")

    return "\n".join(md_lines)


def run_benchmarks(
    input_path: str,
    output_dir: str,
    test_attributes: List[str],
    benchmark_output_dir: str,
    iterations: int = 3,
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
                input_file, ground_truth, config, benchmark_output_dir, iterations
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

    # Number of iterations for each benchmark
    iterations = 1

    results = run_benchmarks(
        input_path, output_dir, test_attributes, benchmark_output_dir, iterations
    )
    if not results:
        return

    # Format and save results
    markdown_report = format_results(results, test_attributes)
    with open(result_path, "w", encoding="utf-8") as f:
        f.write(markdown_report)

    print(f"\nBenchmark complete! Results saved to {result_path}")

    # Print top 3 configurations
    top_results = sorted(results, key=lambda x: x.similarity[0], reverse=True)[:3]
    print("\nTop 3 Configurations:")
    for i, result in enumerate(top_results, 1):
        print(
            f"{i}. Similarity: {result.similarity[0]:.3f} (±{result.similarity[1]:.3f}), Time: {result.execution_time[0]:.2f}s"
        )
        print(f"   Config: {result.config}")


if __name__ == "__main__":
    main()
