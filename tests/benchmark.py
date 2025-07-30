import os
import time
from dataclasses import dataclass
from glob import glob
from pathlib import Path
from statistics import mean, stdev
from typing import Dict, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv

from lexoid.api import parse
from benchmark_utils import calculate_similarities

load_dotenv()

config_options = {
    "parser_type": ["LLM_PARSE", "STATIC_PARSE", "AUTO"],
    "model": [
        # # Google models
        # "gemini-2.5-flash",
        # "gemini-2.5-pro",
        # "gemini-2.0-flash",
        # "gemini-2.0-flash-thinking-exp",
        # "gemini-2.0-flash-001",
        # "gemini-1.5-flash-8b",
        # "gemini-1.5-flash",
        # "gemini-1.5-pro",
        # # Claude models
        # "claude-opus-4-20250514",
        # "claude-sonnet-4-20250514",
        # "claude-3-7-sonnet-20250219",
        # "claude-3-5-sonnet-20241022",
        # # OpenAI models
        # "gpt-4.1",
        # "gpt-4.1-mini",
        # "gpt-4o",
        # "gpt-4o-mini",
        # Mistral models
        "mistral-ocr-latest",
        # # Meta-LLAMA models through HF Hub
        # "meta-llama/Llama-3.2-11B-Vision-Instruct",
        # # # Meta-LLAMA models through Together AI
        # "meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo",
        # "meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo",
        # "meta-llama/Llama-Vision-Free",
        # # # Model through OpenRouter
        # "qwen/qwen-2.5-vl-7b-instruct",
        # "google/gemma-3-27b-it",
        # "microsoft/phi-4-multimodal-instruct",
        # # # Model through fireworks
        # "accounts/fireworks/models/llama4-maverick-instruct-basic",
        # "accounts/fireworks/models/llama4-scout-instruct-basic",
        # Local model
        # "ds4sd/SmolDocling-256M-preview",
    ],
    "framework": ["pdfminer", "pdfplumber"],
    "pages_per_split": [1, 2, 4, 8],
    "max_threads": [1, 2, 4, 8],
    "as_pdf": [True, False],
    "temperature": [0.0, 0.2, 0.7],
}


@dataclass
class BenchmarkResult:
    config: Dict
    similarities: List[Dict]
    mean_similarity: Optional[Dict] = None
    std_similarity: Optional[Dict] = None
    execution_time: Optional[List[float]] = None
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
    input_files = sorted(glob(os.path.join(input_path, "*")))
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
            config["parser_type"] = config.get(
                "parser_type",
                (
                    "LLM_PARSE"
                    if "model" in config
                    else ("STATIC_PARSE" if "framework" in config else "AUTO")
                ),
            )
            result = parse(
                input_path,
                pages_per_split=1,
                api_cost_mapping="tests/api_cost_mapping.json",
                max_processes=1,
                **config,
            )
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
                    + f"{int(start_time)}.md"
                )
                with open(os.path.join(output_save_dir, filename), "w") as fp:
                    fp.write(result["raw"])

            diff_path = os.path.join(
                output_save_dir, f"{Path(input_path).stem}_diff.txt"
            )
            similarity_dict = calculate_similarities(
                result["raw"],
                ground_truth,
                diff_save_path=diff_path,
            )
            similarities.append(similarity_dict)
            execution_times.append(execution_time)
            costs.append(
                result["token_cost"]["total"] if "token_cost" in result else 0.0
            )
        except Exception as e:
            print(f"Error running benchmark for config: {config}\n{e}")
            error = str(e)
            break  # Stop further iterations if an error occurs

    mean_similarity = (
        {metric: mean([s[metric] for s in similarities]) for metric in similarities[0]}
        if similarities
        else None
    )
    std_similarity = (
        {metric: stdev([s[metric] for s in similarities]) for metric in similarities[0]}
        if len(similarities) > 1
        else {metric: 0.0 for metric in similarities[0]}
    )

    return BenchmarkResult(
        config=config,
        similarities=similarities,
        mean_similarity=mean_similarity,
        std_similarity=std_similarity,
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
        all_similarities = [s for r in valid_results for s in r.similarities]
        all_execution_times = [t for r in valid_results for t in r.execution_time]
        all_costs = [c for r in valid_results for c in r.cost]
        avg_similarity = {
            metric: mean([s[metric] for s in all_similarities])
            for metric in all_similarities[0]
        }
        std_similarity = (
            {
                metric: stdev([s[metric] for s in all_similarities])
                for metric in all_similarities[0]
            }
            if len(all_similarities) > 1
            else {metric: 0.0 for metric in avg_similarity}
        )
        avg_execution_time = mean(all_execution_times)
        avg_cost = mean(all_costs)
        error = (
            None
            if len(valid_results) == len(results)
            else f"Failed: {len(results) - len(valid_results)}/{len(results)}"
        )
    else:
        avg_similarity = {}
        std_similarity = {}
        avg_execution_time = 0.0
        avg_cost = 0.0
        error = f"Failed: {len(results)}/{len(results)}"

    return BenchmarkResult(
        config=results[0].config,
        similarities=[avg_similarity],
        mean_similarity=avg_similarity,
        std_similarity=std_similarity,
        execution_time=[avg_execution_time],
        cost=[avg_cost],
        error=error,
    )


def generate_test_configs(input_path: str, test_attributes: List[str]) -> List[Dict]:
    """
    Generate different configuration combinations to test based on specified attributes.
    """

    # Only test as_pdf if input is not a PDF
    is_pdf = input_path.lower().endswith(".pdf")
    if is_pdf and "as_pdf" in test_attributes:
        test_attributes.remove("as_pdf")

    configs = [{}]

    for attr in test_attributes:
        new_configs = []
        for config in configs:
            if attr == "parser_type" or attr == "temperature":
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

    return configs


def format_results(results: List[BenchmarkResult], test_attributes: List[str]) -> str:
    """Format benchmark results as a markdown table, including only tested attributes."""
    sorted_results = sorted(
        results, key=lambda x: x.similarities[0]["sequence_matcher"], reverse=True
    )

    # Dynamically generate table headers based on test_attributes
    headers = ["Rank"]
    for attr in test_attributes:
        headers.append(attr.replace("_", " ").title())
    for metric in results[0].similarities.keys():
        headers.append(metric.replace("_", " ").title())
    headers.extend(["Time (s)", "Cost ($)", "Error"])

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
                f"{result.similarities[0][metric]:.3f} (±{result.std_similarity[metric]:.3f})"
                for metric in result.std_similarity.keys()
            ]
        )
        row.extend(
            [
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
    results: List[BenchmarkResult] = []
    total_configs = len(configs)
    total_files = len(file_pairs)

    print(
        f"Running {total_configs} configurations across {total_files} file(s) for {iterations} iterations..."
    )

    all_results: List[Tuple[str, BenchmarkResult]] = []
    for i, config in enumerate(configs, 1):
        print(f"Progress: {i}/{total_configs} - Testing config: {config}")

        # Run benchmark for each file
        file_results = []
        for input_file, ground_truth_path in file_pairs:
            print(f"Running benchmark for file: {input_file}")
            with open(ground_truth_path, "r", encoding="utf-8") as f:
                ground_truth = f.read()
            result = run_benchmark_config(
                input_file, ground_truth, config, benchmark_output_dir, iterations
            )
            file_results.append(result)
            all_results.append((input_file, result))

        result = aggregate_results(file_results)

        results.append(result)

        # Format and save results
        save_format = "csv"
        if save_format == "markdown":
            markdown_report = format_results(results, test_attributes)
            result_path = os.path.join(benchmark_output_dir, "results.md")
            with open(result_path, "w", encoding="utf-8") as f:
                f.write(markdown_report)
        elif save_format == "csv":
            data = []
            for result in results:
                result_dict = {
                    "Model": result.config.get("model", "AUTO"),
                }
                for metric, value in result.similarities[0].items():
                    mean = value
                    std = result.std_similarity.get(metric, 0.0)
                    result_dict[metric] = f"{mean:.3f} (±{std:.3f})"
                result_dict["Time (s)"] = result.execution_time[0]
                result_dict["Cost ($)"] = result.cost[0]
                data.append(result_dict)
            df = pd.DataFrame(data)
            result_path = os.path.join(benchmark_output_dir, "results.csv")
            df.to_csv(result_path, index=False)

        print(f"\nBenchmark complete! Results saved to {result_path}")

    # Save document-wise results to CSV
    doc_results = []
    for input_file, result in all_results:
        if len(result.similarities) == 0:
            continue
        doc_result = {
            "Input File": os.path.basename(input_file),
        }
        for metric, value in result.similarities[0].items():
            mean = value
            std = result.std_similarity.get(metric, 0.0)
            doc_result[metric] = f"{mean:.3f} (±{std:.3f})"
        for key, value in result.config.items():
            doc_result[key] = value
        doc_result["Time (s)"] = result.execution_time[0]
        doc_result["Cost ($)"] = result.cost[0]
        doc_results.append(doc_result)
    doc_df = pd.DataFrame(doc_results)
    doc_result_path = os.path.join(benchmark_output_dir, "document_results.csv")
    doc_df.to_csv(doc_result_path, index=False)
    print(f"Document-wise results saved to {doc_result_path}")

    return results


def main():
    # Specify which attributes to test
    test_attributes = [
        # "parser_type",
        "model",
        # "framework",
        # "pages_per_split",
        # "max_threads",
        # "as_pdf",
        # "temperature",
    ]

    # Can be either a single file or directory
    input_path = "examples/inputs"
    output_dir = "examples/outputs"

    run_id = "_".join(
        f"{attr}={','.join(map(str, config_options[attr]))}" for attr in test_attributes
    )
    benchmark_output_dir = f"tests/outputs/benchmark_{run_id}_{int(time.time())}/"
    os.makedirs(benchmark_output_dir, exist_ok=True)

    # Number of iterations for each benchmark
    iterations = 1

    results = run_benchmarks(
        input_path, output_dir, test_attributes, benchmark_output_dir, iterations
    )

    # Print top 3 configurations
    top_results = sorted(
        results, key=lambda x: x.mean_similarity["sequence_matcher"], reverse=True
    )[:3]
    print("\nTop 3 Configurations:")
    for i, result in enumerate(top_results, 1):
        print(
            f"{i}. Similarity: {result.mean_similarity["sequence_matcher"]:.3f} (±{result.std_similarity["sequence_matcher"]:.3f}), Time: {result.execution_time[0]:.2f}s"
        )
        print(f"   Config: {result.config}")


if __name__ == "__main__":
    main()
