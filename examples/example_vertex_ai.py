"""
Example script demonstrating Vertex AI usage with Lexoid
"""
import os
from lexoid import parse

def test_vertex_ai():
    """Test parsing with Vertex AI endpoint"""
    # Ensure Vertex AI environment variables are set
    project_id = os.environ.get("GCP_PROJECT")
    location = os.environ.get("GCP_REGION", "us-west1")
    
    if not project_id:
        print("Error: GCP_PROJECT environment variable not set")
        print("Please set it to your Google Cloud project ID")
        return
    
    print(f"Using Vertex AI with project: {project_id} in {location}")
    
    # Parse a sample document
    result = parse(
        "inputs/sample_test_doc.pdf",
        parser_type="LLM_PARSE",
        model="gemini-2.0-flash",
        temperature=0.0
    )
    
    print("\n=== Parsing Results ===")
    print(f"Title: {result['title']}")
    print(f"Number of segments: {len(result['segments'])}")
    print(f"Token usage: {result['token_usage']}")
    print(f"\nFirst 200 characters:\n{result['raw'][:200]}...")
    
    return result

def test_standard_gemini():
    """Test parsing with standard Gemini API endpoint"""
    api_key = os.environ.get("GOOGLE_API_KEY")
    
    if not api_key:
        print("Error: GOOGLE_API_KEY environment variable not set")
        return
    
    # Ensure Vertex AI is disabled for this test
    vertex_project = os.environ.pop("GCP_PROJECT", None)
    
    print("Using standard Gemini API endpoint")
    
    try:
        result = parse(
            "inputs/sample_test_doc.pdf",
            parser_type="LLM_PARSE",
            model="gemini-2.0-flash",
            temperature=0.0
        )
        
        print("\n=== Parsing Results ===")
        print(f"Title: {result['title']}")
        print(f"Number of segments: {len(result['segments'])}")
        print(f"Token usage: {result['token_usage']}")
        print(f"\nFirst 200 characters:\n{result['raw'][:200]}...")
        
        return result
    finally:
        # Restore Vertex AI setting if it was set
        if vertex_project:
            os.environ["GCP_PROJECT"] = vertex_project

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--vertex-ai":
        print("Testing Vertex AI mode...")
        test_vertex_ai()
    elif len(sys.argv) > 1 and sys.argv[1] == "--gemini-api":
        print("Testing standard Gemini API mode...")
        test_standard_gemini()
    else:
        print("Usage:")
        print("  python example_vertex_ai.py --vertex-ai     # Test with Vertex AI")
        print("  python example_vertex_ai.py --gemini-api   # Test with standard Gemini API")
        print("\nEnvironment variables needed:")
        print("  For Vertex AI:")
        print("    - GCP_PROJECT (required)")
        print("    - GCP_REGION (optional, defaults to us-west1)")
        print("    - GOOGLE_APPLICATION_CREDENTIALS (path to service account key)")
        print("\n  For standard Gemini API:")
        print("    - GOOGLE_API_KEY")

