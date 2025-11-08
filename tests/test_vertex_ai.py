"""
Unit tests for Vertex AI integration
"""
import os
import pytest
from unittest.mock import patch, MagicMock
from lexoid.core.parse_type.llm_parser import parse_image_with_gemini


class TestVertexAI:
    """Test Vertex AI functionality"""
    
    @patch('lexoid.core.parse_type.llm_parser.requests.post')
    @patch.dict(os.environ, {
        'GCP_PROJECT': 'test-project',
        'GCP_REGION': 'us-west1'
    }, clear=False)
    @patch('lexoid.core.parse_type.llm_parser.google.auth.default')
    def test_vertex_ai_endpoint_construction(self, mock_auth, mock_post):
        """Test that Vertex AI endpoint is correctly constructed"""
        # Mock authentication
        mock_credentials = MagicMock()
        mock_credentials.valid = True
        mock_credentials.token = 'mock-token'
        mock_auth.return_value = (mock_credentials, None)
        
        # Mock successful response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'candidates': [{
                'content': {
                    'parts': [{'text': 'Test output'}]
                }
            }],
            'usageMetadata': {
                'promptTokenCount': 100,
                'candidatesTokenCount': 50
            }
        }
        mock_post.return_value = mock_response
        
        # Call the function
        result = parse_image_with_gemini(
            base64_file='test_image_data',
            mime_type='image/png',
            model='gemini-2.0-flash',
            pages_per_split_=1
        )
        
        # Verify correct endpoint was called
        call_args = mock_post.call_args
        assert 'us-west1-aiplatform.googleapis.com' in call_args[1]['url']
        assert 'projects/test-project' in call_args[1]['url']
        assert 'models/gemini-2.0-flash' in call_args[1]['url']
        
        # Verify OAuth2 authentication
        headers = call_args[1]['headers']
        assert 'Authorization' in headers
        assert headers['Authorization'] == 'Bearer mock-token'
        
        # Verify result
        assert result['raw'] == 'Test output'
        assert result['token_usage']['input'] == 100
        assert result['token_usage']['output'] == 50
    
    @patch('lexoid.core.parse_type.llm_parser.requests.post')
    @patch.dict(os.environ, {'GOOGLE_API_KEY': 'test-api-key'}, clear=True)
    def test_standard_gemini_endpoint(self, mock_post):
        """Test that standard Gemini API endpoint is used when Vertex AI is not configured"""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'candidates': [{
                'content': {
                    'parts': [{'text': 'Test output'}]
                }
            }],
            'usageMetadata': {
                'promptTokenCount': 100,
                'candidatesTokenCount': 50
            }
        }
        mock_post.return_value = mock_response
        
        # Call the function (without GCP_PROJECT)
        result = parse_image_with_gemini(
            base64_file='test_image_data',
            mime_type='image/png',
            model='gemini-2.0-flash',
            pages_per_split_=1
        )
        
        # Verify correct endpoint was called
        call_args = mock_post.call_args
        assert 'generativelanguage.googleapis.com' in call_args[1]['url']
        assert 'key=test-api-key' in call_args[1]['url']
        
        # Verify no OAuth2 authentication (API key is in URL)
        headers = call_args[1]['headers']
        assert 'Authorization' not in headers
        
        # Verify result
        assert result['raw'] == 'Test output'
    
    @patch.dict(os.environ, {}, clear=True)
    def test_no_credentials_error(self):
        """Test that an error is raised when neither Vertex AI nor API key is configured"""
        with pytest.raises(ValueError) as excinfo:
            parse_image_with_gemini(
                base64_file='test_image_data',
                mime_type='image/png',
                model='gemini-2.0-flash',
                pages_per_split_=1
            )
        
        assert 'GOOGLE_API_KEY' in str(excinfo.value)
        assert 'GCP_PROJECT' in str(excinfo.value)
    
    @patch('lexoid.core.parse_type.llm_parser.requests.post')
    @patch.dict(os.environ, {
        'GCP_PROJECT': 'test-project',
        'GCP_REGION': 'europe-west1'
    }, clear=False)
    @patch('lexoid.core.parse_type.llm_parser.google.auth.default')
    def test_custom_location(self, mock_auth, mock_post):
        """Test that custom location is used in endpoint"""
        # Mock authentication
        mock_credentials = MagicMock()
        mock_credentials.valid = True
        mock_credentials.token = 'mock-token'
        mock_auth.return_value = (mock_credentials, None)
        
        # Mock successful response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'candidates': [{
                'content': {
                    'parts': [{'text': 'Test'}]
                }
            }],
            'usageMetadata': {
                'promptTokenCount': 10,
                'candidatesTokenCount': 5
            }
        }
        mock_post.return_value = mock_response
        
        # Call the function
        parse_image_with_gemini(
            base64_file='test_image_data',
            mime_type='image/png',
            model='gemini-2.0-flash',
            pages_per_split_=1
        )
        
        # Verify correct location in endpoint
        call_args = mock_post.call_args
        assert 'europe-west1-aiplatform.googleapis.com' in call_args[1]['url']
        assert 'locations/europe-west1' in call_args[1]['url']


class TestBackwardCompatibility:
    """Test backward compatibility with existing code"""
    
    @patch('lexoid.core.parse_type.llm_parser.requests.post')
    @patch.dict(os.environ, {'GOOGLE_API_KEY': 'test-key'}, clear=True)
    def test_existing_code_still_works(self, mock_post):
        """Verify that existing code using GOOGLE_API_KEY continues to work"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'candidates': [{
                'content': {
                    'parts': [{'text': 'Output'}]
                }
            }],
            'usageMetadata': {
                'promptTokenCount': 50,
                'candidatesTokenCount': 25
            }
        }
        mock_post.return_value = mock_response
        
        # This should work exactly as before
        result = parse_image_with_gemini(
            base64_file='data',
            mime_type='image/png',
            model='gemini-2.0-flash',
            pages_per_split_=1
        )
        
        assert 'raw' in result
        assert 'segments' in result
        assert 'token_usage' in result
        assert result['token_usage']['input'] == 50
        assert result['token_usage']['output'] == 25


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

