class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Admin uses its own inline scripts; management and visitor pages use external assets.
        if not request.path.startswith("/admin/"):
            response["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
            )
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.path.startswith(("/r/", "/b/")) or request.user.is_authenticated:
            response["Cache-Control"] = "private, no-store"
        return response
