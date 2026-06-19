"""Official LinkedIn API client for the content pipeline.

Posting goes through LinkedIn's versioned REST Posts API (no scraping, no
unofficial endpoints). The client handles 3-legged OAuth (one-time --login) and
text post creation for both member (personal) and organization (Page) authors.
"""
from .client import LinkedInClient, LinkedInError, TokenStore

__all__ = ["LinkedInClient", "LinkedInError", "TokenStore"]
