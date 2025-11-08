# Testing Your Fork in Other Projects

This guide explains how to test your forked version of Lexoid with Vertex AI support in other projects before submitting a PR.

## Option 1: Install from GitHub (Recommended)

### A. Using pip (requirements.txt)

In your dependent project's `requirements.txt`:

```txt
# Install from your fork's specific branch
lexoid @ git+https://github.com/YOUR_USERNAME/Lexoid.git@vertex-ai-support

# Or from a specific commit
lexoid @ git+https://github.com/YOUR_USERNAME/Lexoid.git@abc123def456
```

Then install:
```bash
pip install -r requirements.txt
```

### B. Using Poetry (pyproject.toml)

In your dependent project's `pyproject.toml`:

```toml
[tool.poetry.dependencies]
python = "^3.10"
lexoid = {git = "https://github.com/YOUR_USERNAME/Lexoid.git", branch = "vertex-ai-support"}

# Or with a specific tag/commit
lexoid = {git = "https://github.com/YOUR_USERNAME/Lexoid.git", rev = "v0.1.19"}
```

Then install:
```bash
poetry install
```

### C. Direct pip install (for quick testing)

```bash
pip install git+https://github.com/YOUR_USERNAME/Lexoid.git@vertex-ai-support
```

## Option 2: Local Development Installation

For rapid iteration during development:

### A. Using pip in editable mode

```bash
# In your Lexoid fork directory
pip install -e .

# Or from another directory
pip install -e /path/to/Lexoid
```

### B. Using Poetry

```bash
# In your Lexoid fork directory
poetry install

# In your dependent project
poetry add --editable /path/to/Lexoid
```

## Testing in Docker Compose

### Method 1: Install from GitHub in Container

**docker-compose.yml:**
```yaml
version: '3.8'

services:
  app:
    build:
      context: .
      args:
        LEXOID_REPO: https://github.com/YOUR_USERNAME/Lexoid.git
        LEXOID_BRANCH: vertex-ai-support
    environment:
      - GCP_PROJECT=${GCP_PROJECT}
      - GCP_REGION=${GCP_REGION}
      # Note: In Cloud Run, credentials are automatic
      # For local Docker, mount your ADC credentials:
      # - GOOGLE_APPLICATION_CREDENTIALS=/root/.config/gcloud/application_default_credentials.json
    volumes:
      - ~/.config/gcloud:/root/.config/gcloud:ro  # Mount ADC for local testing
      - ./data:/app/data
    command: python your_app.py
```

**Dockerfile:**
```dockerfile
FROM python:3.10-slim

WORKDIR /app

# Install git (needed for pip to clone from GitHub)
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .

# Install Lexoid from your fork
ARG LEXOID_REPO
ARG LEXOID_BRANCH
RUN pip install git+${LEXOID_REPO}@${LEXOID_BRANCH}

# Install other dependencies
RUN pip install -r requirements.txt

# Copy application code
COPY . .

CMD ["python", "your_app.py"]
```

**requirements.txt:**
```txt
# Your other dependencies
python-dotenv
loguru
# Don't include lexoid here - it's installed via ARG in Dockerfile
```

**Build and run:**
```bash
docker-compose build
docker-compose up
```

### Method 2: Mount Local Lexoid for Development

For faster iteration without rebuilding:

**docker-compose.yml:**
```yaml
version: '3.8'

services:
  app:
    build: .
    environment:
      - GCP_PROJECT=${GCP_PROJECT}
      - GCP_REGION=${GCP_REGION}
      - PYTHONPATH=/app/lexoid-dev
    volumes:
      - ~/.config/gcloud:/root/.config/gcloud:ro  # Mount ADC credentials
      - ../Lexoid:/app/lexoid-dev:ro  # Mount your local Lexoid
      - ./data:/app/data
    command: python your_app.py
```

**Dockerfile:**
```dockerfile
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# Install Lexoid dependencies (without Lexoid itself)
RUN pip install google-cloud-aiplatform google-generativeai openai

COPY . .

CMD ["python", "your_app.py"]
```

## Testing on GCP Staging Server

### Method 1: Install from GitHub

On your GCP VM or Cloud Run:

**If using Cloud Run with Dockerfile:**

```dockerfile
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Install from your fork
RUN pip install git+https://github.com/YOUR_USERNAME/Lexoid.git@vertex-ai-support

COPY . .

CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app
```

**Deploy:**
```bash
gcloud run deploy lexoid-test \
  --source . \
  --region us-west1 \
  --set-env-vars GCP_PROJECT=your-project-id \
  --set-env-vars GCP_REGION=us-west1 \
  --service-account=lexoid-vertex-ai@your-project.iam.gserviceaccount.com
```

### Method 2: Using Compute Engine VM

SSH into your VM and install:

```bash
# SSH into your staging server
gcloud compute ssh your-instance --zone=us-west1-a

# Install your fork
pip install git+https://github.com/YOUR_USERNAME/Lexoid.git@vertex-ai-support

# Or clone and install in editable mode for development
git clone -b vertex-ai-support https://github.com/YOUR_USERNAME/Lexoid.git
cd Lexoid
pip install -e .
```

### Method 3: Using Cloud Build

**cloudbuild.yaml:**
```yaml
steps:
  # Build the container
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'build'
      - '--build-arg'
      - 'LEXOID_REPO=https://github.com/YOUR_USERNAME/Lexoid.git'
      - '--build-arg'
      - 'LEXOID_BRANCH=vertex-ai-support'
      - '-t'
      - 'gcr.io/$PROJECT_ID/your-app:$SHORT_SHA'
      - '.'

  # Push to Container Registry
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/your-app:$SHORT_SHA']

  # Deploy to Cloud Run
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - 'run'
      - 'deploy'
      - 'lexoid-test'
      - '--image'
      - 'gcr.io/$PROJECT_ID/your-app:$SHORT_SHA'
      - '--region'
      - 'us-west1'
      - '--platform'
      - 'managed'

images:
  - 'gcr.io/$PROJECT_ID/your-app:$SHORT_SHA'
```

## Complete Testing Workflow

### 1. Local Docker Testing

```bash
# In your dependent project
cat > docker-compose.test.yml <<EOF
version: '3.8'
services:
  test:
    build:
      context: .
      dockerfile: Dockerfile.test
    environment:
      - GCP_PROJECT=${GCP_PROJECT}
      - GCP_REGION=us-west1
    volumes:
      - ~/.config/gcloud:/root/.config/gcloud:ro  # Mount ADC credentials
    command: python -m pytest tests/
EOF

# Build and test
docker-compose -f docker-compose.test.yml build
docker-compose -f docker-compose.test.yml run test
```

### 2. Create a Test Script

**test_vertex_ai_integration.py:**
```python
"""
Integration test for Vertex AI in your dependent project
"""
import os
from lexoid import parse

def test_vertex_ai_parsing():
    """Test that Vertex AI is working"""
    # Verify Vertex AI is configured
    assert os.environ.get("GCP_PROJECT"), "GCP_PROJECT not set"
    
    # Test parsing
    result = parse(
        "test_document.pdf",
        parser_type="LLM_PARSE",
        model="gemini-2.0-flash"
    )
    
    assert result["raw"], "No content parsed"
    assert result["segments"], "No segments found"
    assert result["token_usage"]["total"] > 0, "No tokens used"
    
    print("✅ Vertex AI integration test passed!")
    print(f"   Parsed {len(result['segments'])} segments")
    print(f"   Used {result['token_usage']['total']} tokens")

if __name__ == "__main__":
    test_vertex_ai_parsing()
```

### 3. GCP Staging Deployment

```bash
#!/bin/bash
# deploy_staging.sh

set -e

echo "🚀 Deploying to GCP staging..."

# Build with your fork
gcloud builds submit \
  --config=cloudbuild.yaml \
  --substitutions=_LEXOID_REPO="https://github.com/YOUR_USERNAME/Lexoid.git",_LEXOID_BRANCH="vertex-ai-support"

echo "✅ Deployed to staging!"
echo "🧪 Run integration tests..."

# Run integration tests against staging
python test_staging.py
```

## Verifying Your Installation

### Check installed version:

```python
import lexoid
import os

# Check version
print(f"Lexoid version: {lexoid.__version__}")

# Verify Vertex AI support
from lexoid.core.parse_type.llm_parser import parse_image_with_gemini
import inspect
source = inspect.getsource(parse_image_with_gemini)
if "GCP_PROJECT" in source:
    print("✅ Vertex AI support is present")
else:
    print("❌ Vertex AI support not found - wrong version?")
```

### Quick functionality test:

```python
import os
from lexoid import parse

# Set Vertex AI config
os.environ["GCP_PROJECT"] = "your-project-id"
os.environ["GCP_REGION"] = "us-west1"

# Test parse
result = parse("test.pdf", parser_type="LLM_PARSE", model="gemini-2.0-flash")
print(f"✅ Successfully parsed {len(result['segments'])} pages")
```

## Troubleshooting

### Issue: "Module not found: lexoid"

**Solution:** Ensure git is installed in Docker:
```dockerfile
RUN apt-get update && apt-get install -y git
```

### Issue: "Permission denied" on GCP

**Solution:** Ensure service account has proper permissions:
```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
    --member="serviceAccount:YOUR_SA@PROJECT.iam.gserviceaccount.com" \
    --role="roles/aiplatform.user"
```

### Issue: Wrong version installed

**Solution:** Force reinstall:
```bash
pip uninstall lexoid -y
pip install --no-cache-dir git+https://github.com/YOUR_USERNAME/Lexoid.git@vertex-ai-support
```

### Issue: Changes not reflected

**Solution:** Clear pip cache:
```bash
pip cache purge
pip install --force-reinstall --no-deps git+https://github.com/YOUR_USERNAME/Lexoid.git@vertex-ai-support
```

## Best Practices

1. **Use specific commits or tags** for reproducible builds:
   ```bash
   pip install git+https://github.com/YOUR_USERNAME/Lexoid.git@abc123def
   ```

2. **Pin dependencies** in production:
   ```txt
   lexoid @ git+https://github.com/YOUR_USERNAME/Lexoid.git@v0.1.19
   ```

3. **Use private repository** if needed:
   ```bash
   pip install git+https://YOUR_TOKEN@github.com/YOUR_USERNAME/Lexoid.git@branch
   ```

4. **Test locally first**, then Docker, then GCP staging

5. **Keep your fork synced** with upstream before testing

## Preparing for PR Submission

Once testing is complete:

1. **Document your changes** (already done ✅)
2. **Ensure all tests pass**:
   ```bash
   pytest tests/test_vertex_ai.py -v
   ```
3. **Update version** to match upstream (done ✅)
4. **Create PR** with clear description of Vertex AI benefits
5. **Reference documentation** you created

## Summary

**For Local Docker:**
```bash
# In your dependent project's Dockerfile
RUN pip install git+https://github.com/YOUR_USERNAME/Lexoid.git@vertex-ai-support
```

**For GCP Staging:**
```bash
# In Cloud Run Dockerfile or VM
RUN pip install git+https://github.com/YOUR_USERNAME/Lexoid.git@vertex-ai-support
```

**For Development:**
```bash
# Editable install
pip install -e /path/to/Lexoid
```

This allows you to thoroughly test your Vertex AI implementation before submitting the PR! 🚀

