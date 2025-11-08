# Vertex AI Quick Start Guide

Simple setup for your two environments: **Local Development** and **GCP Cloud Run**.

## Prerequisites

- Google Cloud Project
- `gcloud` CLI installed

## One-Time Setup

### 1. Enable Vertex AI API

```bash
gcloud services enable aiplatform.googleapis.com
```

### 2. Create Service Account (for Cloud Run)

```bash
# Create service account
gcloud iam service-accounts create lexoid-vertex-ai \
    --display-name="Lexoid Vertex AI"

# Grant permissions
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
    --member="serviceAccount:lexoid-vertex-ai@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/aiplatform.user"
```

## Environment 1: Local Development

### Setup (once):

```bash
# Authenticate with your Google account
gcloud auth application-default login
```

### Usage:

**Set environment variables:**
```bash
export GCP_PROJECT="your-project-id"
export GCP_REGION="us-west1"  # Optional
```

**Or use .env file:**
```env
GCP_PROJECT=your-project-id
GCP_REGION=us-west1
```

**Run your application:**
```python
from lexoid import parse

result = parse("document.pdf", parser_type="LLM_PARSE")
print(result["raw"])
```

That's it! Authentication happens automatically via ADC.

## Environment 2: Local Docker Compose

### docker-compose.yml:

```yaml
version: '3.8'

services:
  app:
    build: .
    environment:
      - GCP_PROJECT=${GCP_PROJECT}
      - GCP_REGION=us-west1
    volumes:
      # Mount your local gcloud credentials
      - ~/.config/gcloud:/root/.config/gcloud:ro
      - ./data:/app/data
```

### Dockerfile:

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# Install git for pip to clone from GitHub
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Install Lexoid from your fork
RUN pip install git+https://github.com/jefffohl/Lexoid.git@vertex-ai-support

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "your_app.py"]
```

### Run:

```bash
# Ensure you're authenticated locally first
gcloud auth application-default login

# Set environment variables
export GCP_PROJECT="your-project-id"

# Run
docker-compose up
```

The container will use your local ADC credentials mounted from `~/.config/gcloud`.

## Environment 3: GCP Cloud Run

### Dockerfile:

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# Install git
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Install Lexoid from your fork
RUN pip install git+https://github.com/jefffohl/Lexoid.git@vertex-ai-support

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# For web services
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 app:app
```

### Deploy:

```bash
gcloud run deploy lexoid-app \
  --source . \
  --region us-west1 \
  --set-env-vars GCP_PROJECT=your-project-id \
  --set-env-vars GCP_REGION=us-west1 \
  --service-account=lexoid-vertex-ai@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --allow-unauthenticated
```

**That's it!** The service account is attached automatically - no keys needed.

## Verification

### Test locally:

```python
import os

# Check environment
print(f"Project: {os.environ.get('GCP_PROJECT')}")
print(f"Location: {os.environ.get('GCP_REGION', 'us-west1')}")

# Test parsing
from lexoid import parse
result = parse("test.pdf", parser_type="LLM_PARSE", model="gemini-2.0-flash")
print(f"✅ Parsed {len(result['segments'])} pages")
```

### Test Cloud Run:

```bash
# Deploy and test
gcloud run deploy lexoid-test --source . --region us-west1 \
  --set-env-vars GCP_PROJECT=your-project-id \
  --service-account=lexoid-vertex-ai@YOUR_PROJECT_ID.iam.gserviceaccount.com

# Get URL
URL=$(gcloud run services describe lexoid-test --region us-west1 --format='value(status.url)')

# Test endpoint
curl $URL/parse -X POST -F "file=@test.pdf"
```

## Troubleshooting

### "Permission denied" locally

```bash
# Re-authenticate
gcloud auth application-default login

# Or ensure you have the role
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
    --member="user:YOUR_EMAIL@gmail.com" \
    --role="roles/aiplatform.user"
```

### "Permission denied" in Cloud Run

```bash
# Verify service account has role
gcloud projects get-iam-policy YOUR_PROJECT_ID \
    --flatten="bindings[].members" \
    --filter="bindings.members:serviceAccount:lexoid-vertex-ai@*"

# Re-grant if needed
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
    --member="serviceAccount:lexoid-vertex-ai@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/aiplatform.user"
```

### Docker can't authenticate

```bash
# Ensure you're authenticated locally first
gcloud auth application-default login

# Verify credentials exist
ls ~/.config/gcloud/application_default_credentials.json

# Then run docker-compose
docker-compose up
```

## Summary

| Environment | Authentication Method | Setup Required |
|-------------|----------------------|----------------|
| **Local Python** | ADC from `gcloud auth application-default login` | One command |
| **Local Docker** | Mount ADC credentials to container | Volume mount |
| **Cloud Run** | Service account attached at deployment | Deploy flag |

**Key Point:** No service account keys to manage! Authentication is automatic via Application Default Credentials.

## Next Steps

1. Test locally first
2. Test in Docker locally  
3. Deploy to Cloud Run staging
4. Submit PR to upstream Lexoid repository

See [TESTING_GUIDE.md](TESTING_GUIDE.md) for more detailed testing scenarios.

