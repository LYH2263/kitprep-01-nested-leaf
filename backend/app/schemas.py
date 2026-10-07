from pydantic import BaseModel, Field


class AdjustIn(BaseModel):
    delta: float = Field(gt=0)  # inbound only — book adjustments never subtract
