from pydantic import BaseModel, ConfigDict, Field


class TerminalBase(BaseModel):
    terminal_name: str = Field(..., max_length=255)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    capacity: int = Field(..., ge=0)


class TerminalCreate(TerminalBase):
    pass


class TerminalRead(TerminalBase):
    model_config = ConfigDict(from_attributes=True)

    terminal_id: int
