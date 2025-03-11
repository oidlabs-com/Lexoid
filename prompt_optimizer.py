import os
from typing import List, Dict, Tuple
from dataclasses import dataclass
import difflib
import json
from pathlib import Path
import time

from lexoid.core.parse_type.llm_parser import parse_llm_doc
from lexoid.core.prompt_templates import (
    OPENAI_SYSTEM_PROMPT,
    OPENAI_USER_PROMPT,
    PARSER_PROMPT,
    LLAMA_PARSER_PROMPT,
)
from lexoid.core.utils import calculate_similarity, remove_html_tags


@dataclass
class DocumentPair:
    input_path: str
    ground_truth_path: str


class PromptOptimizer:
    def __init__(
        self,
        document_pairs: List[DocumentPair],
        initial_prompt: str,
        model: str = "gemini-1.5-flash",
        prompt_name: str = "PARSER_PROMPT",
        iterations: int = 5,
        batch_size: int = 5,
    ):
        self.document_pairs = document_pairs
        self.current_prompt = initial_prompt
        self.model = model
        self.prompt_name = prompt_name
        self.iterations = iterations
        self.batch_size = batch_size
        self.best_prompt = initial_prompt
        self.best_similarity = 0.0

    def generate_markdown(self, doc_path: str) -> str:
        """Generate markdown using the current prompt."""
        prompt_name = self.prompt_name
        if prompt_name == "PARSER_PROMPT" or prompt_name == "LLAMA_PARSER_PROMPT":
            result = parse_llm_doc(
                path=doc_path,
                raw=True,
                model=self.model,
                custom_prompt=self.current_prompt,
                title="test",
                pages_per_split_=1,
            )
        elif prompt_name == "OPENAI_SYSTEM_PROMPT":
            result = parse_llm_doc(
                path=doc_path,
                raw=True,
                model=self.model,
                system_prompt=self.current_prompt,
                title="test",
                pages_per_split_=1,
            )
        elif prompt_name == "OPENAI_USER_PROMPT":
            result = parse_llm_doc(
                path=doc_path,
                raw=True,
                model=self.model,
                user_prompt=self.current_prompt,
                title="test",
                pages_per_split_=1,
            )
        else:
            raise ValueError(f"Unknown prompt name: {prompt_name}")
        return result

    def calculate_diff(self, generated: str, ground_truth: str) -> str:
        """Calculate the difference between generated and ground truth markdown."""
        differ = difflib.Differ()
        diff = list(
            differ.compare(
                remove_html_tags(generated).splitlines(),
                remove_html_tags(ground_truth).splitlines(),
            )
        )
        return "\n".join(diff)

    def optimize_prompt_with_gemini(self, diffs: List[str]) -> str:
        """Use Gemini to optimize the prompt based on diffs."""
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable not set")

        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-pro")

        optimization_prompt = f"""
        You are a prompt optimization expert. Your task is to improve an LLM prompt used for converting documents to markdown.
        
        Current prompt:
        {self.current_prompt}
        
        Here are the differences between the generated markdown and ground truth for multiple documents:
        
        {'-' * 50}
        {'\n'.join(f'Document {i+1} diff:\n{diff}\n{"-" * 50}' for i, diff in enumerate(diffs))}
        
        Based on these differences, suggest an improved version of the prompt that:
        1. Addresses the common patterns of errors seen in the diffs
        2. Maintains the general structure and purpose of the original prompt
        3. Avoids overfitting to specific examples
        4. Keeps the essential instructions while adding or modifying rules to improve accuracy
        
        Return only the improved prompt without any explanations.
        """

        response = model.generate_content(optimization_prompt)
        return response.text.strip()

    def evaluate_prompt(self, prompt: str) -> float:
        """Evaluate a prompt's performance across all test documents."""
        similarities = []
        for pair in self.document_pairs:
            generated = self.generate_markdown(pair.input_path)
            with open(pair.ground_truth_path, "r") as f:
                ground_truth = f.read()
            print(len(generated), len(ground_truth))
            similarity = calculate_similarity(generated, ground_truth)
            similarities.append(similarity)
        return sum(similarities) / len(similarities)

    def optimize(self) -> Tuple[str, float]:
        """Run the optimization process for specified iterations."""
        for iteration in range(self.iterations):
            print(f"\nIteration {iteration + 1}/{self.iterations}")

            # Generate and collect diffs for batch_size documents
            diffs = []
            for pair in self.document_pairs[: self.batch_size]:
                generated = self.generate_markdown(pair.input_path)
                with open(pair.ground_truth_path, "r") as f:
                    ground_truth = f.read()
                diff = self.calculate_diff(generated, ground_truth)
                diffs.append(diff)

            # Get optimized prompt
            new_prompt = self.optimize_prompt_with_gemini(diffs)

            # Evaluate new prompt
            self.current_prompt = new_prompt
            current_similarity = self.evaluate_prompt(new_prompt)

            print(f"Current similarity: {current_similarity:.4f}")

            # Update best prompt if current is better
            if current_similarity > self.best_similarity:
                self.best_similarity = current_similarity
                self.best_prompt = new_prompt
                print("New best prompt found!")

            # Add delay to avoid API rate limits
            time.sleep(2)

        return self.best_prompt, self.best_similarity


def optimize_all_prompts(
    document_pairs: List[DocumentPair], output_dir: Path
) -> Dict[str, Tuple[str, float]]:
    """Optimize all prompts and save results."""
    prompts_and_models = {
        "PARSER_PROMPT": (PARSER_PROMPT, "gemini-1.5-flash"),
        # "OPENAI_SYSTEM_PROMPT": (OPENAI_SYSTEM_PROMPT, "gpt-3.5-turbo"),
        # "OPENAI_USER_PROMPT": (OPENAI_USER_PROMPT, "gpt-3.5-turbo"),
        # "LLAMA_PARSER_PROMPT": (
        #     LLAMA_PARSER_PROMPT,
        #     "meta-llama/Llama-3.2-11B-Vision-Instruct",
        # ),
    }

    results = {}

    for prompt_name, (prompt, model) in prompts_and_models.items():
        print(f"\nOptimizing {prompt_name}...")
        optimizer = PromptOptimizer(
            document_pairs, prompt, model, prompt_name=prompt_name
        )
        best_prompt, similarity = optimizer.optimize()

        results[prompt_name] = (best_prompt, similarity)

        # Save results
        output_path = output_dir / f"{prompt_name.lower()}_optimized.json"
        with open(output_path, "w") as f:
            json.dump(
                {
                    "original_prompt": prompt,
                    "optimized_prompt": best_prompt,
                    "similarity_score": similarity,
                },
                f,
                indent=2,
            )

    return results


if __name__ == "__main__":
    document_pairs = [
        DocumentPair(
            input_path=f"examples/inputs/test_{i}.pdf",
            ground_truth_path=f"examples/outputs/test_{i}.md",
        )
        for i in range(1, 6)
    ]

    output_dir = Path("optimized_prompts")
    output_dir.mkdir(exist_ok=True)

    results = optimize_all_prompts(document_pairs, output_dir)

    print("\nOptimization Results:")
    print("-" * 50)
    for prompt_name, (_, similarity) in results.items():
        print(f"{prompt_name}: {similarity:.4f}")
