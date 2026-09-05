"""Nepali Voice Alert Synthesizer for Disaster Warning.

Generates clear, natural Nepali spoken emergency broadcasts using gTTS ($0 cost)
for instant delivery to Telegram channels as native voice notes, ensuring vital
evacuation instructions reach non-literate and visually impaired communities.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from services.risk_evaluator import RiskAssessment, SeverityLevel

logger = logging.getLogger(__name__)

VOICE_DIR = Path(__file__).resolve().parent.parent / "data" / "voice_alerts"
VOICE_DIR.mkdir(parents=True, exist_ok=True)


def generate_nepali_voice_alert(assessment: RiskAssessment) -> Optional[Path]:
    """Synthesize spoken Nepali voice advisory for warning & emergency flood events."""
    try:
        from gtts import gTTS
    except ImportError:
        logger.warning("gTTS not installed. Skipping voice alert synthesis.")
        return None

    station = assessment.station_name.split("(")[0].strip()
    river = assessment.river_name
    level = f"{assessment.current_level:.1f}"

    lead_text = ""
    if assessment.lead_time_formatted_ne:
        lead_text = f" {assessment.lead_time_formatted_ne}।"

    if assessment.severity == SeverityLevel.EMERGENCY:
        text = (
            f"आपतकालीन बाढी चेतावनी! {station} स्टेसनमा {river} नदीको जलसतह {level} मिटर पुगेर खतराको तह नाघेको छ।{lead_text} "
            f"{assessment.vulnerable_areas_ne} का बासिन्दाहरू तुरुन्त सुरक्षित अग्लो स्थान वा सामुदायिक आश्रयस्थलतर्फ जानुहोला। "
            f"नेपाल प्रहरी १०० वा सशस्त्र प्रहरी बल १११४ मा सम्पर्क गर्नुहोस्।"
        )
    elif assessment.severity == SeverityLevel.WARNING:
        text = (
            f"बाढी सतर्कता सूचना! {station} स्टेसनमा {river} नदीको जलसतह {level} मिटर पुगेको छ।{lead_text} "
            f"नदी किनारका बासिन्दाहरू उच्च सतर्कता अपनाउनुहोला। नदी तर्ने वा पौडी खेल्ने काम नगर्नुहोस्।"
        )
    else:
        return None

    try:
        tts = gTTS(text=text, lang="ne", slow=False)
        out_file = VOICE_DIR / f"{assessment.station_id}_alert.mp3"
        tts.save(str(out_file))
        logger.info(f"Generated Nepali voice alert: {out_file.name}")
        return out_file
    except Exception as e:
        logger.warning(f"Voice synthesis failed for {assessment.station_id}: {e}")
        return None
