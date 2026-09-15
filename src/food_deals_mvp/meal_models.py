"""Shared meal classification contracts."""

from typing import Literal, Self

from pydantic import Field, model_validator

from .models import Contract

MealType = Literal["drink", "breakfast", "lunch", "dinner", "snack"]


class MealClassification(Contract):
    deal_id: str = Field(min_length=1)
    meal_types: list[MealType]

    @model_validator(mode="after")
    def unique_meal_types(self) -> Self:
        if len(self.meal_types) != len(set(self.meal_types)):
            raise ValueError("duplicate meal type")
        return self


class MealClassifications(Contract):
    classifications: list[MealClassification]

