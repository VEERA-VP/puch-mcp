import os, asyncio, re, json
from typing import Annotated, Optional, Dict, Any, List
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.providers.bearer import BearerAuthProvider, RSAKeyPair
from mcp import ErrorData, McpError
from mcp.types import INVALID_PARAMS
from mcp.server.auth.provider import AccessToken
from pydantic import BaseModel, Field

load_dotenv()
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "Q4v@8gP1zL#xD2mV!tN3rB7k")
MY_NUMBER = os.environ.get("MY_NUMBER", "919840499661")

if not AUTH_TOKEN:
    raise RuntimeError("AUTH_TOKEN not set")
if not MY_NUMBER:
    raise RuntimeError("MY_NUMBER not set")

class SimpleBearerAuthProvider(BearerAuthProvider):
    def __init__(self, token: str):
        k = RSAKeyPair.generate()
        super().__init__(public_key=k.public_key, jwks_uri=None, issuer=None, audience=None)
        self.token = token

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        if token == self.token:
            return AccessToken(token=token, client_id="puch-client", scopes=["*"], expires_at=None)
        return None

mcp = FastMCP("Puch MCP Server (EMS Only)", auth=SimpleBearerAuthProvider(AUTH_TOKEN))

class RichToolDescription(BaseModel):
    description: str
    use_when: str
    side_effects: Optional[str] = None

_EMS_SYMPTOMS: Dict[str, List[str]] = {
    "chest_pain": ["chest pain", "pressure in chest", "tight chest"],
    "breathlessness": ["short of breath", "breathless", "difficulty breathing"],
    "unconscious": ["unconscious", "not responding", "passed out", "fainted"],
    "bleeding": ["bleeding", "profuse bleed", "blood everywhere"],
    "seizure": ["seizure", "fitting", "convulsion"],
    "stroke_signs": ["face droop", "arm weakness", "slurred speech", "stroke"],
    "fever": ["fever", "temperature", "high temp", "pyrexia"],
    "pain": ["pain", "ache", "hurts"],
}

_AGE_RX = re.compile(r"\b(\d{1,3})\s*(?:y|yr|yrs|years?)\b", re.I)

def _extract_age(text: str) -> Optional[int]:
    m = _AGE_RX.search(text or "")
    if not m:
        return None
    try:
        age = int(m.group(1))
        if 0 <= age <= 120:
            return age
    except Exception:
        return None
    return age

def _flags_from_text(text: str) -> List[str]:
    found = set()
    low = (text or "").lower()
    for flag, phrases in _EMS_SYMPTOMS.items():
        for p in phrases:
            if p in low:
                found.add(flag)
                break
    return sorted(found)

def _level_from_flags(flags: List[str], age: Optional[int]) -> str:
    critical = {"unconscious", "bleeding"}
    als = {"chest_pain", "breathlessness", "seizure", "stroke_signs"}
    f = set(flags or [])
    if f & critical:
        return "Critical"
    if f & als:
        return "ALS"
    if age is not None and (age < 12 or age > 75) and f:
        return "ALS"
    return "BLS" if f else "General"

@mcp.tool
async def validate() -> str:
    return MY_NUMBER

@mcp.tool(name="symptom_extract")
async def symptom_extract_tool(
    text: Annotated[str, Field(description="Free-text message.")],
    age_years: Annotated[Optional[int], Field(description="Age in years (optional).")] = None,
) -> Dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise McpError(ErrorData(code=INVALID_PARAMS, message="text is required"))
    age = age_years if age_years is not None else _extract_age(text)
    flags = _flags_from_text(text)
    return {"age_years": age, "free_text": text, "flags": flags, "symptoms": flags}

async def _redflags_core(structured: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(structured, dict):
        raise McpError(ErrorData(code=INVALID_PARAMS, message="structured must be an object"))
    flags = list(structured.get("flags", []))
    age = structured.get("age_years")
    level = _level_from_flags(flags, age)
    return {"level_of_care": level, "flags": flags, "age_years": age}

@mcp.tool(name="redflags_validate")
async def redflags_validate(structured: Annotated[Dict[str, Any], Field(description="From symptom_extract.")]) -> Dict[str, Any]:
    return await _redflags_core(structured)

@mcp.tool(name="find_hospital")
async def find_hospital_tool(
    severity: Annotated[str, Field(description="Level of care: General/BLS/ALS/Critical")],
    lat: Annotated[float, Field(description="User latitude")],
    lng: Annotated[float, Field(description="User longitude")],
) -> Dict[str, Any]:
    hospitals = json.load(open("hospitals.json", "r", encoding="utf-8"))
    from math import radians, sin, cos, sqrt, atan2

    def distance(lat1, lon1, lat2, lon2):
        R = 6371
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        return R * c

    nearest = min(hospitals, key=lambda h: distance(lat, lng, h["lat"], h["lng"]))
    return {
        "nearest_hospital": nearest["name"],
        "phone": nearest.get("ambulance_phone") or nearest.get("phone"),
        "distance_km": round(distance(lat, lng, nearest["lat"], nearest["lng"]), 2)
    }

async def main():
    print("🚀 Starting Puch MCP server (EMS Only) on http://0.0.0.0:8086")
    await mcp.run_async("streamable-http", host="0.0.0.0", port=8086)

if __name__ == "__main__":
    asyncio.run(main())
