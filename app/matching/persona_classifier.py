from __future__ import annotations

from app.models.enums import JobFamily, Persona


PERSONA_BY_FAMILY = {
    JobFamily.DATA_ANALYTICS: Persona.DATA,
    JobFamily.PRODUCT_PM: Persona.PRODUCT_PM,
    JobFamily.BUSINESS_SYSTEMS: Persona.BUSINESS_SYSTEMS,
    JobFamily.FINANCE: Persona.FINANCE,
    JobFamily.TECHNICAL: Persona.TECHNICAL,
}


def persona_for_family(job_family: JobFamily) -> Persona | None:
    return PERSONA_BY_FAMILY.get(job_family)

