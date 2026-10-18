"""Shared validated procedure contract for the web workspace and MCP proposals."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateSession(StrictModel):
    title: str = Field(min_length=1, max_length=200)


class ProcedureStep(StrictModel):
    goal: str = Field(min_length=1, max_length=500)
    check: str = Field(min_length=1, max_length=1000)
    action: Literal["upload", "select_media", "fill", "click", "verify_draft"] | None = None
    target: str | None = Field(default=None, min_length=1, max_length=200)
    input: Literal["filename", "caption"] | None = None

    @model_validator(mode="after")
    def validate_action_fields(self):
        if self.target is not None and not self.target.strip():
            raise ValueError("target label cannot be blank")
        if self.action is None:
            if self.target is not None or self.input is not None:
                raise ValueError("target and input require an action")
            return self
        required = {
            "upload": (True, "filename"),
            "select_media": (True, "filename"),
            "fill": (True, "caption"),
            "click": (True, None),
            "verify_draft": (False, None),
        }[self.action]
        if (self.target is not None) != required[0] or self.input != required[1]:
            raise ValueError(f"invalid fields for {self.action} action")
        return self


class Procedure(StrictModel):
    revision: StrictInt = Field(ge=1)
    steps: list[ProcedureStep] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_executable_order(self):
        actions = [step.action for step in self.steps if step.action is not None]
        if actions and actions not in (["upload", "fill", "click", "verify_draft"], ["select_media", "fill", "click", "verify_draft"]):
            raise ValueError("executable procedure actions must select_media or upload, then fill, click, verify_draft in order")
        return self
