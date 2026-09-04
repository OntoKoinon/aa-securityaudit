class MissingScopesError(Exception):
    def __init__(self, scopes, message="Missing required ESI scopes"):
        self.scopes = sorted(set(scopes or []))
        super().__init__(message)
