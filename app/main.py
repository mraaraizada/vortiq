from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas import LinkAnalysisRequest, LinkAnalysisResponse
from app.services.analysis_service import analyze_website

app = FastAPI(
    title="Vortiq — AI-Powered Website Link Analysis",
    description=(
        "Accepts a website URL, extracts its real content, analyzes it with an LLM "
        "(Gemini), and returns structured competitor, search-query, SEO, services, "
        "and target-audience insights."
    ),
    version="1.0.0",
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError) -> JSONResponse:
    errors = [{"field": ".".join(str(p) for p in err["loc"][1:]), "message": err["msg"]} for err in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "Validation failed", "errors": errors})


@app.post("/link-analysis", response_model=LinkAnalysisResponse, summary="Analyze a website's competitors, SEO, services, and audience")
async def create_link_analysis(payload: LinkAnalysisRequest) -> LinkAnalysisResponse:
    return await analyze_website(payload.url)


@app.get("/", include_in_schema=False)
async def root():
    return {"service": "Vortiq", "docs": "/docs", "endpoint": "POST /link-analysis"}
