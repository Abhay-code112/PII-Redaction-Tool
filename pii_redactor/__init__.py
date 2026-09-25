"""PII redaction for Word documents: detect, pseudonymise, write back."""
from .pipeline import Redactor, Policy

__all__ = ["Redactor", "Policy"]
