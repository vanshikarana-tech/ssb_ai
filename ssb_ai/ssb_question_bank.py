"""
ssb_question_bank.py
────────────────────
Three-tier SSB question bank.

Levels
------
  BASIC        — Personal facts, PIQ, ice-breaking, family, hobbies.
                 Tests: Power of Expression, Self-Confidence, Liveliness.

  INTERMEDIATE — Hobby-depth, situational reactions, academic pressure,
                 leadership in small groups.
                 Tests: Initiative, Sense of Responsibility, Cooperation,
                        Speed of Decision Making.

  ADVANCED     — Current affairs, strategic/defence policy, service-specific
                 knowledge, complex ethical dilemmas.
                 Tests: Effective Intelligence, Reasoning Ability,
                        Ability to Influence Group, Social Adaptability.

Structure
---------
Each question is a dict:
  {
    "id":       str   — unique slug, never reused across sessions
    "text":     str   — the question text shown/spoken to the candidate
    "level":    DifficultyLevel
    "category": str   — human-readable tag for the evaluation summary
  }

The QUESTION_BANK dict maps DifficultyLevel → list[Question].
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class DifficultyLevel(str, Enum):
    BASIC        = "Basic"
    INTERMEDIATE = "Intermediate"
    ADVANCED     = "Advanced"


@dataclass(frozen=True)
class Question:
    id:       str
    text:     str
    level:    DifficultyLevel
    category: str

    def __hash__(self) -> int:
        return hash(self.id)


# ─── Helper to build questions concisely ─────────────────────────────────────
def _q(qid: str, text: str, level: DifficultyLevel, category: str) -> Question:
    return Question(id=qid, text=text, level=level, category=category)

B = DifficultyLevel.BASIC
I = DifficultyLevel.INTERMEDIATE
A = DifficultyLevel.ADVANCED


# ─── BASIC — 30 questions ─────────────────────────────────────────────────────
_BASIC: list[Question] = [
    # Opening / Ice-Breaking
    _q("b01", "Good morning. Tell me about your journey to the board — how was your travel here?", B, "Opening"),
    _q("b02", "How have you been finding your stay at the SSB centre so far?", B, "Opening"),
    _q("b03", "What did you do yesterday evening to relax before today?", B, "Opening"),
    _q("b04", "Tell me one thing about yourself that is not on your PIQ form.", B, "Opening"),
    _q("b05", "How did you first hear about the SSB, and what made you decide to appear?", B, "Opening"),

    # Personal / PIQ Facts
    _q("b06", "Walk me through your academic background — schooling, board, and percentage.", B, "Academic"),
    _q("b07", "Why did you choose your particular stream or discipline for higher education?", B, "Academic"),
    _q("b08", "Tell me about your most significant academic achievement and what it taught you.", B, "Academic"),
    _q("b09", "Which subject did you find most challenging, and how did you overcome it?", B, "Academic"),
    _q("b10", "Have you represented your institution in any competition or olympiad?", B, "Academic"),

    # Family
    _q("b11", "Tell me about your family — who are the members and what do they do?", B, "Family"),
    _q("b12", "How has your family influenced your decision to join the Armed Forces?", B, "Family"),
    _q("b13", "Describe the neighbourhood you grew up in and how it shaped your character.", B, "Family"),
    _q("b14", "Is there anyone in your family who has served in the military?", B, "Family"),
    _q("b15", "How does your family feel about you pursuing a career in the defence services?", B, "Family"),

    # Hobbies / Interests
    _q("b16", "What are your hobbies, and how regularly do you pursue them?", B, "Hobbies"),
    _q("b17", "Tell me about the sport you play and the highest level you have competed at.", B, "Hobbies"),
    _q("b18", "If you had one free afternoon with no obligations, how would you spend it and why?", B, "Hobbies"),
    _q("b19", "How do your hobbies contribute to the Officer Like Qualities we look for at SSB?", B, "Hobbies"),
    _q("b20", "Tell me about a time a hobby taught you an important life lesson.", B, "Hobbies"),

    # Self-Awareness
    _q("b21", "What do you consider your greatest strength, and give me an example of it in action?", B, "Self-Awareness"),
    _q("b22", "What is one weakness you are actively working to improve?", B, "Self-Awareness"),
    _q("b23", "Describe yourself in three words and justify each one.", B, "Self-Awareness"),
    _q("b24", "Who is your role model and why?", B, "Self-Awareness"),
    _q("b25", "What has been the most difficult decision you have made in your life so far?", B, "Self-Awareness"),

    # Motivation
    _q("b26", "Why do you want to join the Indian Armed Forces specifically?", B, "Motivation"),
    _q("b27", "Which service — Army, Navy, or Air Force — are you applying for, and why that one?", B, "Motivation"),
    _q("b28", "What will you do if you are not selected at this SSB?", B, "Motivation"),
    _q("b29", "How long have you been preparing for SSB, and what has that journey been like?", B, "Motivation"),
    _q("b30", "Where do you see yourself ten years from now if you are commissioned?", B, "Motivation"),
]


# ─── INTERMEDIATE — 30 questions ─────────────────────────────────────────────
_INTERMEDIATE: list[Question] = [
    # Situational Reactions (SRT-style within PI)
    _q("i01",
       "You are on a trek with your team. One member twists his ankle badly and cannot walk. "
       "The nearest village is 8 km away and it is getting dark. What do you do?",
       I, "Situational"),
    _q("i02",
       "You discover that a close friend in your unit has been falsifying attendance records. "
       "He confides in you and asks you to stay quiet. How do you handle this?",
       I, "Situational"),
    _q("i03",
       "You are the junior-most officer at a post. Your senior gives an order you believe is "
       "tactically wrong and could endanger lives. What is your course of action?",
       I, "Situational"),
    _q("i04",
       "During a community outreach camp, a local civilian becomes aggressive and starts "
       "inciting others against your team. You have no backup. What do you do?",
       I, "Situational"),
    _q("i05",
       "You are leading a patrol when your radio fails mid-mission. Two team members are "
       "injured and the nearest base is 10 km away. How do you proceed?",
       I, "Situational"),
    _q("i06",
       "Your unit wins a competition but you notice the winning entry may have violated the "
       "rules. No one else has noticed. What do you do?",
       I, "Situational"),
    _q("i07",
       "You are given two urgent tasks simultaneously by two different senior officers with "
       "equal priority. How do you manage this?",
       I, "Situational"),
    _q("i08",
       "During a river crossing exercise, a team member panics and refuses to cross. "
       "The group is falling behind schedule. What is your approach?",
       I, "Situational"),

    # Leadership & Group Dynamics
    _q("i09",
       "Tell me about a time you led a group that was not cooperating. How did you bring them together?",
       I, "Leadership"),
    _q("i10",
       "Describe a situation where you had to take an unpopular decision. What was the outcome?",
       I, "Leadership"),
    _q("i11",
       "Have you ever failed as a leader? What did you learn from that experience?",
       I, "Leadership"),
    _q("i12",
       "How do you motivate a team member who is consistently underperforming?",
       I, "Leadership"),
    _q("i13",
       "Tell me about a time you had to work under extreme pressure. How did you perform?",
       I, "Leadership"),

    # Hobby Depth
    _q("i14",
       "You mentioned reading as a hobby. What is the last book you read, and what did it change in your thinking?",
       I, "Hobby Depth"),
    _q("i15",
       "How has your sport shaped your ability to handle defeat and bounce back?",
       I, "Hobby Depth"),
    _q("i16",
       "If you could turn one of your hobbies into a service to your unit, how would you do it?",
       I, "Hobby Depth"),

    # Academic Pressure & Problem Solving
    _q("i17",
       "Describe a time when you had to learn something completely new under a tight deadline.",
       I, "Problem Solving"),
    _q("i18",
       "Tell me about a project or assignment where things went wrong. How did you recover?",
       I, "Problem Solving"),
    _q("i19",
       "How do you approach a problem you have never encountered before?",
       I, "Problem Solving"),
    _q("i20",
       "Give me an example of a time you disagreed with a teacher or authority figure. "
       "How did you handle it professionally?",
       I, "Problem Solving"),

    # Ethics & Values
    _q("i21",
       "What does integrity mean to you, and describe a time you demonstrated it at personal cost?",
       I, "Ethics"),
    _q("i22",
       "Is it ever acceptable to bend the rules for a greater good? Justify your answer with an example.",
       I, "Ethics"),
    _q("i23",
       "How do you handle a situation where your personal values conflict with an order from a superior?",
       I, "Ethics"),
    _q("i24",
       "Tell me about a time you witnessed injustice. What did you do?",
       I, "Ethics"),

    # Social Awareness
    _q("i25",
       "What is one social problem in your hometown, and what practical solution would you propose?",
       I, "Social Awareness"),
    _q("i26",
       "How do you think the Armed Forces contribute to nation-building beyond combat?",
       I, "Social Awareness"),
    _q("i27",
       "Tell me about a time you worked with people from a very different background. "
       "What did you learn?",
       I, "Social Awareness"),
    _q("i28",
       "How would you handle a subordinate who belongs to a different region and culture "
       "and is struggling to integrate?",
       I, "Social Awareness"),

    # Resilience
    _q("i29",
       "Describe the most physically or mentally demanding experience of your life. "
       "How did you push through?",
       I, "Resilience"),
    _q("i30",
       "Have you ever been in a situation where you wanted to quit but did not? "
       "What kept you going?",
       I, "Resilience"),
]


# ─── ADVANCED — 30 questions ─────────────────────────────────────────────────
_ADVANCED: list[Question] = [
    # Current Affairs & Defence Policy
    _q("a01",
       "What is your assessment of India's current border situation with China, "
       "and what strategic options does India have?",
       A, "Defence Policy"),
    _q("a02",
       "Explain the significance of Operation Sindoor for India's strategic posture "
       "and its implications for future deterrence.",
       A, "Defence Policy"),
    _q("a03",
       "What do you understand by 'jointness' in the Indian Armed Forces, "
       "and why has its implementation been slow?",
       A, "Defence Policy"),
    _q("a04",
       "India has a stated policy of No First Use for nuclear weapons. "
       "Do you think this policy serves India's security interests? Defend your position.",
       A, "Strategic Thinking"),
    _q("a05",
       "What is the Agnipath scheme, and what are its long-term implications "
       "for the Indian Army's operational readiness?",
       A, "Defence Policy"),
    _q("a06",
       "How does India's defence procurement policy affect its operational capability? "
       "What reforms would you suggest?",
       A, "Defence Policy"),
    _q("a07",
       "What is the significance of the theatre command restructuring for India's "
       "warfighting capability?",
       A, "Defence Policy"),

    # Service-Specific Knowledge
    _q("a08",
       "What are the primary roles of the Indian Army in counter-insurgency operations, "
       "and how do they differ from conventional warfare?",
       A, "Service Knowledge"),
    _q("a09",
       "Explain the concept of 'Cold Start' doctrine and the debate around its existence "
       "and utility.",
       A, "Service Knowledge"),
    _q("a10",
       "What is the role of the Indian Navy in protecting India's maritime interests, "
       "and what are the key threats it faces?",
       A, "Service Knowledge"),
    _q("a11",
       "How has drone warfare changed the nature of modern conflict, "
       "and how should India adapt?",
       A, "Service Knowledge"),
    _q("a12",
       "What is the significance of the Line of Actual Control versus the Line of Control, "
       "and how do they differ legally and operationally?",
       A, "Service Knowledge"),

    # Strategic & Geopolitical Thinking
    _q("a13",
       "How does China's Belt and Road Initiative affect India's strategic interests "
       "in South Asia?",
       A, "Geopolitics"),
    _q("a14",
       "What is the QUAD, and do you think it is an effective mechanism for "
       "maintaining a free and open Indo-Pacific?",
       A, "Geopolitics"),
    _q("a15",
       "How should India balance its strategic autonomy with the need for defence "
       "partnerships with the United States?",
       A, "Geopolitics"),
    _q("a16",
       "What are the implications of Pakistan's nuclear arsenal for India's "
       "conventional military strategy?",
       A, "Geopolitics"),
    _q("a17",
       "How does India's relationship with Russia affect its ability to align "
       "with Western nations on defence matters?",
       A, "Geopolitics"),

    # Complex Ethical Dilemmas
    _q("a18",
       "You are commanding a patrol in a counter-insurgency zone. You receive credible "
       "intelligence that a civilian house is being used as a weapons cache. "
       "You have no time to wait for higher authorisation. What do you do?",
       A, "Ethical Dilemma"),
    _q("a19",
       "A soldier under your command commits a serious disciplinary violation but "
       "has just received news of a family tragedy. How do you balance discipline "
       "with compassion?",
       A, "Ethical Dilemma"),
    _q("a20",
       "You discover that a senior officer in your unit is involved in financial "
       "corruption. He is well-respected and close to retirement. "
       "What is your course of action?",
       A, "Ethical Dilemma"),
    _q("a21",
       "During a humanitarian relief operation, you have supplies for 100 people "
       "but 200 are present. How do you decide who gets priority?",
       A, "Ethical Dilemma"),

    # Technology & Future Warfare
    _q("a22",
       "How is artificial intelligence changing the nature of warfare, "
       "and what are the ethical implications of autonomous weapons systems?",
       A, "Future Warfare"),
    _q("a23",
       "What is cyber warfare, and how vulnerable is India's critical infrastructure "
       "to a state-sponsored cyber attack?",
       A, "Future Warfare"),
    _q("a24",
       "How should the Indian Armed Forces adapt their training and doctrine "
       "to prepare for multi-domain operations?",
       A, "Future Warfare"),
    _q("a25",
       "What role does space play in modern warfare, and what is India's "
       "current capability in this domain?",
       A, "Future Warfare"),

    # Officer Qualities at Senior Level
    _q("a26",
       "What is the difference between management and leadership, "
       "and which is more important for an officer in the field?",
       A, "Officer Qualities"),
    _q("a27",
       "How would you build morale in a unit that has suffered significant casualties?",
       A, "Officer Qualities"),
    _q("a28",
       "What does 'mission command' mean, and how does it differ from "
       "centralised command and control?",
       A, "Officer Qualities"),
    _q("a29",
       "How do you maintain your own mental health and resilience while also "
       "being responsible for the welfare of your soldiers?",
       A, "Officer Qualities"),
    _q("a30",
       "If you were given command of a demoralised unit with poor discipline, "
       "what would be your first three actions in the first week?",
       A, "Officer Qualities"),
]


# ─── Master Question Bank ─────────────────────────────────────────────────────
QUESTION_BANK: dict[DifficultyLevel, list[Question]] = {
    DifficultyLevel.BASIC:        _BASIC,
    DifficultyLevel.INTERMEDIATE: _INTERMEDIATE,
    DifficultyLevel.ADVANCED:     _ADVANCED,
}

# Flat lookup by ID — O(1) access
QUESTION_BY_ID: dict[str, Question] = {
    q.id: q
    for qs in QUESTION_BANK.values()
    for q in qs
}

# Level progression order
LEVEL_ORDER: list[DifficultyLevel] = [
    DifficultyLevel.BASIC,
    DifficultyLevel.INTERMEDIATE,
    DifficultyLevel.ADVANCED,
]

# Thresholds: average OLQ score needed to advance to the next level
LEVEL_UP_THRESHOLD: dict[DifficultyLevel, float] = {
    DifficultyLevel.BASIC:        6.0,   # avg ≥ 6/10 → unlock Intermediate
    DifficultyLevel.INTERMEDIATE: 7.0,   # avg ≥ 7/10 → unlock Advanced
    DifficultyLevel.ADVANCED:     0.0,   # no further level
}

# Minimum word count for an answer to be considered "substantive"
MIN_SUBSTANTIVE_WORDS = 30
