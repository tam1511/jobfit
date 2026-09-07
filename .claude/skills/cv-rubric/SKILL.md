---
name: cv-rubric
description: Use when scoring a CV against a job description (JD), or when rewriting CV content to match the language of a JD.
---

# CV Rubric

## 1. Scoring Rubric

Score the CV from 0–100 using the following weighted criteria. Every criterion must be evaluated using a measurable metric rather than subjective judgment.

| Criterion | Weight | Measurement |
|---|---:|---|
| Hard Skills Match | 30% | Percentage of required skills in the JD that appear in the CV |
| Experience Match | 25% | Alignment of years of experience and seniority/level with the JD requirements |
| ATS Keywords | 20% | Percentage of industry-specific phrases from the JD that appear in the CV |
| Quantified Achievements | 15% | Percentage of CV bullets that contain measurable outcome numbers |
| Formatting & Length | 10% | Alignment of CV structure, readability, and length with the expectations of the JD |

### Scoring Rules

- Calculate each criterion on a 0–100 scale.
- Apply the weight to each criterion to calculate the overall score.
- Base every score on explicit evidence from the CV and JD.
- Do not award points based on vague impressions.
- When evidence is unavailable, mark the gap rather than assuming the requirement is satisfied.

## 2. Structured Output Schema

Return the evaluation in the following JSON structure:

```json
{
  "overall_score": 0,
  "breakdown": [
    {
      "category": "Hard Skills Match",
      "score": 0,
      "weight": 30,
      "evidence": "..."
    },
    {
      "category": "Experience Match",
      "score": 0,
      "weight": 25,
      "evidence": "..."
    },
    {
      "category": "ATS Keywords",
      "score": 0,
      "weight": 20,
      "evidence": "..."
    },
    {
      "category": "Quantified Achievements",
      "score": 0,
      "weight": 15,
      "evidence": "..."
    },
    {
      "category": "Formatting & Length",
      "score": 0,
      "weight": 10,
      "evidence": "..."
    }
  ],
  "gaps": [
    {
      "severity": "high",
      "evidence": "...",
      "suggestion": "..."
    }
  ],
  "matched_keywords": [],
  "missing_keywords": []
}
```

The frontend may use this structured output to render the overall score, category bars, gap indicators, and keyword highlights.

## 3. CV Rewriting Rules

### NEVER FABRICATE

Do not add any information that does not exist in the original CV.

Never invent:

- Numbers or performance metrics
- Company names
- Technologies, tools, or technical skills
- Certifications
- Job responsibilities
- Projects
- Achievements
- Titles or seniority levels

If the original CV does not contain enough information to write a strong bullet, **ask the user for the missing information instead of making assumptions**.

### Gap-Driven Conversation

The conversation must focus only on the gaps identified during the CV evaluation.

- Do not behave as a general-purpose assistant.
- Identify the most important gaps first.
- Ask about one gap at a time.
- Ask exactly one question per turn.
- Continue until all critical/high-severity gaps have been addressed.
- Do not ask unnecessary questions unrelated to the identified gaps.

### Preserve the Candidate's Voice

- Keep the candidate's original tone and style where possible.
- Do not rewrite the CV into an obviously AI-generated voice.
- Improve clarity, relevance, and impact without changing the candidate's underlying experience.

### Bullet Point Structure

Every rewritten CV bullet should follow this structure:

**Action Verb → Work Performed → Measurable Result**

Prefer concrete, evidence-based language. A measurable result must come from information provided by the candidate or already present in the original CV. Never manufacture a metric to make a bullet appear stronger.
