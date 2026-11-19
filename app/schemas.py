from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.utils.validators import validate_public_url


class LinkAnalysisRequest(BaseModel):
    url: str = Field(..., min_length=1, description="A public http(s) website URL to analyze.")

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        # Raises ValueError itself with a specific reason (bad scheme, no hostname,
        # unresolvable, or private/internal address).
        return validate_public_url(value)


class BrandInfo(BaseModel):
    name: str
    category: str
    summary: str


class CompetitorAnalysis(BaseModel):
    brand_overview: str
    main_products_services: list[str] = Field(default_factory=list)
    competitors: list[dict] = Field(default_factory=list)
    your_strengths: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    note: str | None = None


class SearchQuery(BaseModel):
    query: str
    platforms: list[str] = Field(default_factory=list)
    intent: str
    target_audience: str | None = None


class SeoImprovements(BaseModel):
    primary_keyword: str
    secondary_keywords: list[str] = Field(default_factory=list)
    long_tail_keywords: list[str] = Field(default_factory=list)
    recommended_title: str
    meta_description: str
    supporting_content: list[str] = Field(default_factory=list)


class ServiceInfo(BaseModel):
    service_name: str
    description: str
    target_industry: str | None = None
    target_customer: str | None = None
    main_benefit: str | None = None
    inferred: bool = False


class TargetAudience(BaseModel):
    primary_audience: list[str] = Field(default_factory=list)
    secondary_audience: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    customer_needs: list[str] = Field(default_factory=list)
    location_focus: str | None = None


class Analysis(BaseModel):
    competitor_analysis: CompetitorAnalysis
    target_search_queries: list[SearchQuery]
    seo_improvements: SeoImprovements
    top_services: list[ServiceInfo]
    target_audience: TargetAudience


class LinkAnalysisResponse(BaseModel):
    success: bool
    website: str
    brand: BrandInfo | None = None
    analysis: Analysis | None = None
    error: str | None = None
