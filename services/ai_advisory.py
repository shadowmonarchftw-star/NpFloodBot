"""AI Advisory Generator for Nepal River Basin Early Warning.

Uses Google Gemini Flash (Free Tier) to generate crisp, urgent, bilingual (Nepali + English)
advisories with vulnerable downstream settlements. Includes resilient, high-fidelity
pre-written template fallbacks when API is unavailable, unconfigured, or rate-limited.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional, Tuple

from pydantic import BaseModel

from services.risk_evaluator import RiskAssessment, SeverityLevel

logger = logging.getLogger(__name__)


class AdvisoryResult(BaseModel):
    english_summary: str
    nepali_advisory: str
    is_ai_generated: bool = False
    model_used: str = "Deterministic Fallback Template"


def _generate_fallback_advisory(assessment: RiskAssessment) -> AdvisoryResult:
    """Generate high-urgency, grammatically verified bilingual advisory from pre-written templates."""
    lvl = assessment.severity
    station = assessment.station_name
    river = assessment.river_name
    curr = assessment.current_level
    warn = assessment.warning_level
    dang = assessment.danger_level
    vel = assessment.rising_velocity
    vel_str = f"+{vel:.2f} m/hr" if vel > 0 else f"{vel:.2f} m/hr"
    catchment = assessment.upstream_catchment
    rain_1h = assessment.upstream_forecast_1h_mm
    vuln_ne = assessment.vulnerable_areas_ne
    vuln_en = assessment.vulnerable_areas_en

    if lvl == SeverityLevel.EMERGENCY:
        en_text = (
            f"🚨 CRITICAL FLOOD EMERGENCY at {station}!\n"
            f"• River Level: {curr:.2f}m (DANGER MARK: {dang:.2f}m, Breach: {curr - dang:+.2f}m)\n"
            f"• Trend: Rapidly rising at {vel_str}\n"
            f"• Upstream Rain: {rain_1h:.1f} mm/hr forecasted in {catchment}\n"
            f"• Immediate Action: Downstream communities in {vuln_en} must EVACUATE IMMEDIATELY to designated higher ground or municipal flood shelters. Do not attempt to cross bridges or low-lying paths."
        )
        ne_text = (
            f"🚨 आपतकालीन बाढी चेतावनी (CRITICAL EMERGENCY)!\n"
            f"• स्थान: {station} ({river} नदी)\n"
            f"• वर्तमान जलसतह: {curr:.2f} मिटर (खतराको सीमा: {dang:.2f} मिटर)\n"
            f"• जलसतहको गति: {vel_str} को तीव्र गतिमा बढ्दो\n"
            f"• माथिल्लो तटीय वर्षा: {catchment} क्षेत्रमा {rain_1h:.1f} मि.मि./घण्टा वर्षाको पूर्वानुमान\n"
            f"⚠️ तत्काल निर्देशन: {vuln_ne} का बासिन्दाहरू तुरुन्त सुरक्षित, अग्लो स्थान तथा नजिकैको सामुदायिक आश्रयस्थलतर्फ जानुहोस्। अत्यावश्यक कागजात, औषधि र टर्चलाइट साथमा लिनुहोस्। बाढी पसेका सडक वा पुल तर्ने प्रयास नगर्नुहोला।"
        )
    elif lvl == SeverityLevel.WARNING:
        en_text = (
            f"⚠️ FLOOD WARNING at {station}.\n"
            f"• River Level: {curr:.2f}m (Warning Level: {warn:.2f}m | Danger Level: {dang:.2f}m)\n"
            f"• Trend: {vel_str}\n"
            f"• Upstream Rain: {rain_1h:.1f} mm/hr forecasted in {catchment}\n"
            f"• Advisory: Downstream residents in {vuln_en} should stay on high alert. Move elderly, children, livestock, and critical valuables to upper floors or safe locations. Monitor local ward sirens and DHM updates."
        )
        ne_text = (
            f"⚠️ सतर्कता चेतावनी (FLOOD WARNING)!\n"
            f"• स्थान: {station} ({river} नदी)\n"
            f"• वर्तमान जलसतह: {curr:.2f} मिटर (सतर्कता सीमा: {warn:.2f} मिटर | खतराको सीमा: {dang:.2f} मिटर)\n"
            f"• जलसतहको गति: {vel_str}\n"
            f"• माथिल्लो तटीय वर्षा: {catchment} मा {rain_1h:.1f} मि.मि./घण्टा वर्षाको सम्भावना\n"
            f"📢 सजगता निर्देशन: {vuln_ne} का नदी किनारका बासिन्दाहरू उच्च सतर्कतामा रहनुहोस्। नदी तटीय क्षेत्रमा नजानुहोस्, बालबालिका, वृद्धवृद्धा तथा महत्वपूर्ण सामग्री सुरक्षित स्थानमा सार्नुहोस्।"
        )
    elif lvl == SeverityLevel.ADVISORY:
        en_text = (
            f"🟡 FLOOD ADVISORY at {station}.\n"
            f"• River Level: {curr:.2f}m (Warning Threshold: {warn:.2f}m)\n"
            f"• Trend: {vel_str}\n"
            f"• Weather: {rain_1h:.1f} mm/hr upstream rain in {catchment}\n"
            f"• Advisory: Water levels are swelling. Riverside communities in {vuln_en} should prepare emergency kits and stay alert for escalating water levels."
        )
        ne_text = (
            f"🟡 सजगता पूर्वसूचना (FLOOD ADVISORY)!\n"
            f"• स्थान: {station} ({river} नदी)\n"
            f"• वर्तमान जलसतह: {curr:.2f} मिटर (सतर्कता विन्दु: {warn:.2f} मिटर)\n"
            f"• जलसतहको प्रवृत्ति: {vel_str}\n"
            f"• वर्षा अवस्था: {catchment} क्षेत्रमा {rain_1h:.1f} मि.मि./घण्टा वर्षाको पूर्वानुमान\n"
            f"ℹ️ पूर्वतयारी: {vuln_ne} लगायत तटीय क्षेत्रका नागरिकहरू सतर्क रहन र नदीको बहाव निरन्तर अवलोकन गर्न अनुरोध गरिन्छ।"
        )
    else:
        en_text = (
            f"🟢 NORMAL CONDITIONS at {station}.\n"
            f"• River Level: {curr:.2f}m (Safe below Warning Level: {warn:.2f}m)\n"
            f"• Status: Steady flow, no immediate flood threat detected."
        )
        ne_text = (
            f"🟢 सामान्य अवस्था (NORMAL)!\n"
            f"• स्थान: {station} ({river} नदी)\n"
            f"• वर्तमान जलसतह: {curr:.2f} मिटर (सतर्कता सीमा {warn:.2f}m भन्दा सुरक्षित)\n"
            f"• अवस्था: नदीको बहाव सामान्य रहेको छ।"
        )

    return AdvisoryResult(
        english_summary=en_text,
        nepali_advisory=ne_text,
        is_ai_generated=False,
        model_used="Resilient Disaster Template Engine",
    )


def _call_gemini_api(assessment: RiskAssessment, api_key: str) -> Optional[AdvisoryResult]:
    """Call Google Gemini Flash API using google-genai SDK or direct REST fallback."""
    prompt = f"""
You are the Official Nepal Disaster Early Warning AI Assistant.
Generate a concise, authoritative, urgent bilingual flood bulletin for Telegram broadcast.

HYDROLOGY & METEOROLOGY DATA:
- River & Station: {assessment.river_name} at {assessment.station_name} (Basin: {assessment.basin})
- Current Water Level: {assessment.current_level:.2f} meters
- DHM Warning Level: {assessment.warning_level:.2f} meters
- DHM Danger Level: {assessment.danger_level:.2f} meters
- Rising Velocity: {assessment.rising_velocity:+.2f} m/hour
- Upstream Catchment: {assessment.upstream_catchment}
- Upstream Rainfall Forecast (next 1h): {assessment.upstream_forecast_1h_mm:.1f} mm
- Upstream Rainfall Forecast (next 3h): {assessment.upstream_forecast_3h_mm:.1f} mm
- Compound Risk Detected: {assessment.compound_risk}
- Risk Level: {assessment.severity.value} ({assessment.severity.badge_en})
- Vulnerable Downstream Settlements (English): {assessment.vulnerable_areas_en}
- Vulnerable Downstream Settlements (Nepali): {assessment.vulnerable_areas_ne}

INSTRUCTIONS:
1. Provide an English Summary:
   - High impact, crisp, factual.
   - Summarize the water level relative to danger/warning marks, rising trend, upstream rain, and specific immediate safety actions for {assessment.vulnerable_areas_en}.
2. Provide a Clear, Urgent Nepali Advisory (नेपाली सतर्कता सन्देश):
   - Natural, accurate, urgent Nepali disaster warning phrasing.
   - Explicitly mention the vulnerable downstream settlements ({assessment.vulnerable_areas_ne}).
   - Give direct life-safety instructions (e.g. "तुरुन्त सुरक्षित स्थानमा जानुहोस्", "आकस्मिक झोला लिएर अग्लो स्थानमा सर्नुहोस्").

FORMAT YOUR OUTPUT EXACTLY AS:
===ENGLISH===
<English summary with bullet points>
===NEPALI===
<Urgent actionable Nepali advisory>
"""

    # Attempt 1: Using the official google-genai SDK
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        # We test gemini-2.5-flash, gemini-2.0-flash, and gemini-1.5-flash
        models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
        for m in models_to_try:
            try:
                response = client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        max_output_tokens=700,
                    ),
                )
                if response and response.text:
                    parsed = _parse_bilingual_response(response.text, assessment, model_name=f"Google Gemini Flash ({m})")
                    if parsed:
                        return parsed
            except Exception as e:
                logger.debug(f"google-genai call to model {m} failed: {e}")
                continue
    except ImportError:
        logger.debug("google-genai SDK not installed or import error.")
    except Exception as e:
        logger.debug(f"google-genai invocation failed: {e}")

    # Attempt 2: Direct HTTP REST call to Gemini endpoint (no SDK dependency)
    import requests
    models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    for m in models:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 700},
            }
            resp = requests.post(url, json=payload, timeout=6.0)
            if resp.status_code == 200:
                data = resp.json()
                text = (
                    data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
                if text:
                    parsed = _parse_bilingual_response(text, assessment, model_name=f"Google Gemini REST ({m})")
                    if parsed:
                        return parsed
            else:
                logger.debug(f"Gemini REST model {m} HTTP {resp.status_code}: {resp.text[:120]}")
        except Exception as e:
            logger.debug(f"Gemini REST model {m} error: {e}")
            continue

    return None


def _parse_bilingual_response(text: str, assessment: RiskAssessment, model_name: str) -> Optional[AdvisoryResult]:
    """Parse English and Nepali blocks from Gemini output."""
    if "===ENGLISH===" in text and "===NEPALI===" in text:
        parts = text.split("===NEPALI===")
        en_raw = parts[0].replace("===ENGLISH===", "").strip()
        ne_raw = parts[1].strip()
        if len(en_raw) > 20 and len(ne_raw) > 20:
            return AdvisoryResult(
                english_summary=en_raw,
                nepali_advisory=ne_raw,
                is_ai_generated=True,
                model_used=model_name,
            )

    # Fallback to splitting by common headers if markers weren't preserved
    lines = text.splitlines()
    en_lines = []
    ne_lines = []
    mode = "en"
    for line in lines:
        if any(h in line.lower() for h in ["nepali", "नेपाली"]):
            mode = "ne"
            continue
        if mode == "en":
            en_lines.append(line)
        else:
            ne_lines.append(line)

    en_part = "\n".join(en_lines).strip()
    ne_part = "\n".join(ne_lines).strip()
    if en_part and ne_part:
        return AdvisoryResult(
            english_summary=en_part,
            nepali_advisory=ne_part,
            is_ai_generated=True,
            model_used=model_name,
        )

    return None


def generate_bilingual_advisory(assessment: RiskAssessment) -> AdvisoryResult:
    """Generate bilingual alert message using Google Gemini Flash or resilient templates.

    Guarantees that an advisory is always returned and never raises unhandled exceptions.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if api_key:
        try:
            ai_advisory = _call_gemini_api(assessment, api_key)
            if ai_advisory:
                logger.info(f"Generated AI flood advisory using {ai_advisory.model_used}.")
                return ai_advisory
            else:
                logger.warning("Gemini Flash call did not return valid response. Using resilient template fallback.")
        except Exception as e:
            logger.warning(f"Error during Gemini AI advisory generation: {e}. Using resilient template fallback.")
    else:
        logger.info("GEMINI_API_KEY not set. Using verified disaster alert template engine.")

    return _generate_fallback_advisory(assessment)


def generate_basin_overview_advisory(assessments: List[RiskAssessment]) -> AdvisoryResult:
    """Generate bilingual status overview for all monitored river basins."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    total = len(assessments)
    highest_severity = max((a.severity for a in assessments), key=lambda s: s.rank, default=SeverityLevel.NORMAL)

    bullet_data = []
    for a in assessments:
        bullet_data.append(
            f"- {a.station_name}: Level={a.current_level:.2f}m (Warn={a.warning_level:.2f}m, Dang={a.danger_level:.2f}m), "
            f"Velocity={a.rising_velocity:+.2f}m/h, Rain={a.upstream_forecast_1h_mm:.1f}mm/h in {a.upstream_catchment}, Status={a.severity.value}"
        )
    stations_summary = "\n".join(bullet_data)

    prompt = f"""
You are the Nepal Disaster & Hydrology Early Warning AI Assistant.
Generate an authoritative, concise real-time river basin status overview bulletin in both English and Nepali.

REAL-TIME BASIN READINGS ({total} Monitored Stations):
{stations_summary}

Overall Threat Status: {highest_severity.value} ({highest_severity.badge_en})

INSTRUCTIONS:
1. Provide an English Summary (2-3 crisp sentences):
   - Summarize whether rivers are safe/normal or if any warnings exist.
   - Mention the current weather status in upstream catchments.
2. Provide a clear, natural Nepali Summary (नेपाली बुलेटिन सारांश - 2-3 sentences):
   - Inform the public about current river conditions in clear, professional Nepali.
   - Mention that Bagmati, Roshi, Koshi and Narayani basins are currently monitored in real time.

FORMAT YOUR OUTPUT EXACTLY AS:
===ENGLISH===
<English summary>
===NEPALI===
<Nepali summary>
"""

    if api_key:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            for m in ["gemini-1.5-flash", "gemini-2.5-flash", "gemini-2.0-flash"]:
                try:
                    resp = client.models.generate_content(
                        model=m,
                        contents=prompt,
                        config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=600),
                    )
                    if resp and resp.text:
                        parsed = _parse_bilingual_response(resp.text, assessments[0], model_name=f"Google Gemini Flash ({m})")
                        if parsed:
                            return parsed
                except Exception as e:
                    logger.debug(f"Gemini SDK {m} overview failed: {e}")
        except Exception as e:
            logger.debug(f"Gemini overview exception: {e}")

    # Deterministic fallback summary
    if highest_severity == SeverityLevel.NORMAL:
        en = (
            f"All {total} monitored river stations across Bagmati, Nakkhu, Roshi Khola, Koshi, and Narayani "
            f"basins are currently flowing within SAFE, NORMAL parameters. Upstream catchment precipitation is light and stable."
        )
        ne = (
            f"हाल बागमती (बल्खु, गौरीघाट, सुन्दरीजल, चोभार), नख्खु खोला, रोशी खोला, सप्तकोशी तथा नारायणी "
            f"जलाधारका सबै {total} वटै स्टेसनहरूमा नदीको जलसतह सतर्कता सीमाभन्दा तल सामान्य र सुरक्षित अवस्थामा रहेको छ। "
            f"माथिल्लो तटीय जलाधारहरूमा कुनै आकस्मिक जोखिम देखिएको छैन।"
        )
    else:
        en = (
            f"Real-time monitoring across {total} river stations indicates elevated water levels. "
            f"Peak threat status is currently {highest_severity.badge_en}. Riverside residents should stay alert."
        )
        ne = (
            f"नेपालका प्रमुख {total} नदी स्टेसनहरूको वास्तविक अनुगमन गर्दा जलसतह सतर्कताको तहमा पुगेको पाइएको छ। "
            f"हालको उच्च जोखिम स्थिति: {highest_severity.badge_ne}। नदी किनारका बासिन्दाहरू सतर्क रहनुहोला।"
        )

    return AdvisoryResult(
        english_summary=en,
        nepali_advisory=ne,
        is_ai_generated=False,
        model_used="Resilient Hydrology Summary Engine",
    )

