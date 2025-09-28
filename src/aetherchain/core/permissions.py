from rest_framework import permissions
from django.conf import settings

class IsBearerAuthenticated(permissions.BasePermission):
    """
    Custom permission to only allow access to clients with a valid Bearer token.
    (Corrected version with robust string stripping)
    """

    def has_permission(self, request, view):
        # Retrieve the API_TOKEN from Django settings and strip whitespace
        api_token = getattr(settings, 'API_TOKEN', None)
        if api_token:
            api_token = api_token.strip()

        # If the API_TOKEN is not configured or is empty, deny access
        if not api_token:
            return False

        # Get the 'Authorization' header from the incoming request
        auth_header = request.headers.get('Authorization')

        # If the header is missing, deny access
        if not auth_header:
            return False

        # Check if the header format is "Bearer <token>"
        try:
            auth_type, provided_token = auth_header.split()
            provided_token = provided_token.strip()
            if auth_type.lower() != 'bearer':
                return False
        except (ValueError, AttributeError):
            # Header is malformed (e.g., doesn't contain a space)
            return False
        
        # Compare the provided token with the expected token
        return provided_token == api_token
