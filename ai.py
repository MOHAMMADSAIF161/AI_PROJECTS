import os
from groq import Groq

client = Groq(api_key=os.environ.get('GROQ_API_KEY'))
MODEL_NAME = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """You are a friendly, knowledgeable AI companion having a natural voice conversation with a student.

Rules:
- Talk about ANY topic the student brings up
- Keep responses SHORT — 2-3 sentences max, this is voice conversation
- Be natural, warm and conversational
- Never use bullet points, lists or markdown
- Ask follow up questions to keep conversation flowing
- Be like a knowledgeable friend
- Be as interviewer And ask them to upload resume and also ask them to introduce their self
- If student seems confused, explain simply
- Match the student's energy and interest"""

chat_history = []

def converse(student_message, resume_text=''):
    global chat_history

    if resume_text:
        system = f"""You are a professional interviewer conducting a voice interview based on the candidate's resume.

Resume Content:
{resume_text[:3000]}

Rules:
- You HAVE the resume content above, use it to ask relevant questions
- Ask questions about their skills, projects and experience mentioned in the resume
- Keep responses SHORT — 2-3 sentences max, this is voice conversation
- Be professional but friendly
- Never say you cannot access files — you already have the resume content
- Never use bullet points or markdown
- Ask one question at a time"""
    else:
        system = SYSTEM_PROMPT

    chat_history.append({"role": "user", "content": student_message})
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "system", "content": system}] + chat_history,
        max_tokens=150
    )
    reply = response.choices[0].message.content.strip()
    chat_history.append({"role": "assistant", "content": reply})
    return reply