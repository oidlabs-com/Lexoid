# Vertex AI Migration Guide

## Overview

This guide explains the changes made to Lexoid to support Google Cloud Vertex AI for enhanced data privacy and compliance.

## What Changed

### Core Implementation (`lexoid/core/parse_type/llm_parser.py`)

The `parse_image_with_gemini()` function has been updated to:

1. **Detect configuration mode** - Automatically switches between standard Gemini API and Vertex AI based on environment variables
2. **Support OAuth2 authentication** - Uses Google Cloud credentials for Vertex AI
3. **Maintain backward compatibility** - Existing code using `GOOGLE_API_KEY` continues to work unchanged

### Key Changes:

**Before** (Hardcoded endpoint):
```python
url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
```

**After** (Dynamic endpoint selection):
```python
# Automatically selects endpoint based on GCP_PROJECT presence
if use_vertex_ai:
    url = f"https://{vertex_location}-aiplatform.googleapis.com/v1/projects/{vertex_project_id}/..."
    headers = {"Authorization": f"Bearer {credentials.token}", ...}
else:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
```

## Migration Steps

### For New Projects (Using Vertex AI)

1. **Install dependencies:**
   ```bash
   poetry install
   # This will install google-cloud-aiplatform
   ```

2. **Set up Google Cloud:**
   ```bash
   # Enable Vertex AI API
   gcloud services enable aiplatform.googleapis.com
   
   # Create service account
   gcloud iam service-accounts create lexoid-vertex-ai
   
   # Grant permissions
   gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
       --member="serviceAccount:lexoid-vertex-ai@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
       --role="roles/aiplatform.user"
   
   # Create key
   gcloud iam service-accounts keys create ~/lexoid-vertex-key.json \
       --iam-account=lexoid-vertex-ai@YOUR_PROJECT_ID.iam.gserviceaccount.com
   ```

3. **Configure environment:**
   ```bash
   export GCP_PROJECT="your-project-id"
   export GCP_REGION="us-west1"
   export GOOGLE_APPLICATION_CREDENTIALS="$HOME/lexoid-vertex-key.json"
   ```

4. **Use Lexoid normally:**
   ```python
   from lexoid import parse
   
   result = parse("document.pdf", parser_type="LLM_PARSE")
   # Automatically uses Vertex AI!
   ```

### For Existing Projects (No Changes Required)

**Your existing code continues to work unchanged:**

```python
# Existing code - still works!
import os
os.environ["GOOGLE_API_KEY"] = "your-api-key"

from lexoid import parse
result = parse("document.pdf", parser_type="LLM_PARSE")
```

**No migration required** unless you want enhanced privacy features.

## Environment Variables Reference

### Vertex AI Mode (New)
```bash
GCP_PROJECT=your-project-id          # Required to enable Vertex AI
GCP_REGION=us-west1                # Optional, defaults to us-west1
GOOGLE_APPLICATION_CREDENTIALS=/path/to/key   # Service account key path
```

### Standard Gemini API Mode (Existing)
```bash
GOOGLE_API_KEY=your-api-key                   # Still works as before
```

## Testing Your Setup

### Test Vertex AI:
```bash
cd examples
python example_vertex_ai.py --vertex-ai
```

### Test Standard Gemini API:
```bash
cd examples
python example_vertex_ai.py --gemini-api
```

### Run Unit Tests:
```bash
pytest tests/test_vertex_ai.py -v
```

## Benefits of Using Vertex AI

| Feature | Standard Gemini API | Vertex AI |
|---------|-------------------|-----------|
| **Data Privacy** | Data processed on Google's public infrastructure | Data stays in your GCP project |
| **Compliance** | Standard terms | Enterprise compliance (HIPAA, SOC 2, etc.) |
| **Audit Logs** | Limited | Full Cloud Audit Logs |
| **VPC Integration** | No | Yes (additional configuration) |
| **Data Residency** | No control | Choose your region |
| **Cost** | Per-request pricing | Enterprise pricing |
| **Setup Complexity** | Very simple (API key) | Moderate (GCP project required) |

## Common Issues

### Issue: "ImportError: google-cloud-aiplatform is required"
**Solution:** Install the package:
```bash
pip install google-cloud-aiplatform
# or
poetry install
```

### Issue: "Authentication failed"
**Solution:** Verify your credentials:
```bash
# Test authentication
gcloud auth application-default print-access-token

# Verify service account has permissions
gcloud projects get-iam-policy YOUR_PROJECT_ID \
    --flatten="bindings[].members" \
    --filter="bindings.members:serviceAccount:YOUR_SA@PROJECT.iam.gserviceaccount.com"
```

### Issue: "Region not found"
**Solution:** Use a supported region:
```bash
# Common regions
export GCP_REGION="us-west1"      # Iowa
export GCP_REGION="us-east1"         # South Carolina
export GCP_REGION="europe-west1"     # Belgium
export GCP_REGION="asia-southeast1"  # Singapore
```

## Performance Considerations

- **Latency**: Vertex AI may have slightly higher latency due to OAuth2 token refresh
- **Cost**: Check Vertex AI pricing (may differ from public API)
- **Rate Limits**: Vertex AI has project-level quotas

## Security Best Practices

1. ✅ Use service accounts (not personal credentials)
2. ✅ Rotate service account keys regularly
3. ✅ Use minimal IAM permissions (`roles/aiplatform.user` only)
4. ✅ Store credentials securely (never in code)
5. ✅ Enable Cloud Audit Logs
6. ✅ Use Secret Manager for production deployments

## Files Modified

1. **`pyproject.toml`** - Added `google-cloud-aiplatform` dependency
2. **`lexoid/core/parse_type/llm_parser.py`** - Updated `parse_image_with_gemini()`
3. **`README.md`** - Added Vertex AI documentation
4. **`CHANGELOG.md`** - Documented new feature

## Files Added

1. **`docs/vertex_ai_setup.md`** - Comprehensive setup guide
2. **`examples/example_vertex_ai.py`** - Example usage script
3. **`tests/test_vertex_ai.py`** - Unit tests
4. **`VERTEX_AI_MIGRATION_GUIDE.md`** - This file

## Support

For issues or questions:
- See the [Vertex AI Setup Guide](docs/vertex_ai_setup.md)
- Check [Google Cloud Vertex AI Documentation](https://cloud.google.com/vertex-ai/docs)
- File an issue on the Lexoid repository

## Summary

✅ **Zero Breaking Changes** - Existing code continues to work  
✅ **Opt-in Feature** - Only enabled when `GCP_PROJECT` is set  
✅ **Enhanced Privacy** - Data stays in your GCP project  
✅ **Enterprise Ready** - Compliance and audit features  
✅ **Well Tested** - Unit tests and examples included  

The implementation follows the YAGNI and KISS principles - it's a simple, clean addition that doesn't complicate the existing codebase.

