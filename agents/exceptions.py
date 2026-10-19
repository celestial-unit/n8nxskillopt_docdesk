"""agents/exceptions.py — Pipeline exception hierarchy."""

class PipelineError(Exception):
    """Base exception for all pipeline errors."""
    pass

class AgentParseError(PipelineError):
    """Raised when an agent cannot parse the LLM response as valid JSON."""
    pass

class RAGEngineError(PipelineError):
    """Raised when the RAG engine fails."""
    pass

class SkillNotFoundError(PipelineError):
    """Raised when no skill file is found for an agent."""
    pass
