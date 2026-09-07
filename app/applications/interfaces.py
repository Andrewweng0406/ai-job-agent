from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.application import Application
from app.models.job import Job


class ApplicationAdapter(ABC):
    ats_type: str

    @abstractmethod
    def can_handle(self, job: Job) -> bool:
        """Return true only when this adapter safely supports the job workflow."""

    @abstractmethod
    def prepare(self, application: Application) -> Application:
        """Prepare local state and artifacts before opening an external workflow."""

    @abstractmethod
    def fill(self, application: Application) -> Application:
        """Fill supported application fields. Must return HUMAN_REQUIRED when ambiguous."""

    @abstractmethod
    def upload_resume(self, application: Application, resume_path: str) -> Application:
        """Upload an already generated resume artifact."""

    @abstractmethod
    def answer_questions(self, application: Application) -> Application:
        """Answer only questions grounded in the candidate profile."""

    @abstractmethod
    def validate(self, application: Application) -> Application:
        """Validate that the application is ready to submit."""

    @abstractmethod
    def submit(self, application: Application) -> Application:
        """Submit only when the adapter has explicit support for the workflow."""

    @abstractmethod
    def verify_submission(self, application: Application) -> bool:
        """Return true only with reliable success evidence."""

