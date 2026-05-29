import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_FILE)

def generate_custom_email(company_name, role, user_skills, base_template):
    """
    Attempts to use Gemini API to generate a personalized email.
    Gracefully falls back to the base_template if it fails or API key is missing.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return base_template

    try:
        import google.generativeai as genai
    except ImportError:
        print("   [AI Engine] google.generativeai not installed. Falling back to template.")
        return base_template

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
You are an expert job application email writer. I have a base template and some details.
Please rewrite the base template to make it highly personalized for the specific company and role, highlighting my skills appropriately. Keep it concise, professional, and matching the original tone. Do NOT add placeholder brackets like [Your Name]. Ensure that the output string matches the overall structure of the base template.

Details:
Company: {company_name}
Role: {role}
My Skills: {user_skills}

Base Template:
{base_template}

Return ONLY the text of the custom email. Do not add conversational filler.
"""
        response = model.generate_content(prompt)
        if response and response.text:
            return response.text.strip()
    except Exception as e:
        print(f"   [AI Engine] Failed to generate custom email: {e}")
    
    return base_template
