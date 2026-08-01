class CreatorIntelligenceError(Exception):
    """Base application error."""

class DatabaseError(CreatorIntelligenceError):
    """Database operation failed."""

class MigrationError(DatabaseError):
    """Database migration failed."""

class ValidationError(CreatorIntelligenceError):
    """User input or imported data failed validation."""
