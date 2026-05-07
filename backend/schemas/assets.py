from pydantic import BaseModel, Field


class CreateAssetRequest(BaseModel):
    asset_type: str = Field(min_length=1, max_length=16)
    symbol: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    market: str | None = Field(default=None, max_length=32)


class UpdateAssetRequest(BaseModel):
    asset_type: str | None = Field(default=None, min_length=1, max_length=16)
    symbol: str | None = Field(default=None, min_length=1, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    market: str | None = Field(default=None, max_length=32)
