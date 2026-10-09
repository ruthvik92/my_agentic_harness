from typing import Annotated, Literal

from pydantic import Field, model_validator

from local_agent.contracts import Record

Ref = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_./-]{0,63}$")]
Node = Annotated[str, Field(pattern=r"^(0|[A-Za-z_][A-Za-z0-9_]{0,63})$")]
Value = Annotated[
    str, Field(pattern=r"^[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+|[pnuUmMkK]|[mM][eE][gG])?$")
]


class Evidence(Record):
    page: int = Field(ge=1)
    region: tuple[float, float, float, float]
    note: str = Field(max_length=2000)

    @model_validator(mode="after")
    def region_order(self):
        left, top, right, bottom = self.region
        if not 0 <= left < right <= 1 or not 0 <= top < bottom <= 1:
            raise ValueError("evidence region must be normalized left,top,right,bottom")
        return self


class Component(Record):
    ref: Ref
    kind: Literal["R", "C", "L", "D", "Q", "IC", "connector", "switch", "other"]
    value: Value | None = None
    nodes: tuple[Node, ...] = Field(default=(), max_length=32)
    part_number: str | None = Field(default=None, max_length=128)
    connection_status: Literal["observed", "uncertain", "boundary"] = Field(
        description="Observed requires empty uncertainty. Observed R/C/L require a matching reference prefix, a known numeric SPICE value and exactly two nodes. Missing values or untraced wires must be uncertain or boundary with an explanation. Potentiometers are other unless an explicit reviewed equivalent is supplied."
    )
    evidence: Evidence
    uncertainty: str = Field(default="", max_length=2000)


class CircuitGraph(Record):
    title: str = Field(min_length=1, max_length=256)
    pages: tuple[int, ...] = Field(min_length=1, max_length=10)
    coverage: Literal["partial", "selected_region"]
    components: tuple[Component, ...] = Field(min_length=1, max_length=1000)
    unresolved: tuple[str, ...] = Field(default=(), max_length=500)

    @model_validator(mode="after")
    def identities(self):
        refs = [component.ref.casefold() for component in self.components]
        if len(set(refs)) != len(refs):
            raise ValueError("duplicate component references")
        if any(c.evidence.page not in self.pages for c in self.components):
            raise ValueError("component evidence page must appear in pages")
        errors = []
        for component in self.components:
            if component.connection_status == "observed" and component.uncertainty.strip():
                errors.append(
                    f"{component.ref}: a component with uncertainty must be marked uncertain or boundary"
                )
            if component.kind in {"R", "C", "L"} and component.connection_status == "observed":
                if (
                    len(component.nodes) != 2
                    or not component.value
                    or component.ref[0].upper() != component.kind
                ):
                    errors.append(
                        f"{component.ref}: observed passive requires matching reference, value and two nodes; "
                        "mark uncertain with an explanation when values or connectivity are unknown"
                    )
            if component.connection_status != "observed" and not component.uncertainty:
                errors.append(
                    f"{component.ref}: uncertain/boundary component requires an explanation"
                )
        if errors:
            raise ValueError(
                "; ".join(errors[:20])
                + (f"; {len(errors) - 20} more violations" if len(errors) > 20 else "")
            )
        return self
